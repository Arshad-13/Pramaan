import { cn } from '@/lib/utils'

/** Small brand mark: a seal ring with a check, plus the wordmark. `inverted` is for dark panels. */
export function Logo({
  className,
  showWord = true,
  inverted = false,
}: {
  className?: string
  showWord?: boolean
  inverted?: boolean
}) {
  const disc = inverted ? 'fill-white' : 'fill-primary'
  const mark = inverted ? 'stroke-[oklch(0.2_0.05_258)]' : 'stroke-primary-foreground'
  return (
    <span className={cn('inline-flex items-center gap-2.5', inverted && 'text-white', className)}>
      <svg viewBox="0 0 32 32" width="28" height="28" fill="none" aria-hidden="true">
        <circle cx="16" cy="16" r="14" className={disc} />
        <circle cx="16" cy="16" r="10.75" strokeWidth="1.4" opacity="0.7" className={mark} />
        <path
          d="M10.7 16.6l3.7 3.7 7-7.8"
          strokeWidth="2.1"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={mark}
        />
      </svg>
      {showWord && (
        <span className="font-serif text-xl font-semibold tracking-tight">Pramaan</span>
      )}
    </span>
  )
}
