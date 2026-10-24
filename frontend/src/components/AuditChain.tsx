import { Link2, Link2Off } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useState } from 'react'

import { HashChunks } from '@/components/HashChunks'
import { actionLabel, detailFacts } from '@/lib/audit'
import type { AuditEntry } from '@/lib/types'
import { cn } from '@/lib/utils'

/** The audit log as a chain: each entry can show the hash of the entry before it and its own, so
 *  the link is visible. After a verification fails, `badSeq` marks the first broken entry. The
 *  text always says which entry is wrong; the red outline only points at it. */
export function AuditChain({ entries, badSeq }: { entries: AuditEntry[]; badSeq?: number | null }) {
  const reduce = useReducedMotion()
  const [open, setOpen] = useState<number | null>(null)

  return (
    <ol aria-label="Audit log entries, newest first">
      {entries.map((entry, i) => {
        const bad = badSeq === entry.seq
        const expanded = open === entry.seq
        const facts = detailFacts(entry.details_json)
        return (
          <motion.li
            key={entry.seq}
            initial={reduce ? false : { opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.16, delay: Math.min(i, 8) * 0.025, ease: [0.25, 1, 0.5, 1] }}
            className="relative pl-9"
          >
            <span aria-hidden="true" className={cn('absolute bottom-0 left-[0.8rem] top-0 w-px', bad ? 'bg-danger' : 'bg-border-strong')} />
            <span
              aria-hidden="true"
              className={cn(
                'absolute left-0 top-4 grid size-[1.65rem] place-items-center rounded-full border bg-surface',
                bad ? 'border-danger-border text-danger' : 'border-border-strong text-muted-foreground',
              )}
            >
              {bad ? <Link2Off className="size-3.5" /> : <Link2 className="size-3.5" />}
            </span>
            <div className={cn('my-1.5 rounded-lg border', bad ? 'border-danger-border bg-danger-soft' : 'border-border bg-surface')}>
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : entry.seq)}
                className="flex w-full flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3 text-left"
              >
                <span className="font-mono text-sm tabular-nums text-muted-foreground">#{entry.seq}</span>
                <span className="font-medium">{actionLabel(entry.action)}</span>
                {entry.actor_role && <span className="text-sm text-muted-foreground">by {entry.actor_role}</span>}
                <time className="ml-auto text-sm text-muted-foreground" dateTime={entry.ts}>
                  {new Date(entry.ts).toLocaleString()}
                </time>
                {bad && <span className="w-full text-sm font-medium text-danger">The chain breaks here: this entry was changed or its link is wrong.</span>}
              </button>
              {expanded && (
                <dl className="space-y-2 border-t border-border px-4 py-3 text-sm">
                  {entry.resource_id && (
                    <div>
                      <dt className="text-muted-foreground">About</dt>
                      <dd className="break-all font-mono">{entry.resource_id}</dd>
                    </div>
                  )}
                  {facts.length > 0 && (
                    <div>
                      <dt className="text-muted-foreground">Details</dt>
                      <dd>{facts.join(' · ')}</dd>
                    </div>
                  )}
                  <div>
                    <dt className="text-muted-foreground">Link to the entry before it</dt>
                    <dd>
                      <HashChunks value={entry.prev_hash.slice(0, 24)} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Seal of this entry</dt>
                    <dd>
                      <HashChunks value={entry.entry_hash.slice(0, 24)} />
                    </dd>
                  </div>
                </dl>
              )}
            </div>
          </motion.li>
        )
      })}
    </ol>
  )
}
