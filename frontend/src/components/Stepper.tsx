import { Check } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface Step {
  /** Id of the section this step jumps to. */
  target: string
  label: string
  done: boolean
}

/**
 * Progress through a long form: which parts are finished, and a way to jump to each. All fields
 * stay on one page (nothing is hidden behind "Next"), so this informs rather than gates.
 */
export function Stepper({ steps }: { steps: Step[] }) {
  const firstOpen = steps.findIndex((s) => !s.done)
  return (
    <nav aria-label="Progress" className="mb-8">
      <ol className="flex flex-wrap gap-x-6 gap-y-2">
        {steps.map((step, i) => {
          const current = i === firstOpen
          return (
            <li key={step.target}>
              <button
                type="button"
                aria-current={current ? 'step' : undefined}
                onClick={() => {
                  const el = document.getElementById(step.target)
                  const calm = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
                  el?.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'start' })
                }}
                className={cn(
                  'flex items-center gap-2 rounded-md py-1 text-sm transition-colors duration-150',
                  current ? 'font-medium text-foreground' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <span
                  className={cn(
                    'grid size-6 place-items-center rounded-full border text-xs font-semibold',
                    step.done ? 'border-verified-border bg-verified-soft text-verified' : current ? 'border-foreground' : 'border-border-strong',
                  )}
                  aria-hidden="true"
                >
                  {step.done ? <Check className="size-3.5" /> : i + 1}
                </span>
                {step.label}
                <span className="sr-only">{step.done ? ' (done)' : current ? ' (current)' : ''}</span>
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
