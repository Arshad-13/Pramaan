import { motion, useReducedMotion } from 'motion/react'

import type { ContentZone, VerifyOverlay } from '@/lib/types'
import { cn } from '@/lib/utils'

const STATUS_WORD: Record<ContentZone['status'], string> = {
  MISMATCH: 'Differs',
  EXTRA_CONTENT: 'Extra writing',
  UNREADABLE: 'Could not be read',
}

/** The uploaded page with each differing field outlined, and a plain list of what was signed
 *  versus what the document shows. The list carries every fact; the outlines only point at it. */
export function TamperOverlay({ overlay, zones }: { overlay: VerifyOverlay; zones: ContentZone[] }) {
  const reduce = useReducedMotion()
  return (
    <section aria-labelledby="overlay-h" className="space-y-4">
      <h3 id="overlay-h" className="text-sm font-semibold">
        {zones.length === 0 ? 'Your upload' : 'Where the page differs'}
      </h3>
      <div className="relative overflow-hidden rounded-lg border border-border bg-surface-2">
        <img src={overlay.image} alt="The uploaded prescription" className="block h-auto w-full" />
        <svg
          viewBox={`0 0 ${overlay.width} ${overlay.height}`}
          className="pointer-events-none absolute inset-0 size-full"
          aria-hidden="true"
        >
          {zones.map((zone, i) => (
            <motion.polygon
              key={zone.zone}
              points={zone.quad.map(([x, y]) => `${x},${y}`).join(' ')}
              fill={zone.status === 'UNREADABLE' ? 'var(--warning)' : 'var(--danger)'}
              fillOpacity={0.14}
              stroke={zone.status === 'UNREADABLE' ? 'var(--warning)' : 'var(--danger)'}
              strokeWidth={3}
              vectorEffect="non-scaling-stroke"
              initial={reduce ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.2, delay: 0.12 * i }}
            />
          ))}
        </svg>
      </div>
      {zones.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {zones.map((zone) => (
            <li key={zone.zone} className="px-4 py-3 text-sm">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-medium">{zone.label}</span>
                <span className={cn('text-xs', zone.status === 'UNREADABLE' ? 'text-warning' : 'text-danger')}>
                  {STATUS_WORD[zone.status]}
                </span>
              </p>
              {zone.status !== 'EXTRA_CONTENT' && (
                <p className="mt-1 text-muted-foreground">
                  Signed <span className="font-mono text-foreground">{zone.signed || 'nothing'}</span>
                </p>
              )}
              <p className="text-muted-foreground">
                {zone.status === 'EXTRA_CONTENT' ? 'Document has writing here: ' : 'Document reads '}
                <span className="font-mono text-foreground">{zone.read ? zone.read : 'something unclear'}</span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
