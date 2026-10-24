import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react'

import { api, ApiError } from '@/lib/api'
import type { User } from '@/lib/types'

interface AuthValue {
  /** undefined while the first check is in flight, null when signed out. */
  user: User | null | undefined
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
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

  const signIn = useCallback(
    async (email: string, password: string) => {
      await api('/auth/login', { method: 'POST', body: { email, password } })
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
    // Mark the visitor signed out first: the mounted 'me' query must keep its observer, or the
    // UI keeps showing the old user and the login page bounces straight back to the dashboard.
    queryClient.setQueryData(['me'], null)
    // Then drop everything else so no one sees another user's data.
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' })
  }, [queryClient])

  const value = useMemo(() => ({ user, signIn, signOut }), [user, signIn, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
