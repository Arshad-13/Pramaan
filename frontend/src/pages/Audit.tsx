import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Loader2, ShieldCheck, ShieldX, Stamp } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { AuditChain } from '@/components/AuditChain'
import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError } from '@/lib/api'
import type { AuditPage, AuditVerify } from '@/lib/types'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 20
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

  const { data, isPending, isError } = useQuery({
    queryKey: ['audit', page],
    queryFn: () => api<AuditPage>(`/admin/audit?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`),
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
        {isPending && <Skeleton className="h-40 w-full" />}
        {isError && (
          <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
            The log could not be loaded.
          </p>
        )}
        {data && <AuditChain entries={data.items} badSeq={result && !result.ok ? result.first_bad_seq : null} />}
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
