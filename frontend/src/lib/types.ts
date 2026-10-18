/** API shapes (mirrors app/schemas.py). Generated types arrive when openapi.json export lands. */

export type Role = 'doctor' | 'patient' | 'pharmacist' | 'admin' | 'auditor'
export type ApprovalStatus = 'APPROVED' | 'PENDING' | 'REJECTED'

export interface User {
  public_id: string
  email: string
  name: string
  role: Role
  license_no: string | null
  org_name: string | null
  patient_code: string | null
  approval_status: ApprovalStatus
  is_active: boolean
  created_at: string
}

export interface UserList {
  items: User[]
  total: number
}

export interface ActivationResult {
  user: User
  activation_token: string
  expires_at: string
}

export const ROLE_LABEL: Record<Role, string> = {
  doctor: 'Doctor',
  patient: 'Patient',
  pharmacist: 'Pharmacist',
  admin: 'Administrator',
  auditor: 'Auditor',
}

export type Frequency = 'OD' | 'BD' | 'TDS' | 'QID' | 'HS' | 'SOS'
export type RxStatus = 'ISSUED' | 'DISPENSED' | 'REVOKED' | 'EXPIRED'

export interface Medicine {
  name: string
  dose_mg: number
  frequency: Frequency
  duration_days: number
}

export interface Prescription {
  id: string
  status: RxStatus
  issued_at: string
  expires_at: string
  max_fills: number
  fills_used: number
  doctor_name: string | null
  patient_name: string | null
  medicines: Medicine[]
  notes: string
  key_id: string
  fingerprint: string
  risk_score: number | null
  require_pin: boolean
  readable: boolean
}

export interface IssueResult {
  rx_id: string
  issued_at: string
  expires_at: string
  max_fills: number
  key_id: string
  fingerprint: string
  risk: { score: number; flags: string[]; explanations: string[] }
  warnings: string[]
}

export interface PatientMatch {
  public_id: string
  name: string
  patient_code: string | null
}

export type VerifyResultCode =
  | 'VALID'
  | 'TAMPERED'
  | 'REVOKED'
  | 'ALREADY_USED'
  | 'EXPIRED'
  | 'SUSPICIOUS'
  | 'REVIEW_REQUIRED'
  | 'NOT_FOUND'
  | 'INVALID_QR'

export interface VerifyChecks {
  signature_valid: boolean | null
  hash_match: boolean | null
  key_state: string | null
  doctor_active: boolean | null
  status: string | null
  fills_remaining: number | null
  not_expired: boolean | null
  content_check: string
  file_integrity: string | null
}

export interface VerifyResult {
  result: VerifyResultCode
  reason_codes: string[]
  rx_id: string | null
  checks: VerifyChecks | null
  risk: { score: number; flags: string[]; explanations: string[] } | null
  warnings: string[]
  doctor: { name: string; license_no: string } | null
  patient: { name: string } | null
  medicines: Medicine[] | null
  issued_at: string | null
  expires_at: string | null
  can_dispense: boolean
  pin_required: boolean
}

export interface DispenseResult {
  rx_id: string
  fill_no: number
  fills_remaining: number
  status: string
}

export interface PinInfo {
  pin: string
  seconds_remaining: number
  step_seconds: number
}

export interface RiskInfo {
  score: number
  flags: string[]
  explanations: string[]
}

export interface MedicineNote {
  index: number
  name: string
  status: 'KNOWN' | 'POSSIBLE_TYPO' | 'UNKNOWN'
  suggestion: string | null
  generic: string | null
  flags: string[]
}

export interface RiskCheck {
  risk: RiskInfo
  threshold: number
  requires_override: boolean
  medicines: MedicineNote[]
  warnings: string[]
  controlled: boolean
}

export interface Drug {
  name: string
  generic: string
  is_brand: boolean
}
