import { zodResolver } from '@hookform/resolvers/zod'
import { KeyRound, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { AuthLayout } from '@/components/AuthLayout'
import { Field } from '@/components/Field'
import { describe } from '@/lib/aria'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api, ApiError } from '@/lib/api'

const activateSchema = z
  .object({
    email: z.string().email('Enter the email your administrator used.'),
    token: z.string().min(20, 'Paste the full activation code.'),
    login_password: z.string().min(10, 'Use at least 10 characters.').max(128),
    signing_password: z.string().min(10, 'Use at least 10 characters.').max(128),
  })
  .refine((v) => v.login_password !== v.signing_password, {
    path: ['signing_password'],
    message: 'The signing password must be different from your login password.',
  })
type Values = z.infer<typeof activateSchema>

export default function Activate() {
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(activateSchema) })

  async function onSubmit(values: Values) {
    setFormError(null)
    try {
      await api('/auth/activate', { method: 'POST', body: values })
      navigate('/login', { state: { notice: 'Account activated. Sign in with your login password.' } })
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : 'Something went wrong. Try again.')
    }
  }

  return (
    <AuthLayout title="Activate your doctor account" description="Use the one-time code from your administrator.">
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5" noValidate>
        <Field id="email" label="Email" error={errors.email?.message}>
          <Input type="email" autoComplete="username" {...describe('email', errors.email?.message)} {...register('email')} />
        </Field>
        <Field id="token" label="Activation code" error={errors.token?.message}>
          <Input className="font-mono text-sm" autoComplete="off" spellCheck={false} {...describe('token', errors.token?.message)} {...register('token')} />
        </Field>
        <Field id="login_password" label="Login password" hint="Used to sign in. At least 10 characters." error={errors.login_password?.message}>
          <Input type="password" autoComplete="new-password" {...describe('login_password', errors.login_password?.message, 'hint')} {...register('login_password')} />
        </Field>

        <div className="rounded-lg border border-border bg-surface-2 p-4">
          <p className="flex items-center gap-2 text-sm font-medium">
            <KeyRound className="size-4" aria-hidden="true" /> Signing password
          </p>
          <p className="mt-1.5 text-sm text-muted-foreground">
            This unlocks your private signing key each time you issue a prescription. It must differ from
            your login password. It is never stored and cannot be recovered, so remember it.
          </p>
          <div className="mt-3">
            <Field id="signing_password" label="Choose a signing password" error={errors.signing_password?.message}>
              <Input type="password" autoComplete="new-password" {...describe('signing_password', errors.signing_password?.message)} {...register('signing_password')} />
            </Field>
          </div>
        </div>

        {formError && (
          <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
            {formError}
          </p>
        )}
        <Button type="submit" size="lg" disabled={isSubmitting} aria-busy={isSubmitting}>
          {isSubmitting && <Loader2 className="animate-spin" aria-hidden="true" />}
          Activate account
        </Button>
      </form>
      <p className="mt-6 text-sm text-muted-foreground">
        Already activated?{' '}
        <Link to="/login" className="font-medium text-foreground underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  )
}
