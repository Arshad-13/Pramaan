import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RiskGauge } from '@/components/RiskGauge'
import { AuthProvider } from '@/lib/auth'
import type { RiskCheck, User } from '@/lib/types'
import NewPrescription from '@/pages/NewPrescription'

const DOCTOR: User = {
  public_id: 'd1',
  email: 'dr.shah@clinic.test',
  name: 'Dr. A. Shah',
  role: 'doctor',
  license_no: 'GJ-12345',
  org_name: 'Shah Clinic, Surat',
  patient_code: null,
  approval_status: 'APPROVED',
  is_active: true,
  created_at: '2026-10-18T10:00:00Z',
}

const note = (over: Partial<RiskCheck['medicines'][number]> = {}): RiskCheck['medicines'][number] => ({
  index: 0,
  name: 'x',
  status: 'KNOWN',
  suggestion: null,
  generic: null,
  flags: [],
  ...over,
})

const LOW: RiskCheck = {
  risk: { score: 0, flags: [], explanations: [] },
  threshold: 60,
  requires_override: false,
  medicines: [note({ name: 'Amoxicillin' })],
  warnings: ['MODEL_UNAVAILABLE'],
  controlled: false,
}
const FAKE: RiskCheck = {
  ...LOW,
  risk: { score: 60, flags: ['UNKNOWN_DRUG'], explanations: ['"Xyzzolam" is not in the drug list.'] },
  requires_override: true,
  medicines: [note({ name: 'Xyzzolam', status: 'UNKNOWN', flags: ['UNKNOWN_DRUG'] })],
}
const TYPO: RiskCheck = {
  ...LOW,
  risk: { score: 15, flags: ['POSSIBLE_TYPO'], explanations: ['"Amoxicilin" looks like "Amoxicillin". Check the spelling.'] },
  medicines: [note({ name: 'Amoxicilin', status: 'POSSIBLE_TYPO', suggestion: 'Amoxicillin', flags: ['POSSIBLE_TYPO'] })],
}
const CONTROLLED: RiskCheck = {
  ...LOW,
  risk: { score: 10, flags: ['CONTROLLED_SUBSTANCE'], explanations: ['Tramadol is a controlled medicine (schedule H1).'] },
  controlled: true,
}

const json = (status: number, body?: unknown) => new Response(body === undefined ? null : JSON.stringify(body), { status })

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/p']}>
          <Routes>
            <Route path="/p" element={<NewPrescription />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('RiskGauge', () => {
  it('exposes the score as an accessible meter with a text label', () => {
    render(<RiskGauge score={75} threshold={60} />)
    const meter = screen.getByRole('meter', { name: 'Risk score' })
    expect(meter).toHaveAttribute('aria-valuenow', '75')
    expect(meter).toHaveAttribute('aria-valuetext', '75 out of 100. Needs review.')
    expect(screen.getByText('Needs review')).toBeInTheDocument()
  })
  it('says "No concerns" at zero and "Minor notes" below the threshold', () => {
    const { rerender } = render(<RiskGauge score={0} threshold={60} />)
    expect(screen.getByText('No concerns')).toBeInTheDocument()
    rerender(<RiskGauge score={15} threshold={60} />)
    expect(screen.getByText('Minor notes')).toBeInTheDocument()
  })
})

describe('New prescription: safety check', () => {
  const fetchMock = vi.fn()
  let riskResponse: RiskCheck
  beforeEach(() => {
    fetchMock.mockReset()
    riskResponse = LOW
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/auth/me') return json(200, DOCTOR)
      if (url === '/api/drugs') return json(200, [{ name: 'Amoxicillin', generic: 'Amoxicillin', is_brand: false }])
      if (url === '/api/prescriptions/risk-check') return json(200, riskResponse)
      if (url.startsWith('/api/patients/lookup')) return json(200, { public_id: 'p1', name: 'Ravi Patel', patient_code: 'K7M2-Q9XD' })
      if (url === '/api/prescriptions' && init?.method === 'POST')
        return json(201, { rx_id: 'rx-1', issued_at: 'x', expires_at: '2026-11-17T10:30:00Z', max_fills: 1, key_id: 'k', fingerprint: 'aa', risk: LOW.risk, warnings: [] })
      throw new Error(`unexpected ${url}`)
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  async function fillMedicine(name: string, dose = '500', days = '5') {
    await userEvent.type(await screen.findByLabelText('Medicine'), name)
    await userEvent.type(screen.getByLabelText('Dose (mg)'), dose)
    await userEvent.type(screen.getByLabelText('Days'), days)
  }
  async function pickPatient() {
    await userEvent.type(await screen.findByLabelText('Patient email'), 'ravi@example.test')
    await userEvent.click(screen.getByRole('button', { name: 'Find' }))
    await screen.findByText('K7M2-Q9XD')
  }

  it('asks for the check only once a medicine, dose and duration are filled in', async () => {
    renderPage()
    expect(await screen.findByText(/runs as soon as you have entered a medicine/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/prescriptions/risk-check')).toBe(false)
    await fillMedicine('Amoxicillin')
    expect(await screen.findByRole('meter', { name: 'Risk score' })).toHaveAttribute('aria-valuenow', '0')
    expect(screen.getByText('No unusual drug names or doses found.')).toBeInTheDocument()
    const call = fetchMock.mock.calls.find(([u]) => u === '/api/prescriptions/risk-check')!
    expect(JSON.parse(call[1].body)).toEqual({
      medicines: [{ name: 'Amoxicillin', dose_mg: 500, frequency: 'TDS', duration_days: 5 }],
      max_fills: 1,
    })
  })

  it('offers the drug list for autosuggest', async () => {
    renderPage()
    await screen.findByLabelText('Medicine')
    await waitFor(() => expect(document.querySelector('#drug-list option[value="Amoxicillin"]')).not.toBeNull())
    expect(screen.getByLabelText('Medicine')).toHaveAttribute('list', 'drug-list')
  })

  it('suggests the correct spelling and applies it with one click', async () => {
    riskResponse = TYPO
    renderPage()
    await fillMedicine('Amoxicilin')
    expect(await screen.findByText(/Did you mean/)).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Risk score' })).toHaveAttribute('aria-valuenow', '15')
    await userEvent.click(screen.getByRole('button', { name: 'Use Amoxicillin' }))
    expect(screen.getByLabelText('Medicine')).toHaveValue('Amoxicillin')
  })

  it('requires a reason when the check says the prescription is unusual', async () => {
    riskResponse = FAKE
    renderPage()
    await pickPatient()
    await fillMedicine('Xyzzolam')
    expect(await screen.findByText('"Xyzzolam" is not in the drug list.')).toBeInTheDocument()
    expect(screen.getByText('This name is not in the drug list. You can still issue it with a reason.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Signing password'), 'a-long-signing-phrase')

    await userEvent.type(screen.getByLabelText(/Reason for issuing anyway/), 'too short')
    await userEvent.click(screen.getByRole('button', { name: 'Sign and issue' }))
    expect(await screen.findByText('Give a reason of at least 10 characters.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u, i]) => u === '/api/prescriptions' && i?.method === 'POST')).toBe(false)

    await userEvent.clear(screen.getByLabelText(/Reason for issuing anyway/))
    await userEvent.type(screen.getByLabelText(/Reason for issuing anyway/), 'Specialist confirmed this compound by phone.')
    await userEvent.click(screen.getByRole('button', { name: 'Sign and issue' }))
    expect(await screen.findByText('Signed and stored securely')).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([u, i]) => u === '/api/prescriptions' && i?.method === 'POST')!
    expect(JSON.parse(post[1].body).override_reason).toBe('Specialist confirmed this compound by phone.')
  })

  it('sends no reason when none is needed', async () => {
    renderPage()
    await pickPatient()
    await fillMedicine('Amoxicillin')
    await screen.findByRole('meter')
    await userEvent.type(screen.getByLabelText('Signing password'), 'a-long-signing-phrase')
    expect(screen.queryByLabelText(/Reason for issuing anyway/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sign and issue' }))
    await screen.findByText('Signed and stored securely')
    const post = fetchMock.mock.calls.find(([u, i]) => u === '/api/prescriptions' && i?.method === 'POST')!
    expect(JSON.parse(post[1].body).override_reason).toBeUndefined()
  })

  it('shows the reason box if the server asks even though the live check did not', async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/auth/me') return json(200, DOCTOR)
      if (url === '/api/drugs') return json(200, [])
      if (url === '/api/prescriptions/risk-check') return json(200, LOW)
      if (url.startsWith('/api/patients/lookup')) return json(200, { public_id: 'p1', name: 'Ravi Patel', patient_code: 'K7M2-Q9XD' })
      if (url === '/api/prescriptions' && init?.method === 'POST')
        return json(409, { detail: 'needs confirmation', code: 'RISK_CONFIRMATION_REQUIRED', risk: FAKE.risk, threshold: 60 })
      throw new Error(`unexpected ${url}`)
    })
    renderPage()
    await pickPatient()
    await fillMedicine('Amoxicillin')
    await screen.findByRole('meter')
    await userEvent.type(screen.getByLabelText('Signing password'), 'a-long-signing-phrase')
    await userEvent.click(screen.getByRole('button', { name: 'Sign and issue' }))
    expect(await screen.findByLabelText(/Reason for issuing anyway/)).toBeInTheDocument()
    expect(screen.getByText('This prescription needs a reason before it can be signed.')).toBeInTheDocument()
  })

  it('limits controlled medicines to one fill in the form and explains why', async () => {
    riskResponse = CONTROLLED
    renderPage()
    await screen.findByLabelText('Medicine')
    const fills = screen.getByLabelText('Fills allowed')
    await userEvent.clear(fills)
    await userEvent.type(fills, '3')
    await fillMedicine('Tramadol', '50', '5')
    expect(await screen.findByText('Tramadol is a controlled medicine (schedule H1).')).toBeInTheDocument()
    await waitFor(() => expect(fills).toHaveValue(1))
    expect(within(screen.getByRole('figure', { name: 'Prescription preview' })).getByText('Fills allowed: 1')).toBeInTheDocument()
  })
})
