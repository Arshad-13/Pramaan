import { Languages } from 'lucide-react'

import { LOCALES, useLocale, type Locale } from '@/lib/i18n'
import { cn } from '@/lib/utils'

/** A native select: works with every keyboard and screen reader, and shows each language in itself. */
export function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, setLocale, t } = useLocale()
  return (
    <label className={cn('relative inline-flex items-center', className)}>
      <span className="sr-only">{t('shell.language')}</span>
      <Languages className="pointer-events-none absolute left-2.5 size-4 text-muted-foreground" aria-hidden="true" />
      <select
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
        lang={locale}
        className="h-9 rounded-md border border-border bg-surface pl-8 pr-2 text-sm text-foreground transition-colors duration-150 hover:border-border-strong"
      >
        {LOCALES.map(({ code, name }) => (
          <option key={code} value={code} lang={code}>
            {name}
          </option>
        ))}
      </select>
    </label>
  )
}
