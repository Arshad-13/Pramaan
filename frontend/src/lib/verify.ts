/** Turning a verification result into the step-by-step evidence the pharmacist sees. */
import type { VerifyResult } from '@/lib/types'

export type StepState = 'pass' | 'fail' | 'warn' | 'skipped'

export interface Step {
  id: string
  label: string
  state: StepState
  note?: string
}

/** Plain-language text for every reason code the server can return. */
export const REASON_TEXT: Record<string, string> = {
  MALFORMED_QR: 'This is not a Pramaan prescription code.',
  NOT_FOUND: 'No prescription with this identifier exists.',
  DB_RECORD_ALTERED: 'The stored record does not match what the doctor signed.',
  QR_HASH_MISMATCH: 'The code does not match the signed prescription.',
  INVALID_SIGNATURE: "The doctor's digital signature is not valid.",
  KEY_ID_MISMATCH: 'The code names a different signing key than the prescription.',
  KEY_NOT_FOUND: "The doctor's signing key could not be found.",
  DOCTOR_KEY_REVOKED: "The doctor's signing key was revoked.",
  DOCTOR_SUSPENDED: "The doctor's account was suspended.",
  RX_REVOKED: 'The doctor withdrew this prescription.',
  FULLY_DISPENSED: 'Every permitted fill has already been dispensed.',
  RX_EXPIRED: 'The validity period set by the doctor has ended.',
  RISK_ABOVE_THRESHOLD: 'The contents look unusual and need your review.',
}

export function reasonText(code: string): string {
  return REASON_TEXT[code] ?? code
}

const HARD_FAILURES = new Set(['INVALID_QR', 'NOT_FOUND', 'TAMPERED'])

/** The seven checks, in pipeline order. Steps after a hard failure are shown as skipped. */
export function timelineSteps(r: VerifyResult): Step[] {
  const has = (...codes: string[]) => codes.some((c) => r.reason_codes.includes(c))
  const hard = HARD_FAILURES.has(r.result)
  const skipped = (id: string, label: string): Step => ({ id, label, state: 'skipped', note: 'Not checked' })

  const steps: Step[] = []
  steps.push({
    id: 'read',
    label: 'Code read',
    state: r.result === 'INVALID_QR' ? 'fail' : 'pass',
    note: r.result === 'INVALID_QR' ? reasonText('MALFORMED_QR') : undefined,
  })
  if (r.result === 'INVALID_QR') {
    return [
      steps[0],
      skipped('found', 'Prescription found'),
      skipped('record', 'Record unaltered'),
      skipped('signature', "Doctor's signature"),
      skipped('standing', 'Doctor in good standing'),
      skipped('status', 'Unused, current and not withdrawn'),
      skipped('risk', 'Risk check'),
    ]
  }
  if (r.result === 'NOT_FOUND') {
    return [
      steps[0],
      { id: 'found', label: 'Prescription found', state: 'fail', note: reasonText('NOT_FOUND') },
      skipped('record', 'Record unaltered'),
      skipped('signature', "Doctor's signature"),
      skipped('standing', 'Doctor in good standing'),
      skipped('status', 'Unused, current and not withdrawn'),
      skipped('risk', 'Risk check'),
    ]
  }

  steps.push({ id: 'found', label: 'Prescription found', state: 'pass' })
  const recordBad = has('DB_RECORD_ALTERED', 'QR_HASH_MISMATCH')
  steps.push({
    id: 'record',
    label: 'Record unaltered',
    state: recordBad ? 'fail' : 'pass',
    note: recordBad ? reasonText(r.reason_codes.find((c) => c === 'QR_HASH_MISMATCH') ?? 'DB_RECORD_ALTERED') : undefined,
  })
  const sigBad = has('INVALID_SIGNATURE', 'KEY_ID_MISMATCH', 'KEY_NOT_FOUND')
  steps.push({
    id: 'signature',
    label: "Doctor's signature",
    state: sigBad ? 'fail' : 'pass',
    note: sigBad ? reasonText(r.reason_codes.find((c) => ['INVALID_SIGNATURE', 'KEY_ID_MISMATCH', 'KEY_NOT_FOUND'].includes(c))!) : undefined,
  })
  if (hard) {
    return [
      ...steps,
      skipped('standing', 'Doctor in good standing'),
      skipped('status', 'Unused, current and not withdrawn'),
      skipped('risk', 'Risk check'),
    ]
  }

  const standingBad = has('DOCTOR_KEY_REVOKED', 'DOCTOR_SUSPENDED')
  steps.push({
    id: 'standing',
    label: 'Doctor in good standing',
    state: standingBad ? 'fail' : 'pass',
    note: standingBad ? reasonText(r.reason_codes.find((c) => c.startsWith('DOCTOR_'))!) : undefined,
  })
  const statusCode = ['RX_REVOKED', 'FULLY_DISPENSED', 'RX_EXPIRED'].find((c) => has(c))
  steps.push({
    id: 'status',
    label: 'Unused, current and not withdrawn',
    state: statusCode ? 'fail' : 'pass',
    note: statusCode ? reasonText(statusCode) : undefined,
  })
  const risky = has('RISK_ABOVE_THRESHOLD')
  steps.push({
    id: 'risk',
    label: 'Risk check',
    state: risky ? 'warn' : 'pass',
    note: risky ? reasonText('RISK_ABOVE_THRESHOLD') : undefined,
  })
  return steps
}
