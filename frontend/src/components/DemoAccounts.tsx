import { FlaskConical } from 'lucide-react'

import { DEMO_ACCOUNTS, DEMO_LOGINS_ENABLED, type DemoAccount } from '@/lib/demoAccounts'

const heading = 'flex items-center gap-2 text-sm font-medium'
const panel = 'mt-8 rounded-lg border border-dashed border-border-strong bg-surface-2 p-4'
const chip =
  'rounded-md border border-border bg-surface px-3 py-2 text-left transition-colors duration-150 hover:border-foreground/40 focus-visible:border-ring'

/** One-click fill of the sign-in form with a seeded demo account. Hidden when VITE_DEMO_LOGINS=false. */
export function DemoLogins({ onPick }: { onPick: (account: DemoAccount) => void }) {
  if (!DEMO_LOGINS_ENABLED) return null
  return (
    <section aria-labelledby="demo-logins" className={panel}>
      <h2 id="demo-logins" className={heading}>
        <FlaskConical className="size-4" aria-hidden="true" /> Demo accounts
      </h2>
      <p className="mt-1 text-xs text-muted-foreground">Click one to fill the form, then continue.</p>
      <ul className="mt-3 grid grid-cols-2 gap-2">
        {DEMO_ACCOUNTS.map((account) => (
          <li key={account.email}>
            <button type="button" onClick={() => onPick(account)} className={`${chip} w-full`}>
              <span className="block text-xs font-medium capitalize text-muted-foreground">{account.role}</span>
              <span className="block truncate text-sm font-medium">{account.name}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** One-click fill of the register form with fresh, unique test details. */
export function DemoSignups({ onPick }: { onPick: (role: 'patient' | 'pharmacist') => void }) {
  if (!DEMO_LOGINS_ENABLED) return null
  return (
    <section aria-labelledby="demo-signups" className={panel}>
      <h2 id="demo-signups" className={heading}>
        <FlaskConical className="size-4" aria-hidden="true" /> Test details
      </h2>
      <p className="mt-1 text-xs text-muted-foreground">Fill the form with a new test account.</p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {(['patient', 'pharmacist'] as const).map((role) => (
          <button key={role} type="button" onClick={() => onPick(role)} className={chip}>
            <span className="block text-xs font-medium text-muted-foreground">Fill as</span>
            <span className="block text-sm font-medium capitalize">{role}</span>
          </button>
        ))}
      </div>
    </section>
  )
}
