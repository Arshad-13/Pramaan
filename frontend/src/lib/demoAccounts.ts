/**
 * Demo accounts created by `scripts/seed_demo.py`, hard-coded so every role can be tried with one click.
 * These are throwaway local-demo passwords. Build with VITE_DEMO_LOGINS=false to hide the panels.
 */
export const DEMO_LOGINS_ENABLED = import.meta.env.VITE_DEMO_LOGINS !== 'false'

export type DemoRole = 'admin' | 'auditor' | 'doctor' | 'pharmacist' | 'patient'

export interface DemoAccount {
  role: DemoRole
  name: string
  email: string
  password: string
}

export const DOCTOR_SIGNING_PASSWORD = 'Doctor-Signing-Phrase-9'

export const DEMO_ACCOUNTS: DemoAccount[] = [
  { role: 'admin', name: 'Administrator', email: 'admin@pramaan.test', password: 'Admin-Demo-2026' },
  { role: 'auditor', name: 'Auditor', email: 'auditor@pramaan.test', password: 'Auditor-Demo-2026' },
  { role: 'doctor', name: 'Dr. Shah', email: 'dr.shah@clinic.test', password: 'Doctor-Login-2026' },
  { role: 'doctor', name: 'Dr. Iyer', email: 'dr.iyer@clinic.test', password: 'Doctor-Login-2026' },
  { role: 'pharmacist', name: 'Meera, City Pharm', email: 'meera@citypharm.test', password: 'Pharma-Secret-2026' },
  { role: 'pharmacist', name: 'Rohan, MedPlus', email: 'rohan@medplus.test', password: 'Pharma-Secret-2026' },
  { role: 'patient', name: 'Ravi Patel', email: 'ravi.patel@example.test', password: 'Patient-Demo-2026' },
  { role: 'patient', name: 'Sneha Rao', email: 'sneha.rao@example.test', password: 'Patient-Demo-2026' },
  { role: 'patient', name: 'Kabir Khan', email: 'kabir.khan@example.test', password: 'Patient-Demo-2026' },
  { role: 'patient', name: 'Anita Desai', email: 'anita.desai@example.test', password: 'Patient-Demo-2026' },
]

export interface DemoSignup {
  label: string
  role: 'patient' | 'pharmacist'
  name: string
  email: string
  password: string
  license_no?: string
  org_name?: string
}

/** Fresh details each click, because the server rejects an email that is already registered. */
export function demoSignup(role: 'patient' | 'pharmacist'): DemoSignup {
  const tag = Math.random().toString(36).slice(2, 7)
  return role === 'patient'
    ? {
        label: 'Patient',
        role,
        name: 'Test Patient',
        email: `test.patient.${tag}@example.test`,
        password: 'Patient-Demo-2026',
      }
    : {
        label: 'Pharmacist',
        role,
        name: 'Test Pharmacist',
        email: `test.pharmacist.${tag}@example.test`,
        password: 'Pharma-Secret-2026',
        license_no: `GJ-${Math.floor(10000 + Math.random() * 90000)}`,
        org_name: 'Test Chemist',
      }
}
