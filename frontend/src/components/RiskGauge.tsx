import { cn } from '@/lib/utils'

/** A 0-100 meter with the review threshold marked. Colour follows the score, and the number and
 *  label always say the same thing, so colour is never the only signal. */
export function RiskGauge({ score, threshold }: { score: number; threshold: number }) {
  const over = score >= threshold
  const level = over ? 'Needs review' : score > 0 ? 'Minor notes' : 'No concerns'
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm">
          <span className="font-semibold [font-variant-numeric:tabular-nums]">{score}</span>
          <span className="text-muted-foreground"> / 100</span>
        </p>
        <p className={cn('text-sm font-medium', over ? 'text-warning' : 'text-muted-foreground')}>{level}</p>
      </div>
      <div
        role="meter"
        aria-label="Risk score"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score}
        aria-valuetext={`${score} out of 100. ${level}.`}
        className="relative mt-2 h-2 rounded-full bg-surface-2"
      >
        <div
          className={cn('h-full rounded-full transition-[width] duration-200 ease-[var(--ease-out-quart)]', over ? 'bg-warning-solid' : 'bg-primary/70')}
          style={{ width: `${Math.max(score > 0 ? 3 : 0, Math.min(100, score))}%` }}
        />
        <span
          aria-hidden="true"
          className="absolute -top-1 h-4 w-px bg-foreground/50"
          style={{ left: `${threshold}%` }}
          title={`Review threshold: ${threshold}`}
        />
      </div>
    </div>
  )
}
