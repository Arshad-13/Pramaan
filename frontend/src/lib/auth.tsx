import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { toast } from 'sonner'

import { api, ApiError, setSessionEndedHandler } from '@/lib/api'
import type { User } from '@/lib/types'

/** What the password step produced: a session, or a request for the second step. */
export type SignInResult = { status: 'signed-in' } | { status: 'mfa'; mfaToken: string }

interface AuthValue {
  /** undefined while the first check is in flight, null when signed out. */
  user: User | null | undefined
  signIn: (email: string, password: string) => Promise<SignInResult>
  /** Second sign-in step: a code from the authenticator app, or a recovery code. */
  completeMfa: (mfaToken: string, code: string) => Promise<void>
  signOut: () => Promise<void>
  /** Forget the local session without calling the server (it already ended every session). */
  endSession: () => void
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const { data: user } = useQuery({
    queryKey: ['me'],
    queryFn: async (): Promise<User | null> => {
      try {
        return await api<User>('/auth/me')
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    staleTime: 60_000,
    retry: false,
  })

  const endSession = useCallback(() => {
    // Mark the visitor signed out first: the mounted 'me' query must keep its observer, or the
    // UI keeps showing the old user and the login page bounces straight back to the dashboard.
    queryClient.setQueryData(['me'], null)
    // Then drop everything else so no one sees another user's data.
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' })
  }, [queryClient])

  // A 401 on any signed-in request means the session ended (expired, or ended elsewhere). Say so
  // once, drop the cached user and data, and RequireAuth sends the visitor to the sign-in page.
  useEffect(
    () =>
      setSessionEndedHandler(() => {
        if (queryClient.getQueryData(['me']) == null) return // already signed out: stay quiet
        endSession()
        toast.info('Your session ended. Sign in again to continue.')
      }),
    [queryClient, endSession],
  )

  const signIn = useCallback(
    async (email: string, password: string): Promise<SignInResult> => {
      const result = await api<{ mfa_required?: boolean; mfa_token?: string }>('/auth/login', {
        method: 'POST',
        body: { email, password },
      })
      if (result?.mfa_required && result.mfa_token) return { status: 'mfa', mfaToken: result.mfa_token }
      await queryClient.invalidateQueries({ queryKey: ['me'] })
      return { status: 'signed-in' }
    },
    [queryClient],
  )

  const completeMfa = useCallback(
    async (mfaToken: string, code: string) => {
      await api('/auth/login/mfa', { method: 'POST', body: { mfa_token: mfaToken, code } })
      await queryClient.invalidateQueries({ queryKey: ['me'] })
    },
    [queryClient],
  )

  const signOut = useCallback(async () => {
    try {
      await api('/auth/logout', { method: 'POST' })
    } catch (error) {
      // 401 means the session was already gone, which is the state we wanted. Anything else
      // (offline, server error) leaves the session alive, so say so instead of pretending.
      if (!(error instanceof ApiError && error.status === 401)) throw error
    }
    endSession()
  }, [endSession])

  const value = useMemo(
    () => ({ user, signIn, completeMfa, signOut, endSession }),
    [user, signIn, completeMfa, signOut, endSession],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
