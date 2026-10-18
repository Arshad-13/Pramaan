import { useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleX } from 'lucide-react'

import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'

async function fetchHealth(): Promise<{ status: string }> {
  const response = await fetch('/api/health', { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`health ${response.status}`)
  return response.json()
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
  return (
    <>
      <PageHeader
        title="Overview"
        description="Doctors issue signed prescriptions. Pharmacists verify them. Every decision is recorded in a tamper-evident log."
      />
      <section aria-labelledby="service-heading" className="max-w-xl rounded-lg border border-border bg-surface">
        <h2 id="service-heading" className="border-b border-border px-5 py-3 text-sm font-semibold">
          Service
        </h2>
        <dl className="divide-y divide-border text-sm">
          <div className="flex items-center justify-between px-5 py-3">
            <dt className="text-muted-foreground">API</dt>
            <dd aria-live="polite">
              <ServiceStatus />
            </dd>
          </div>
          <div className="flex items-center justify-between px-5 py-3">
            <dt className="text-muted-foreground">Sign-in</dt>
            <dd>
              <Badge>Available after Phase 3</Badge>
            </dd>
          </div>
        </dl>
      </section>
    </>
  )
}
