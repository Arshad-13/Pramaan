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
