import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Download, Loader2, ShieldCheck, ShieldX, Stamp, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { AuditChain } from '@/components/AuditChain'
import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError } from '@/lib/api'
import { actionLabel } from '@/lib/audit'
import { ROLE_LABEL, type AuditPage, type AuditVerify, type Role } from '@/lib/types'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 20
const ROLES: Role[] = ['doctor', 'patient', 'pharmacist', 'admin', 'auditor']

interface Filters {
  action: string
  role: string
  resource: string
  from: string
  to: string
}
const NO_FILTERS: Filters = { action: '', role: '', resource: '', from: '', to: '' }

/** Query string for the filters. Dates are whole days in UTC, matching the times the log shows. */
function filterQuery(f: Filters): URLSearchParams {
  const q = new URLSearchParams()
  if (f.action) q.set('action', f.action)
  if (f.role) q.set('actor_role', f.role)
  if (f.resource.trim()) q.set('resource', f.resource.trim())
  if (f.from) q.set('since', `${f.from}T00:00:00Z`)
  if (f.to) q.set('until', `${f.to}T23:59:59Z`)
  return q
}
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

function VerifyResult({ result }: { result: AuditVerify }) {
  const ok = result.ok
  const Icon = ok ? ShieldCheck : ShieldX
  return (
    <section
      aria-label="Chain verification result"
      aria-live="polite"
      className={cn('rounded-lg border p-5', ok ? 'border-verified-border bg-verified-soft' : 'border-danger-border bg-danger-soft')}
    >
      <Badge tone={ok ? 'verified' : 'danger'}>
        <Icon aria-hidden="true" /> {ok ? 'Chain intact' : 'Tampering detected'}
      </Badge>
      <h2 className="mt-2 font-serif text-xl font-semibold tracking-tight">
        {ok
          ? `${result.checked === 1 ? 'The only entry matches' : `All ${result.checked} entries link up and match`} their signed checkpoints.`
          : result.first_bad_seq !== null
            ? `The log was altered at entry #${result.first_bad_seq}.`
            : 'The log does not match its signed checkpoints.'}
      </h2>
      <p className="mt-1 text-sm text-foreground">
        {plural(result.checked, 'entry', 'entries')} checked · {plural(result.checkpoints, 'signed checkpoint', 'signed checkpoints')} · {plural(result.anchors, 'copy', 'copies')} stored outside the database
        {result.truncated && ' · the newest entries have been deleted'}
      </p>
      {result.problems.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
          {result.problems.slice(0, 6).map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function Audit() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)
  const [result, setResult] = useState<AuditVerify | null>(null)
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const filtered = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS)
  const change = (patch: Partial<Filters>) => {
    setFilters({ ...filters, ...patch })
    setPage(0)
  }

  const { data, isPending, isError } = useQuery({
    queryKey: ['audit', page, filters],
    queryFn: () => {
      const q = filterQuery(filters)
      q.set('limit', String(PAGE_SIZE))
      q.set('offset', String(page * PAGE_SIZE))
      return api<AuditPage>(`/admin/audit?${q}`)
    },
    placeholderData: keepPreviousData,
  })
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['audit'] })
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')

  const verify = useMutation({
    mutationFn: () => api<AuditVerify>('/admin/audit/verify'),
    onSuccess: (r) => {
      setResult(r)
      refresh()
    },
    onError: fail,
  })
  const checkpoint = useMutation({
    mutationFn: () => api<AuditVerify>('/admin/audit/checkpoint', { method: 'POST' }),
    onSuccess: (r) => {
      setResult(r)
      toast.success('Signed checkpoint added.')
      refresh()
    },
    onError: fail,
  })

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  const busy = verify.isPending || checkpoint.isPending

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every security-relevant action, chained so that any edit or deletion is detected."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <a href={`/api/admin/audit/export?${filterQuery(filters)}`} download>
                <Download aria-hidden="true" /> Export CSV
              </a>
            </Button>
            <Button variant="outline" onClick={() => checkpoint.mutate()} disabled={busy}>
              {checkpoint.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Stamp aria-hidden="true" />}
              Add signed checkpoint
            </Button>
            <Button onClick={() => verify.mutate()} disabled={busy} aria-busy={verify.isPending}>
              {verify.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <ShieldCheck aria-hidden="true" />}
              Verify chain
            </Button>
          </div>
        }
      />
      <div className="max-w-3xl space-y-6">
        {result && <VerifyResult result={result} />}
        <form
          aria-label="Filter the log"
          onSubmit={(e) => e.preventDefault()}
          className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          <div>
            <label htmlFor="f-action" className="mb-1 block text-sm font-medium">
              Action
            </label>
            <select
              id="f-action"
              value={filters.action}
              onChange={(e) => change({ action: e.target.value })}
              className="h-10 w-full rounded-md border border-border-strong bg-surface px-2 text-sm"
            >
              <option value="">Any action</option>
              {(data?.actions ?? []).map((a) => (
                <option key={a} value={a}>
                  {actionLabel(a)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="f-role" className="mb-1 block text-sm font-medium">
              Done by
            </label>
            <select
              id="f-role"
              value={filters.role}
              onChange={(e) => change({ role: e.target.value })}
              className="h-10 w-full rounded-md border border-border-strong bg-surface px-2 text-sm"
            >
              <option value="">Anyone</option>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="f-resource" className="mb-1 block text-sm font-medium">
              Item (id)
            </label>
            <input
              id="f-resource"
              value={filters.resource}
              onChange={(e) => change({ resource: e.target.value })}
              placeholder="Prescription or account id"
              className="h-10 w-full rounded-md border border-border-strong bg-surface px-3 text-sm placeholder:text-muted-foreground"
            />
          </div>
          <div>
            <label htmlFor="f-from" className="mb-1 block text-sm font-medium">
              From (UTC)
            </label>
            <input
              id="f-from"
              type="date"
              value={filters.from}
              max={filters.to || undefined}
              onChange={(e) => change({ from: e.target.value })}
              className="h-10 w-full rounded-md border border-border-strong bg-surface px-3 text-sm"
            />
          </div>
          <div>
            <label htmlFor="f-to" className="mb-1 block text-sm font-medium">
              To (UTC)
            </label>
            <input
              id="f-to"
              type="date"
              value={filters.to}
              min={filters.from || undefined}
              onChange={(e) => change({ to: e.target.value })}
              className="h-10 w-full rounded-md border border-border-strong bg-surface px-3 text-sm"
            />
          </div>
          <div className="flex items-end">
            {filtered && (
              <Button type="button" variant="ghost" onClick={() => change(NO_FILTERS)}>
                <X aria-hidden="true" /> Clear filters
              </Button>
            )}
          </div>
        </form>
        {isPending && <Skeleton className="h-40 w-full" />}
        {isError && (
          <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
            The log could not be loaded.
          </p>
        )}
        {data && data.items.length === 0 && (
          <p className="rounded-lg border border-dashed border-border-strong p-5 text-sm text-muted-foreground">
            {filtered ? 'No log entries match these filters. Widen the dates or clear a filter.' : 'The log is empty.'}
          </p>
        )}
        {data && data.items.length > 0 && <AuditChain entries={data.items} badSeq={result && !result.ok ? result.first_bad_seq : null} />}
        {filtered && <p className="text-sm text-muted-foreground">Filters only change what you see. Verify chain always checks the whole log.</p>}
        {data && (
          <nav aria-label="Pages of the audit log" className="flex items-center justify-between text-sm">
            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
              <ChevronLeft aria-hidden="true" /> Newer
            </Button>
            <span className="text-muted-foreground">
              Page {page + 1} of {pages} · {data.total} entries
            </span>
            <Button variant="outline" size="sm" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
              Older <ChevronRight aria-hidden="true" />
            </Button>
          </nav>
        )}
      </div>
    </>
  )
}
