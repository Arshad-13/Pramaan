import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  Bot,
  CircleCheck,
  CircleX,
  FilePlus2,
  Files,
  KeyRound,
  ScanLine,
  ScrollText,
  ShieldCheck,
  TriangleAlert,
  UserCheck,
  UsersRound,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { ActivityBars } from '@/components/ActivityBars'
import { EmptyState } from '@/components/EmptyState'
import { PageHeader } from '@/components/PageHeader'
import { RelativeTime } from '@/components/RelativeTime'
import { RxStatusBadge } from '@/components/RxStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { eventLabel } from '@/lib/audit'
import { useAuth } from '@/lib/auth'
import { dayPartGreeting, greetingName } from '@/lib/greeting'
import { formatDate, medicineSummary } from '@/lib/rx'
import { daysUntil, lastDays } from '@/lib/series'
import type { AuditPage, ModelStatus, Prescription, RecentActivity, SecurityEvent, UserList } from '@/lib/types'
import { VERDICT_META, type Verdict } from '@/lib/verdicts'

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

interface Stat {
  label: string
  value: ReactNode
  hint?: string
}

/** The few numbers that matter, in one quiet strip (not a row of identical cards). */
function Glance({ rows, loading }: { rows: Stat[]; loading: boolean }) {
  return (
    <section aria-label="At a glance" className="mb-6 rounded-lg border border-border bg-surface">
      <dl className="grid grid-cols-2 divide-x divide-y divide-border sm:grid-cols-3 sm:divide-y-0 lg:flex lg:divide-y-0">
        {rows.map((row) => (
          <div key={row.label} className="min-w-0 flex-1 px-5 py-4">
            <dt className="text-xs text-muted-foreground">{row.label}</dt>
            <dd className="mt-1">
              <span className="font-serif text-2xl font-semibold tabular-nums">
                {loading ? <Skeleton className="inline-block h-7 w-10 align-middle" /> : row.value}
              </span>
              {row.hint && <span className="mt-0.5 block text-xs text-muted-foreground">{row.hint}</span>}
            </dd>
          </div>
        ))}
        <div className="min-w-0 flex-1 px-5 py-4">
          <dt className="text-xs text-muted-foreground">Service</dt>
          <dd className="mt-1.5" aria-live="polite">
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

function ListSkeleton() {
  return (
    <div className="space-y-3 p-5" role="status" aria-label="Loading">
      <Skeleton className="h-5 w-3/4" />
      <Skeleton className="h-5 w-2/3" />
      <Skeleton className="h-5 w-1/2" />
    </div>
  )
}

const Columns = ({ children }: { children: ReactNode }) => (
  <div className="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] lg:items-start">{children}</div>
)
const Stack = ({ children }: { children: ReactNode }) => <div className="flex flex-col gap-6">{children}</div>

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
            <RelativeTime iso={rx.issued_at} className="text-sm text-muted-foreground" />
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
  const waiting = all.filter((r) => r.status === 'ISSUED' && r.fills_used === 0)
  const flagged = all.filter((r) => r.flagged)
  return (
    <>
      <Glance
        loading={isPending}
        rows={[
          { label: 'Issued in total', value: all.length },
          { label: 'Not yet picked up', value: waiting.length },
          { label: 'Dispensed', value: count('DISPENSED') },
          { label: 'Expired or withdrawn', value: count('EXPIRED') + count('REVOKED') },
          { label: 'Flagged when issued', value: flagged.length, hint: flagged.length ? 'worth a second look' : undefined },
        ]}
      />
      <Columns>
        <Panel title="Latest prescriptions" to="/prescriptions">
          {isPending ? (
            <ListSkeleton />
          ) : all.length === 0 ? (
            <EmptyState
              icon={FilePlus2}
              title="No prescriptions yet"
              action={
                <Button asChild size="sm">
                  <Link to="/prescriptions/new">Write the first one</Link>
                </Button>
              }
            >
              Pick a patient, add medicines, sign with your signing password. The prescription and its QR code appear here straight away.
            </EmptyState>
          ) : (
            <PrescriptionList items={all.slice(0, 6)} who="patient_name" />
          )}
        </Panel>
        <Stack>
          <Panel title="Last 14 days">
            {isPending ? <ListSkeleton /> : <ActivityBars days={lastDays(all.map((r) => r.issued_at), 14)} noun="prescriptions issued" />}
          </Panel>
          {flagged.length > 0 && (
            <Panel title="Worth a second look" to="/prescriptions" linkLabel="Review">
              <ul className="divide-y divide-border">
                {flagged.slice(0, 3).map((rx) => (
                  <li key={rx.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                    <span className="min-w-0 truncate">
                      <span className="font-medium">{rx.patient_name ?? 'Unknown'}</span>
                      <span className="text-muted-foreground"> · risk {rx.risk_score}</span>
                    </span>
                    <RelativeTime iso={rx.issued_at} className="shrink-0 text-muted-foreground" />
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </Stack>
      </Columns>
    </>
  )
}

const HOW_TO_USE = [
  { icon: Files, text: 'Open the prescription and show its QR code or PDF at the pharmacy.' },
  { icon: KeyRound, text: 'Read out the 6-digit PIN. It changes every two minutes.' },
  { icon: UserCheck, text: 'The pharmacist checks it is genuine, then hands over your medicine.' },
]

function PatientHome() {
  const { data, isPending } = useQuery({ queryKey: ['prescriptions', 'mine'], queryFn: () => api<Prescription[]>('/prescriptions/mine') })
  const all = data ?? []
  const active = all.filter((r) => r.status === 'ISSUED')
  const soonest = active.length ? active.reduce((a, b) => (a.expires_at < b.expires_at ? a : b)) : null
  return (
    <>
      <Glance
        loading={isPending}
        rows={[
          { label: 'Ready to use', value: active.length },
          { label: 'Already dispensed', value: all.filter((r) => r.status === 'DISPENSED').length },
          { label: 'Expired or withdrawn', value: all.filter((r) => r.status === 'EXPIRED' || r.status === 'REVOKED').length },
        ]}
      />
      <Columns>
        <Panel title="Ready to use" to="/prescriptions" linkLabel="Open with PIN">
          {isPending ? (
            <ListSkeleton />
          ) : active.length === 0 ? (
            <EmptyState icon={Files} title="Nothing is waiting">
              Prescriptions your doctor issues to you appear here with a PDF and a PIN for the pharmacy. Give your doctor the patient code from your Account page so they can find you.
            </EmptyState>
          ) : (
            <ul className="divide-y divide-border">
              {active.map((rx) => {
                const left = daysUntil(rx.expires_at)
                return (
                  <li key={rx.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-5 py-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{rx.doctor_name ?? 'Your doctor'}</p>
                      <p className="truncate text-sm text-muted-foreground">
                        {rx.medicines.map((m) => m.name).join(', ')} · valid until {formatDate(rx.expires_at)}
                        {left <= 7 && left > 0 && ` (${left} ${left === 1 ? 'day' : 'days'} left)`}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <RxStatusBadge status={rx.status} readable={rx.readable} />
                      <Button asChild size="sm" variant="outline">
                        <Link to={`/prescriptions?pin=${rx.id}`}>
                          <KeyRound aria-hidden="true" /> Show PIN
                        </Link>
                      </Button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </Panel>
        <Stack>
          {soonest && daysUntil(soonest.expires_at) <= 7 && (
            <p role="note" className="flex items-start gap-2 rounded-lg border border-warning-border bg-warning-soft px-4 py-3 text-sm text-warning">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span>
                A prescription from {soonest.doctor_name ?? 'your doctor'} expires {formatDate(soonest.expires_at)}. Use it before then, or ask for a new one.
              </span>
            </p>
          )}
          <Panel title="At the pharmacy">
            <ol className="divide-y divide-border">
              {HOW_TO_USE.map(({ icon: Icon, text }, i) => (
                <li key={text} className="flex items-start gap-3 px-5 py-3 text-sm">
                  <span className="grid size-6 shrink-0 place-items-center rounded-full bg-surface-2 text-xs font-semibold text-muted-foreground" aria-hidden="true">
                    {i + 1}
                  </span>
                  <span className="flex-1">{text}</span>
                  <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                </li>
              ))}
            </ol>
          </Panel>
        </Stack>
      </Columns>
    </>
  )
}

// --- pharmacist -------------------------------------------------------------------------------------

function PharmacistHome() {
  const { data, isPending } = useQuery({ queryKey: ['verify', 'recent'], queryFn: () => api<RecentActivity>('/verify/recent') })
  const checked = (data?.verified_today ?? 0) + (data?.flagged_today ?? 0)
  return (
    <>
      <Glance
        loading={isPending}
        rows={[
          { label: 'Verified today', value: data?.verified_today ?? 0 },
          { label: 'Needed attention today', value: data?.flagged_today ?? 0, hint: 'tampered, used, expired or odd' },
          { label: 'Dispensed today', value: data?.dispensed_today ?? 0 },
        ]}
      />
      <Columns>
        <Panel title="Your latest checks" to="/verify/history" linkLabel="All checks">
          {isPending ? (
            <ListSkeleton />
          ) : !data?.recent.length ? (
            <EmptyState
              icon={ScanLine}
              title="Nothing checked yet"
              action={
                <Button asChild size="sm">
                  <Link to="/verify">Verify the first one</Link>
                </Button>
              }
            >
              Scan the QR code, paste it, or upload a photo or PDF of the prescription. You see the verdict and the reasons within seconds.
            </EmptyState>
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
                    <RelativeTime iso={r.ts} className="shrink-0 text-sm text-muted-foreground" />
                  </li>
                )
              })}
            </ul>
          )}
        </Panel>
        <Stack>
          <Panel title="Today so far">
            <div className="px-5 py-4 text-sm">
              {isPending ? (
                <Skeleton className="h-4 w-full" />
              ) : checked === 0 ? (
                <p className="text-muted-foreground">No checks yet today.</p>
              ) : (
                <>
                  <div className="flex h-2 overflow-hidden rounded-full bg-surface-2" role="img" aria-label={`${data?.verified_today ?? 0} verified, ${data?.flagged_today ?? 0} needed attention`}>
                    <span className="bg-verified-solid" style={{ width: `${((data?.verified_today ?? 0) / checked) * 100}%` }} />
                    <span className="bg-warning-solid" style={{ width: `${((data?.flagged_today ?? 0) / checked) * 100}%` }} />
                  </div>
                  <p className="mt-2 text-muted-foreground">
                    {data?.verified_today} verified, {data?.flagged_today} needed attention.
                  </p>
                </>
              )}
            </div>
          </Panel>
          <Panel title="Dispensing is separate">
            <p className="px-5 py-4 text-sm text-muted-foreground">
              A verified result does not hand over medicine by itself. After the verdict, check the patient's identity and enter their PIN to record the dispense.
            </p>
          </Panel>
        </Stack>
      </Columns>
    </>
  )
}

// --- admin and auditor ---------------------------------------------------------------------------------

const SEVERITY_TONE = { HIGH: 'danger', MEDIUM: 'warning', LOW: 'neutral' } as const
const SEVERITY_LABEL = { HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' } as const

function AlertsPanel({ events, loading }: { events: SecurityEvent[]; loading: boolean }) {
  const open = events.filter((e) => (e.status ?? 'OPEN') === 'OPEN')
  return (
    <Panel title="Latest security alerts" to="/admin" linkLabel="All alerts">
      {loading ? (
        <ListSkeleton />
      ) : events.length === 0 ? (
        <EmptyState icon={ShieldCheck} title="No security alerts so far.">
          Replays, repeated failed checks, lockouts and risky issuing show up here as they happen.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-border">
          {(open.length ? open : events).slice(0, 6).map((e) => (
            <li key={e.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <Badge tone={SEVERITY_TONE[e.severity]}>{SEVERITY_LABEL[e.severity]}</Badge>
                <span className="truncate font-medium">{eventLabel(e.event_type)}</span>
              </div>
              <RelativeTime iso={e.ts} className="text-sm text-muted-foreground" />
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

const MODEL_COPY: Record<ModelStatus['status'], { tone: 'verified' | 'warning' | 'danger'; label: string; text: string }> = {
  OK: { tone: 'verified', label: 'Active', text: 'The signed anomaly model is loaded and scoring new prescriptions.' },
  MISSING: { tone: 'warning', label: 'Not installed', text: 'No model file. Prescriptions are scored by the rules only.' },
  UNSIGNED: { tone: 'danger', label: 'Unsigned', text: 'A model file exists without a signature, so it is ignored.' },
  BAD_SIGNATURE: { tone: 'danger', label: 'Signature failed', text: 'The model file does not match its signature, so it is ignored.' },
  CORRUPT: { tone: 'danger', label: 'Unreadable', text: 'The model file cannot be read, so it is ignored.' },
}

function ModelPanel() {
  const { data, isPending, isError } = useQuery({ queryKey: ['admin', 'model-status'], queryFn: () => api<ModelStatus>('/admin/model-status') })
  return (
    <Panel title="Anomaly model">
      {isPending ? (
        <ListSkeleton />
      ) : isError || !data ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">Model status is not available right now.</p>
      ) : (
        <div className="space-y-2 px-5 py-4 text-sm">
          <Badge tone={MODEL_COPY[data.status].tone}>
            <Bot aria-hidden="true" /> {MODEL_COPY[data.status].label}
          </Badge>
          <p className="text-muted-foreground">{MODEL_COPY[data.status].text}</p>
          {data.status === 'OK' && (
            <p className="text-xs text-muted-foreground">
              {data.features.length} features, adds at most {data.weight_points} of 100 risk points
              {data.file_modified_at && (
                <>
                  , trained <RelativeTime iso={data.file_modified_at} />
                </>
              )}
              .
            </p>
          )}
        </div>
      )}
    </Panel>
  )
}

function AdminHome() {
  const events = useEvents()
  const pending = useQuery({
    queryKey: ['admin', 'users', 'pending-list'],
    queryFn: () => api<UserList>('/admin/users?role=pharmacist&approval_status=PENDING&limit=5'),
  })
  const people = useQuery({ queryKey: ['admin', 'users', 'count'], queryFn: () => api<UserList>('/admin/users?limit=1') })
  const list = events.data ?? []
  const loading = events.isPending || pending.isPending || people.isPending
  return (
    <>
      <Glance
        loading={loading}
        rows={[
          { label: 'Pharmacists awaiting approval', value: pending.data?.total ?? 0 },
          { label: 'People with accounts', value: people.data?.total ?? 0 },
          { label: 'High-severity alerts', value: list.filter((e) => e.severity === 'HIGH').length },
          { label: 'Medium-severity alerts', value: list.filter((e) => e.severity === 'MEDIUM').length },
        ]}
      />
      <Columns>
        <AlertsPanel events={list} loading={events.isPending} />
        <Stack>
          <Panel title="Waiting for a decision" to="/admin" linkLabel="Open">
            {pending.isPending ? (
              <ListSkeleton />
            ) : !pending.data?.items.length ? (
              <EmptyState icon={UserCheck} title="No pharmacists are waiting.">
                New pharmacy registrations appear here until you approve or reject them.
              </EmptyState>
            ) : (
              <ul className="divide-y divide-border">
                {pending.data.items.map((u) => (
                  <li key={u.public_id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                    <span className="min-w-0 truncate">
                      <span className="font-medium">{u.name}</span>
                      {u.org_name && <span className="text-muted-foreground"> · {u.org_name}</span>}
                    </span>
                    <RelativeTime iso={u.created_at} className="shrink-0 text-muted-foreground" />
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <ModelPanel />
        </Stack>
      </Columns>
    </>
  )
}

function AuditorHome() {
  const events = useEvents()
  const log = useQuery({ queryKey: ['audit', 'count'], queryFn: () => api<AuditPage>('/admin/audit?limit=1') })
  const list = events.data ?? []
  return (
    <>
      <Glance
        loading={events.isPending || log.isPending}
        rows={[
          { label: 'Entries in the audit log', value: log.data?.total ?? 0 },
          { label: 'High-severity alerts', value: list.filter((e) => e.severity === 'HIGH').length },
          { label: 'Medium-severity alerts', value: list.filter((e) => e.severity === 'MEDIUM').length },
        ]}
      />
      <Columns>
        <AlertsPanel events={list} loading={events.isPending} />
        <Stack>
          <Panel title="Integrity">
            <div className="space-y-3 px-5 py-4 text-sm">
              <p className="text-muted-foreground">Every entry is chained to the one before it with a key the database does not hold. Run the check whenever you need proof nothing was edited or removed.</p>
              <Button asChild variant="outline" size="sm">
                <Link to="/audit">
                  <ScrollText aria-hidden="true" /> Check the chain
                </Link>
              </Button>
            </div>
          </Panel>
          <ModelPanel />
        </Stack>
      </Columns>
    </>
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
      <div className="max-w-6xl">
        {user.role === 'doctor' && <DoctorHome />}
        {user.role === 'patient' && <PatientHome />}
        {user.role === 'pharmacist' && <PharmacistHome />}
        {user.role === 'admin' && <AdminHome />}
        {user.role === 'auditor' && <AuditorHome />}
      </div>
    </>
  )
}
