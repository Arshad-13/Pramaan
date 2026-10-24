import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/lib/auth'
import { greetingName } from '@/lib/greeting'
import type { Prescription, Role, User } from '@/lib/types'
import Dashboard from '@/pages/Dashboard'

const user = (role: Role, name: string): User => ({
  public_id: 'u1', email: 'x@y.test', name, role, license_no: null, org_name: null, patient_code: null,
  approval_status: 'APPROVED', is_active: true, created_at: '2026-10-18T10:00:00Z',
})

const rx = (id: string, status: Prescription['status'], extra: Partial<Prescription> = {}): Prescription => ({
  id, status, issued_at: '2026-10-20T10:00:00Z', expires_at: '2026-11-19T10:00:00Z', max_fills: 1,
  fills_used: status === 'DISPENSED' ? 1 : 0, doctor_name: 'Dr. A. Shah', patient_name: 'Ravi Patel',
  medicines: [{ name: 'Amoxicillin', dose_mg: 500, frequency: 'TDS', duration_days: 5 }], notes: '', key_id: 'k',
  fingerprint: 'f', risk_score: 0, require_pin: true, readable: true, ...extra,
})

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('greetingName', () => {
  it('uses the title and surname for doctors, the first name for others', () => {
    expect(greetingName('Dr. A. Shah')).toBe('Dr. Shah')
    expect(greetingName('dr Meera Iyer')).toBe('Dr. Iyer')
    expect(greetingName('Ravi Patel')).toBe('Ravi')
    expect(greetingName('Dr.')).toBe('Dr.')
    expect(greetingName(undefined)).toBe('')
  })
})

describe('Dashboard', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  function route(me: User, routes: Record<string, unknown>) {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return json(me)
      if (url === '/api/health') return json({ status: 'ok' })
      const hit = Object.keys(routes).find((k) => url.startsWith(k))
      if (hit) return json(routes[hit])
      throw new Error(`unexpected ${url}`)
    })
  }

  it('greets a doctor properly and summarises their prescriptions', async () => {
    route(user('doctor', 'Dr. A. Shah'), {
      '/api/prescriptions/mine': [rx('1', 'ISSUED'), rx('2', 'DISPENSED'), rx('3', 'REVOKED'), rx('4', 'ISSUED', { risk_score: 75 })],
    })
    renderDashboard()
    expect(await screen.findByRole('heading', { name: /, Dr\. Shah$/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /New prescription/ })).toHaveAttribute('href', '/prescriptions/new')
    const glance = await screen.findByRole('region', { name: 'At a glance' })
    expect(within(glance).getByText('Issued in total').nextSibling).toHaveTextContent('4')
    expect(within(glance).getByText('Not yet picked up').nextSibling).toHaveTextContent('2')
    expect(within(glance).getByText('Flagged when issued').nextSibling).toHaveTextContent('1')
    expect(screen.getAllByText('Ravi Patel').length).toBeGreaterThan(0)
  })

  it('shows a patient only what is ready to use', async () => {
    route(user('patient', 'Ravi Patel'), { '/api/prescriptions/mine': [rx('1', 'ISSUED'), rx('2', 'DISPENSED')] })
    renderDashboard()
    expect(await screen.findByRole('heading', { name: /, Ravi$/ })).toBeInTheDocument()
    const ready = await screen.findByRole('region', { name: 'Ready to use' })
    expect(within(ready).getAllByRole('listitem')).toHaveLength(1)
    expect(screen.queryByRole('link', { name: /New prescription/ })).not.toBeInTheDocument()
  })

  it('shows a pharmacist their checks today and links to verify', async () => {
    route(user('pharmacist', 'Meera Shah'), {
      '/api/verify/recent': {
        verified_today: 3, flagged_today: 1, dispensed_today: 2,
        recent: [{ ts: '2026-10-24T10:00:00Z', result: 'TAMPERED', rx_ref: 'abcd1234' }, { ts: '2026-10-24T09:00:00Z', result: 'VALID', rx_ref: null }],
      },
    })
    renderDashboard()
    expect(await screen.findByRole('link', { name: /Verify a prescription/ })).toHaveAttribute('href', '/verify')
    expect(await screen.findByText('Tampered')).toBeInTheDocument()
    expect(screen.getByText('abcd1234')).toBeInTheDocument()
    const glance = screen.getByRole('region', { name: 'At a glance' })
    expect(within(glance).getByText('Verified today').nextSibling).toHaveTextContent('3')
    expect(within(glance).getByText('Dispensed today').nextSibling).toHaveTextContent('2')
  })

  it('shows an admin pending approvals and alert counts', async () => {
    route(user('admin', 'Site Admin'), {
      '/api/admin/security-events': [
        { id: 2, ts: '2026-10-24T10:00:00Z', user_id: 1, ip: null, event_type: 'POSSIBLE_REPLAY', severity: 'MEDIUM', details_json: '{}' },
        { id: 1, ts: '2026-10-24T09:00:00Z', user_id: 1, ip: null, event_type: 'AUDIT_CHAIN_BROKEN', severity: 'HIGH', details_json: '{}' },
      ],
      '/api/admin/users?role=pharmacist': { items: [], total: 2 },
      '/api/admin/users?limit=1': { items: [], total: 9 },
    })
    renderDashboard()
    expect(await screen.findByText('Possible replay at another pharmacy')).toBeInTheDocument()
    const glance = screen.getByRole('region', { name: 'At a glance' })
    expect(within(glance).getByText('Pharmacists awaiting approval').nextSibling).toHaveTextContent('2')
    expect(within(glance).getByText('High-severity alerts').nextSibling).toHaveTextContent('1')
  })

  it('shows an auditor the size of the log and alert counts', async () => {
    route(user('auditor', 'Anita Auditor'), {
      '/api/admin/security-events': [],
      '/api/admin/audit': { items: [], total: 88 },
    })
    renderDashboard()
    expect(await screen.findByText('No security alerts so far.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open the audit log/ })).toHaveAttribute('href', '/audit')
    const glance = screen.getByRole('region', { name: 'At a glance' })
    expect(within(glance).getByText('Entries in the audit log').nextSibling).toHaveTextContent('88')
  })
})
