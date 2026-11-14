import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, History, PackageCheck, ScanLine } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { EmptyState } from '@/components/EmptyState'
import { PageHeader } from '@/components/PageHeader'
import { RelativeTime } from '@/components/RelativeTime'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { useT, type MessageKey } from '@/lib/i18n'
import type { DispenseItem, HistoryItem } from '@/lib/types'
import { reasonText } from '@/lib/verify'
import { VERDICT_META, VERDICTS, type Verdict } from '@/lib/verdicts'
import { cn } from '@/lib/utils'

const PAGE = 20

interface Page<T> {
  items: T[]
  total: number
}

type Tab = 'checks' | 'dispensed'

function Pager({ offset, total, onChange }: { offset: number; total: number; onChange: (next: number) => void }) {
  if (total <= PAGE) return null
  const from = offset + 1
  const to = Math.min(total, offset + PAGE)
  return (
    <nav aria-label="Pages" className="mt-4 flex items-center justify-between gap-3 text-sm">
      <p className="text-muted-foreground" aria-live="polite">
        {from}–{to} of {total}
      </p>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - PAGE))}>
          <ChevronLeft aria-hidden="true" /> Newer
        </Button>
        <Button size="sm" variant="outline" disabled={to >= total} onClick={() => onChange(offset + PAGE)}>
          Older <ChevronRight aria-hidden="true" />
        </Button>
      </div>
    </nav>
  )
}

function Loading() {
  return (
    <div role="status" aria-label="Loading" className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}

function Checks() {
  const t = useT()
  const [params, setParams] = useSearchParams()
  const result = params.get('result') ?? ''
  const [offset, setOffset] = useState(0)

  const { data, isPending, isError } = useQuery({
    queryKey: ['verify-history', result, offset],
    queryFn: () => api<Page<HistoryItem>>(`/verify/history?limit=${PAGE}&offset=${offset}${result ? `&result=${result}` : ''}`),
    placeholderData: keepPreviousData,
  })

  function setResult(value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set('result', value)
    else next.delete('result')
    setParams(next, { replace: true })
    setOffset(0)
  }

  return (
    <section aria-label="Checks">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label htmlFor="history-result" className="text-sm font-medium">
          Show
        </label>
        <select
          id="history-result"
          value={result}
          onChange={(e) => setResult(e.target.value)}
          className="h-10 rounded-md border border-border-strong bg-surface px-2 text-sm"
        >
          <option value="">All results</option>
          {VERDICTS.map((v) => (
            <option key={v} value={v}>
              {t(`verdict.${v}.label` as MessageKey)}
            </option>
          ))}
        </select>
        {data && (
          <p className="text-sm text-muted-foreground">
            {data.total} {data.total === 1 ? 'check' : 'checks'}
          </p>
        )}
      </div>

      {isPending && <Loading />}
      {isError && (
        <p role="alert" className="text-danger">
          Could not load your checks. Try again.
        </p>
      )}
      {data && data.items.length === 0 && (
        <div className="rounded-lg border border-border bg-surface">
          <EmptyState
            icon={ScanLine}
            title={result ? 'No checks with that result' : 'No checks yet'}
            action={
              <Button asChild size="sm">
                <Link to="/verify">Verify a prescription</Link>
              </Button>
            }
          >
            {result ? 'Pick another result, or show all.' : 'Each prescription you verify is listed here, with the outcome.'}
          </EmptyState>
        </div>
      )}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Your recent verification checks, newest first</caption>
            <thead className="border-b border-border text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  When
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Result
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Prescription
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Why
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.items.map((item, i) => {
                const meta = VERDICT_META[item.result as Verdict]
                const Icon = meta?.icon
                return (
                  <tr key={`${item.ts}-${i}`}>
                    <td className="whitespace-nowrap px-4 py-3">
                      <RelativeTime iso={item.ts} />
                    </td>
                    <td className="px-4 py-3">
                      {meta ? (
                        <Badge tone={meta.tone}>
                          <Icon aria-hidden="true" /> {t(`verdict.${item.result}.label` as MessageKey)}
                        </Badge>
                      ) : (
                        <Badge>{item.result}</Badge>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{item.rx_ref ?? '—'}</td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {item.reasons.length ? item.reasons.map((code) => reasonText(code, t)).join(' ') : item.result === 'VALID' ? 'All checks passed.' : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager offset={offset} total={data.total} onChange={setOffset} />}
    </section>
  )
}

function Dispensed() {
  const [offset, setOffset] = useState(0)
  const { data, isPending, isError } = useQuery({
    queryKey: ['verify-dispenses', offset],
    queryFn: () => api<Page<DispenseItem>>(`/verify/dispenses?limit=${PAGE}&offset=${offset}`),
    placeholderData: keepPreviousData,
  })
  return (
    <section aria-label="Dispensed">
      {isPending && <Loading />}
      {isError && (
        <p role="alert" className="text-danger">
          Could not load your dispenses. Try again.
        </p>
      )}
      {data && data.items.length === 0 && (
        <div className="rounded-lg border border-border bg-surface">
          <EmptyState icon={PackageCheck} title="Nothing dispensed yet">
            Medicines you hand over after a successful check are recorded here.
          </EmptyState>
        </div>
      )}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Medicines you dispensed, newest first</caption>
            <thead className="border-b border-border text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  When
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Prescription
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Fill
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.items.map((item, i) => (
                <tr key={`${item.ts}-${i}`}>
                  <td className="whitespace-nowrap px-4 py-3">
                    <RelativeTime iso={item.ts} />
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{item.rx_ref}</td>
                  <td className="px-4 py-3 tabular-nums">#{item.fill_no}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager offset={offset} total={data.total} onChange={setOffset} />}
    </section>
  )
}

export default function VerifyHistory() {
  const [tab, setTab] = useState<Tab>('checks')
  return (
    <>
      <PageHeader
        title="History"
        description="Your own verification checks and dispenses. Activity by other pharmacists is not shown."
        actions={
          <Button asChild>
            <Link to="/verify">
              <ScanLine aria-hidden="true" /> Verify
            </Link>
          </Button>
        }
      />
      <div role="group" aria-label="History view" className="mb-5 inline-flex rounded-md border border-border bg-surface-2 p-0.5">
        {(
          [
            ['checks', 'Checks', History],
            ['dispensed', 'Dispensed', PackageCheck],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            aria-pressed={tab === value}
            onClick={() => setTab(value)}
            className={cn(
              'inline-flex h-10 items-center gap-2 rounded-sm px-4 text-sm font-medium transition-colors duration-150',
              tab === value ? 'bg-surface text-foreground shadow-[inset_0_0_0_1px_var(--border)]' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <Icon className="size-4" aria-hidden="true" /> {label}
          </button>
        ))}
      </div>
      {tab === 'checks' ? <Checks /> : <Dispensed />}
    </>
  )
}
