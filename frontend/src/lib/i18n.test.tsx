import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LocaleProvider } from '@/components/LocaleProvider'
import { AuthProvider } from '@/lib/auth'
import { initialLocale, LOCALES, translate } from '@/lib/i18n'
import { en } from '@/lib/i18n/en'
import { gu } from '@/lib/i18n/gu'
import { hi } from '@/lib/i18n/hi'
import { REASON_TEXT, reasonText } from '@/lib/verify'
import type { VerifyResult } from '@/lib/types'
import Login from '@/pages/Login'
import Verify from '@/pages/Verify'

vi.mock('qr-scanner', () => ({
  default: class {
    start() {
      return Promise.resolve()
    }
    stop() {}
    destroy() {}
  },
}))

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
const json = (status: number, body?: unknown) => new Response(body === undefined ? null : JSON.stringify(body), { status })

describe('message catalogues', () => {
  const keys = Object.keys(en) as (keyof typeof en)[]

  it('give every language every message, never empty', () => {
    for (const [name, catalogue] of [['hi', hi], ['gu', gu]] as const) {
      expect(Object.keys(catalogue).sort(), name).toEqual([...keys].sort())
      for (const key of keys) expect(catalogue[key].trim(), `${name} ${key}`).not.toBe('')
    }
  })

  it('keep the same {placeholders} as English, so no number is dropped from a sentence', () => {
    for (const key of keys) {
      expect(placeholders(hi[key]), `hi ${key}`).toEqual(placeholders(en[key]))
      expect(placeholders(gu[key]), `gu ${key}`).toEqual(placeholders(en[key]))
    }
  })

  it('translate() fills placeholders and falls back to English text only when a key is unknown', () => {
    expect(translate('hi', 'pin.changesIn', { n: 12 })).toContain('12')
    expect(translate('gu', 'dispense.done', { n: 2 })).toContain('2')
    expect(translate('en', 'pin.changesIn', { n: 5 })).toBe('It changes in 5 s')
  })

  it('give every server reason code a message in every language', () => {
    for (const code of Object.keys(REASON_TEXT)) {
      expect(hi[`reason.${code}` as keyof typeof hi]).toBeTruthy()
      expect(gu[`reason.${code}` as keyof typeof gu]).toBeTruthy()
    }
    expect(reasonText('RX_REVOKED', (key) => translate('hi', key))).toBe(hi['reason.RX_REVOKED'])
    expect(reasonText('SOMETHING_NEW', (key) => translate('hi', key))).toBe('SOMETHING_NEW')
  })

  it('names every language in itself', () => {
    expect(LOCALES.map((l) => l.name)).toEqual(['English', 'हिन्दी', 'ગુજરાતી'])
  })
})

describe('choosing a language', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.lang = 'en'
    fetchMock.mockReset()
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/public-config') return json(200, { demo_mode: false })
      return json(401, { detail: 'Not authenticated.' })
    })
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  function renderApp(children: React.ReactNode) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <LocaleProvider>
        <QueryClientProvider client={client}>
          <AuthProvider>
            <MemoryRouter>{children}</MemoryRouter>
          </AuthProvider>
        </QueryClientProvider>
      </LocaleProvider>,
    )
  }

  it('switches the sign-in page to Hindi and Gujarati, sets <html lang>, and remembers the choice', async () => {
    renderApp(<Login />)
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Language'), 'hi')
    expect(screen.getByRole('heading', { name: hi['login.title'] })).toBeInTheDocument()
    expect(screen.getByLabelText(hi['login.email'])).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('hi')
    expect(localStorage.getItem('pramaan.lang')).toBe('hi')

    await userEvent.selectOptions(screen.getByLabelText(hi['shell.language']), 'gu')
    expect(screen.getByRole('heading', { name: gu['login.title'] })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('gu')
  })

  it('translates form validation messages too', async () => {
    renderApp(<Login />)
    await userEvent.selectOptions(await screen.findByLabelText('Language'), 'hi')
    await userEvent.click(screen.getByRole('button', { name: hi['login.submit'] }))
    expect(await screen.findByText(hi['login.emailRequired'])).toBeInTheDocument()
  })

  it('starts in the saved language, then the browser language, then English', () => {
    localStorage.setItem('pramaan.lang', 'gu')
    expect(initialLocale()).toBe('gu')
    localStorage.setItem('pramaan.lang', 'xx')
    expect(initialLocale()).toBe('en') // jsdom reports en-US
  })

  it('shows the verification verdict, the next step and the reasons in the chosen language', async () => {
    localStorage.setItem('pramaan.lang', 'hi')
    const revoked: VerifyResult = {
      result: 'REVOKED',
      reason_codes: ['RX_REVOKED'],
      rx_id: 'rx-1',
      checks: null,
      risk: null,
      warnings: [],
      doctor: null,
      patient: null,
      medicines: null,
      issued_at: null,
      expires_at: null,
      can_dispense: false,
      pin_required: false,
    }
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/public-config') return json(200, { demo_mode: false })
      if (url === '/api/auth/me')
        return json(200, { public_id: 'ph1', email: 'm@x.test', name: 'Meera', role: 'pharmacist', license_no: 'P', org_name: 'O', patient_code: null, approval_status: 'APPROVED', is_active: true, created_at: '2026-10-18T10:00:00Z' })
      if (url === '/api/verify/qr') return json(200, revoked)
      throw new Error(`unexpected ${url}`)
    })
    renderApp(<Verify />)
    await userEvent.click(await screen.findByRole('tab', { name: hi['verify.tab.paste'] }))
    await userEvent.type(screen.getByLabelText(hi['verify.codeLabel']), 'PRM2.' + 'x'.repeat(40) + '{Enter}')
    const verdict = await screen.findByRole('region', { name: hi['verify.resultLabel'] })
    expect(within(verdict).getByRole('heading', { name: hi['verdict.REVOKED.label'] })).toBeInTheDocument()
    expect(within(verdict).getByText(hi['next.revoked'])).toBeInTheDocument()
    expect(within(verdict).getByText(hi['reason.RX_REVOKED'])).toBeInTheDocument()
  })
})
