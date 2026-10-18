import { chunkHash } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Hex hashes/fingerprints in grouped monospace so two values can be compared by eye. */
export function HashChunks({
  value,
  size = 4,
  className,
}: {
  value: string
  size?: number
  className?: string
}) {
  return (
    <code
      className={cn(
        'font-mono text-sm tracking-wide text-foreground [font-variant-numeric:tabular-nums]',
        className,
      )}
      title={value}
    >
      {chunkHash(value, size)}
    </code>
  )
}
