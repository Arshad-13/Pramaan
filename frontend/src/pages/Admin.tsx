import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Check, Clock, Copy, Loader2, ShieldAlert, UserPlus, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { Field } from '@/components/Field'
import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError } from '@/lib/api'
import { detailFacts, eventLabel } from '@/lib/audit'
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
  const [confirming, setConfirming] = useState<string | null>(null)
  const { data, isPending } = useQuery({
    queryKey: ['admin', 'users', 'all', role],
    queryFn: () => api<UserList>(`/admin/users?limit=100${role ? `&role=${role}` : ''}`),
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
      <div className="mb-3 flex items-center gap-3">
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
            {data?.items.map((u) => (
              <tr key={u.public_id}>
                <td className="px-4 py-3">
                  <p className="font-medium">{u.name}</p>
                  <p className="text-muted-foreground">{u.email}</p>
                </td>
                <td className="px-4 py-3">{ROLE_LABEL[u.role]}</td>
                <td className="px-4 py-3"><StatusBadge user={u} /></td>
                <td className="px-4 py-3 text-right">
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

function SecurityEvents() {
  const { data, isPending } = useQuery({
    queryKey: ['admin', 'events'],
    queryFn: () => api<SecurityEvent[]>('/admin/security-events?limit=25'),
  })
  if (isPending) return <Skeleton className="h-20 w-full max-w-3xl" />
  if (!data?.length)
    return <p className="rounded-lg border border-dashed border-border-strong p-5 text-sm text-muted-foreground">No security alerts so far.</p>
  return (
    <ul className="max-w-3xl divide-y divide-border rounded-lg border border-border bg-surface">
      {data.map((event) => (
        <li key={event.id} className="px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Badge tone={SEVERITY_TONE[event.severity]}>
              <ShieldAlert aria-hidden="true" /> {event.severity === 'HIGH' ? 'High' : event.severity === 'MEDIUM' ? 'Medium' : 'Low'}
            </Badge>
            <span className="font-medium">{eventLabel(event.event_type)}</span>
            <time className="ml-auto text-sm text-muted-foreground" dateTime={event.ts}>
              {new Date(event.ts).toLocaleString()}
            </time>
          </div>
          {detailFacts(event.details_json).length > 0 && (
            <p className="mt-1 text-sm text-muted-foreground">{detailFacts(event.details_json).join(' · ')}</p>
          )}
        </li>
      ))}
    </ul>
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
      <Section title="Security alerts" description="Unusual activity the system noticed, newest first. Details hold counts and identifiers only, never personal data.">
        <SecurityEvents />
      </Section>
    </>
  )
}
