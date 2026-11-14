import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { CircleCheck, Copy, Download, Loader2, ShieldCheck, ShieldOff } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Field } from '@/components/Field'
import { QrMatrix } from '@/components/QrMatrix'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api, ApiError } from '@/lib/api'
import { describe } from '@/lib/aria'
import type { MfaEnrol, User } from '@/lib/types'

const passwordSchema = z.object({ password: z.string().min(1, 'Enter your current password.') })
const codeSchema = z.object({ code: z.string().trim().min(6, 'Enter the 6-digit code from the app.') })
const offSchema = z.object({
  password: z.string().min(1, 'Enter your current password.'),
  code: z.string().trim().min(6, 'Enter a code from the app, or a recovery code.'),
})

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : 'Something went wrong. Try again.')

function FormError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
      {message}
    </p>
  )
}

/** Groups of four, so a secret typed by hand is easy to check against the screen. */
const groups = (secret: string) => secret.replace(/(.{4})/g, '$1 ').trim()

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const text = codes.join('\n')
  return (
    <div className="flex flex-col gap-4">
      <p className="flex items-start gap-2 text-sm">
        <CircleCheck className="mt-0.5 size-4 shrink-0 text-verified" aria-hidden="true" />
        <span>
          Two-factor sign-in is on. <strong>Save these recovery codes now.</strong> Each works once if you lose your phone, and this is the only time they are shown.
        </span>
      </p>
      <ul className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-md border border-border bg-surface-2 p-4 font-mono text-sm" aria-label="Recovery codes">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text)
              toast.success('Recovery codes copied.')
            } catch {
              toast.error('Could not copy. Select the codes and copy them by hand.')
            }
          }}
        >
          <Copy aria-hidden="true" /> Copy
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            const url = URL.createObjectURL(new Blob([`Pramaan recovery codes\n\n${text}\n`], { type: 'text/plain' }))
            const a = document.createElement('a')
            a.href = url
            a.download = 'pramaan-recovery-codes.txt'
            a.click()
            URL.revokeObjectURL(url)
          }}
        >
          <Download aria-hidden="true" /> Download
        </Button>
        <Button type="button" onClick={onDone}>
          I have saved them
        </Button>
      </div>
    </div>
  )
}

function SetUp({ onCancel, onEnabled }: { onCancel: () => void; onEnabled: (codes: string[]) => void }) {
  const [enrol, setEnrol] = useState<MfaEnrol | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pw = useForm<z.infer<typeof passwordSchema>>({ resolver: zodResolver(passwordSchema) })
  const code = useForm<z.infer<typeof codeSchema>>({ resolver: zodResolver(codeSchema) })

  if (!enrol) {
    return (
      <form
        className="flex flex-col gap-4"
        noValidate
        onSubmit={pw.handleSubmit(async (v) => {
          setError(null)
          try {
            setEnrol(await api<MfaEnrol>('/auth/mfa/enrol', { method: 'POST', body: { password: v.password } }))
          } catch (e) {
            setError(errorText(e))
          }
        })}
      >
        <p className="text-sm text-muted-foreground">
          You will need an authenticator app on your phone (any app that scans a QR code for time-based codes). Confirm your password to begin.
        </p>
        <Field id="mfa-password" label="Current password" error={pw.formState.errors.password?.message}>
          <Input type="password" autoComplete="current-password" {...describe('mfa-password', pw.formState.errors.password?.message)} {...pw.register('password')} />
        </Field>
        <FormError message={error} />
        <div className="flex gap-2">
          <Button type="submit" disabled={pw.formState.isSubmitting} aria-busy={pw.formState.isSubmitting}>
            {pw.formState.isSubmitting && <Loader2 className="animate-spin" aria-hidden="true" />}
            Continue
          </Button>
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    )
  }

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={code.handleSubmit(async (v) => {
        setError(null)
        try {
          const done = await api<{ recovery_codes: string[] }>('/auth/mfa/enable', { method: 'POST', body: { code: v.code } })
          onEnabled(done.recovery_codes)
        } catch (e) {
          setError(errorText(e))
        }
      })}
    >
      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
        <li>Open your authenticator app and add an account by scanning this code.</li>
        <li>Type the 6-digit code the app shows to finish.</li>
      </ol>
      <div className="flex flex-wrap items-start gap-5">
        <QrMatrix matrix={enrol.qr_matrix} label="QR code for your authenticator app" />
        <div className="min-w-0 text-sm">
          <p className="text-muted-foreground">Cannot scan? Type this key instead:</p>
          <p className="mt-1 break-all font-mono text-sm font-medium" data-testid="mfa-secret">
            {groups(enrol.secret)}
          </p>
        </div>
      </div>
      <Field id="mfa-code" label="Code from the app" error={code.formState.errors.code?.message}>
        <Input inputMode="numeric" autoComplete="one-time-code" className="max-w-40 font-mono tracking-widest" {...describe('mfa-code', code.formState.errors.code?.message)} {...code.register('code')} />
      </Field>
      <FormError message={error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={code.formState.isSubmitting} aria-busy={code.formState.isSubmitting}>
          {code.formState.isSubmitting && <Loader2 className="animate-spin" aria-hidden="true" />}
          Turn on
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function TurnOff({ onCancel, onDone }: { onCancel: () => void; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof offSchema>>({ resolver: zodResolver(offSchema) })
  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={form.handleSubmit(async (v) => {
        setError(null)
        try {
          await api('/auth/mfa/disable', { method: 'POST', body: v })
          onDone()
        } catch (e) {
          setError(errorText(e))
        }
      })}
    >
      <p className="text-sm text-muted-foreground">Turning it off makes sign-in depend on your password alone. Confirm with your password and a current code.</p>
      <Field id="off-password" label="Current password" error={form.formState.errors.password?.message}>
        <Input type="password" autoComplete="current-password" {...describe('off-password', form.formState.errors.password?.message)} {...form.register('password')} />
      </Field>
      <Field id="off-code" label="Code or recovery code" error={form.formState.errors.code?.message}>
        <Input autoComplete="one-time-code" className="max-w-56 font-mono tracking-widest" {...describe('off-code', form.formState.errors.code?.message)} {...form.register('code')} />
      </Field>
      <FormError message={error} />
      <div className="flex gap-2">
        <Button type="submit" variant="destructive" disabled={form.formState.isSubmitting} aria-busy={form.formState.isSubmitting}>
          {form.formState.isSubmitting && <Loader2 className="animate-spin" aria-hidden="true" />}
          Turn off
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

type Mode = 'idle' | 'setup' | 'codes' | 'off'

/** Account page card: turn authenticator-app sign-in on or off, and show recovery codes once. */
export function TwoFactorCard({ user }: { user: User }) {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<Mode>('idle')
  const [codes, setCodes] = useState<string[]>([])
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['me'] })
  const on = !!user.mfa_enabled

  return (
    <section aria-labelledby="mfa-h" className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
        <h2 id="mfa-h" className="text-sm font-semibold">
          Two-factor sign-in
        </h2>
        {on ? (
          <Badge tone="verified">
            <ShieldCheck aria-hidden="true" /> On
          </Badge>
        ) : (
          <Badge>
            <ShieldOff aria-hidden="true" /> Off
          </Badge>
        )}
      </div>
      <div className="px-5 py-4">
        {mode === 'codes' ? (
          <RecoveryCodes
            codes={codes}
            onDone={() => {
              setCodes([])
              setMode('idle')
            }}
          />
        ) : mode === 'setup' ? (
          <SetUp
            onCancel={() => setMode('idle')}
            onEnabled={(c) => {
              setCodes(c)
              setMode('codes')
              void refresh()
            }}
          />
        ) : mode === 'off' ? (
          <TurnOff
            onCancel={() => setMode('idle')}
            onDone={() => {
              setMode('idle')
              void refresh()
              toast.success('Two-factor sign-in is off.')
            }}
          />
        ) : (
          <div className="flex flex-col gap-3 text-sm">
            <p className="text-muted-foreground">
              {on
                ? 'Signing in asks for a code from your authenticator app after your password.'
                : 'Add a second step to sign-in: a short code from an app on your phone, so a stolen password alone is not enough.'}
            </p>
            {on ? (
              <Button variant="outline" className="self-start" onClick={() => setMode('off')}>
                Turn off
              </Button>
            ) : (
              <Button className="self-start" onClick={() => setMode('setup')}>
                Set up
              </Button>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
