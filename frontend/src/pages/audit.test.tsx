import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/lib/auth'
import { actionLabel, detailFacts, eventLabel } from '@/lib/audit'
import type { AuditEntry, AuditVerify, User } from '@/lib/types'
import Admin from '@/pages/Admin'
import Audit from '@/pages/Audit'

const AUDITOR: User = {
  public_id: 'a1',
  email: 'audit@pramaan.test',
  name: 'Anita Auditor',
  role: 'auditor',
  license_no: null,
  org_name: null,
  patient_code: null,
  approval_status: 'APPROVED',
  is_active: true,
  created_at: '2026-10-18T10:00:00Z',
}

const entry = (seq: number, action: string, extra: Partial<AuditEntry> = {}): AuditEntry => ({
  seq,
  ts: '2026-10-20T10:00:00Z',
  actor_id: 1,
  actor_role: 'doctor',
  action,
  resource_id: null,
  details_json: '{}',
  prev_hash: 'a'.repeat(64),
  entry_hash: 'b'.repeat(64),
  ...extra,
})

const OK: AuditVerify = { ok: true, checked: 42, first_bad_seq: null, checkpoint_ok: true, truncated: false, problems: [], last_seq: 42, checkpoints: 2, anchors: 2 }
const BROKEN: AuditVerify = { ...OK, ok: false, first_bad_seq: 3, problems: ['Entry 3: hash does not match its contents'] }

const json = (status: number, body?: unknown) => new Response(body === undefined ? null : JSON.stringify(body), { status })

function renderPage(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter>{node}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('audit labels', () => {
  it('turns action codes into plain language and falls back gracefully', () => {
    expect(actionLabel('RX_ISSUED_WITH_OVERRIDE')).toBe('Prescription issued despite a warning')
    expect(actionLabel('SOMETHING_NEW')).toBe('something new')
    expect(eventLabel('AUDIT_CHAIN_BROKEN')).toBe('Audit chain failed verification')
  })
  it('extracts simple facts from details and ignores malformed JSON', () => {
    expect(detailFacts('{"result":"VALID","reasons":["x"],"count":2}')).toEqual(['result: VALID', 'count: 2'])
    expect(detailFacts('not json')).toEqual([])
  })
})

describe('Audit page', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  const entries = [entry(5, 'RX_DISPENSED', { actor_role: 'pharmacist' }), entry(4, 'RX_VERIFIED'), entry(3, 'LOGIN_SUCCESS')]

  function route(verify: AuditVerify = OK) {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return json(200, AUDITOR)
      if (url.startsWith('/api/admin/audit/verify')) return json(200, verify)
      if (url === '/api/admin/audit/checkpoint') return json(200, { ...verify, checkpoints: 3 })
      if (url.startsWith('/api/admin/audit')) return json(200, { items: entries, total: 45 })
      throw new Error(`unexpected ${url}`)
    })
  }

  it('lists entries newest first in plain language', async () => {
    route()
    renderPage(<Audit />)
    const list = await screen.findByRole('list', { name: 'Audit log entries, newest first' })
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(within(items[0]).getByText('Prescription dispensed')).toBeInTheDocument()
    expect(within(items[0]).getByText('by pharmacist')).toBeInTheDocument()
    expect(screen.getByText(/Page 1 of 3 · 45 entries/)).toBeInTheDocument()
  })

  it('shows the hashes that link an entry to the one before it when opened', async () => {
    route()
    renderPage(<Audit />)
    await userEvent.click(await screen.findByRole('button', { name: /Prescription verified/ }))
    expect(screen.getByText('Link to the entry before it')).toBeInTheDocument()
    expect(screen.getByText('Seal of this entry')).toBeInTheDocument()
  })

  it('reports an intact chain', async () => {
    route(OK)
    renderPage(<Audit />)
    await userEvent.click(await screen.findByRole('button', { name: 'Verify chain' }))
    const result = await screen.findByRole('region', { name: 'Chain verification result' })
    expect(within(result).getByText('Chain intact')).toBeInTheDocument()
    expect(within(result).getByText(/All 42 entries link up/)).toBeInTheDocument()
  })

  it('names the altered entry and marks it in the list', async () => {
    route(BROKEN)
    renderPage(<Audit />)
    await userEvent.click(await screen.findByRole('button', { name: 'Verify chain' }))
    const result = await screen.findByRole('region', { name: 'Chain verification result' })
    expect(within(result).getByText('Tampering detected')).toBeInTheDocument()
    expect(within(result).getByText('The log was altered at entry #3.')).toBeInTheDocument()
    expect(within(result).getByText('Entry 3: hash does not match its contents')).toBeInTheDocument()
    expect(screen.getByText(/The chain breaks here/)).toBeInTheDocument()
  })

  it('adds a signed checkpoint', async () => {
    route()
    renderPage(<Audit />)
    await userEvent.click(await screen.findByRole('button', { name: /Add signed checkpoint/ }))
    expect(await screen.findByText(/3 signed checkpoints/)).toBeInTheDocument()
    expect(screen.getByText(/2 copies stored outside/)).toBeInTheDocument()
    const call = fetchMock.mock.calls.find(([u]) => u === '/api/admin/audit/checkpoint')!
    expect(call[1].method).toBe('POST')
  })

  it('pages through older entries', async () => {
    route()
    renderPage(<Audit />)
    await userEvent.click(await screen.findByRole('button', { name: /Older/ }))
    expect(await screen.findByText(/Page 2 of 3/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('offset=20'))).toBe(true)
  })
})

describe('Admin security alerts', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists alerts with severity as text, not only colour', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return json(200, { ...AUDITOR, role: 'admin' })
      if (url.startsWith('/api/admin/security-events'))
        return json(200, [
          { id: 2, ts: '2026-10-20T10:00:00Z', user_id: 3, ip: null, event_type: 'AUDIT_CHAIN_BROKEN', severity: 'HIGH', details_json: '{"first_bad_seq":3}' },
          { id: 1, ts: '2026-10-20T09:00:00Z', user_id: 4, ip: null, event_type: 'RISK_OVERRIDE', severity: 'LOW', details_json: '{}' },
        ])
      return json(200, { items: [], total: 0 })
    })
    renderPage(<Admin />)
    expect(await screen.findByText('Audit chain failed verification')).toBeInTheDocument()
    expect(screen.getByText('High')).toBeInTheDocument()
    expect(screen.getByText('Low')).toBeInTheDocument()
    expect(screen.getByText('first bad seq: 3')).toBeInTheDocument()
  })

  it('says so when there are no alerts', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return json(200, { ...AUDITOR, role: 'admin' })
      if (url.startsWith('/api/admin/security-events')) return json(200, [])
      return json(200, { items: [], total: 0 })
    })
    renderPage(<Admin />)
    expect(await screen.findByText('No security alerts so far.')).toBeInTheDocument()
  })
})
