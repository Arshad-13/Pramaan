/** Thin fetch wrapper for the Pramaan API (same origin, cookie session, CSRF header). */

export class ApiError extends Error {
  status: number
  /** The parsed JSON error body, when there was one (for structured codes such as risk prompts). */
  body: unknown
  constructor(status: number, message: string, body: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export const CSRF_COOKIE = 'pramaan_csrf'
export const CSRF_HEADER = 'X-CSRF-Token'

/** The CSRF token is a readable cookie set at sign-in; echo it on every state-changing request. */
export function readCsrfToken(cookie: string = document.cookie): string | null {
  for (const part of cookie.split(';')) {
    const [name, ...rest] = part.trim().split('=')
    if (name === CSRF_COOKIE) return decodeURIComponent(rest.join('='))
  }
  return null
}

interface FastApiValidationItem {
  loc?: (string | number)[]
  msg?: string
}

/** Turn FastAPI's `detail` (a string, or a list of validation errors) into one readable line. */
export function formatDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = (detail as FastApiValidationItem[])
      .map((item) => {
        const field = item.loc?.filter((p) => p !== 'body').join('.')
        const msg = (item.msg ?? '').replace(/^Value error, /, '')
        return field ? `${field}: ${msg}` : msg
      })
      .filter(Boolean)
    if (parts.length) return parts.join('; ')
  }
  return fallback
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
}

export async function api<T = void>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  const isForm = typeof FormData !== 'undefined' && options.body instanceof FormData
  // A multipart body sets its own Content-Type (with the boundary), so only JSON needs one.
  if (options.body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') {
    const csrf = readCsrfToken()
    if (csrf) headers[CSRF_HEADER] = csrf
  }

  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: options.body === undefined ? undefined : isForm ? (options.body as FormData) : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your connection and try again.')
  }

  if (response.status === 204) return undefined as T
  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    /* empty or non-JSON body */
  }
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail
    throw new ApiError(response.status, formatDetail(detail, `Request failed (${response.status})`), data)
  }
  return data as T
}
