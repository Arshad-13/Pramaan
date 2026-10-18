import { zodResolver } from '@hookform/resolvers/zod'
import { Clock, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { AuthLayout } from '@/components/AuthLayout'
import { Field } from '@/components/Field'
import { describe } from '@/lib/aria'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api, ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'

const schema = z
  .object({
    role: z.enum(['patient', 'pharmacist']),
    name: z.string().min(2, 'Enter your full name.'),
    email: z.string().email('Enter a valid email address.'),
    password: z.string().min(10, 'Use at least 10 characters.').max(128),
    license_no: z.string().optional(),
    org_name: z.string().optional(),
  })
  .superRefine((v, ctx) => {
    if (v.role === 'pharmacist') {
      if (!v.license_no?.trim()) ctx.addIssue({ code: 'custom', path: ['license_no'], message: 'Enter your licence number.' })
      if (!v.org_name?.trim()) ctx.addIssue({ code: 'custom', path: ['org_name'], message: 'Enter your pharmacy name.' })
    }
  })
type Values = z.infer<typeof schema>

export default function Register() {
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const {
    register,
    handleSubmit,
    control,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { role: 'patient' } })
  const role = useWatch({ control, name: 'role' })

  async function onSubmit(values: Values) {
    setFormError(null)
    try {
      await api('/auth/register', {
        method: 'POST',
        body: {
          ...values,
          license_no: values.role === 'pharmacist' ? values.license_no : undefined,
          org_name: values.role === 'pharmacist' ? values.org_name : undefined,
        },
      })
      if (values.role === 'pharmacist') setPending(true)
      else navigate('/login', { state: { notice: 'Account created. You can sign in now.' } })
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : 'Something went wrong. Try again.')
    }
  }

  if (pending) {
    return (
      <AuthLayout title="Registration received">
        <div role="status" className="flex items-start gap-3 rounded-lg border border-warning-border bg-warning-soft p-4 text-warning">
          <Clock className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
          <p className="text-sm">
            An administrator will review your licence details. You can sign in once your account is
            approved.
          </p>
        </div>
        <Button asChild variant="outline" className="mt-6">
          <Link to="/login">Back to sign in</Link>
        </Button>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="Create an account" description="Patients can start right away. Pharmacists are approved by an administrator.">
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5" noValidate>
        <div role="radiogroup" aria-label="Account type" className="grid grid-cols-2 gap-1 rounded-md border border-border bg-surface-2 p-1">
          {(['patient', 'pharmacist'] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={role === value}
              onClick={() => setValue('role', value, { shouldValidate: false })}
              className={cn(
                'h-9 rounded-sm text-sm font-medium capitalize transition-colors duration-150',
                role === value ? 'bg-surface text-foreground shadow-[inset_0_0_0_1px_var(--border)]' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {value}
            </button>
          ))}
        </div>

        <Field id="name" label="Full name" error={errors.name?.message}>
          <Input autoComplete="name" {...describe('name', errors.name?.message)} {...register('name')} />
        </Field>
        <Field id="email" label="Email" error={errors.email?.message}>
          <Input type="email" autoComplete="email" {...describe('email', errors.email?.message)} {...register('email')} />
        </Field>
        {role === 'pharmacist' && (
          <>
            <Field id="license_no" label="Pharmacy licence number" error={errors.license_no?.message}>
              <Input {...describe('license_no', errors.license_no?.message)} {...register('license_no')} />
            </Field>
            <Field id="org_name" label="Pharmacy name" error={errors.org_name?.message}>
              <Input {...describe('org_name', errors.org_name?.message)} {...register('org_name')} />
            </Field>
          </>
        )}
        <Field id="password" label="Password" hint="At least 10 characters." error={errors.password?.message}>
          <Input type="password" autoComplete="new-password" {...describe('password', errors.password?.message, 'hint')} {...register('password')} />
        </Field>

        {formError && (
          <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
            {formError}
          </p>
        )}
        <Button type="submit" size="lg" disabled={isSubmitting} aria-busy={isSubmitting}>
          {isSubmitting && <Loader2 className="animate-spin" aria-hidden="true" />}
          Create account
        </Button>
      </form>
      <p className="mt-6 text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link to="/login" className="font-medium text-foreground underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  )
}
