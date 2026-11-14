/** Times people can read at a glance, with the exact moment always one hover away. */

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** "just now", "5 min ago", "3 h ago", "yesterday", then a plain date. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = now - then
  if (diff < 0) return 'in the future' // clock skew: say so rather than "-3 min ago"
  if (diff < MINUTE) return 'just now'
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)} min ago`
  if (diff < DAY) return `${Math.floor(diff / HOUR)} h ago`
  const days = Math.floor(diff / DAY)
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days} days ago`
  return new Date(then).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: days > 300 ? 'numeric' : undefined })
}

/** "14 Nov 2026, 3:42 pm" in the viewer's time zone. */
export function exactTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** "3:42 pm" */
export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}
