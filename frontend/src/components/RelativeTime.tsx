import { exactTime, relativeTime } from '@/lib/time'

/** A relative time ("5 min ago") whose title and machine-readable value carry the exact moment. */
export function RelativeTime({ iso, className }: { iso: string; className?: string }) {
  return (
    <time dateTime={iso} title={exactTime(iso)} className={className}>
      {relativeTime(iso)}
    </time>
  )
}
