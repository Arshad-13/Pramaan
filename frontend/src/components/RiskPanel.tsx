import { CheckCircle2, Info, TriangleAlert } from 'lucide-react'

import { RiskGauge } from '@/components/RiskGauge'
import type { RiskCheck } from '@/lib/types'

const WARNING_TEXT: Record<string, string> = {
  MODEL_UNAVAILABLE: 'The pattern-detection model is not loaded, so only the rule checks ran.',
  CONTROLLED_NO_REFILLS: 'Controlled medicines can only be issued with one fill.',
}

/** The live safety check shown before signing. When the score needs review, the doctor must give
 *  a reason; it is stored with the prescription and the admin is notified. */
export function RiskPanel({
  check,
  forced,
  override,
  onOverride,
  error,
}: {
  check: RiskCheck | undefined
  /** The server asked for confirmation even though the live check did not. */
  forced?: boolean
  override: string
  onOverride: (value: string) => void
  error?: string | null
}) {
  if (!check) {
    return (
      <p className="text-sm text-muted-foreground">
        The safety check runs as soon as you have entered a medicine, dose and duration.
      </p>
    )
  }
  const needs = check.requires_override || forced
  const hasConcerns = check.risk.explanations.length > 0
  return (
    <section aria-labelledby="risk-h" className="rounded-lg border border-border bg-surface p-4">
      <h2 id="risk-h" className="mb-3 text-sm font-semibold">
        Safety check
      </h2>
      <RiskGauge score={check.risk.score} threshold={check.threshold} />

      <div aria-live="polite">
        {hasConcerns ? (
          <ul className="mt-4 space-y-2">
            {check.risk.explanations.map((text) => (
              <li key={text} className="flex items-start gap-2 text-sm">
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
                <span>{text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <CheckCircle2 className="size-4" aria-hidden="true" /> No unusual drug names or doses found.
          </p>
        )}
        {check.warnings
          .filter((w) => WARNING_TEXT[w])
          .map((w) => (
            <p key={w} className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" /> {WARNING_TEXT[w]}
            </p>
          ))}
      </div>

      {needs && (
        <div className="mt-4 rounded-md border border-warning-border bg-warning-soft p-3">
          <label htmlFor="override" className="text-sm font-medium text-warning">
            Reason for issuing anyway (required)
          </label>
          <textarea
            id="override"
            rows={2}
            value={override}
            onChange={(e) => onOverride(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? 'override-error' : 'override-hint'}
            className="mt-1.5 w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-foreground aria-[invalid=true]:border-danger-solid"
          />
          {error ? (
            <p id="override-error" role="alert" className="mt-1 text-xs font-medium text-danger">
              {error}
            </p>
          ) : (
            <p id="override-hint" className="mt-1 text-xs text-foreground/70">
              At least 10 characters. This is saved with the prescription and an administrator is notified.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
