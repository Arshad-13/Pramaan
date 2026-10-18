import { Monitor, Moon, Sun } from 'lucide-react'

import { useTheme, type ThemePref } from '@/lib/theme'
import { cn } from '@/lib/utils'

const OPTIONS: { value: ThemePref; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light theme', icon: Sun },
  { value: 'system', label: 'System theme', icon: Monitor },
  { value: 'dark', label: 'Dark theme', icon: Moon },
]

/** Three-way theme switch: light, dark, or follow the system. */
export function ThemeToggle({ className }: { className?: string }) {
  const { pref, setPref } = useTheme()
  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className={cn('inline-flex rounded-md border border-border bg-surface p-0.5', className)}
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={pref === value}
          aria-label={label}
          title={label}
          onClick={() => setPref(value)}
          className={cn(
            'grid size-8 place-items-center rounded-sm text-muted-foreground transition-colors duration-150',
            'hover:text-foreground aria-checked:bg-surface-2 aria-checked:text-foreground',
          )}
        >
          <Icon className="size-4" aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
