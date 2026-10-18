/** How a prescription reads on paper. Mirrors app/core/payload.py so the live preview shows the
 *  same words the signed PDF will contain (what you see is what you sign). */
import type { Frequency, Medicine } from '@/lib/types'

export const FREQUENCIES: { value: Frequency; label: string }[] = [
  { value: 'OD', label: 'Once daily' },
  { value: 'BD', label: 'Twice daily' },
  { value: 'TDS', label: 'Three times daily' },
  { value: 'QID', label: 'Four times daily' },
  { value: 'HS', label: 'At bedtime' },
  { value: 'SOS', label: 'If needed' },
]

export const MAX_MEDICINES = 8
export const MAX_NOTES_CHARS = 500

const pad = (n: number) => String(n).padStart(2, '0')

/** '2026-10-18 10:30 UTC' */
export function dateTimeUtc(d: Date): string {
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
}

export function addDays(d: Date, days: number): Date {
  return new Date(d.getTime() + days * 86_400_000)
}

export function patientLine(name: string, age?: number | null): string {
  return `Patient: ${name}` + (age != null ? `, ${age} yrs` : '')
}

export function medicineCells(m: Medicine): [string, string, string, string] {
  return [m.name, `${m.dose_mg} mg`, m.frequency, `${m.duration_days} days`]
}

/** Short readable list for tables: "Amoxicillin 500 mg TDS, 5 days". */
export function medicineSummary(m: Medicine): string {
  return `${m.name} ${m.dose_mg} mg ${m.frequency}, ${m.duration_days} days`
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
}
