import { ShieldAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/auth'
import type { Role } from '@/lib/types'

/** Redirects signed-out visitors to /login; shows a clear message if the role does not fit. */
export function RequireAuth({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user } = useAuth()
  const location = useLocation()

  if (user === undefined) {
    return (
      <div role="status" aria-label="Loading" className="space-y-3 p-10">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-24 w-full max-w-xl" />
      </div>
    )
  }
  if (user === null) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (roles && !roles.includes(user.role)) {
    return (
      <>
        <PageHeader title="Not available" />
        <div className="flex max-w-xl items-start gap-3 rounded-lg border border-border bg-surface p-5">
          <ShieldAlert className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <p>Your account does not have access to this page.</p>
        </div>
      </>
    )
  }
  return <>{children}</>
}
