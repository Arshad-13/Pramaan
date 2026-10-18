import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RxPreview } from '@/components/RxPreview'
import { AuthProvider } from '@/lib/auth'
import { addDays, dateTimeUtc, medicineCells, patientLine } from '@/lib/rx'
import type { Prescription, User } from '@/lib/types'
import MyPrescriptions from '@/pages/MyPrescriptions'
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
const PATIENT: User = { ...DOCTOR, public_id: 'p1', name: 'Ravi Patel', role: 'patient', license_no: null, org_name: null, patient_code: 'K7M2-Q9XD' }

const RX: Prescription = {
  id: 'rx-1',
  status: 'ISSUED',
  issued_at: '2026-10-18T10:30:00Z',
  expires_at: '2026-11-17T10:30:00Z',
  max_fills: 1,
  fills_used: 0,
  doctor_name: 'Dr. A. Shah',
  patient_name: 'Ravi Patel',
  medicines: [{ name: 'Amoxicillin', dose_mg: 500, frequency: 'TDS', duration_days: 5 }],
  notes: '',
  key_id: '9a1c0e77b2d4f605',
  fingerprint: '9a1c 0e77 b2d4',
  risk_score: 0,
  readable: true,
}

function json(status: number, body?: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), { status })
}

function renderPage(element: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/p']}>
          <Routes>
            <Route path="/p" element={element} />
            <Route path="/prescriptions" element={<h1>List page</h1>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('printed-text helpers (mirror the signed PDF)', () => {
  it('formats dates to the minute in UTC', () => {
    expect(dateTimeUtc(new Date('2026-10-18T10:30:17Z'))).toBe('2026-10-18 10:30 UTC')
    expect(dateTimeUtc(addDays(new Date('2026-10-18T10:30:00Z'), 30))).toBe('2026-11-17 10:30 UTC')
  })
  it('builds the patient line and medicine cells', () => {
    expect(patientLine('Ravi Patel')).toBe('Patient: Ravi Patel')
    expect(patientLine('Ravi Patel', 34)).toBe('Patient: Ravi Patel, 34 yrs')
    expect(medicineCells({ name: 'Amoxicillin', dose_mg: 500, frequency: 'TDS', duration_days: 5 })).toEqual([
      'Amoxicillin',
      '500 mg',
      'TDS',
      '5 days',
    ])
  })
})

describe('RxPreview', () => {
  it('shows exactly the wording that will be signed, and says it is unsigned', () => {
    render(
      <RxPreview
        clinic="Shah Clinic, Surat"
        doctorName="Dr. A. Shah"
        licenseNo="GJ-12345"
        patientName="Ravi Patel"
        ageYears={34}
        validityDays={30}
        maxFills={1}
        medicines={RX.medicines}
        notes="After food"
        now={new Date('2026-10-18T10:30:00Z')}
      />,
    )
    const page = screen.getByRole('figure', { name: 'Prescription preview' })
    for (const text of [
      'Shah Clinic, Surat',
      'Dr. A. Shah',
      'Reg. No. GJ-12345',
      'Issued: 2026-10-18 10:30 UTC',
      'Valid until: 2026-11-17 10:30 UTC',
      'Fills allowed: 1',
      'Patient: Ravi Patel, 34 yrs',
      'Amoxicillin',
      '500 mg',
      'TDS',
      '5 days',
      'After food',
    ]) {
      expect(within(page).getByText(text)).toBeInTheDocument()
    }
    expect(within(page).getByText(/Preview · not signed yet/)).toBeInTheDocument()
  })

  it('prompts for a patient and shows an empty state before anything is entered', () => {
    render(
      <RxPreview clinic="C" doctorName="D" licenseNo="L" patientName={null} validityDays={30} maxFills={1} medicines={[]} notes="" />,
    )
    expect(screen.getByText('Patient: choose a patient')).toBeInTheDocument()
    expect(screen.getByText('Medicines you add appear here.')).toBeInTheDocument()
  })
})

describe('NewPrescription', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  function route(overrides: Record<string, (init?: RequestInit) => Response> = {}) {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (overrides[url]) return overrides[url](init)
      if (url === '/api/auth/me') return json(200, DOCTOR)
      if (url.startsWith('/api/patients/lookup'))
        return json(200, { public_id: 'p1', name: 'Ravi Patel', patient_code: 'K7M2-Q9XD' })
      throw new Error(`unexpected ${init?.method ?? 'GET'} ${url}`)
    })
  }

  async function fillValidForm() {
    await userEvent.type(await screen.findByLabelText('Patient email'), 'ravi@example.test')
    await userEvent.click(screen.getByRole('button', { name: 'Find' }))
    expect(await screen.findByText('Ravi Patel')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Medicine'), 'Amoxicillin')
    await userEvent.type(screen.getByLabelText('Dose (mg)'), '500')
    await userEvent.type(screen.getByLabelText('Days'), '5')
    await userEvent.type(screen.getByLabelText('Signing password'), 'a-long-signing-phrase')
  }

  it('updates the live preview as the doctor types', async () => {
    route()
    renderPage(<NewPrescription />)
    const preview = await screen.findByRole('figure', { name: 'Prescription preview' })
    expect(await within(preview).findByText('Shah Clinic, Surat')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Medicine'), 'Ibuprofen')
    await userEvent.type(screen.getByLabelText('Dose (mg)'), '400')
    expect(within(preview).getByText('Ibuprofen')).toBeInTheDocument()
    expect(within(preview).getByText('400 mg')).toBeInTheDocument()
  })

  it('never nests one form inside another (the patient search sits inside the prescription form)', async () => {
    route()
    const { container } = renderPage(<NewPrescription />)
    await screen.findByLabelText('Patient email')
    expect(container.querySelectorAll('form form')).toHaveLength(0)
    expect(container.querySelectorAll('form')).toHaveLength(1)
  })

  it('searches when Enter is pressed in the patient field without submitting the prescription', async () => {
    route()
    renderPage(<NewPrescription />)
    await userEvent.type(await screen.findByLabelText('Patient email'), 'ravi@example.test{Enter}')
    expect(await screen.findByText('K7M2-Q9XD')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/prescriptions')).toBe(false)
  })

  it('finds a patient by exact email and shows the match', async () => {
    route()
    renderPage(<NewPrescription />)
    await userEvent.type(await screen.findByLabelText('Patient email'), 'ravi@example.test')
    await userEvent.click(screen.getByRole('button', { name: 'Find' }))
    expect(await screen.findByText('K7M2-Q9XD')).toBeInTheDocument()
    const lookup = fetchMock.mock.calls.find(([u]) => String(u).startsWith('/api/patients/lookup'))!
    expect(lookup[0]).toBe('/api/patients/lookup?email=ravi%40example.test')
  })

  it('requires a patient and valid medicine fields before anything is sent', async () => {
    route()
    renderPage(<NewPrescription />)
    await userEvent.type(await screen.findByLabelText('Signing password'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Sign and issue' }))
    expect(await screen.findByText('Enter the medicine name.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/prescriptions')).toBe(false)
  })

  it('signs, sends the right body, then offers the PDF', async () => {
    route({
      '/api/prescriptions': () =>
        json(201, {
          rx_id: 'rx-9', issued_at: '2026-10-18T10:30:00Z', expires_at: '2026-11-17T10:30:00Z',
          max_fills: 1, key_id: 'k', fingerprint: '9a1c 0e77 b2d4',
          risk: { score: 0, flags: [], explanations: [] }, warnings: [],
        }),
    })
    renderPage(<NewPrescription />)
    await fillValidForm()
    await userEvent.click(screen.getByRole('button', { name: 'Sign and issue' }))
    expect(await screen.findByText('Signed and stored securely')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open PDF/ })).toHaveAttribute('href', '/api/prescriptions/rx-9/pdf')

    const call = fetchMock.mock.calls.find(([u]) => u === '/api/prescriptions')!
    expect(JSON.parse(call[1].body)).toMatchObject({
      patient_id: 'p1',
      medicines: [{ name: 'Amoxicillin', dose_mg: 500, frequency: 'TDS', duration_days: 5 }],
      validity_days: 30,
      max_fills: 1,
      signing_password: 'a-long-signing-phrase',
    })
  })

  it('shows a wrong signing password on that field and clears it', async () => {
    route({ '/api/prescriptions': () => json(403, { detail: 'Could not unlock your signing key.' }) })
    renderPage(<NewPrescription />)
    await fillValidForm()
    await userEvent.click(screen.getByRole('button', { name: 'Sign and issue' }))
    expect(await screen.findByText('Could not unlock your signing key.')).toBeInTheDocument()
    expect(screen.getByLabelText('Signing password')).toHaveValue('')
    expect(screen.queryByText('Signed and stored securely')).not.toBeInTheDocument()
  })

  it('shows server-side content errors above the button', async () => {
    route({ '/api/prescriptions': () => json(400, { detail: 'Medicine 1 medicine name is too long to print on the prescription.' }) })
    renderPage(<NewPrescription />)
    await fillValidForm()
    await userEvent.click(screen.getByRole('button', { name: 'Sign and issue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('too long to print')
  })

  it('adds and removes medicine rows up to the limit', async () => {
    route()
    renderPage(<NewPrescription />)
    await screen.findByLabelText('Medicine')
    for (let i = 0; i < 7; i++) await userEvent.click(screen.getByRole('button', { name: /Add medicine/ }))
    expect(screen.getAllByLabelText('Medicine')).toHaveLength(8)
    expect(screen.queryByRole('button', { name: /Add medicine/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove medicine 8' }))
    expect(screen.getAllByLabelText('Medicine')).toHaveLength(7)
  })
})

describe('MyPrescriptions', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists prescriptions with status, fills and a PDF link', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === '/api/auth/me' ? json(200, DOCTOR) : json(200, [RX, { ...RX, id: 'rx-2', status: 'REVOKED', patient_name: 'Sneha Rao' }]),
    )
    renderPage(<MyPrescriptions />)
    expect(await screen.findByText('Ravi Patel')).toBeInTheDocument()
    expect(screen.getByText('Sneha Rao')).toBeInTheDocument()
    expect(screen.getAllByText('Amoxicillin 500 mg TDS, 5 days').length).toBe(2)
    expect(screen.getAllByText('Issued')).toHaveLength(2) // column heading + status badge
    expect(screen.getByText('Revoked')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /PDF/ })[0]).toHaveAttribute('href', '/api/prescriptions/rx-1/pdf')
  })

  it('revokes only after a second confirming click, and only unused prescriptions', async () => {
    let revoked = false
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/auth/me') return json(200, DOCTOR)
      if (url === '/api/prescriptions/rx-1/revoke') {
        revoked = true
        expect(init?.method).toBe('POST')
        return json(200, { ...RX, status: 'REVOKED' })
      }
      return json(200, [revoked ? { ...RX, status: 'REVOKED' } : RX, { ...RX, id: 'rx-2', status: 'DISPENSED' }])
    })
    renderPage(<MyPrescriptions />)
    await screen.findAllByText('Ravi Patel')
    expect(screen.getAllByRole('button', { name: 'Revoke' })).toHaveLength(1) // not for the dispensed one
    await userEvent.click(screen.getByRole('button', { name: 'Revoke' }))
    expect(revoked).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Confirm revoke' }))
    await waitFor(() => expect(revoked).toBe(true))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument())
  })

  it('patients see the doctor, no revoke control, and a helpful empty state', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === '/api/auth/me' ? json(200, PATIENT) : json(200, [RX]),
    )
    const { unmount } = renderPage(<MyPrescriptions />)
    expect(await screen.findByText('Dr. A. Shah')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
    unmount()

    fetchMock.mockImplementation(async (url: string) => (url === '/api/auth/me' ? json(200, PATIENT) : json(200, [])))
    renderPage(<MyPrescriptions />)
    expect(await screen.findByText(/will appear here/)).toBeInTheDocument()
  })

  it('flags a record that failed its integrity check instead of showing its contents', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === '/api/auth/me'
        ? json(200, DOCTOR)
        : json(200, [{ ...RX, readable: false, medicines: [], patient_name: null }]),
    )
    renderPage(<MyPrescriptions />)
    expect(await screen.findByText('Integrity check failed')).toBeInTheDocument()
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0)
  })
})
