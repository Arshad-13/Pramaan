import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Check, CheckCheck, Clock, Copy, Eye, Loader2, RotateCcw, Search, ShieldAlert, ShieldOff, UserPlus, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { Field } from '@/components/Field'
import { PageHeader } from '@/components/PageHeader'
import { RelativeTime } from '@/components/RelativeTime'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError } from '@/lib/api'
import { detailFacts, eventLabel } from '@/lib/audit'
import { cn } from '@/lib/utils'
import { ROLE_LABEL, type ActivationResult, type Role, type SecurityEvent, type User, type UserList } from '@/lib/types'

const ROLES: Role[] = ['doctor', 'patient', 'pharmacist', 'admin', 'auditor']

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Try again.'
}

function StatusBadge({ user }: { user: User }) {
  if (!user.is_active)
    return (
      <Badge tone="danger">
        <Ban aria-hidden="true" /> Deactivated
      </Badge>
    )
  if (user.approval_status === 'PENDING')
    return (
      <Badge tone="warning">
        <Clock aria-hidden="true" /> Pending approval
      </Badge>
    )
  if (user.approval_status === 'REJECTED')
    return (
      <Badge tone="danger">
        <X aria-hidden="true" /> Rejected
      </Badge>
    )
  return (
    <Badge>
      <Check aria-hidden="true" /> Active
    </Badge>
  )
}

function Section({ title, children, description }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="text-lg font-semibold">{title}</h2>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

function PendingPharmacists() {
  const queryClient = useQueryClient()
  const key = ['admin', 'users', 'pending']
  const { data, isPending } = useQuery({
    queryKey: key,
    queryFn: () => api<UserList>('/admin/users?role=pharmacist&approval_status=PENDING'),
  })
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'approve' | 'reject' }) =>
      api<User>(`/admin/users/${id}/${action}`, { method: 'POST' }),
    onSuccess: (_user, { action }) => {
      toast.success(action === 'approve' ? 'Pharmacist approved.' : 'Registration rejected.')
      void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  if (isPending) return <Skeleton className="h-20 w-full max-w-3xl" />
  if (!data?.items.length)
    return <p className="rounded-lg border border-dashed border-border-strong p-5 text-sm text-muted-foreground">No pharmacist registrations are waiting for review.</p>

  return (
    <ul className="max-w-3xl divide-y divide-border rounded-lg border border-border bg-surface">
      {data.items.map((u) => (
        <li key={u.public_id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <p className="font-medium">{u.name}</p>
            <p className="truncate text-sm text-muted-foreground">
              {u.org_name} · licence {u.license_no} · {u.email}
            </p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ id: u.public_id, action: 'approve' })}>
              <Check aria-hidden="true" /> Approve
            </Button>
            <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => decide.mutate({ id: u.public_id, action: 'reject' })}>
              Reject
            </Button>
          </div>
        </li>
      ))}
    </ul>
  )
}

function ActivationPanel({ result, onDismiss }: { result: ActivationResult; onDismiss: () => void }) {
  async function copy() {
    try {
      await navigator.clipboard.writeText(result.activation_token)
      toast.success('Code copied.')
    } catch {
      toast.error('Could not copy. Select the code and copy it manually.')
    }
  }
  return (
    <div role="status" className="max-w-xl rounded-lg border border-verified-border bg-verified-soft p-5">
      <p className="font-medium text-verified">Doctor account created for {result.user.name}</p>
      <p className="mt-1 text-sm text-foreground">
        Give this one-time code to the doctor. It is shown only now and expires on{' '}
        {new Date(result.expires_at).toLocaleString()}. They choose their own passwords when they activate.
      </p>
      <div className="mt-3 flex items-center gap-2">
        <code className="min-w-0 flex-1 select-all break-all rounded-md border border-border bg-surface px-3 py-2 font-mono text-sm">
          {result.activation_token}
        </code>
        <Button type="button" variant="outline" size="icon" aria-label="Copy activation code" onClick={copy}>
          <Copy aria-hidden="true" />
        </Button>
      </div>
      <Button type="button" variant="ghost" size="sm" className="mt-3" onClick={onDismiss}>
        I have passed it on
      </Button>
    </div>
  )
}

function AddDoctor() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ name: '', email: '', license_no: '', org_name: '' })
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ActivationResult | null>(null)

  const create = useMutation({
    mutationFn: () => api<ActivationResult>('/admin/users', { method: 'POST', body: form }),
    onSuccess: (data) => {
      setResult(data)
      setForm({ name: '', email: '', license_no: '', org_name: '' })
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
    onError: (e) => setError(errorMessage(e)),
  })

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value })
  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    create.mutate()
  }

  return (
    <div className="space-y-4">
      {result && <ActivationPanel result={result} onDismiss={() => setResult(null)} />}
      <form onSubmit={submit} className="grid max-w-3xl gap-4 rounded-lg border border-border bg-surface p-5 sm:grid-cols-2">
        <Field id="d-name" label="Doctor's name">
          <Input id="d-name" value={form.name} onChange={set('name')} required minLength={2} />
        </Field>
        <Field id="d-email" label="Email">
          <Input id="d-email" type="email" value={form.email} onChange={set('email')} required />
        </Field>
        <Field id="d-license" label="Registration (licence) number">
          <Input id="d-license" value={form.license_no} onChange={set('license_no')} required minLength={2} />
        </Field>
        <Field id="d-org" label="Clinic or hospital">
          <Input id="d-org" value={form.org_name} onChange={set('org_name')} required minLength={2} />
        </Field>
        {error && (
          <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger sm:col-span-2">
            {error}
          </p>
        )}
        <div className="sm:col-span-2">
          <Button type="submit" disabled={create.isPending} aria-busy={create.isPending}>
            {create.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <UserPlus aria-hidden="true" />}
            Create doctor account
          </Button>
        </div>
      </form>
    </div>
  )
}

function People() {
  const queryClient = useQueryClient()
  const [role, setRole] = useState<Role | ''>('')
  const [search, setSearch] = useState('')
  const [confirming, setConfirming] = useState<string | null>(null)
  const [resetting, setResetting] = useState<string | null>(null)
  const q = search.trim()
  const { data, isPending } = useQuery({
    queryKey: ['admin', 'users', 'all', role, q],
    queryFn: () => api<UserList>(`/admin/users?limit=100${role ? `&role=${role}` : ''}${q ? `&q=${encodeURIComponent(q)}` : ''}`),
    placeholderData: keepPreviousData,
  })
  const resetMfa = useMutation({
    mutationFn: (id: string) => api<User>(`/admin/users/${id}/reset-mfa`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Two-step sign-in removed. They can set it up again after signing in.')
      setResetting(null)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
    onError: (e) => {
      toast.error(errorMessage(e))
      setResetting(null)
    },
  })
  const deactivate = useMutation({
    mutationFn: (id: string) => api<User>(`/admin/users/${id}/deactivate`, { method: 'PATCH' }),
    onSuccess: () => {
      toast.success('Account deactivated.')
      setConfirming(null)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
    },
    onError: (e) => {
      toast.error(errorMessage(e))
      setConfirming(null)
    },
  })

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            type="search"
            aria-label="Search people"
            placeholder="Search name or email"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 pl-9"
          />
        </div>
        <label htmlFor="role-filter" className="text-sm text-muted-foreground">
          Show
        </label>
        <select
          id="role-filter"
          value={role}
          onChange={(e) => setRole(e.target.value as Role | '')}
          className="h-9 rounded-md border border-border-strong bg-surface px-2 text-sm"
        >
          <option value="">Everyone</option>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABEL[r]}s
            </option>
          ))}
        </select>
        {data && <span className="text-sm text-muted-foreground">{data.total} total</span>}
      </div>
      <div className="overflow-x-auto rounded-lg border border-border bg-surface">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <thead className="bg-surface-2 text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-4 py-2.5 font-medium">Person</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Role</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isPending && (
              <tr>
                <td colSpan={4} className="px-4 py-4"><Skeleton className="h-5 w-full" /></td>
              </tr>
            )}
            {data && data.items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-muted-foreground">
                  {q || role ? 'Nobody matches. Try a shorter name or another role.' : 'No accounts yet.'}
                </td>
              </tr>
            )}
            {data?.items.map((u) => (
              <tr key={u.public_id}>
                <td className="px-4 py-3">
                  <p className="font-medium">{u.name}</p>
                  <p className="text-muted-foreground">{u.email}</p>
                </td>
                <td className="px-4 py-3">{ROLE_LABEL[u.role]}</td>
                <td className="px-4 py-3"><StatusBadge user={u} /></td>
                <td className="px-4 py-3 text-right">
                  {u.is_active && u.mfa_enabled && (
                    resetting === u.public_id ? (
                      <span className="mr-2 inline-flex gap-2">
                        <Button size="sm" variant="destructive" disabled={resetMfa.isPending} onClick={() => resetMfa.mutate(u.public_id)}>
                          Confirm reset
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setResetting(null)}>Cancel</Button>
                      </span>
                    ) : (
                      <Button size="sm" variant="ghost" className="mr-2" onClick={() => setResetting(u.public_id)} title="Use when someone has lost their phone and recovery codes">
                        <ShieldOff aria-hidden="true" /> Reset two-step
                      </Button>
                    )
                  )}
                  {u.is_active &&
                    (confirming === u.public_id ? (
                      <span className="inline-flex gap-2">
                        <Button size="sm" variant="destructive" disabled={deactivate.isPending} onClick={() => deactivate.mutate(u.public_id)}>
                          Confirm deactivate
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>Cancel</Button>
                      </span>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => setConfirming(u.public_id)}>
                        Deactivate
                      </Button>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {confirming && (
        <p className="mt-2 text-xs text-muted-foreground">
          Deactivating signs the person out immediately. For doctors it also revokes their signing keys, so
          their unused prescriptions stop verifying.
        </p>
      )}
    </div>
  )
}

const SEVERITY_TONE = { HIGH: 'danger', MEDIUM: 'warning', LOW: 'neutral' } as const
const SEVERITY_LABEL = { HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' } as const

type AlertFilter = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | 'ALL'
const ALERT_FILTERS: [AlertFilter, string][] = [
  ['OPEN', 'Open'],
  ['ACKNOWLEDGED', 'Acknowledged'],
  ['RESOLVED', 'Resolved'],
  ['ALL', 'All'],
]

function AlertRow({ event }: { event: SecurityEvent }) {
  const queryClient = useQueryClient()
  const status = event.status ?? 'OPEN'
  const [note, setNote] = useState('')
  const [closing, setClosing] = useState(false)
  const update = useMutation({
    mutationFn: (next: { status: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED'; note?: string }) =>
      api<SecurityEvent>(`/admin/security-events/${event.id}`, { method: 'PATCH', body: { status: next.status, note: next.note || null } }),
    onSuccess: (_data, next) => {
      toast.success(next.status === 'RESOLVED' ? 'Alert resolved.' : next.status === 'ACKNOWLEDGED' ? 'Alert acknowledged.' : 'Alert reopened.')
      setClosing(false)
      setNote('')
      void queryClient.invalidateQueries({ queryKey: ['admin', 'events'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'events-open'] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const facts = detailFacts(event.details_json)
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Badge tone={SEVERITY_TONE[event.severity]}>
          <ShieldAlert aria-hidden="true" /> {SEVERITY_LABEL[event.severity]}
        </Badge>
        <span className="font-medium">{eventLabel(event.event_type)}</span>
        {status !== 'OPEN' && (
          <Badge tone={status === 'RESOLVED' ? 'verified' : 'neutral'}>
            {status === 'RESOLVED' ? <CheckCheck aria-hidden="true" /> : <Eye aria-hidden="true" />}
            {status === 'RESOLVED' ? 'Resolved' : 'Acknowledged'}
          </Badge>
        )}
        <RelativeTime iso={event.ts} className="ml-auto text-sm text-muted-foreground" />
      </div>
      {facts.length > 0 && <p className="mt-1 text-sm text-muted-foreground">{facts.join(' · ')}</p>}
      {event.note && <p className="mt-1 text-sm">Note: {event.note}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {status === 'OPEN' && (
          <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => update.mutate({ status: 'ACKNOWLEDGED' })}>
            <Eye aria-hidden="true" /> Acknowledge
          </Button>
        )}
        {status !== 'RESOLVED' && !closing && (
          <Button size="sm" variant="outline" onClick={() => setClosing(true)}>
            <CheckCheck aria-hidden="true" /> Resolve
          </Button>
        )}
        {status !== 'OPEN' && (
          <Button size="sm" variant="ghost" disabled={update.isPending} onClick={() => update.mutate({ status: 'OPEN' })}>
            <RotateCcw aria-hidden="true" /> Reopen
          </Button>
        )}
      </div>
      {closing && (
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            update.mutate({ status: 'RESOLVED', note: note.trim() })
          }}
        >
          <div className="min-w-0 flex-1">
            <label htmlFor={`note-${event.id}`} className="mb-1 block text-sm font-medium">
              What was done? (optional)
            </label>
            <Input id={`note-${event.id}`} value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="For example: spoke to the doctor, false alarm" />
          </div>
          <Button type="submit" size="sm" disabled={update.isPending}>
            Mark resolved
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setClosing(false)}>
            Cancel
          </Button>
        </form>
      )}
    </li>
  )
}

function SecurityEvents() {
  const [filter, setFilter] = useState<AlertFilter>('OPEN')
  const { data, isPending } = useQuery({
    queryKey: ['admin', 'events', filter],
    queryFn: () => api<SecurityEvent[]>(`/admin/security-events?limit=50${filter === 'ALL' ? '' : `&status=${filter}`}`),
    placeholderData: keepPreviousData,
  })
  return (
    <div>
      <div role="group" aria-label="Filter alerts" className="mb-3 flex flex-wrap gap-1.5">
        {ALERT_FILTERS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
            className={cn(
              'inline-flex h-8 items-center rounded-md border px-3 text-sm transition-colors duration-150',
              filter === value ? 'border-foreground bg-foreground text-background' : 'border-border bg-surface text-muted-foreground hover:text-foreground',
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {isPending && <Skeleton className="h-20 w-full max-w-3xl" />}
      {data && data.length === 0 && (
        <p className="rounded-lg border border-dashed border-border-strong p-5 text-sm text-muted-foreground">
          {filter === 'OPEN'
            ? 'No security alerts are waiting for you.'
            : filter === 'ALL'
              ? 'No security alerts so far.'
              : `No ${filter === 'RESOLVED' ? 'resolved' : 'acknowledged'} alerts.`}
        </p>
      )}
      {data && data.length > 0 && (
        <ul className="max-w-3xl divide-y divide-border rounded-lg border border-border bg-surface">
          {data.map((event) => (
            <AlertRow key={event.id} event={event} />
          ))}
        </ul>
      )}
    </div>
  )
}

export default function Admin() {
  return (
    <>
      <PageHeader title="Administration" description="Approve pharmacists, create doctor accounts, and manage who can sign in." />
      <Section title="Waiting for approval" description="Pharmacists cannot verify prescriptions until you approve their registration.">
        <PendingPharmacists />
      </Section>
      <Section title="Add a doctor" description="You never see the doctor's passwords. They set their own using the one-time code.">
        <AddDoctor />
      </Section>
      <Section title="People">
        <People />
      </Section>
      <Section title="Security alerts" description="Unusual activity the system noticed, newest first. Acknowledge what you have seen and resolve what you have dealt with. Details hold counts and identifiers only, never personal data.">
        <SecurityEvents />
      </Section>
    </>
  )
}
