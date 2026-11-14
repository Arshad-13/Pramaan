/** Small helpers for the activity charts on the dashboards. */

export interface DayCount {
  /** Local calendar day, 'YYYY-MM-DD'. */
  day: string
  count: number
}

const pad = (n: number) => String(n).padStart(2, '0')
const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

/** How many of the given moments fall on each of the last `days` local days (oldest first, today last). */
export function lastDays(isoTimes: string[], days: number, now: Date = new Date()): DayCount[] {
  const buckets = new Map<string, number>()
  const out: DayCount[] = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i)
    const key = dayKey(d)
    buckets.set(key, 0)
    out.push({ day: key, count: 0 })
  }
  for (const iso of isoTimes) {
    const t = new Date(iso)
    if (Number.isNaN(t.getTime())) continue
    const key = dayKey(t)
    if (buckets.has(key)) buckets.set(key, (buckets.get(key) ?? 0) + 1)
  }
  return out.map((d) => ({ ...d, count: buckets.get(d.day) ?? 0 }))
}

/** Whole days from now until the moment (negative once past). */
export function daysUntil(iso: string, now: number = Date.now()): number {
  return Math.ceil((new Date(iso).getTime() - now) / 86_400_000)
}
