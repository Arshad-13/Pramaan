import type { HTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'rounded-md bg-surface-2 [animation:skeleton-pulse_1.6s_ease-in-out_infinite]',
        className,
      )}
      {...props}
    />
  )
}
