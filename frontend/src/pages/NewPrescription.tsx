import { zodResolver } from '@hookform/resolvers/zod'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, FileDown, KeyRound, Loader2, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useFieldArray, useForm, useWatch } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { z } from 'zod'

import { describe } from '@/lib/aria'
import { Field } from '@/components/Field'
import { PageHeader } from '@/components/PageHeader'
import { PatientPicker } from '@/components/PatientPicker'
import { RiskPanel } from '@/components/RiskPanel'
import { RxPreview } from '@/components/RxPreview'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api, ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useDebouncedValue } from '@/lib/hooks'
import { MAX_MEDICINES, MAX_NOTES_CHARS, FREQUENCIES } from '@/lib/rx'
import type { Drug, IssueResult, Medicine, PatientMatch, RiskCheck } from '@/lib/types'

const num = (min: number, max: number, what: string) =>
  z
    .number({ error: `Enter ${what}.` })
    .int(`${what} must be a whole number.`)
    .min(min, `Must be at least ${min}.`)
    .max(max, `Must be at most ${max}.`)

const schema = z.object({
  medicines: z
    .array(
      z.object({
        name: z.string().trim().min(2, 'Enter the medicine name.').max(60, 'Too long (60 characters).'),
        dose_mg: num(1, 99999, 'a dose in mg'),
        frequency: z.enum(['OD', 'BD', 'TDS', 'QID', 'HS', 'SOS']),
        duration_days: num(1, 365, 'the number of days'),
      }),
    )
    .min(1)
    .max(MAX_MEDICINES),
  notes: z.string().max(MAX_NOTES_CHARS, `At most ${MAX_NOTES_CHARS} characters.`),
  validity_days: num(1, 90, 'validity in days'),
  max_fills: num(1, 5, 'the number of fills'),
  age_years: z.number().int().min(0).max(120).optional(),
  signing_password: z.string().min(1, 'Enter your signing password.'),
})
type Values = z.infer<typeof schema>

const emptyMedicine = (): Values['medicines'][number] => ({
  name: '',
  dose_mg: undefined as unknown as number,
  frequency: 'TDS',
  duration_days: undefined as unknown as number,
})

const textareaClass =
  'w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-base text-foreground placeholder:text-muted-foreground transition-colors duration-150 hover:border-foreground/40 focus-visible:border-ring aria-[invalid=true]:border-danger-solid'

const selectClass =
  'h-10 w-full rounded-md border border-border-strong bg-surface px-2 text-base text-foreground transition-colors duration-150 hover:border-foreground/40 focus-visible:border-ring'

export default function NewPrescription() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [patient, setPatient] = useState<PatientMatch | null>(null)
  const [patientError, setPatientError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [issued, setIssued] = useState<IssueResult | null>(null)

  const {
    register,
    control,
    handleSubmit,
    setError,
    setValue,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      medicines: [emptyMedicine()],
      notes: '',
      validity_days: 30,
      max_fills: 1,
      signing_password: '',
    },
  })
  const { fields, append, remove } = useFieldArray({ control, name: 'medicines' })
  const watched = useWatch({ control })

  const previewMedicines = useMemo<Medicine[]>(
    () =>
      (watched.medicines ?? []).map((m) => ({
        name: m?.name ?? '',
        dose_mg: Number(m?.dose_mg) || 0,
        frequency: m?.frequency ?? 'TDS',
        duration_days: Number(m?.duration_days) || 0,
      })),
    [watched.medicines],
  )

  // Live safety check: only rows that are complete enough to be scored, after a short pause.
  const scorable = useMemo(() => {
    const rows = previewMedicines
      .map((m, index) => ({ m, index }))
      .filter(({ m }) => m.name.trim().length >= 2 && m.dose_mg > 0 && m.duration_days > 0)
    return rows.length ? { rows, max_fills: Number(watched.max_fills) || 1 } : null
  }, [previewMedicines, watched.max_fills])
  const debouncedScorable = useDebouncedValue(scorable, 400)
  const { data: riskCheck } = useQuery({
    queryKey: ['risk-check', debouncedScorable],
    queryFn: () =>
      api<RiskCheck>('/prescriptions/risk-check', {
        method: 'POST',
        body: { medicines: debouncedScorable!.rows.map((r) => r.m), max_fills: debouncedScorable!.max_fills },
      }),
    enabled: debouncedScorable !== null,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
  const { data: drugs } = useQuery({
    queryKey: ['drugs'],
    queryFn: () => api<Drug[]>('/drugs'),
    staleTime: Infinity,
  })

  const [override, setOverride] = useState('')
  const [overrideError, setOverrideError] = useState<string | null>(null)
  const [serverAsked, setServerAsked] = useState(false)
  const needsOverride = Boolean(riskCheck?.requires_override) || serverAsked

  // Controlled medicines allow one fill only: reflect that in the form (and so in the preview).
  const maxFills = Number(watched.max_fills)
  useEffect(() => {
    if (riskCheck?.controlled && maxFills > 1) setValue('max_fills', 1)
  }, [riskCheck?.controlled, maxFills, setValue])

  // Map a note (indexed within the scored rows) back to the form row it describes.
  const noteFor = (rowIndex: number) => {
    const position = debouncedScorable?.rows.findIndex((r) => r.index === rowIndex) ?? -1
    return position >= 0 ? riskCheck?.medicines.find((n) => n.index === position) : undefined
  }

  async function onSubmit(values: Values) {
    setFormError(null)
    setOverrideError(null)
    if (!patient) {
      setPatientError('Choose a patient first.')
      return
    }
    if (needsOverride && override.trim().length < 10) {
      setOverrideError('Give a reason of at least 10 characters.')
      return
    }
    try {
      const result = await api<IssueResult>('/prescriptions', {
        method: 'POST',
        body: {
          ...values,
          patient_id: patient.public_id,
          override_reason: needsOverride ? override.trim() : undefined,
        },
      })
      setValue('signing_password', '') // never keep the password around
      setIssued(result)
      void queryClient.invalidateQueries({ queryKey: ['prescriptions'] })
    } catch (error) {
      setValue('signing_password', '')
      const code = error instanceof ApiError ? (error.body as { code?: string } | null)?.code : undefined
      if (code === 'RISK_CONFIRMATION_REQUIRED') {
        setServerAsked(true)
        setOverrideError('This prescription needs a reason before it can be signed.')
      } else if (error instanceof ApiError && (error.status === 403 || error.status === 423)) {
        setError('signing_password', { message: error.message })
      } else {
        setFormError(error instanceof ApiError ? error.message : 'Something went wrong. Try again.')
      }
    }
  }

  if (issued) {
    return (
      <>
        <PageHeader title="Prescription signed" />
        <div role="status" className="max-w-xl rounded-lg border border-verified-border bg-verified-soft p-6">
          <p className="flex items-center gap-2 font-medium text-verified">
            <CheckCircle2 className="size-5" aria-hidden="true" /> Signed and stored securely
          </p>
          <dl className="mt-4 space-y-2 text-sm text-foreground">
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">For</dt>
              <dd>{patient?.name}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Fingerprint</dt>
              <dd className="font-mono tracking-wide">{issued.fingerprint}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Valid until</dt>
              <dd>{new Date(issued.expires_at).toLocaleString()}</dd>
            </div>
          </dl>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button asChild>
              <a href={`/api/prescriptions/${issued.rx_id}/pdf`} target="_blank" rel="noopener">
                <FileDown aria-hidden="true" /> Open PDF
              </a>
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setIssued(null)
                setPatient(null)
                setOverride('')
                setServerAsked(false)
                reset()
              }}
            >
              Issue another
            </Button>
            <Button variant="ghost" asChild>
              <Link to="/prescriptions">My prescriptions</Link>
            </Button>
          </div>
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="New prescription"
        description="Check the preview, then sign. Only what you see here is signed and printed."
      />
      <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_25rem]">
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="max-w-2xl space-y-8">
          <section aria-labelledby="patient-h">
            <h2 id="patient-h" className="mb-3 text-sm font-semibold">
              Patient
            </h2>
            <PatientPicker
              selected={patient}
              onSelect={(p) => {
                setPatient(p)
                setPatientError(null)
              }}
            />
            {patientError && (
              <p role="alert" className="mt-2 text-sm font-medium text-danger">
                {patientError}
              </p>
            )}
            <div className="mt-4 max-w-[10rem]">
              <Field id="age" label="Age (optional)" error={errors.age_years?.message}>
                <Input
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={120}
                  {...describe('age', errors.age_years?.message)}
                  {...register('age_years', {
                    setValueAs: (v) => (v === '' || v == null ? undefined : Number(v)),
                  })}
                />
              </Field>
            </div>
          </section>

          <section aria-labelledby="meds-h">
            <h2 id="meds-h" className="mb-3 text-sm font-semibold">
              Medicines
            </h2>
            <datalist id="drug-list">
              {drugs?.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.is_brand ? `${d.generic} (brand)` : ''}
                </option>
              ))}
            </datalist>
            <ul className="space-y-4">
              {fields.map((field, i) => {
                const e = errors.medicines?.[i]
                const note = noteFor(i)
                return (
                  <li key={field.id} className="rounded-lg border border-border bg-surface p-4">
                    <div className="grid gap-3 sm:grid-cols-[1fr_6.5rem]">
                      <Field id={`m${i}-name`} label="Medicine" error={e?.name?.message}>
                        <Input
                          autoComplete="off"
                          list="drug-list"
                          {...describe(`m${i}-name`, e?.name?.message)}
                          {...register(`medicines.${i}.name`)}
                        />
                      </Field>
                      <Field id={`m${i}-dose`} label="Dose (mg)" error={e?.dose_mg?.message}>
                        <Input
                          type="number"
                          inputMode="numeric"
                          min={1}
                          {...describe(`m${i}-dose`, e?.dose_mg?.message)}
                          {...register(`medicines.${i}.dose_mg`, { valueAsNumber: true })}
                        />
                      </Field>
                    </div>
                    <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_7rem_auto] sm:items-end">
                      <Field id={`m${i}-freq`} label="How often">
                        <select id={`m${i}-freq`} className={selectClass} {...register(`medicines.${i}.frequency`)}>
                          {FREQUENCIES.map((f) => (
                            <option key={f.value} value={f.value}>
                              {f.value} · {f.label}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field id={`m${i}-days`} label="Days" error={e?.duration_days?.message}>
                        <Input
                          type="number"
                          inputMode="numeric"
                          min={1}
                          {...describe(`m${i}-days`, e?.duration_days?.message)}
                          {...register(`medicines.${i}.duration_days`, { valueAsNumber: true })}
                        />
                      </Field>
                      {fields.length > 1 && (
                        <Button type="button" variant="ghost" size="icon" aria-label={`Remove medicine ${i + 1}`} onClick={() => remove(i)}>
                          <Trash2 aria-hidden="true" />
                        </Button>
                      )}
                    </div>
                    {note?.status === 'POSSIBLE_TYPO' && note.suggestion && (
                      <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-warning">
                        Did you mean <strong>{note.suggestion}</strong>?
                        <Button type="button" size="sm" variant="outline" onClick={() => setValue(`medicines.${i}.name`, note.suggestion!, { shouldValidate: true })}>
                          Use {note.suggestion}
                        </Button>
                      </p>
                    )}
                    {note?.status === 'UNKNOWN' && (
                      <p className="mt-3 text-sm text-warning">This name is not in the drug list. You can still issue it with a reason.</p>
                    )}
                  </li>
                )
              })}
            </ul>
            {fields.length < MAX_MEDICINES && (
              <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => append(emptyMedicine())}>
                <Plus aria-hidden="true" /> Add medicine
              </Button>
            )}
          </section>

          <section aria-labelledby="terms-h" className="space-y-4">
            <h2 id="terms-h" className="text-sm font-semibold">
              Notes and validity
            </h2>
            <Field id="notes" label="Notes for the pharmacist (optional)" error={errors.notes?.message} hint={`${(watched.notes ?? '').length}/${MAX_NOTES_CHARS}`}>
              <textarea rows={3} className={textareaClass} {...describe('notes', errors.notes?.message, 'hint')} {...register('notes')} />
            </Field>
            <div className="grid max-w-md grid-cols-2 gap-3">
              <Field id="validity" label="Valid for (days)" error={errors.validity_days?.message} hint="Up to 90 days">
                <Input type="number" inputMode="numeric" min={1} max={90} {...describe('validity', errors.validity_days?.message, 'hint')} {...register('validity_days', { valueAsNumber: true })} />
              </Field>
              <Field id="fills" label="Fills allowed" error={errors.max_fills?.message} hint="1 for a single use">
                <Input type="number" inputMode="numeric" min={1} max={5} {...describe('fills', errors.max_fills?.message, 'hint')} {...register('max_fills', { valueAsNumber: true })} />
              </Field>
            </div>
          </section>

          <RiskPanel
            check={riskCheck}
            forced={serverAsked}
            override={override}
            onOverride={(v) => {
              setOverride(v)
              setOverrideError(null)
            }}
            error={overrideError}
          />

          <section aria-labelledby="sign-h" className="rounded-lg border border-border bg-surface-2 p-4">
            <h2 id="sign-h" className="flex items-center gap-2 text-sm font-semibold">
              <KeyRound className="size-4" aria-hidden="true" /> Sign
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Enter your signing password to unlock your private key for this one prescription. It is never stored.
            </p>
            <div className="mt-3 max-w-sm">
              <Field id="signing" label="Signing password" error={errors.signing_password?.message}>
                <Input type="password" autoComplete="off" {...describe('signing', errors.signing_password?.message)} {...register('signing_password')} />
              </Field>
            </div>
            {formError && (
              <p role="alert" className="mt-4 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
                {formError}
              </p>
            )}
            <Button type="submit" size="lg" className="mt-5" disabled={isSubmitting} aria-busy={isSubmitting}>
              {isSubmitting && <Loader2 className="animate-spin" aria-hidden="true" />}
              Sign and issue
            </Button>
          </section>
        </form>

        <aside aria-label="Preview" className="xl:sticky xl:top-6 xl:self-start">
          <h2 className="mb-3 text-sm font-semibold">Preview</h2>
          <RxPreview
            clinic={user?.org_name ?? ''}
            doctorName={user?.name ?? ''}
            licenseNo={user?.license_no ?? ''}
            patientName={patient?.name ?? null}
            ageYears={watched.age_years ?? null}
            validityDays={Number(watched.validity_days)}
            maxFills={Number(watched.max_fills) || 1}
            medicines={previewMedicines}
            notes={watched.notes ?? ''}
          />
        </aside>
      </div>
    </>
  )
}
