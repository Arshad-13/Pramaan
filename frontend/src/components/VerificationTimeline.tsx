import { Check, Minus, TriangleAlert, X } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'

import type { VerifyResult } from '@/lib/types'
import { timelineSteps, type StepState } from '@/lib/verify'
import { cn } from '@/lib/utils'

const STATE_STYLE: Record<StepState, { icon: typeof Check; ring: string; word: string }> = {
  pass: { icon: Check, ring: 'border-verified-border bg-verified-soft text-verified', word: 'Passed' },
  fail: { icon: X, ring: 'border-danger-border bg-danger-soft text-danger', word: 'Failed' },
  warn: { icon: TriangleAlert, ring: 'border-warning-border bg-warning-soft text-warning', word: 'Needs review' },
  skipped: { icon: Minus, ring: 'border-border bg-surface-2 text-muted-foreground', word: 'Not checked' },
}

/** The checks behind a verdict. Text is always visible; only the status marks "stamp in" one
 *  after another (state, not decoration). Reduced-motion users get the final state at once. */
export function VerificationTimeline({ result }: { result: VerifyResult }) {
  const reduce = useReducedMotion()
  const steps = timelineSteps(result)

  return (
    <ol aria-label="Checks performed" className="divide-y divide-border rounded-lg border border-border bg-surface">
      {steps.map((step, i) => {
        const { icon: Icon, ring, word } = STATE_STYLE[step.state]
        return (
          <li key={step.id} className="flex items-start gap-3 px-4 py-3">
            <motion.span
              className={cn('mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border', ring)}
              initial={reduce ? false : { scale: 1.45 }}
              animate={{ scale: 1 }}
              transition={{ duration: 0.18, delay: 0.09 * i, ease: [0.25, 1, 0.5, 1] }}
            >
              <Icon className="size-3.5" strokeWidth={2.5} aria-hidden="true" />
            </motion.span>
            <div className="min-w-0">
              <p className={cn('text-sm font-medium', step.state === 'skipped' && 'text-muted-foreground')}>
                {step.label} <span className="sr-only">: {word}</span>
              </p>
              {step.note && <p className="text-sm text-muted-foreground">{step.note}</p>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
