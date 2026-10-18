import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError } from '@/lib/api'
import type { PinInfo } from '@/lib/types'

const R = 26
const CIRC = 2 * Math.PI * R

/** The patient's dispense PIN with a countdown ring. A new PIN is fetched when the step ends. */
export function PinRing({ rxId }: { rxId: string }) {
  const { data, isPending, error, dataUpdatedAt } = useQuery({
    queryKey: ['pin', rxId],
    queryFn: () => api<PinInfo>(`/prescriptions/${rxId}/pin`),
    gcTime: 0,
    staleTime: 0,
    // Fetch the next PIN right after this one expires.
    refetchInterval: (query) => (query.state.data ? query.state.data.seconds_remaining * 1000 + 400 : false),
  })

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(id)
  }, [])

  if (isPending) return <Skeleton className="h-20 w-64" />
  if (error || !data) {
    return (
      <p role="alert" className="text-sm text-danger">
        {error instanceof ApiError && error.status === 409
          ? 'This prescription can no longer be dispensed.'
          : 'Could not load the PIN. Try again.'}
      </p>
    )
  }

  const left = Math.max(0, data.seconds_remaining - (now - dataUpdatedAt) / 1000)
  const fraction = Math.min(1, left / data.step_seconds)

  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 64 64" className="size-16 shrink-0 -rotate-90" aria-hidden="true">
        <circle cx="32" cy="32" r={R} fill="none" stroke="var(--border)" strokeWidth="5" />
        <circle
          cx="32"
          cy="32"
          r={R}
          fill="none"
          stroke="var(--verified-solid)"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={CIRC}
          strokeDashoffset={CIRC * (1 - fraction)}
        />
      </svg>
      <div>
        <p className="font-mono text-3xl font-semibold tracking-[0.25em] [font-variant-numeric:tabular-nums]" aria-label={`PIN ${data.pin.split('').join(' ')}`}>
          {data.pin.slice(0, 3)} {data.pin.slice(3)}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Show this to the pharmacist. It changes in {Math.ceil(left)} s.
        </p>
      </div>
    </div>
  )
}
