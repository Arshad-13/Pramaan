import { createContext, useContext } from 'react'

import { en, type MessageKey, type Messages } from '@/lib/i18n/en'
import { gu } from '@/lib/i18n/gu'
import { hi } from '@/lib/i18n/hi'

export type { MessageKey }
export type Locale = 'en' | 'hi' | 'gu'

/** Each language is named in itself, so a person can find theirs without reading English. */
export const LOCALES: { code: Locale; name: string }[] = [
  { code: 'en', name: 'English' },
  { code: 'hi', name: 'हिन्दी' },
  { code: 'gu', name: 'ગુજરાતી' },
]

const CATALOGUES: Record<Locale, Messages> = { en, hi, gu }
export const STORAGE_KEY = 'pramaan.lang'

export type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string

export function translate(locale: Locale, key: MessageKey, vars?: Record<string, string | number>): string {
  const text = CATALOGUES[locale][key] ?? en[key]
  return vars ? text.replace(/\{(\w+)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole)) : text
}

export function isLocale(value: unknown): value is Locale {
  return value === 'en' || value === 'hi' || value === 'gu'
}

/** The saved choice, else the browser language if we have it, else English. */
export function initialLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (isLocale(saved)) return saved
  } catch {
    /* storage can be blocked: fall through */
  }
  const preferred = typeof navigator !== 'undefined' ? navigator.language?.slice(0, 2) : undefined
  return isLocale(preferred) ? preferred : 'en'
}

export interface LocaleValue {
  locale: Locale
  setLocale: (next: Locale) => void
  t: Translate
}

export const LocaleContext = createContext<LocaleValue>({
  locale: 'en',
  setLocale: () => {},
  t: (key, vars) => translate('en', key, vars),
})

export function useLocale(): LocaleValue {
  return useContext(LocaleContext)
}

export function useT(): Translate {
  return useContext(LocaleContext).t
}
