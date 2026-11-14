import type { DayCount } from '@/lib/series'

const weekday = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

/**
 * A small bar chart of counts per day. One colour, no gridlines; the exact numbers are in each bar's
 * tooltip and in the text summary, so the chart never carries information by shape alone.
 */
export function ActivityBars({ days, noun }: { days: DayCount[]; noun: string }) {
  const max = Math.max(1, ...days.map((d) => d.count))
  const total = days.reduce((sum, d) => sum + d.count, 0)
  const busiest = days.reduce((best, d) => (d.count > best.count ? d : best), days[0])
  const summary =
    total === 0
      ? `No ${noun} in the last ${days.length} days.`
      : `${total} ${noun} in the last ${days.length} days. Busiest day: ${weekday(busiest.day)} with ${busiest.count}.`
  const w = 10
  const gap = 4
  const h = 56
  return (
    <figure className="px-5 py-4">
      <svg viewBox={`0 0 ${days.length * (w + gap) - gap} ${h}`} role="img" aria-label={summary} className="h-20 w-full" preserveAspectRatio="none">
        {days.map((d, i) => {
          const barH = d.count === 0 ? 2 : Math.max(4, (d.count / max) * (h - 4))
          return (
            <rect key={d.day} x={i * (w + gap)} y={h - barH} width={w} height={barH} rx={2} className={d.count === 0 ? 'fill-border' : 'fill-primary'}>
              <title>{`${weekday(d.day)}: ${d.count}`}</title>
            </rect>
          )
        })}
      </svg>
      <figcaption className="mt-2 flex justify-between text-xs text-muted-foreground">
        <span>{weekday(days[0].day)}</span>
        <span>{summary}</span>
        <span>Today</span>
      </figcaption>
    </figure>
  )
}
