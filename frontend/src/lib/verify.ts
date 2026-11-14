/** Turning a verification result into the step-by-step evidence the pharmacist sees. */
import { translate, type MessageKey, type Translate } from '@/lib/i18n'
import { en } from '@/lib/i18n/en'
import type { VerifyResult } from '@/lib/types'

export type StepState = 'pass' | 'fail' | 'warn' | 'skipped'

export interface Step {
  id: string
  label: string
  /** Translation key for the label. */
  labelKey: MessageKey
  state: StepState
  note?: string
  /** Translation key for the note (the English text is in `note`). */
  noteKey?: MessageKey
}

const english: Translate = (key, vars) => translate('en', key, vars)

/**
 * The line under "Verified record". "Dispense according to this record" is only right when the
 * prescription is cleared; under any other verdict it must not read like an instruction to hand
 * the medicine over.
 */
export function recordGuidanceKey(result: VerifyResult): MessageKey {
  if (result.can_dispense) return 'record.guidance.dispense'
  if (result.result === 'TAMPERED') return 'record.guidance.tampered'
  if (result.result === 'REVIEW_REQUIRED') return 'record.guidance.review'
  return 'record.guidance.other'
}

export function recordGuidance(result: VerifyResult, t: Translate = english): string {
  return t(recordGuidanceKey(result))
}

/** What to do next, in one sentence, for each verdict: shown right under the verdict. */
export function nextActionKey(result: VerifyResult): MessageKey {
  if (result.can_dispense && result.result === 'REVIEW_REQUIRED') return 'next.reviewDispense'
  if (result.can_dispense) return 'next.dispense'
  if (result.reason_codes.includes('RX_SUPERSEDED')) return 'next.superseded'
  switch (result.result) {
    case 'TAMPERED':
      return 'next.tampered'
    case 'REVOKED':
      return 'next.revoked'
    case 'ALREADY_USED':
      return 'next.used'
    case 'EXPIRED':
      return 'next.expired'
    case 'SUSPICIOUS':
      return 'next.suspicious'
    case 'REVIEW_REQUIRED':
      return 'next.review'
    case 'NOT_FOUND':
      return 'next.notFound'
    case 'INVALID_QR':
      return 'next.invalid'
    default:
      return 'next.default'
  }
}

export function nextAction(result: VerifyResult, t: Translate = english): string {
  return t(nextActionKey(result))
}

/** Plain-language text for every reason code the server can return (English; see i18n for others). */
export const REASON_TEXT: Record<string, string> = Object.fromEntries(
  Object.entries(en)
    .filter(([key]) => key.startsWith('reason.'))
    .map(([key, text]) => [key.slice('reason.'.length), text]),
)

/** The text for a reason code, in the language of `t` when one is given (English otherwise). */
export function reasonText(code: string, t?: Translate): string {
  const key = `reason.${code}` as MessageKey
  if (t && key in en) return t(key)
  return REASON_TEXT[code] ?? code
}

const HARD_FAILURES = new Set(['INVALID_QR', 'NOT_FOUND', 'TAMPERED'])

type StepId = 'read' | 'found' | 'record' | 'signature' | 'content' | 'standing' | 'status' | 'risk'
const LABELS: Record<StepId, MessageKey> = {
  read: 'step.read',
  found: 'step.found',
  record: 'step.record',
  signature: 'step.signature',
  content: 'step.content',
  standing: 'step.standing',
  status: 'step.status',
  risk: 'step.risk',
}

function step(id: StepId, state: StepState, reasonCode?: string): Step {
  const labelKey = LABELS[id]
  const noteKey = reasonCode ? (`reason.${reasonCode}` as MessageKey) : undefined
  return { id, label: en[labelKey], labelKey, state, note: reasonCode ? reasonText(reasonCode) : undefined, noteKey }
}

function skipped(id: StepId): Step {
  const labelKey = LABELS[id]
  return { id, label: en[labelKey], labelKey, state: 'skipped', note: en['state.skipped'], noteKey: 'state.skipped' }
}

/** The seven checks, in pipeline order. Steps after a hard failure are shown as skipped. */
export function timelineSteps(r: VerifyResult): Step[] {
  const has = (...codes: string[]) => codes.some((c) => r.reason_codes.includes(c))
  const hard = HARD_FAILURES.has(r.result)
  const firstOf = (...codes: string[]) => codes.find((c) => r.reason_codes.includes(c))

  if (r.result === 'INVALID_QR') {
    return [
      step('read', 'fail', has('NO_QR_IN_FILE') ? 'NO_QR_IN_FILE' : 'MALFORMED_QR'),
      skipped('found'),
      skipped('record'),
      skipped('signature'),
      skipped('standing'),
      skipped('status'),
      skipped('risk'),
    ]
  }
  if (r.result === 'NOT_FOUND') {
    return [
      step('read', 'pass'),
      step('found', 'fail', 'NOT_FOUND'),
      skipped('record'),
      skipped('signature'),
      skipped('standing'),
      skipped('status'),
      skipped('risk'),
    ]
  }

  const steps: Step[] = [step('read', 'pass'), step('found', 'pass')]
  const recordBad = has('DB_RECORD_ALTERED', 'QR_HASH_MISMATCH')
  steps.push(
    recordBad
      ? step('record', 'fail', r.reason_codes.find((c) => c === 'QR_HASH_MISMATCH') ?? 'DB_RECORD_ALTERED')
      : step('record', 'pass'),
  )
  const contentRan = (r.checks?.content_check ?? 'NOT_CHECKED') !== 'NOT_CHECKED'
  const sigCode = firstOf('INVALID_SIGNATURE', 'KEY_ID_MISMATCH', 'KEY_NOT_FOUND')
  steps.push(sigCode ? step('signature', 'fail', sigCode) : step('signature', 'pass'))

  const content = r.checks?.content_check ?? 'NOT_CHECKED'
  if (content !== 'NOT_CHECKED') {
    const badCode = firstOf('HIDDEN_TEXT_OR_OVERLAY', 'EXTRA_CONTENT', 'CONTENT_MISMATCH')
    steps.push(
      badCode
        ? step('content', 'fail', badCode)
        : content === 'MATCH'
          ? step('content', 'pass')
          : step('content', 'warn', 'UNREADABLE_CONTENT'),
    )
  }
  if (hard && !contentRan) {
    return [...steps, skipped('standing'), skipped('status'), skipped('risk')]
  }

  const standingCode = r.reason_codes.find((c) => c.startsWith('DOCTOR_'))
  steps.push(has('DOCTOR_KEY_REVOKED', 'DOCTOR_SUSPENDED') && standingCode ? step('standing', 'fail', standingCode) : step('standing', 'pass'))
  const statusCode = firstOf('RX_SUPERSEDED', 'RX_REVOKED', 'FULLY_DISPENSED', 'RX_EXPIRED')
  steps.push(statusCode ? step('status', 'fail', statusCode) : step('status', 'pass'))
  steps.push(has('RISK_ABOVE_THRESHOLD') ? step('risk', 'warn', 'RISK_ABOVE_THRESHOLD') : step('risk', 'pass'))
  return steps
}
