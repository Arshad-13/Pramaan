import { zodResolver } from '@hookform/resolvers/zod'
import { Eye, EyeOff, KeyRound, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { AuthLayout } from '@/components/AuthLayout'
import { DemoLogins } from '@/components/DemoAccounts'
import { Field } from '@/components/Field'
import { describe } from '@/lib/aria'
import type { DemoAccount } from '@/lib/demoAccounts'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useT, type Translate } from '@/lib/i18n'

const makeSchema = (t: Translate) =>
  z.object({
    email: z.string().min(1, t('login.emailRequired')),
    password: z.string().min(1, t('login.passwordRequired')),
  })
type Values = z.infer<ReturnType<typeof makeSchema>>

const makeCodeSchema = (t: Translate) => z.object({ code: z.string().trim().min(6, t('mfa.codeRequired')) })
type CodeValues = z.infer<ReturnType<typeof makeCodeSchema>>

/** Second step: a code from the authenticator app, or one of the recovery codes. */
function SecondStep({ mfaToken, onBack, onDone }: { mfaToken: string; onBack: () => void; onDone: () => void }) {
  const { completeMfa } = useAuth()
  const t = useT()
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<CodeValues>({ resolver: zodResolver(makeCodeSchema(t)) })

  async function onSubmit(values: CodeValues) {
    setFormError(null)
    try {
      await completeMfa(mfaToken, values.code)
      onDone()
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : t('common.generic'))
    }
  }

  return (
    <AuthLayout title={t('mfa.title')} description={t('mfa.description')}>
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5" noValidate>
        <Field id="code" label={t('mfa.code')} hint={t('mfa.hint')} error={errors.code?.message}>
          <Input
            inputMode="text"
            autoComplete="one-time-code"
            autoFocus
            className="font-mono tracking-widest"
            {...describe('code', errors.code?.message, 'hint')}
            {...register('code')}
          />
        </Field>
        {formError && (
          <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
            {formError}
          </p>
        )}
        <Button type="submit" size="lg" disabled={isSubmitting} aria-busy={isSubmitting}>
          {isSubmitting ? <Loader2 className="animate-spin" aria-hidden="true" /> : <KeyRound aria-hidden="true" />}
          {t('mfa.submit')}
        </Button>
        <button type="button" onClick={onBack} className="self-start text-sm font-medium text-muted-foreground underline underline-offset-4 hover:text-foreground">
          {t('mfa.other')}
        </button>
      </form>
    </AuthLayout>
  )
}

export default function Login() {
  const { user, signIn } = useAuth()
  const t = useT()
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as { from?: string; notice?: string } | null
  const [show, setShow] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(makeSchema(t)) })

  function fillDemo(account: DemoAccount) {
    setFormError(null)
    setValue('email', account.email, { shouldValidate: true })
    setValue('password', account.password, { shouldValidate: true })
  }

  if (user) return <Navigate to={state?.from ?? '/'} replace />

  async function onSubmit(values: Values) {
    setFormError(null)
    try {
      const result = await signIn(values.email, values.password)
      if (result.status === 'mfa') {
        setMfaToken(result.mfaToken)
        return
      }
      navigate(state?.from ?? '/', { replace: true })
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : t('common.generic'))
    }
  }

  if (mfaToken) {
    return <SecondStep mfaToken={mfaToken} onBack={() => setMfaToken(null)} onDone={() => navigate(state?.from ?? '/', { replace: true })} />
  }

  return (
    <AuthLayout title={t('login.title')} description={t('login.description')}>
      {state?.notice && (
        <p role="status" className="mb-5 rounded-md border border-verified-border bg-verified-soft px-3 py-2 text-sm text-verified">
          {state.notice}
        </p>
      )}
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5" noValidate>
        <Field id="email" label={t('login.email')} error={errors.email?.message}>
          <Input
            type="email"
            autoComplete="username"
            {...describe('email', errors.email?.message)}
            {...register('email')}
          />
        </Field>
        <Field id="password" label={t('login.password')} error={errors.password?.message}>
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
              aria-label={show ? t('login.hide') : t('login.show')}
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
          {t('login.submit')}
        </Button>
      </form>

      <DemoLogins onPick={fillDemo} />

      <p className="mt-6 text-sm text-muted-foreground">
        {t('login.newHere')}{' '}
        <Link to="/register" className="font-medium text-foreground underline underline-offset-4">
          {t('login.create')}
        </Link>
        . {t('login.doctorNote')}{' '}
        <Link to="/activate" className="font-medium text-foreground underline underline-offset-4">
          {t('login.activate')}
        </Link>
        .
      </p>
    </AuthLayout>
  )
}
