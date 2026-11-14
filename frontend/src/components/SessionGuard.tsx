import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { toast } from 'sonner'

import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { planSessionWarning } from '@/lib/session'
import { clockTime } from '@/lib/time'

const TOAST_ID = 'session-expiry'

/**
 * Tells the person, before it happens, that their session is about to end, and offers to renew it.
 * Renewal is a deliberate click ("Stay signed in"), never automatic, and the server will not renew
 * past the hard limit: then the message says when the limit is, so the person can finish and sign in
 * again rather than lose work to a silent expiry.
 */
export function SessionGuard() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const expiresAt = user?.session_expires_at
  const endsBy = user?.session_ends_by

  useEffect(() => {
    if (!expiresAt) return
    const { delayMs, canRenew } = planSessionWarning(expiresAt, endsBy)
    const timer = window.setTimeout(() => {
      if (canRenew) {
        toast.warning('Your session ends in about 2 minutes.', {
          id: TOAST_ID,
          duration: Infinity,
          action: {
            label: 'Stay signed in',
            onClick: () => {
              api('/auth/refresh', { method: 'POST' })
                .then(() => queryClient.invalidateQueries({ queryKey: ['me'] }))
                .then(() => toast.success('Session renewed.', { id: TOAST_ID, duration: 4000 }))
                .catch(() => toast.error('Could not renew the session. Save your work and sign in again.', { id: TOAST_ID }))
            },
          },
        })
      } else {
        toast.warning(
          `Your session ends in about 2 minutes and cannot be extended further (limit ${clockTime(endsBy ?? expiresAt)}). Finish up and sign in again.`,
          { id: TOAST_ID, duration: Infinity },
        )
      }
    }, delayMs)
    return () => {
      window.clearTimeout(timer)
      toast.dismiss(TOAST_ID)
    }
  }, [expiresAt, endsBy, queryClient])

  return null
}
