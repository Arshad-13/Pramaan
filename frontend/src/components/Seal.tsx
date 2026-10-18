import { motion, useReducedMotion } from 'motion/react'

import { cn } from '@/lib/utils'
import { VERDICT_META, type Tone, type Verdict } from '@/lib/verdicts'

const RING_COLOR: Record<Tone, string> = {
  verified: 'var(--verified-solid)',
  danger: 'var(--danger-solid)',
  warning: 'var(--warning-solid)',
}
const ICON_COLOR: Record<Tone, string> = {
  verified: 'text-verified',
  danger: 'text-danger',
  warning: 'text-warning',
}

const TICKS = Array.from({ length: 60 }, (_, i) => i)

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
  const meta = VERDICT_META[verdict]
  const Icon = meta.icon
  const color = RING_COLOR[meta.tone]

  return (
    <div
      role="img"
      aria-label={meta.label}
      className={cn('relative inline-grid shrink-0 place-items-center', className)}
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 100 100"
        width={size}
        height={size}
        className="absolute inset-0"
        aria-hidden="true"
      >
        {TICKS.map((i) => {
          const angle = (i / TICKS.length) * Math.PI * 2
          const long = i % 5 === 0
          const r1 = 48.5
          const r2 = long ? 44.5 : 46.5
          return (
            <line
              key={i}
              x1={50 + Math.cos(angle) * r1}
              y1={50 + Math.sin(angle) * r1}
              x2={50 + Math.cos(angle) * r2}
              y2={50 + Math.sin(angle) * r2}
              stroke={color}
              strokeWidth={long ? 0.9 : 0.6}
              opacity={0.55}
            />
          )
        })}
        <circle cx="50" cy="50" r="39" fill="none" stroke={color} strokeWidth="1.5" opacity="0.25" />
        <motion.circle
          cx="50"
          cy="50"
          r="39"
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          transform="rotate(-90 50 50)"
          initial={reduce ? false : { pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.55, ease: [0.25, 1, 0.5, 1] }}
        />
      </svg>
      <Icon
        className={cn('relative', ICON_COLOR[meta.tone])}
        style={{ width: size * 0.34, height: size * 0.34 }}
        strokeWidth={1.75}
        aria-hidden="true"
      />
    </div>
  )
}
