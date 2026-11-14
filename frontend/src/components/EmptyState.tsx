import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

/** An empty list that says what the place is for and what to do next (never just "No data"). */
export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-start gap-3 px-5 py-8 sm:flex-row sm:items-center sm:gap-4">
      <span className="grid size-10 shrink-0 place-items-center rounded-md bg-surface-2 text-muted-foreground">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        {children && <p className="mt-0.5 text-sm text-muted-foreground">{children}</p>}
      </div>
      {action}
    </div>
  )
}
