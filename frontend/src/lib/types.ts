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
