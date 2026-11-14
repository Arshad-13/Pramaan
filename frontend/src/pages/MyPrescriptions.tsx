import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Copy, FileDown, FilePlus2, FilePenLine, KeyRound, Search, SearchX } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { EmptyState } from '@/components/EmptyState'
import { PageHeader } from '@/components/PageHeader'
import { PinScreen } from '@/components/PinScreen'
import { RelativeTime } from '@/components/RelativeTime'
import { RxStatusBadge } from '@/components/RxStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { formatDate, medicineSummary } from '@/lib/rx'
import { exactTime } from '@/lib/time'
import type { Prescription, RxStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

type StatusFilter = 'ALL' | RxStatus | 'FLAGGED'

const STATUS_LABEL: Record<RxStatus, string> = { ISSUED: 'Issued', DISPENSED: 'Dispensed', EXPIRED: 'Expired', REVOKED: 'Revoked' }

function matches(rx: Prescription, query: string): boolean {
  if (!query) return true
  const haystack = [rx.patient_name, rx.doctor_name, rx.id, rx.fingerprint, ...rx.medicines.map((m) => m.name)].join(' ').toLowerCase()
  return query
    .toLowerCase()
    .split(/\s+/)
    .every((word) => haystack.includes(word))
}

function Details({ rx, isDoctor }: { rx: Prescription; isDoctor: boolean }) {
  const fills = rx.fills ?? []
  return (
    <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-xs text-muted-foreground">Handed over</dt>
        <dd>
          {fills.length === 0 ? (
            <span className="text-muted-foreground">Not yet.</span>
          ) : (
            <ul className="space-y-0.5">
              {fills.map((f) => (
                <li key={f.fill_no}>
                  Fill {f.fill_no}
                  {f.pharmacy && <> · {f.pharmacy}</>} · <span title={exactTime(f.ts)}>{exactTime(f.ts)}</span>
                </li>
              ))}
            </ul>
          )}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Valid</dt>
        <dd>
          {exactTime(rx.issued_at)} to {formatDate(rx.expires_at)}
        </dd>
      </div>
      {rx.notes && (
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted-foreground">Notes</dt>
          <dd className="whitespace-pre-wrap">{rx.notes}</dd>
        </div>
      )}
      {rx.superseded_by && (
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted-foreground">Replaced</dt>
          <dd>
            A corrected prescription replaced this one.{' '}
            {isDoctor && (
              <span className="font-mono text-xs text-muted-foreground" title="Id of the corrected prescription">
                {rx.superseded_by.slice(0, 8)}
              </span>
            )}
          </dd>
        </div>
      )}
      <div className="sm:col-span-2">
        <dt className="text-xs text-muted-foreground">Signing key</dt>
        <dd className="font-mono text-xs">{rx.key_id}</dd>
      </div>
    </dl>
  )
}

export default function MyPrescriptions() {
  const { user } = useAuth()
  const isDoctor = user?.role === 'doctor'
  const isPatient = user?.role === 'patient'
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [confirming, setConfirming] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  const query = params.get('q') ?? ''
  const status = (params.get('status') ?? 'ALL') as StatusFilter
  const pinFor = params.get('pin')

  const { data, isPending, isError } = useQuery({
    queryKey: ['prescriptions', 'mine'],
    queryFn: () => api<Prescription[]>('/prescriptions/mine'),
  })

  const revoke = useMutation({
    mutationFn: (id: string) => api<Prescription>(`/prescriptions/${id}/revoke`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Prescription revoked. It will no longer verify.')
      setConfirming(null)
      void queryClient.invalidateQueries({ queryKey: ['prescriptions'] })
    },
    onError: (e) => {
      toast.error(e instanceof ApiError ? e.message : 'Could not revoke. Try again.')
      setConfirming(null)
    },
  })

  function setParam(name: string, value: string | null) {
    const next = new URLSearchParams(params)
    if (value) next.set(name, value)
    else next.delete(name)
    setParams(next, { replace: true })
  }

  const all = useMemo(() => data ?? [], [data])
  const counts = useMemo(() => {
    const c: Record<string, number> = { ALL: all.length, FLAGGED: all.filter((r) => r.flagged).length }
    for (const rx of all) c[rx.status] = (c[rx.status] ?? 0) + 1
    return c
  }, [all])
  const shown = all.filter((rx) => (status === 'ALL' ? true : status === 'FLAGGED' ? rx.flagged : rx.status === status) && matches(rx, query))

  const chips: StatusFilter[] = ['ALL', 'ISSUED', 'DISPENSED', 'EXPIRED', 'REVOKED', ...(isDoctor && counts.FLAGGED ? (['FLAGGED'] as const) : [])]
  const pinRx = pinFor ? all.find((r) => r.id === pinFor && r.status === 'ISSUED' && r.require_pin) : undefined

  return (
    <>
      <PageHeader
        title="My prescriptions"
        description={isDoctor ? 'Prescriptions you have issued.' : 'Prescriptions issued to you.'}
        actions={
          isDoctor ? (
            <Button asChild>
              <Link to="/prescriptions/new">
                <FilePlus2 aria-hidden="true" /> New prescription
              </Link>
            </Button>
          ) : undefined
        }
      />

      {pinRx && <PinScreen rxId={pinRx.id} title={pinRx.doctor_name ?? 'Your prescription'} onClose={() => setParam('pin', null)} />}

      {isPending && (
        <div role="status" aria-label="Loading" className="space-y-3">
          <Skeleton className="h-10 w-full max-w-md" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}
      {isError && (
        <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
          Could not load your prescriptions. Refresh to try again.
        </p>
      )}
      {data && data.length === 0 && (
        <div className="max-w-2xl rounded-lg border border-dashed border-border-strong bg-surface">
          {isDoctor ? (
            <EmptyState
              icon={FilePlus2}
              title="You have not issued any prescriptions yet."
              action={
                <Button asChild>
                  <Link to="/prescriptions/new">Write the first one</Link>
                </Button>
              }
            >
              Each one is signed with your key and gets a QR code the pharmacist can check.
            </EmptyState>
          ) : (
            <EmptyState icon={FilePlus2} title="Nothing here yet">
              Prescriptions your doctor issues to you will appear here, with a PDF you can show at the pharmacy. Your patient code is on the Account page.
            </EmptyState>
          )}
        </div>
      )}

      {data && data.length > 0 && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <div className="relative w-full max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input
                type="search"
                aria-label="Search prescriptions"
                placeholder={isDoctor ? 'Search patient or medicine' : 'Search doctor or medicine'}
                defaultValue={query}
                onChange={(e) => setParam('q', e.target.value.trim() || null)}
                className="pl-9"
              />
            </div>
            <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-1.5">
              {chips.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  aria-pressed={status === chip}
                  onClick={() => setParam('status', chip === 'ALL' ? null : chip)}
                  className={cn(
                    'inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-sm transition-colors duration-150',
                    status === chip ? 'border-foreground bg-foreground text-background' : 'border-border bg-surface text-muted-foreground hover:text-foreground',
                  )}
                >
                  {chip === 'ALL' ? 'All' : chip === 'FLAGGED' ? 'Flagged' : STATUS_LABEL[chip]}
                  <span className="tabular-nums">{counts[chip] ?? 0}</span>
                </button>
              ))}
            </div>
          </div>

          {shown.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border-strong bg-surface">
              <EmptyState
                icon={SearchX}
                title="No prescriptions match"
                action={
                  <Button variant="outline" size="sm" onClick={() => setParams(new URLSearchParams(), { replace: true })}>
                    Clear filters
                  </Button>
                }
              >
                Try a different word, or show all statuses.
              </EmptyState>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border bg-surface">
              <table className="w-full min-w-[46rem] text-left text-sm">
                <caption className="sr-only">Prescriptions</caption>
                <thead className="bg-surface-2 text-xs text-muted-foreground">
                  <tr>
                    <th scope="col" className="px-4 py-2.5 font-medium">Issued</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">{isDoctor ? 'Patient' : 'Doctor'}</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Medicines</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Fills</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
                    <th scope="col" className="px-4 py-2.5 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {shown.map((rx) => (
                    <Fragment key={rx.id}>
                      <tr className="align-top">
                        <td className="whitespace-nowrap px-4 py-3">
                          {formatDate(rx.issued_at)}
                          <p className="text-xs text-muted-foreground">
                            <RelativeTime iso={rx.issued_at} /> · until {formatDate(rx.expires_at)}
                          </p>
                        </td>
                        <td className="px-4 py-3">{(isDoctor ? rx.patient_name : rx.doctor_name) ?? 'Unavailable'}</td>
                        <td className="px-4 py-3">
                          {rx.medicines.length === 0 ? (
                            <span className="text-muted-foreground">Unavailable</span>
                          ) : (
                            <ul className="space-y-0.5">
                              {rx.medicines.map((m, i) => (
                                <li key={i}>{medicineSummary(m)}</li>
                              ))}
                            </ul>
                          )}
                          <p className="mt-1 font-mono text-xs tracking-wide text-muted-foreground" title="Fingerprint">
                            {rx.fingerprint}
                          </p>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3">
                          {rx.fills_used} of {rx.max_fills}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-col items-start gap-1.5">
                            <RxStatusBadge status={rx.status} readable={rx.readable} />
                            {isDoctor && rx.risk_score != null && rx.risk_score > 0 && (
                              <Badge tone={rx.flagged ? 'warning' : 'neutral'}>Risk {rx.risk_score}</Badge>
                            )}
                            {rx.superseded_by && <Badge>Replaced</Badge>}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="inline-flex flex-wrap justify-end gap-2">
                            <Button asChild size="sm" variant="outline">
                              <a href={`/api/prescriptions/${rx.id}/pdf`} target="_blank" rel="noopener">
                                <FileDown aria-hidden="true" /> PDF
                              </a>
                            </Button>
                            {isPatient && rx.status === 'ISSUED' && rx.require_pin && (
                              <Button size="sm" variant="outline" onClick={() => setParam('pin', rx.id)}>
                                <KeyRound aria-hidden="true" /> Show PIN
                              </Button>
                            )}
                            {isDoctor && rx.readable && rx.patient_id && (
                              <Button asChild size="sm" variant="ghost">
                                <Link to={`/prescriptions/new?repeat=${rx.id}`} title="Start a new prescription with the same patient and medicines">
                                  <Copy aria-hidden="true" /> Repeat
                                </Link>
                              </Button>
                            )}
                            {isDoctor && rx.readable && rx.patient_id && rx.status === 'ISSUED' && rx.fills_used === 0 && (
                              <Button asChild size="sm" variant="ghost">
                                <Link to={`/prescriptions/new?correct=${rx.id}`} title="Issue a corrected prescription that replaces this one">
                                  <FilePenLine aria-hidden="true" /> Correct
                                </Link>
                              </Button>
                            )}
                            {isDoctor &&
                              rx.status === 'ISSUED' &&
                              (confirming === rx.id ? (
                                <>
                                  <Button size="sm" variant="destructive" disabled={revoke.isPending} onClick={() => revoke.mutate(rx.id)}>
                                    Confirm revoke
                                  </Button>
                                  <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                                    Cancel
                                  </Button>
                                </>
                              ) : (
                                <Button size="sm" variant="ghost" onClick={() => setConfirming(rx.id)}>
                                  Revoke
                                </Button>
                              ))}
                            <Button
                              size="sm"
                              variant="ghost"
                              aria-expanded={open === rx.id}
                              aria-controls={`details-${rx.id}`}
                              aria-label={open === rx.id ? 'Hide details' : 'Show details'}
                              onClick={() => setOpen(open === rx.id ? null : rx.id)}
                            >
                              <ChevronDown className={cn('transition-transform duration-150', open === rx.id && 'rotate-180')} aria-hidden="true" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                      {open === rx.id && (
                        <tr id={`details-${rx.id}`} className="bg-surface-2">
                          <td colSpan={6} className="px-4 py-4">
                            <Details rx={rx} isDoctor={!!isDoctor} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-3 text-xs text-muted-foreground" aria-live="polite">
            Showing {shown.length} of {all.length}
          </p>
        </>
      )}
    </>
  )
}
