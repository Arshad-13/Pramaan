import { motion, useReducedMotion } from 'motion/react'

import { SealFrame } from '@/components/SealFrame'
import { RING_COLOR, VERDICT_META, type Verdict } from '@/lib/verdicts'

/**
 * The verdict seal: a stamped ring with edge ticks and the verdict icon at its centre.
 * Motion only conveys state (the ring draws once when a verdict arrives); the faint full
 * track and the icon are always visible, and reduced-motion users get the final state.
 */
export function Seal({
  verdict,
  size = 96,
  className,
}: {
  verdict: Verdict
  size?: number
  className?: string
}) {
  const reduce = useReducedMotion()

  return (
    <SealFrame verdict={verdict} size={size} className={className}>
      <motion.circle
        cx="50"
        cy="50"
        r="39"
        fill="none"
        stroke={RING_COLOR[VERDICT_META[verdict].tone]}
        strokeWidth="3"
        strokeLinecap="round"
        transform="rotate(-90 50 50)"
        initial={reduce ? false : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.55, ease: [0.25, 1, 0.5, 1] }}
      />
    </SealFrame>
  )
}
