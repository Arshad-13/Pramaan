import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { toast } from 'sonner'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }))

import { AppShell } from '@/components/AppShell'
import { RequireAuth } from '@/components/RequireAuth'
import { api } from '@/lib/api'
import { AuthProvider } from '@/lib/auth'
import { DEMO_ACCOUNTS } from '@/lib/demoAccounts'
import type { User } from '@/lib/types'
import Account from '@/pages/Account'
import Activate from '@/pages/Activate'
import Login from '@/pages/Login'

const PATIENT: User = {
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
}

function json(status: number, body?: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), { status })
}

function renderAt(path: string, children: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('auth flow', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('sends signed-out visitors from a protected page to the sign-in page', async () => {
    fetchMock.mockResolvedValue(json(401, { detail: 'Not authenticated.' }))
    renderAt(
      '/admin',
      <Routes>
        <Route path="/login" element={<h1>Sign in page</h1>} />
        <Route
          path="/admin"
          element={
            <RequireAuth roles={['admin']}>
              <h1>Secret admin page</h1>
            </RequireAuth>
          }
        />
      </Routes>,
    )
    expect(await screen.findByText('Sign in page')).toBeInTheDocument()
    expect(screen.queryByText('Secret admin page')).not.toBeInTheDocument()
  })

  it('explains when a signed-in user lacks the role', async () => {
    fetchMock.mockResolvedValue(json(200, PATIENT))
    renderAt(
      '/admin',
      <Routes>
        <Route
          path="/admin"
          element={
            <RequireAuth roles={['admin']}>
              <h1>Secret admin page</h1>
            </RequireAuth>
          }
        />
      </Routes>,
    )
    expect(await screen.findByText(/does not have access/i)).toBeInTheDocument()
    expect(screen.queryByText('Secret admin page')).not.toBeInTheDocument()
  })

  it('signs in, then lands on the home page', async () => {
    let signedIn = false
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/auth/login') {
        signedIn = true
        return json(200, { access_token: 'x', token_type: 'bearer', role: 'patient', name: 'Ravi Patel' })
      }
      if (url === '/api/auth/me') return signedIn ? json(200, PATIENT) : json(401, { detail: 'no' })
      throw new Error(`unexpected ${init?.method ?? 'GET'} ${url}`)
    })
    renderAt(
      '/login',
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<h1>Home page</h1>} />
      </Routes>,
    )
    await userEvent.type(await screen.findByLabelText('Email'), 'ravi@example.test')
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse-battery')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Home page')).toBeInTheDocument()
    const loginCall = fetchMock.mock.calls.find(([u]) => u === '/api/auth/login')!
    expect(JSON.parse(loginCall[1].body)).toEqual({
      email: 'ravi@example.test',
      password: 'correct-horse-battery',
    })
  })

  it('fills the sign-in form from a demo account with one click', async () => {
    fetchMock.mockResolvedValue(json(401, { detail: 'no' }))
    renderAt('/login', <Routes><Route path="/login" element={<Login />} /></Routes>)
    await userEvent.click(await screen.findByRole('button', { name: /Dr\. Shah/ }))
    expect(screen.getByLabelText('Email')).toHaveValue('dr.shah@clinic.test')
    expect(screen.getByLabelText('Password')).toHaveValue('Doctor-Login-2026')
    await userEvent.click(screen.getByRole('button', { name: /Administrator/ }))
    expect(screen.getByLabelText('Email')).toHaveValue('admin@pramaan.test')
  })

  it('offers one demo account for every role', () => {
    const roles = new Set(DEMO_ACCOUNTS.map((a) => a.role))
    expect(roles).toEqual(new Set(['admin', 'auditor', 'doctor', 'pharmacist', 'patient']))
  })

  it('shows the server error and stays on the page when sign-in fails', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === '/api/auth/login'
        ? json(401, { detail: 'Invalid email or password.' })
        : json(401, { detail: 'no' }),
    )
    renderAt('/login', <Routes><Route path="/login" element={<Login />} /></Routes>)
    await userEvent.type(await screen.findByLabelText('Email'), 'ravi@example.test')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
  })

  it('validates empty sign-in fields without calling the API login', async () => {
    fetchMock.mockResolvedValue(json(401, { detail: 'no' }))
    renderAt('/login', <Routes><Route path="/login" element={<Login />} /></Routes>)
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter your email address.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/auth/login')).toBe(false)
  })

  it('refuses an activation where the signing password equals the login password', async () => {
    fetchMock.mockResolvedValue(json(401, { detail: 'no' }))
    renderAt('/activate', <Routes><Route path="/activate" element={<Activate />} /></Routes>)
    await userEvent.type(await screen.findByLabelText('Email'), 'dr@clinic.test')
    await userEvent.type(screen.getByLabelText('Activation code'), 'x'.repeat(24))
    await userEvent.type(screen.getByLabelText('Login password'), 'same-password-123')
    await userEvent.type(screen.getByLabelText('Choose a signing password'), 'same-password-123')
    await userEvent.click(screen.getByRole('button', { name: 'Activate account' }))
    expect(await screen.findByText(/must be different/i)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/auth/activate')).toBe(false)
  })

  it('shows the user and role-filtered navigation in the app shell, and signs out', async () => {
    let signedIn = true
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return signedIn ? json(200, PATIENT) : json(401, { detail: 'no' })
      if (url === '/api/auth/logout') {
        signedIn = false
        return json(204)
      }
      throw new Error(`unexpected ${url}`)
    })
    renderAt(
      '/',
      <Routes>
        <Route path="/login" element={<h1>Sign in page</h1>} />
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route index element={<h1>Home page</h1>} />
        </Route>
      </Routes>,
    )
    expect(await screen.findByText('Home page')).toBeInTheDocument()
    expect(screen.getAllByText('Ravi Patel').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: 'My prescriptions' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('link', { name: 'Administration' })).not.toBeInTheDocument()

    await userEvent.click(screen.getAllByRole('button', { name: 'Sign out' })[0])
    await waitFor(() => expect(screen.getByText('Sign in page')).toBeInTheDocument())
  })

  it('stays on the real sign-in page after signing out (no bounce back to the dashboard)', async () => {
    let signedIn = true
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return signedIn ? json(200, PATIENT) : json(401, { detail: 'no' })
      if (url === '/api/auth/logout') {
        signedIn = false
        return json(204)
      }
      throw new Error(`unexpected ${url}`)
    })
    renderAt(
      '/',
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route index element={<h1>Home page</h1>} />
        </Route>
      </Routes>,
    )
    expect(await screen.findByText('Home page')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Sign out' })[0])
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByText('Home page')).not.toBeInTheDocument()
  })

  it('sends the user to the sign-in page when a request finds the session has ended', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return json(200, PATIENT)
      if (url === '/api/prescriptions/mine') return json(401, { detail: 'Not authenticated.' })
      throw new Error(`unexpected ${url}`)
    })
    function Probe() {
      useEffect(() => {
        api('/prescriptions/mine').catch(() => undefined)
      }, [])
      return <h1>Home page</h1>
    }
    renderAt(
      '/',
      <Routes>
        <Route path="/login" element={<h1>Sign in page</h1>} />
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route index element={<Probe />} />
        </Route>
      </Routes>,
    )
    expect(await screen.findByText('Sign in page')).toBeInTheDocument()
    expect(screen.queryByText('Home page')).not.toBeInTheDocument()
  })

  it('changes the password from the account page and returns to sign-in with a notice', async () => {
    let signedIn = true
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/auth/me') return signedIn ? json(200, PATIENT) : json(401, { detail: 'no' })
      if (url === '/api/auth/change-password') {
        signedIn = false
        expect(JSON.parse(String(init?.body))).toEqual({
          current_password: 'old-password-123',
          new_password: 'brand-new-password-9',
        })
        return json(204)
      }
      throw new Error(`unexpected ${url}`)
    })
    renderAt(
      '/account',
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route path="account" element={<Account />} />
        </Route>
      </Routes>,
    )
    expect(await screen.findByText('K7M2-Q9XD')).toBeInTheDocument() // the patient code is shown
    await userEvent.type(screen.getByLabelText('Current password'), 'old-password-123')
    await userEvent.type(screen.getByLabelText('New password'), 'brand-new-password-9')
    await userEvent.type(screen.getByLabelText('New password again'), 'brand-new-password-9')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('Password changed'))
  })

  it('checks the new password on the account page before calling the server', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return json(200, PATIENT)
      throw new Error(`unexpected ${url}`)
    })
    renderAt(
      '/account',
      <Routes>
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route path="account" element={<Account />} />
        </Route>
      </Routes>,
    )
    await userEvent.type(await screen.findByLabelText('Current password'), 'same-password-123')
    await userEvent.type(screen.getByLabelText('New password'), 'same-password-123')
    await userEvent.type(screen.getByLabelText('New password again'), 'different-password-1')
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByText('The two new passwords do not match.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => u === '/api/auth/change-password')).toBe(false)
  })

  it('stays signed in and says so when the sign-out request cannot reach the server', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return json(200, PATIENT)
      throw new TypeError('network down')
    })
    renderAt(
      '/',
      <Routes>
        <Route path="/login" element={<h1>Sign in page</h1>} />
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route index element={<h1>Home page</h1>} />
        </Route>
      </Routes>,
    )
    expect(await screen.findByText('Home page')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Sign out' })[0])
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(screen.getByText('Home page')).toBeInTheDocument()
    expect(screen.queryByText('Sign in page')).not.toBeInTheDocument()
  })
})
