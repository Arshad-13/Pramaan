import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn(), warning: vi.fn(), dismiss: vi.fn() } }))

import { QrMatrix } from '@/components/QrMatrix'
import { TwoFactorCard } from '@/components/TwoFactorCard'
import { dayPartGreeting } from '@/lib/greeting'
import { planSessionWarning, WARN_BEFORE_MS } from '@/lib/session'
import { exactTime, relativeTime } from '@/lib/time'
import type { User } from '@/lib/types'

const USER: User = {
  public_id: 'p1',
  email: 'ravi@example.test',
  name: 'Ravi Patel',
  role: 'patient',
  license_no: null,
  org_name: null,
  patient_code: 'K7M2-Q9XD',
  approval_status: 'APPROVED',
  is_active: true,
  created_at: '2026-10-18T10:00:00Z',
  mfa_enabled: false,
}

function json(status: number, body?: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), { status })
}

describe('relative times', () => {
  const now = new Date('2026-11-14T12:00:00Z').getTime()
  const ago = (ms: number) => new Date(now - ms).toISOString()
  it('reads at a glance and never says a negative duration', () => {
    expect(relativeTime(ago(20_000), now)).toBe('just now')
    expect(relativeTime(ago(5 * 60_000), now)).toBe('5 min ago')
    expect(relativeTime(ago(3 * 3_600_000), now)).toBe('3 h ago')
    expect(relativeTime(ago(30 * 3_600_000), now)).toBe('yesterday')
    expect(relativeTime(ago(4 * 86_400_000), now)).toBe('4 days ago')
    expect(relativeTime(ago(-60_000), now)).toBe('in the future')
    expect(relativeTime('not a date', now)).toBe('')
    expect(exactTime(ago(0))).toMatch(/2026/)
  })
})

describe('greeting', () => {
  it('does not say good morning in the small hours', () => {
    expect(dayPartGreeting(new Date(2026, 10, 14, 2, 0))).toBe('Working late')
    expect(dayPartGreeting(new Date(2026, 10, 14, 5, 0))).toBe('Good morning')
    expect(dayPartGreeting(new Date(2026, 10, 14, 13, 0))).toBe('Good afternoon')
    expect(dayPartGreeting(new Date(2026, 10, 14, 21, 0))).toBe('Good evening')
  })
})

describe('session warning plan', () => {
  const now = Date.parse('2026-11-14T10:00:00Z')
  it('warns two minutes before the token ends and offers renewal while the limit is later', () => {
    const plan = planSessionWarning('2026-11-14T10:30:00Z', '2026-11-14T18:00:00Z', now)
    expect(plan).toEqual({ delayMs: 30 * 60_000 - WARN_BEFORE_MS, canRenew: true })
  })
  it('says renewal is no longer possible at the hard limit, and warns at once if already close', () => {
    const plan = planSessionWarning('2026-11-14T10:01:00Z', '2026-11-14T10:01:00Z', now)
    expect(plan).toEqual({ delayMs: 0, canRenew: false })
  })
  it('treats a missing limit as the token expiry', () => {
    expect(planSessionWarning('2026-11-14T10:30:00Z', undefined, now).canRenew).toBe(false)
  })
})

describe('QR matrix', () => {
  it('draws one square per dark module on a white quiet zone', () => {
    const { container } = render(
      <QrMatrix
        label="code"
        matrix={[
          [true, false],
          [false, true],
        ]}
      />,
    )
    expect(screen.getByRole('img', { name: 'code' })).toBeInTheDocument()
    expect(container.querySelector('path')?.getAttribute('d')).toBe('M4 4h1v1h-1zM5 5h1v1h-1z')
    expect(container.querySelector('svg')?.getAttribute('viewBox')).toBe('0 0 10 10')
  })
})

describe('two-factor card', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  function renderCard(user: User) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <TwoFactorCard user={user} />
      </QueryClientProvider>,
    )
  }

  it('sets up with the password, shows the key and QR, then shows recovery codes once', async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/auth/mfa/enrol') {
        expect(JSON.parse(String(init?.body))).toEqual({ password: 'correct-horse-battery' })
        return json(200, { secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/x', qr_matrix: [[true]] })
      }
      if (url === '/api/auth/mfa/enable') {
        expect(JSON.parse(String(init?.body))).toEqual({ code: '123456' })
        return json(200, { recovery_codes: ['aaaaa-bbbbb', 'ccccc-ddddd'] })
      }
      return json(200, {})
    })
    renderCard(USER)
    expect(screen.getByText('Off')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Set up' }))
    await userEvent.type(screen.getByLabelText('Current password'), 'correct-horse-battery')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByTestId('mfa-secret')).toHaveTextContent('JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP')
    expect(screen.getByRole('img', { name: /QR code for your authenticator app/ })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Code from the app'), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Turn on' }))

    const list = await screen.findByRole('list', { name: 'Recovery codes' })
    expect(list).toHaveTextContent('aaaaa-bbbbb')
    expect(list).toHaveTextContent('ccccc-ddddd')
    await userEvent.click(screen.getByRole('button', { name: 'I have saved them' }))
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Recovery codes' })).not.toBeInTheDocument())
  })

  it('shows the server message when the code is wrong and stays on the step', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/mfa/enrol') return json(200, { secret: 'ABCDABCDABCDABCD', otpauth_uri: 'otpauth://totp/x', qr_matrix: [[true]] })
      return json(400, { detail: 'That code is not right.' })
    })
    renderCard(USER)
    await userEvent.click(screen.getByRole('button', { name: 'Set up' }))
    await userEvent.type(screen.getByLabelText('Current password'), 'correct-horse-battery')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await userEvent.type(await screen.findByLabelText('Code from the app'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not right.')
  })

  it('turns it off with the password and a code', async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/auth/mfa/disable') {
        expect(JSON.parse(String(init?.body))).toEqual({ password: 'correct-horse-battery', code: '654321' })
        return json(204)
      }
      return json(200, {})
    })
    renderCard({ ...USER, mfa_enabled: true })
    expect(screen.getByText('On')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Turn off' }))
    await userEvent.type(screen.getByLabelText('Current password'), 'correct-horse-battery')
    await userEvent.type(screen.getByLabelText('Code or recovery code'), '654321')
    await userEvent.click(screen.getAllByRole('button', { name: 'Turn off' }).at(-1)!)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/auth/mfa/disable', expect.anything()))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Two-factor sign-in is off.'))
  })
})
