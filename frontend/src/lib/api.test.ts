import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, formatDetail, readCsrfToken } from './api'
import { navFor } from './nav'

function respond(status: number, body?: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), { status })
}

describe('readCsrfToken', () => {
  it('finds the token among other cookies', () => {
    expect(readCsrfToken('a=1; pramaan_csrf=abc123; b=2')).toBe('abc123')
  })
  it('returns null when absent', () => {
    expect(readCsrfToken('a=1; b=2')).toBeNull()
  })
  it('does not match a cookie that merely contains the name', () => {
    expect(readCsrfToken('x_pramaan_csrf=evil')).toBeNull()
  })
})

describe('formatDetail', () => {
  it('passes strings through', () => {
    expect(formatDetail('Nope', 'fallback')).toBe('Nope')
  })
  it('summarises FastAPI validation errors', () => {
    const detail = [{ loc: ['body', 'email'], msg: 'Value error, not a valid email address' }]
    expect(formatDetail(detail, 'fallback')).toBe('email: not a valid email address')
  })
  it('falls back for unknown shapes', () => {
    expect(formatDetail(undefined, 'fallback')).toBe('fallback')
    expect(formatDetail([], 'fallback')).toBe('fallback')
  })
})

describe('api()', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    document.cookie = 'pramaan_csrf=; max-age=0'
  })
  afterEach(() => vi.unstubAllGlobals())

  it('sends the CSRF header on state-changing requests only', async () => {
    document.cookie = 'pramaan_csrf=token-xyz'
    fetchMock.mockResolvedValue(respond(200, { ok: true }))
    await api('/things', { method: 'POST', body: { a: 1 } })
    await api('/things')
    const [, post] = fetchMock.mock.calls[0]
    const [, get] = fetchMock.mock.calls[1]
    expect(post.headers['X-CSRF-Token']).toBe('token-xyz')
    expect(post.headers['Content-Type']).toBe('application/json')
    expect(get.headers['X-CSRF-Token']).toBeUndefined()
    expect(post.credentials).toBe('same-origin')
  })

  it('targets /api and serialises the body', async () => {
    fetchMock.mockResolvedValue(respond(200, {}))
    await api('/auth/login', { method: 'POST', body: { email: 'a@b.test' } })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/login')
    expect(fetchMock.mock.calls[0][1].body).toBe('{"email":"a@b.test"}')
  })

  it('returns undefined for 204', async () => {
    fetchMock.mockResolvedValue(respond(204))
    await expect(api('/auth/logout', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('throws ApiError with the server message and status', async () => {
    fetchMock.mockResolvedValue(respond(401, { detail: 'Invalid email or password.' }))
    await expect(api('/auth/login', { method: 'POST', body: {} })).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
      message: 'Invalid email or password.',
    })
  })

  it('copes with a non-JSON error body', async () => {
    fetchMock.mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502 }))
    const error = await api('/x').catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(502)
  })

  it('reports an unreachable server as status 0', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(api('/x')).rejects.toMatchObject({ status: 0 })
  })
})

describe('navFor', () => {
  const labels = (role?: Parameters<typeof navFor>[0]) => navFor(role).map((n) => n.label)
  it('shows each role only its own destinations', () => {
    expect(labels('patient')).toContain('My prescriptions')
    expect(labels('patient')).not.toContain('Administration')
    expect(labels('doctor')).toEqual(expect.arrayContaining(['New prescription', 'My prescriptions']))
    expect(labels('pharmacist')).toContain('Verify')
    expect(labels('admin')).toContain('Administration')
    expect(labels('admin')).not.toContain('Audit log')
    expect(labels('auditor')).toContain('Audit log')
  })
  it('shows only common entries when there is no role', () => {
    expect(labels(undefined)).not.toContain('Administration')
  })
})
