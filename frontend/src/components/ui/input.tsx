import type { InputHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'h-10 w-full rounded-md border border-border-strong bg-surface px-3 text-base text-foreground',
        'placeholder:text-muted-foreground transition-colors duration-150',
        'hover:border-foreground/40 focus-visible:border-ring',
        'disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-danger-solid',
        className,
      )}
      {...props}
    />
  )
}
