import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Loader2, PackageCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api, ApiError } from '@/lib/api'
import { useT } from '@/lib/i18n'
import type { DispenseResult, VerifyResult } from '@/lib/types'

/** Hand over the medicine: needs the patient's PIN (or, for PIN-less prescriptions, a confirmation
 *  that the pharmacist checked the patient's identity). The server re-verifies everything. */
export function DispensePanel({
  result,
  qr,
  onDone,
  onReset,
}: {
  result: VerifyResult
  qr: string
  onDone?: (r: DispenseResult) => void
  onReset: () => void
}) {
  const t = useT()
  const [pin, setPin] = useState('')
  const [identity, setIdentity] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<DispenseResult | null>(null)

  const dispense = useMutation({
    mutationFn: () =>
      api<DispenseResult>(`/prescriptions/${result.rx_id}/dispense`, {
        method: 'POST',
        body: {
          qr_string: qr,
          patient_pin: result.pin_required ? pin.trim() : undefined,
          patient_identity_checked: result.pin_required ? undefined : identity,
        },
      }),
    onSuccess: (r) => {
      setDone(r)
      onDone?.(r)
    },
    onError: (e) => {
      setPin('')
      setError(e instanceof ApiError ? e.message : t('common.generic'))
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    dispense.mutate()
  }

  if (done) {
    return (
      <div role="status" className="rounded-lg border border-verified-border bg-verified-soft p-5">
        <p className="flex items-center gap-2 font-medium text-verified">
          <CheckCircle2 className="size-5" aria-hidden="true" /> {t('dispense.done', { n: done.fill_no })}
        </p>
        <p className="mt-1 text-sm text-foreground">
          {done.fills_remaining > 0
            ? t(done.fills_remaining === 1 ? 'dispense.moreOne' : 'dispense.moreMany', { n: done.fills_remaining })
            : t('dispense.fullyUsed')}
        </p>
        <Button className="mt-4" variant="outline" onClick={onReset}>
          {t('verify.another')}
        </Button>
      </div>
    )
  }

  const ready = result.pin_required ? /^\d{6}$/.test(pin.trim()) : identity
  return (
    <form onSubmit={submit} className="rounded-lg border border-border bg-surface p-5" noValidate>
      <h3 className="text-sm font-semibold">{t('dispense.title')}</h3>
      {result.pin_required ? (
        <div className="mt-3 max-w-xs">
          <label htmlFor="patient-pin" className="text-sm font-medium">
            {t('dispense.pin')}
          </label>
          <Input
            id="patient-pin"
            className="mt-1.5 text-center font-mono text-xl tracking-[0.4em]"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
            aria-describedby="pin-hint"
          />
          <p id="pin-hint" className="mt-1.5 text-xs text-muted-foreground">
            {t('dispense.pinHint')}
          </p>
        </div>
      ) : (
        <label className="mt-3 flex items-start gap-2.5 text-sm">
          <input type="checkbox" className="mt-0.5 size-4" checked={identity} onChange={(e) => setIdentity(e.target.checked)} />
          <span>{t('dispense.identity')}</span>
        </label>
      )}
      {error && (
        <p role="alert" className="mt-4 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      <Button type="submit" size="lg" className="mt-5" disabled={!ready || dispense.isPending} aria-busy={dispense.isPending}>
        {dispense.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <PackageCheck aria-hidden="true" />}
        {t('dispense.submit')}
      </Button>
    </form>
  )
}
