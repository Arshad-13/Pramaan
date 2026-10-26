import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'
import { RING_COLOR, VERDICT_META, type Tone, type Verdict } from '@/lib/verdicts'

const ICON_COLOR: Record<Tone, string> = {
  verified: 'text-verified',
  danger: 'text-danger',
  warning: 'text-warning',
}

const TICKS = Array.from({ length: 60 }, (_, i) => i)

/**
 * The still part of the verdict seal: edge ticks, a faint full track and the verdict icon.
 * The bold ring is passed in as `children` (an SVG element drawn in the 100x100 viewBox), so the
 * animated version (Seal, which needs the motion library) and a plain decorative one (the sign-in
 * panel, which must not pull that library in) share everything else.
 */
export function SealFrame({
  verdict,
  size = 96,
  className,
  children,
}: {
  verdict: Verdict
  size?: number
  className?: string
  children?: ReactNode
}) {
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
      <svg viewBox="0 0 100 100" width={size} height={size} className="absolute inset-0" aria-hidden="true">
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
        {children}
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
