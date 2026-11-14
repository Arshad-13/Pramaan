import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { api, ApiError } from '@/lib/api'
import { useT } from '@/lib/i18n'
import type { PinInfo } from '@/lib/types'

const R = 54
const CIRC = 2 * Math.PI * R

/**
 * The dispense PIN, full screen: large enough to read across a pharmacy counter, with a countdown
 * ring. Closes with the button or Escape. A new PIN is fetched when the step ends.
 */
export function PinScreen({ rxId, title, onClose }: { rxId: string; title: string; onClose: () => void }) {
  const t = useT()
  const closeRef = useRef<HTMLButtonElement>(null)
  const { data, isPending, error, dataUpdatedAt } = useQuery({
    queryKey: ['pin', rxId],
    queryFn: () => api<PinInfo>(`/prescriptions/${rxId}/pin`),
    gcTime: 0,
    staleTime: 0,
    refetchInterval: (query) => (query.state.data ? query.state.data.seconds_remaining * 1000 + 400 : false),
  })

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [onClose])

  const left = data ? Math.max(0, data.seconds_remaining - (now - dataUpdatedAt) / 1000) : 0
  const fraction = data ? Math.min(1, left / data.step_seconds) : 0
  const blocked = error instanceof ApiError && error.status === 409

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`PIN for ${title}`}
      className="fixed inset-0 z-[var(--z-modal)] flex flex-col items-center justify-center gap-8 bg-background px-6"
    >
      <Button ref={closeRef} variant="ghost" size="icon" aria-label={t('pin.close')} onClick={onClose} className="absolute right-4 top-4">
        <X aria-hidden="true" />
      </Button>
      <div className="text-center">
        <p className="text-sm text-muted-foreground">{t('pin.intro')}</p>
        <p className="mt-1 font-serif text-xl font-semibold">{title}</p>
      </div>
      {isPending ? (
        <Skeleton className="h-28 w-72" />
      ) : error || !data ? (
        <p role="alert" className="max-w-sm text-center text-danger">
          {blocked ? t('pin.blocked') : t('pin.error')}
        </p>
      ) : (
        <>
          <div className="relative grid place-items-center">
            <svg viewBox="0 0 128 128" className="size-64 -rotate-90 sm:size-72" aria-hidden="true">
              <circle cx="64" cy="64" r={R} fill="none" stroke="var(--border)" strokeWidth="6" />
              <circle
                cx="64"
                cy="64"
                r={R}
                fill="none"
                stroke="var(--verified-solid)"
                strokeWidth="6"
                strokeLinecap="round"
                strokeDasharray={CIRC}
                strokeDashoffset={CIRC * (1 - fraction)}
              />
            </svg>
            <p className="absolute whitespace-pre font-mono text-4xl font-semibold tracking-[0.08em] [font-variant-numeric:tabular-nums] sm:text-5xl">
              {`${data.pin.slice(0, 3)} ${data.pin.slice(3)}`}
            </p>
          </div>
          <p className="text-muted-foreground" aria-live="off">
            {t('pin.changesIn', { n: Math.ceil(left) })}
          </p>
        </>
      )}
    </div>
  )
}
