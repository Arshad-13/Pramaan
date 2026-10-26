import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Field } from '@/components/Field'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api, ApiError } from '@/lib/api'
import { describe } from '@/lib/aria'
import { useAuth } from '@/lib/auth'
import { ROLE_LABEL } from '@/lib/types'

const schema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password.'),
    new_password: z.string().min(10, 'Use at least 10 characters.').max(128, 'Use at most 128 characters.'),
    confirm_password: z.string().min(1, 'Type the new password again.'),
  })
  .refine((v) => v.new_password === v.confirm_password, {
    path: ['confirm_password'],
    message: 'The two new passwords do not match.',
  })
  .refine((v) => v.new_password !== v.current_password, {
    path: ['new_password'],
    message: 'Choose a password you have not used just now.',
  })
type Values = z.infer<typeof schema>

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{children}</dd>
    </div>
  )
}

export default function Account() {
  const { user, endSession } = useAuth()
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  if (!user) return null

  async function onSubmit(values: Values) {
    setFormError(null)
    try {
      await api('/auth/change-password', {
        method: 'POST',
        body: { current_password: values.current_password, new_password: values.new_password },
      })
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : 'Something went wrong. Try again.')
      return
    }
    // The server ended every session (this one included). Forgetting ours makes RequireAuth send
    // the visitor to the sign-in page, so say what happened with a toast that survives the redirect.
    toast.success('Password changed. You were signed out everywhere; sign in with the new one.')
    endSession()
  }

  return (
    <>
      <PageHeader title="Account" description="Your details, and the password you sign in with." />

      <div className="grid max-w-4xl gap-6 lg:grid-cols-2 lg:items-start">
        <section aria-labelledby="details-h" className="rounded-lg border border-border bg-surface">
          <h2 id="details-h" className="border-b border-border px-5 py-3 text-sm font-semibold">
            Your details
          </h2>
          <dl className="grid gap-y-3 px-5 py-4 text-sm">
            <Detail label="Name">{user.name}</Detail>
            <Detail label="Email">{user.email}</Detail>
            <Detail label="Role">{ROLE_LABEL[user.role]}</Detail>
            {user.license_no && <Detail label="Registration number">{user.license_no}</Detail>}
            {user.org_name && <Detail label={user.role === 'pharmacist' ? 'Pharmacy' : 'Clinic'}>{user.org_name}</Detail>}
            {user.patient_code && (
              <Detail label="Patient code">
                <span className="font-mono">{user.patient_code}</span>
                <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
                  Give this to your doctor so they can find you.
                </span>
              </Detail>
            )}
          </dl>
        </section>

        <section aria-labelledby="password-h" className="rounded-lg border border-border bg-surface">
          <h2 id="password-h" className="border-b border-border px-5 py-3 text-sm font-semibold">
            Change password
          </h2>
          <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5 px-5 py-4" noValidate>
            <Field id="current_password" label="Current password" error={errors.current_password?.message}>
              <Input type="password" autoComplete="current-password" {...describe('current_password', errors.current_password?.message)} {...register('current_password')} />
            </Field>
            <Field id="new_password" label="New password" hint="At least 10 characters." error={errors.new_password?.message}>
              <Input type="password" autoComplete="new-password" {...describe('new_password', errors.new_password?.message, 'hint')} {...register('new_password')} />
            </Field>
            <Field id="confirm_password" label="New password again" error={errors.confirm_password?.message}>
              <Input type="password" autoComplete="new-password" {...describe('confirm_password', errors.confirm_password?.message)} {...register('confirm_password')} />
            </Field>

            <p className="text-sm text-muted-foreground">
              Changing it signs you out on every device.
              {user.role === 'doctor' && ' Your signing password is separate and does not change.'}
            </p>

            {formError && (
              <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
                {formError}
              </p>
            )}
            <Button type="submit" disabled={isSubmitting} aria-busy={isSubmitting} className="self-start">
              {isSubmitting && <Loader2 className="animate-spin" aria-hidden="true" />}
              Change password
            </Button>
          </form>
        </section>
      </div>
    </>
  )
}
