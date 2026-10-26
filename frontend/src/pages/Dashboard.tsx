import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CircleCheck, CircleX, FilePlus2, ScanLine, ScrollText, TriangleAlert, UsersRound } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '@/components/PageHeader'
import { RxStatusBadge } from '@/components/RxStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { eventLabel } from '@/lib/audit'
import { useAuth } from '@/lib/auth'
import { dayPartGreeting, greetingName } from '@/lib/greeting'
import { formatDate, medicineSummary } from '@/lib/rx'
import type { AuditPage, Prescription, RecentActivity, SecurityEvent, UserList } from '@/lib/types'
import { VERDICT_META, type Verdict } from '@/lib/verdicts'
import { cn } from '@/lib/utils'

/** 'ok' when the server can really serve, 'degraded' when it is up but something it needs is not. */
async function fetchReadiness(): Promise<'ok' | 'degraded'> {
  const response = await fetch('/api/ready', { headers: { Accept: 'application/json' } })
  if (response.status === 503) return 'degraded'
  if (!response.ok) throw new Error(`ready ${response.status}`)
  return 'ok'
}

function ServiceStatus() {
  const { data, isPending, isError } = useQuery({ queryKey: ['ready'], queryFn: fetchReadiness, refetchInterval: 15_000, retry: 1 })
  if (isPending) return <Skeleton className="h-6 w-24" />
  if (isError)
    return (
      <Badge tone="danger">
        <CircleX aria-hidden="true" /> Unreachable
      </Badge>
    )
  if (data === 'degraded')
    return (
      <Badge tone="warning">
        <TriangleAlert aria-hidden="true" /> Degraded
      </Badge>
    )
  return (
    <Badge tone="verified">
      <CircleCheck aria-hidden="true" /> Running
    </Badge>
  )
}

/** A quiet list of facts. Numbers sit beside their labels (no oversized "hero" numbers). */
function Glance({ rows, loading }: { rows: { label: string; value: ReactNode; hint?: string }[]; loading: boolean }) {
  return (
    <section aria-labelledby="glance-h" className="rounded-lg border border-border bg-surface">
      <h2 id="glance-h" className="border-b border-border px-5 py-3 text-sm font-semibold">
        At a glance
      </h2>
      <dl className="divide-y divide-border text-sm">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-4 px-5 py-3">
            <dt className="text-muted-foreground">
              {row.label}
              {row.hint && <span className="block text-xs">{row.hint}</span>}
            </dt>
            <dd className="text-right font-medium tabular-nums">
              {loading ? <Skeleton className="inline-block h-4 w-8 align-middle" /> : row.value}
            </dd>
          </div>
        ))}
        <div className="flex items-center justify-between gap-4 px-5 py-3">
          <dt className="text-muted-foreground">Service</dt>
          <dd aria-live="polite">
            <ServiceStatus />
          </dd>
        </div>
      </dl>
    </section>
  )
}

function Panel({ title, to, linkLabel, children }: { title: string; to?: string; linkLabel?: string; children: ReactNode }) {
  const id = `panel-${title.replace(/\W+/g, '-').toLowerCase()}`
  return (
    <section aria-labelledby={id} className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
        <h2 id={id} className="text-sm font-semibold">
          {title}
        </h2>
        {to && (
          <Link to={to} className="inline-flex items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground">
            {linkLabel ?? 'See all'} <ArrowRight className="size-3.5" aria-hidden="true" />
          </Link>
        )}
      </div>
      {children}
    </section>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="px-5 py-6 text-sm text-muted-foreground">{children}</p>
}

function ListSkeleton() {
  return (
    <div className="space-y-3 p-5">
      <Skeleton className="h-5 w-3/4" />
      <Skeleton className="h-5 w-2/3" />
      <Skeleton className="h-5 w-1/2" />
    </div>
  )
}

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

// --- doctor and patient ----------------------------------------------------------------------------

function PrescriptionList({ items, who }: { items: Prescription[]; who: 'patient_name' | 'doctor_name' }) {
  return (
    <ul className="divide-y divide-border">
      {items.map((rx) => (
        <li key={rx.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{rx[who] ?? 'Unknown'}</p>
            <p className="truncate text-sm text-muted-foreground">
              {rx.medicines.length ? medicineSummary(rx.medicines[0]) : 'No medicines'}
              {rx.medicines.length > 1 && ` + ${rx.medicines.length - 1} more`}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">{formatDate(rx.issued_at)}</span>
            <RxStatusBadge status={rx.status} readable={rx.readable} />
          </div>
        </li>
      ))}
    </ul>
  )
}

function DoctorHome() {
  const { data, isPending } = useQuery({ queryKey: ['prescriptions', 'mine'], queryFn: () => api<Prescription[]>('/prescriptions/mine') })
  const all = data ?? []
  const count = (status: string) => all.filter((r) => r.status === status).length
  const waiting = all.filter((r) => r.status === 'ISSUED' && r.fills_used === 0).length
  const flagged = all.filter((r) => r.flagged).length
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-start">
      <Panel title="Latest prescriptions" to="/prescriptions">
        {isPending ? (
          <ListSkeleton />
        ) : all.length === 0 ? (
          <Empty>You have not issued any prescriptions yet. Write the first one and it will appear here.</Empty>
        ) : (
          <PrescriptionList items={all.slice(0, 6)} who="patient_name" />
        )}
      </Panel>
      <Glance
        loading={isPending}
        rows={[
          { label: 'Issued in total', value: all.length },
          { label: 'Not yet picked up', value: waiting },
          { label: 'Dispensed', value: count('DISPENSED') },
          { label: 'Expired or withdrawn', value: count('EXPIRED') + count('REVOKED') },
          { label: 'Flagged when issued', value: flagged, hint: flagged ? 'worth a second look' : undefined },
        ]}
      />
    </div>
  )
}

function PatientHome() {
  const { data, isPending } = useQuery({ queryKey: ['prescriptions', 'mine'], queryFn: () => api<Prescription[]>('/prescriptions/mine') })
  const all = data ?? []
  const active = all.filter((r) => r.status === 'ISSUED')
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-start">
      <Panel title="Ready to use" to="/prescriptions" linkLabel="Open with PIN">
        {isPending ? (
          <ListSkeleton />
        ) : active.length === 0 ? (
          <Empty>Nothing is waiting. Prescriptions your doctor issues to you will appear here with a PDF and a PIN for the pharmacy.</Empty>
        ) : (
          <ul className="divide-y divide-border">
            {active.map((rx) => (
              <li key={rx.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{rx.doctor_name ?? 'Your doctor'}</p>
                  <p className="truncate text-sm text-muted-foreground">
                    {rx.medicines.map((m) => m.name).join(', ')} · valid until {formatDate(rx.expires_at)}
                  </p>
                </div>
                <RxStatusBadge status={rx.status} readable={rx.readable} />
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Glance
        loading={isPending}
        rows={[
          { label: 'Ready to use', value: active.length },
          { label: 'Already dispensed', value: all.filter((r) => r.status === 'DISPENSED').length },
          { label: 'Expired or withdrawn', value: all.filter((r) => r.status === 'EXPIRED' || r.status === 'REVOKED').length },
        ]}
      />
    </div>
  )
}

// --- pharmacist -------------------------------------------------------------------------------------

function PharmacistHome() {
  const { data, isPending } = useQuery({ queryKey: ['verify', 'recent'], queryFn: () => api<RecentActivity>('/verify/recent') })
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-start">
      <Panel title="Your latest checks" to="/verify" linkLabel="Verify">
        {isPending ? (
          <ListSkeleton />
        ) : !data?.recent.length ? (
          <Empty>You have not verified anything yet. Scan a code or upload a photo or PDF of a prescription to begin.</Empty>
        ) : (
          <ul className="divide-y divide-border">
            {data.recent.map((r, i) => {
              const meta = VERDICT_META[r.result as Verdict]
              const Icon = meta?.icon
              return (
                <li key={`${r.ts}-${i}`} className="flex items-center justify-between gap-4 px-5 py-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <Badge tone={meta?.tone ?? 'neutral'}>
                      {Icon && <Icon aria-hidden="true" />} {meta?.label ?? r.result}
                    </Badge>
                    {r.rx_ref && <span className="truncate font-mono text-sm text-muted-foreground">{r.rx_ref}</span>}
                  </div>
                  <time className="shrink-0 text-sm text-muted-foreground" dateTime={r.ts}>
                    {when(r.ts)}
                  </time>
                </li>
              )
            })}
          </ul>
        )}
      </Panel>
      <Glance
        loading={isPending}
        rows={[
          { label: 'Verified today', value: data?.verified_today ?? 0 },
          { label: 'Needed attention today', value: data?.flagged_today ?? 0, hint: 'tampered, used, expired or odd' },
          { label: 'Dispensed today', value: data?.dispensed_today ?? 0 },
        ]}
      />
    </div>
  )
}

// --- admin and auditor ---------------------------------------------------------------------------------

const SEVERITY_TONE = { HIGH: 'danger', MEDIUM: 'warning', LOW: 'neutral' } as const

function AlertsPanel({ events, loading }: { events: SecurityEvent[]; loading: boolean }) {
  return (
    <Panel title="Latest security alerts" to="/admin" linkLabel="All alerts">
      {loading ? (
        <ListSkeleton />
      ) : events.length === 0 ? (
        <Empty>No security alerts so far.</Empty>
      ) : (
        <ul className="divide-y divide-border">
          {events.slice(0, 6).map((e) => (
            <li key={e.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <Badge tone={SEVERITY_TONE[e.severity]}>{e.severity === 'HIGH' ? 'High' : e.severity === 'MEDIUM' ? 'Medium' : 'Low'}</Badge>
                <span className="truncate font-medium">{eventLabel(e.event_type)}</span>
              </div>
              <time className="text-sm text-muted-foreground" dateTime={e.ts}>
                {when(e.ts)}
              </time>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function useEvents() {
  return useQuery({ queryKey: ['admin', 'events', 'home'], queryFn: () => api<SecurityEvent[]>('/admin/security-events?limit=100') })
}

function AdminHome() {
  const events = useEvents()
  const pending = useQuery({ queryKey: ['admin', 'users', 'pending-count'], queryFn: () => api<UserList>('/admin/users?role=pharmacist&approval_status=PENDING&limit=1') })
  const people = useQuery({ queryKey: ['admin', 'users', 'count'], queryFn: () => api<UserList>('/admin/users?limit=1') })
  const list = events.data ?? []
  const loading = events.isPending || pending.isPending || people.isPending
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-start">
      <AlertsPanel events={list} loading={events.isPending} />
      <Glance
        loading={loading}
        rows={[
          { label: 'Pharmacists awaiting approval', value: pending.data?.total ?? 0 },
          { label: 'People with accounts', value: people.data?.total ?? 0 },
          { label: 'High-severity alerts', value: list.filter((e) => e.severity === 'HIGH').length },
          { label: 'Medium-severity alerts', value: list.filter((e) => e.severity === 'MEDIUM').length },
        ]}
      />
    </div>
  )
}

function AuditorHome() {
  const events = useEvents()
  const log = useQuery({ queryKey: ['audit', 'count'], queryFn: () => api<AuditPage>('/admin/audit?limit=1') })
  const list = events.data ?? []
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-start">
      <AlertsPanel events={list} loading={events.isPending} />
      <Glance
        loading={events.isPending || log.isPending}
        rows={[
          { label: 'Entries in the audit log', value: log.data?.total ?? 0 },
          { label: 'High-severity alerts', value: list.filter((e) => e.severity === 'HIGH').length },
          { label: 'Medium-severity alerts', value: list.filter((e) => e.severity === 'MEDIUM').length },
        ]}
      />
    </div>
  )
}

// --- page ----------------------------------------------------------------------------------------------------

const HOME = {
  doctor: { description: 'Your prescriptions, and what has happened to them.', action: { to: '/prescriptions/new', label: 'New prescription', icon: FilePlus2 } },
  patient: { description: 'Your prescriptions and the PIN you show at the pharmacy.', action: null },
  pharmacist: { description: 'Check a prescription before you dispense it.', action: { to: '/verify', label: 'Verify a prescription', icon: ScanLine } },
  admin: { description: 'Who can use Pramaan, and anything unusual that happened.', action: { to: '/admin', label: 'Manage people', icon: UsersRound } },
  auditor: { description: 'The record of everything that mattered, and whether it still adds up.', action: { to: '/audit', label: 'Open the audit log', icon: ScrollText } },
} as const

export default function Dashboard() {
  const { user } = useAuth()
  if (!user) return null
  const config = HOME[user.role]
  const Action = config.action
  return (
    <>
      <PageHeader
        title={`${dayPartGreeting()}, ${greetingName(user.name)}`}
        description={config.description}
        actions={
          Action && (
            <Button asChild size="lg">
              <Link to={Action.to}>
                <Action.icon aria-hidden="true" /> {Action.label}
              </Link>
            </Button>
          )
        }
      />
      <div className={cn('max-w-5xl')}>
        {user.role === 'doctor' && <DoctorHome />}
        {user.role === 'patient' && <PatientHome />}
        {user.role === 'pharmacist' && <PharmacistHome />}
        {user.role === 'admin' && <AdminHome />}
        {user.role === 'auditor' && <AuditorHome />}
      </div>
    </>
  )
}
