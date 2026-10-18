import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PinRing } from '@/components/PinRing'
import { VerificationTimeline } from '@/components/VerificationTimeline'
import { AuthProvider } from '@/lib/auth'
import type { User, VerifyResult } from '@/lib/types'
import { REASON_TEXT, timelineSteps } from '@/lib/verify'
import Verify from '@/pages/Verify'

// The camera is not available in tests: replace the scanner library with a controllable fake.
const scannerHooks: { emit?: (text: string) => void } = {}
vi.mock('qr-scanner', () => ({
  default: class {
    constructor(_video: unknown, onDecode: (r: { data: string }) => void) {
      scannerHooks.emit = (text) => onDecode({ data: text })
    }
    start() {
      return Promise.resolve()
    }
    stop() {}
    destroy() {}
  },
}))

const PHARMACIST: User = {
  public_id: 'ph1',
  email: 'asha@pharm.test',
  name: 'Asha Mehta',
  role: 'pharmacist',
  license_no: 'PH-1',
  org_name: 'City Pharmacy',
  patient_code: null,
  approval_status: 'APPROVED',
  is_active: true,
  created_at: '2026-10-18T10:00:00Z',
}

const CHECKS = {
  signature_valid: true, hash_match: true, key_state: 'ACTIVE', doctor_active: true, status: 'ISSUED',
  fills_remaining: 1, not_expired: true, content_check: 'NOT_CHECKED', file_integrity: null,
}

const VALID: VerifyResult = {
  result: 'VALID',
  reason_codes: [],
  rx_id: 'rx-1',
  checks: CHECKS,
  risk: { score: 0, flags: [], explanations: [] },
  warnings: [],
  doctor: { name: 'Dr. A. Shah', license_no: 'GJ-12345' },
  patient: { name: 'R. Patel' },
  medicines: [{ name: 'Amoxicillin', dose_mg: 500, frequency: 'TDS', duration_days: 5 }],
  issued_at: '2026-10-18T10:30:00Z',
  expires_at: '2026-11-17T10:30:00Z',
  can_dispense: true,
  pin_required: true,
}
const NO_DATA = { rx_id: null, checks: null, risk: null, warnings: [], doctor: null, patient: null, medicines: null, issued_at: null, expires_at: null, can_dispense: false, pin_required: false }

const json = (status: number, body?: unknown) => new Response(body === undefined ? null : JSON.stringify(body), { status })

function renderVerify() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter>
          <Verify />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

const CODE = 'PRM2.' + 'x'.repeat(40)

describe('timelineSteps', () => {
  const states = (r: VerifyResult) => Object.fromEntries(timelineSteps(r).map((s) => [s.id, s.state]))

  it('passes every step for a valid prescription', () => {
    expect(Object.values(states(VALID))).toEqual(Array(7).fill('pass'))
  })
  it('skips everything after an unreadable code', () => {
    const s = states({ ...VALID, ...NO_DATA, result: 'INVALID_QR', reason_codes: ['MALFORMED_QR'] })
    expect(s).toMatchObject({ read: 'fail', found: 'skipped', record: 'skipped', signature: 'skipped', risk: 'skipped' })
  })
  it('stops at "not found"', () => {
    const s = states({ ...VALID, ...NO_DATA, result: 'NOT_FOUND', reason_codes: ['NOT_FOUND'] })
    expect(s).toMatchObject({ read: 'pass', found: 'fail', record: 'skipped' })
  })
  it('marks the failing integrity step for tampering and skips the later ones', () => {
    const hash = states({ ...VALID, ...NO_DATA, result: 'TAMPERED', reason_codes: ['QR_HASH_MISMATCH'] })
    expect(hash).toMatchObject({ found: 'pass', record: 'fail', signature: 'pass', standing: 'skipped', status: 'skipped' })
    const sig = states({ ...VALID, ...NO_DATA, result: 'TAMPERED', reason_codes: ['INVALID_SIGNATURE'] })
    expect(sig).toMatchObject({ record: 'pass', signature: 'fail', risk: 'skipped' })
  })
  it('shows a revoked prescription as authentic but withdrawn', () => {
    expect(states({ ...VALID, result: 'REVOKED', reason_codes: ['RX_REVOKED'], can_dispense: false })).toMatchObject({
      signature: 'pass',
      standing: 'pass',
      status: 'fail',
      risk: 'pass',
    })
  })
  it('flags a revoked key under "good standing"', () => {
    expect(states({ ...VALID, result: 'REVOKED', reason_codes: ['DOCTOR_KEY_REVOKED'] })).toMatchObject({ standing: 'fail', status: 'pass' })
  })
  it('warns (not fails) on risk', () => {
    expect(states({ ...VALID, result: 'SUSPICIOUS', reason_codes: ['RISK_ABOVE_THRESHOLD'] })).toMatchObject({ risk: 'warn', status: 'pass' })
  })
  it('has readable text for every reason the server can send', () => {
    for (const code of [
      'MALFORMED_QR', 'NOT_FOUND', 'DB_RECORD_ALTERED', 'QR_HASH_MISMATCH', 'INVALID_SIGNATURE',
      'KEY_ID_MISMATCH', 'KEY_NOT_FOUND', 'DOCTOR_KEY_REVOKED', 'DOCTOR_SUSPENDED', 'RX_REVOKED',
      'FULLY_DISPENSED', 'RX_EXPIRED', 'RISK_ABOVE_THRESHOLD',
    ])
      expect(REASON_TEXT[code]).toBeTruthy()
  })
})

describe('VerificationTimeline', () => {
  it('lists the checks with accessible outcomes', () => {
    render(<VerificationTimeline result={{ ...VALID, result: 'REVOKED', reason_codes: ['RX_REVOKED'] }} />)
    const list = screen.getByRole('list', { name: 'Checks performed' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(7)
    expect(within(list).getByText(/Unused, current and not withdrawn/)).toBeInTheDocument()
    expect(within(list).getByText('The doctor withdrew this prescription.')).toBeInTheDocument()
    expect(within(list).getAllByText(': Passed').length).toBe(6)
    expect(within(list).getByText(': Failed')).toBeInTheDocument()
  })
})

describe('Verify page', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  function route(verifyBody: unknown, extra: Record<string, (init?: RequestInit) => Response> = {}) {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (extra[url]) return extra[url](init)
      if (url === '/api/auth/me') return json(200, PHARMACIST)
      if (url === '/api/verify/qr') return json(200, verifyBody)
      throw new Error(`unexpected ${init?.method ?? 'GET'} ${url}`)
    })
  }

  async function pasteAndVerify() {
    await userEvent.click(await screen.findByRole('tab', { name: /Paste code/ }))
    await userEvent.type(screen.getByLabelText('Prescription code'), CODE)
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
  }

  it('verifies a pasted code and shows the verdict, the record and the checks', async () => {
    route(VALID)
    renderVerify()
    await pasteAndVerify()
    const verdict = await screen.findByRole('region', { name: 'Verification result' })
    expect(within(verdict).getByRole('heading', { name: 'Verified' })).toBeInTheDocument()
    expect(screen.getByText('Verified record')).toBeInTheDocument()
    expect(screen.getByText('Dispense according to this verified record, not the paper.')).toBeInTheDocument()
    expect(screen.getByText('R. Patel')).toBeInTheDocument()
    expect(screen.getByText('Amoxicillin')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Checks performed' })).toBeInTheDocument()
    const call = fetchMock.mock.calls.find(([u]) => u === '/api/verify/qr')!
    expect(JSON.parse(call[1].body)).toEqual({ qr_string: CODE })
  })

  it('verifies a code from the live camera', async () => {
    route(VALID)
    renderVerify()
    await screen.findByLabelText('Camera view')
    await waitFor(() => expect(scannerHooks.emit).toBeTypeOf('function'))
    scannerHooks.emit!(CODE)
    expect(await screen.findByRole('heading', { name: 'Verified' })).toBeInTheDocument()
  })

  it('shows tampering without exposing any prescription data or a dispense control', async () => {
    route({ ...VALID, ...NO_DATA, result: 'TAMPERED', reason_codes: ['QR_HASH_MISMATCH'] })
    renderVerify()
    await pasteAndVerify()
    expect(await screen.findByRole('heading', { name: 'Tampered' })).toBeInTheDocument()
    expect(screen.getByText('This prescription does not match what the doctor signed.')).toBeInTheDocument()
    expect(screen.getAllByText('The code does not match the signed prescription.').length).toBeGreaterThan(0)
    expect(screen.queryByText('Verified record')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dispense' })).not.toBeInTheDocument()
  })

  it('shows the record but no dispense control for a revoked prescription', async () => {
    route({ ...VALID, result: 'REVOKED', reason_codes: ['RX_REVOKED'], can_dispense: false })
    renderVerify()
    await pasteAndVerify()
    expect(await screen.findByRole('heading', { name: 'Revoked' })).toBeInTheDocument()
    expect(screen.getByText('Verified record')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dispense' })).not.toBeInTheDocument()
  })

  it('keeps Dispense disabled until a six-digit PIN is entered, then dispenses', async () => {
    route(VALID, {
      '/api/prescriptions/rx-1/dispense': () => json(200, { rx_id: 'rx-1', fill_no: 1, fills_remaining: 0, status: 'DISPENSED' }),
    })
    renderVerify()
    await pasteAndVerify()
    const button = await screen.findByRole('button', { name: 'Dispense' })
    expect(button).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Patient.s PIN/), '12a45')
    expect(button).toBeDisabled() // the letter is stripped: only four digits so far
    await userEvent.type(screen.getByLabelText(/Patient.s PIN/), '67')
    expect(button).toBeEnabled()
    await userEvent.click(button)
    expect(await screen.findByText(/Dispensed \(fill 1\)/)).toBeInTheDocument()
    expect(screen.getByText('This prescription is now fully used.')).toBeInTheDocument()
    const call = fetchMock.mock.calls.find(([u]) => u === '/api/prescriptions/rx-1/dispense')!
    expect(JSON.parse(call[1].body)).toEqual({ qr_string: CODE, patient_pin: '124567' })
  })

  it('shows a wrong PIN inline and clears the field', async () => {
    route(VALID, { '/api/prescriptions/rx-1/dispense': () => json(403, { detail: 'That PIN is not correct.' }) })
    renderVerify()
    await pasteAndVerify()
    await userEvent.type(await screen.findByLabelText(/Patient.s PIN/), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Dispense' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That PIN is not correct.')
    expect(screen.getByLabelText(/Patient.s PIN/)).toHaveValue('')
  })

  it('asks for an identity confirmation instead of a PIN when the prescription has none', async () => {
    route({ ...VALID, pin_required: false }, {
      '/api/prescriptions/rx-1/dispense': () => json(200, { rx_id: 'rx-1', fill_no: 1, fills_remaining: 2, status: 'ISSUED' }),
    })
    renderVerify()
    await pasteAndVerify()
    const button = await screen.findByRole('button', { name: 'Dispense' })
    expect(screen.queryByLabelText(/Patient.s PIN/)).not.toBeInTheDocument()
    expect(button).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: /checked the patient.s identity/ }))
    await userEvent.click(button)
    expect(await screen.findByText('2 more fills remain on this prescription.')).toBeInTheDocument()
    const call = fetchMock.mock.calls.find(([u]) => u === '/api/prescriptions/rx-1/dispense')!
    expect(JSON.parse(call[1].body)).toEqual({ qr_string: CODE, patient_identity_checked: true })
  })

  it('starts over with "Verify another"', async () => {
    route(VALID)
    renderVerify()
    await pasteAndVerify()
    await screen.findByRole('heading', { name: 'Verified' })
    await userEvent.click(screen.getByRole('button', { name: /Verify another/ }))
    expect(await screen.findByRole('tab', { name: /Scan/ })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Verified' })).not.toBeInTheDocument()
  })

  it('shows a server error without a verdict', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === '/api/auth/me' ? json(200, PHARMACIST) : json(429, { detail: 'Too many requests.' }),
    )
    renderVerify()
    await pasteAndVerify()
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests.')
  })
})

describe('PinRing', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  function renderRing() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <PinRing rxId="rx-1" />
      </QueryClientProvider>,
    )
  }

  it('shows the PIN in two groups with a countdown', async () => {
    fetchMock.mockResolvedValue(json(200, { pin: '482913', seconds_remaining: 87, step_seconds: 120 }))
    renderRing()
    expect(await screen.findByText('482 913')).toBeInTheDocument()
    expect(screen.getByText(/It changes in 8\d s/)).toBeInTheDocument()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/prescriptions/rx-1/pin')
  })

  it('explains when the prescription can no longer be dispensed', async () => {
    fetchMock.mockResolvedValue(json(409, { detail: 'This prescription can no longer be dispensed.' }))
    renderRing()
    expect(await screen.findByRole('alert')).toHaveTextContent('can no longer be dispensed')
  })
})
