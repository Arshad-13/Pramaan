import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/lib/auth'
import type { User } from '@/lib/types'
import VerifyHistory from '@/pages/VerifyHistory'

const PHARMACIST: User = {
  public_id: 'ph1',
  email: 'meera@citypharm.test',
  name: 'Meera Joshi',
  role: 'pharmacist',
  license_no: 'PH-1',
  org_name: 'City Pharmacy',
  patient_code: null,
  approval_status: 'APPROVED',
  is_active: true,
  created_at: '2026-10-18T10:00:00Z',
}

const json = (status: number, body?: unknown) => new Response(body === undefined ? null : JSON.stringify(body), { status })

describe('VerifyHistory', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  function renderPage() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <MemoryRouter>
            <VerifyHistory />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    )
  }

  it('lists checks with outcome text, filters by result and shows dispenses', async () => {
    const now = new Date().toISOString()
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return json(200, PHARMACIST)
      if (url.startsWith('/api/verify/history')) {
        const onlyRevoked = url.includes('result=REVOKED')
        const items = [
          { ts: now, result: 'REVOKED', rx_ref: 'abcd1234', reasons: ['RX_REVOKED'] },
          ...(onlyRevoked ? [] : [{ ts: now, result: 'VALID', rx_ref: 'ef567890', reasons: [] }]),
        ]
        return json(200, { items, total: items.length })
      }
      if (url.startsWith('/api/verify/dispenses')) return json(200, { items: [{ ts: now, rx_ref: 'ef567890', fill_no: 1 }], total: 1 })
      throw new Error(`unexpected ${url}`)
    })
    renderPage()
    const table = await screen.findByRole('table', { name: /recent verification checks/ })
    expect(within(table).getByText('Revoked')).toBeInTheDocument()
    expect(within(table).getByText('Verified')).toBeInTheDocument()
    expect(within(table).getByText('The doctor withdrew this prescription.')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Show'), 'REVOKED')
    await vi.waitFor(() => expect(within(screen.getByRole('table')).queryByText('Verified')).not.toBeInTheDocument())
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('result=REVOKED'))).toBe(true)

    await userEvent.click(screen.getByRole('button', { name: 'Dispensed' }))
    const dispensed = await screen.findByRole('table', { name: /Medicines you dispensed/ })
    expect(within(dispensed).getByText('#1')).toBeInTheDocument()
  })

  it('shows a teaching empty state when nothing has been checked yet', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === '/api/auth/me' ? json(200, PHARMACIST) : json(200, { items: [], total: 0 }),
    )
    renderPage()
    expect(await screen.findByText('No checks yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Verify a prescription' })).toHaveAttribute('href', '/verify')
  })
})
