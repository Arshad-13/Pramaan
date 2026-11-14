import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { initialLocale, LocaleContext, STORAGE_KEY, translate, type Locale, type LocaleValue } from '@/lib/i18n'

/** Holds the chosen language, remembers it, and keeps <html lang> in step (screen readers pick the voice from it). */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale)

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* the choice still applies for this visit */
    }
  }, [])

  const value = useMemo<LocaleValue>(
    () => ({ locale, setLocale, t: (key, vars) => translate(locale, key, vars) }),
    [locale, setLocale],
  )
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}
