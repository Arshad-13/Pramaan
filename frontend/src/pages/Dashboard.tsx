import { useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleX } from 'lucide-react'

import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/auth'
import { ROLE_LABEL, type Role } from '@/lib/types'

async function fetchHealth(): Promise<{ status: string }> {
  const response = await fetch('/api/health', { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`health ${response.status}`)
  return response.json()
}

const ROLE_HINT: Record<Role, string> = {
  doctor: 'Issue signed prescriptions and see their status.',
  patient: 'See your prescriptions and the code to show at the pharmacy.',
  pharmacist: 'Scan a prescription to check it and dispense.',
  admin: 'Approve pharmacists, create doctor accounts and manage access.',
  auditor: 'Review the audit log and check that it has not been altered.',
}

function ServiceStatus() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 15_000,
    retry: 1,
  })

  if (isPending) return <Skeleton className="h-6 w-28" />
  if (isError || data?.status !== 'ok') {
    return (
      <Badge tone="danger">
        <CircleX aria-hidden="true" /> Unreachable
      </Badge>
    )
  }
  return (
    <Badge tone="verified">
      <CircleCheck aria-hidden="true" /> Running
    </Badge>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const firstName = user?.name.split(' ')[0]
  return (
    <>
      <PageHeader
        title={firstName ? `Welcome, ${firstName}` : 'Overview'}
        description={user ? ROLE_HINT[user.role] : undefined}
      />
      <section aria-labelledby="account-heading" className="max-w-xl rounded-lg border border-border bg-surface">
        <h2 id="account-heading" className="border-b border-border px-5 py-3 text-sm font-semibold">
          Your account
        </h2>
        <dl className="divide-y divide-border text-sm">
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-muted-foreground">Role</dt>
            <dd>{user ? ROLE_LABEL[user.role] : ''}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-muted-foreground">Email</dt>
            <dd className="truncate">{user?.email}</dd>
          </div>
          {user?.patient_code && (
            <div className="flex items-center justify-between gap-4 px-5 py-3">
              <dt className="text-muted-foreground">Patient code</dt>
              <dd className="font-mono tracking-wide">{user.patient_code}</dd>
            </div>
          )}
          {user?.license_no && (
            <div className="flex items-center justify-between gap-4 px-5 py-3">
              <dt className="text-muted-foreground">Licence number</dt>
              <dd>{user.license_no}</dd>
            </div>
          )}
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-muted-foreground">Service</dt>
            <dd aria-live="polite">
              <ServiceStatus />
            </dd>
          </div>
        </dl>
      </section>
    </>
  )
}
