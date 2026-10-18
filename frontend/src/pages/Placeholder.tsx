import type { LucideIcon } from 'lucide-react'

import { PageHeader } from '@/components/PageHeader'

/** Empty state for screens that land in a later phase. Says what the screen will do. */
export default function Placeholder({
  title,
  description,
  icon: Icon,
  phase,
}: {
  title: string
  description: string
  icon: LucideIcon
  phase: string
}) {
  return (
    <>
      <PageHeader title={title} />
      <div className="flex max-w-xl flex-col items-start gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-6">
        <Icon className="size-6 text-muted-foreground" aria-hidden="true" />
        <p>{description}</p>
        <p className="text-sm text-muted-foreground">Arrives in {phase}.</p>
      </div>
    </>
  )
}
