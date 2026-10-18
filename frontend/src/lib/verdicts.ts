import {
  Ban,
  CircleHelp,
  Clock,
  PackageCheck,
  QrCode,
  ScanSearch,
  ShieldCheck,
  ShieldX,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'

/** Every result the verification pipeline can return (Spec Section 10.2). */
export const VERDICTS = [
  'VALID',
  'TAMPERED',
  'REVOKED',
  'ALREADY_USED',
  'EXPIRED',
  'SUSPICIOUS',
  'REVIEW_REQUIRED',
  'NOT_FOUND',
  'INVALID_QR',
] as const

export type Verdict = (typeof VERDICTS)[number]
export type Tone = 'verified' | 'danger' | 'warning'

export interface VerdictMeta {
  label: string
  tone: Tone
  icon: LucideIcon
  summary: string
}

/** Colour is always paired with an icon and a text label (never colour alone). */
export const VERDICT_META: Record<Verdict, VerdictMeta> = {
  VALID: {
    label: 'Verified',
    tone: 'verified',
    icon: ShieldCheck,
    summary: 'Signature, hash and status all check out.',
  },
  TAMPERED: {
    label: 'Tampered',
    tone: 'danger',
    icon: ShieldX,
    summary: 'This prescription does not match what the doctor signed.',
  },
  REVOKED: {
    label: 'Revoked',
    tone: 'danger',
    icon: Ban,
    summary: 'The doctor or an administrator withdrew this prescription.',
  },
  ALREADY_USED: {
    label: 'Already used',
    tone: 'warning',
    icon: PackageCheck,
    summary: 'All permitted fills have been dispensed.',
  },
  EXPIRED: {
    label: 'Expired',
    tone: 'warning',
    icon: Clock,
    summary: 'The validity period set by the doctor has ended.',
  },
  SUSPICIOUS: {
    label: 'Suspicious',
    tone: 'warning',
    icon: TriangleAlert,
    summary: 'Authentic, but the contents look unusual. Review before dispensing.',
  },
  REVIEW_REQUIRED: {
    label: 'Review required',
    tone: 'warning',
    icon: ScanSearch,
    summary: 'Authentic, but some printed fields could not be read. Use the verified record.',
  },
  NOT_FOUND: {
    label: 'Not found',
    tone: 'danger',
    icon: CircleHelp,
    summary: 'No prescription with this identifier exists.',
  },
  INVALID_QR: {
    label: 'Invalid QR',
    tone: 'danger',
    icon: QrCode,
    summary: 'The code is not a valid Pramaan prescription code.',
  },
}
