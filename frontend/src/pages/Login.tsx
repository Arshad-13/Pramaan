import { zodResolver } from '@hookform/resolvers/zod'
import { Eye, EyeOff, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { AuthLayout } from '@/components/AuthLayout'
import { Field } from '@/components/Field'
import { describe } from '@/lib/aria'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'

const schema = z.object({
  email: z.string().min(1, 'Enter your email address.'),
  password: z.string().min(1, 'Enter your password.'),
})
type Values = z.infer<typeof schema>

export default function Login() {
  const { user, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as { from?: string; notice?: string } | null
  const [show, setShow] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  if (user) return <Navigate to={state?.from ?? '/'} replace />

  async function onSubmit(values: Values) {
    setFormError(null)
    try {
      await signIn(values.email, values.password)
      navigate(state?.from ?? '/', { replace: true })
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : 'Something went wrong. Try again.')
    }
  }

  return (
    <AuthLayout title="Sign in" description="Use the account your administrator or pharmacy set up.">
      {state?.notice && (
        <p role="status" className="mb-5 rounded-md border border-verified-border bg-verified-soft px-3 py-2 text-sm text-verified">
          {state.notice}
        </p>
      )}
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5" noValidate>
        <Field id="email" label="Email" error={errors.email?.message}>
          <Input
            type="email"
            autoComplete="username"
            {...describe('email', errors.email?.message)}
            {...register('email')}
          />
        </Field>
        <Field id="password" label="Password" error={errors.password?.message}>
          <div className="relative">
            <Input
              type={show ? 'text' : 'password'}
              autoComplete="current-password"
              className="pr-11"
              {...describe('password', errors.password?.message)}
              {...register('password')}
            />
            <button
              type="button"
              aria-label={show ? 'Hide password' : 'Show password'}
              aria-pressed={show}
              onClick={() => setShow((v) => !v)}
              className="absolute right-1 top-1 grid size-8 place-items-center rounded-sm text-muted-foreground hover:text-foreground"
            >
              {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
        </Field>

        {formError && (
          <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
            {formError}
          </p>
        )}

        <Button type="submit" size="lg" disabled={isSubmitting} aria-busy={isSubmitting}>
          {isSubmitting && <Loader2 className="animate-spin" aria-hidden="true" />}
          Sign in
        </Button>
      </form>

      <p className="mt-6 text-sm text-muted-foreground">
        New patient or pharmacist?{' '}
        <Link to="/register" className="font-medium text-foreground underline underline-offset-4">
          Create an account
        </Link>
        . Doctors receive an activation code from an administrator:{' '}
        <Link to="/activate" className="font-medium text-foreground underline underline-offset-4">
          activate your account
        </Link>
        .
      </p>
    </AuthLayout>
  )
}
