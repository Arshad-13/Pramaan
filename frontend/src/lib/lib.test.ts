import { beforeEach, describe, expect, it } from 'vitest'

import { chunkHash, fingerprint } from './format'
import { pageTitle } from './nav'
import { applyTheme, getStoredPref } from './theme'
import { VERDICT_META, VERDICTS } from './verdicts'

describe('format', () => {
  it('groups hex into chunks of four', () => {
    expect(chunkHash('9a1c0e77b2d4f605')).toBe('9a1c 0e77 b2d4 f605')
  })
  it('keeps a short final chunk and ignores whitespace', () => {
    expect(chunkHash('abc de f')).toBe('abcd ef')
  })
  it('builds the 4-4-4 fingerprint from the first 12 hex characters', () => {
    expect(fingerprint('9a1c0e77b2d4f6053f0c')).toBe('9a1c 0e77 b2d4')
  })
})

describe('pageTitle', () => {
  it('names each page, tolerates a trailing slash, and flags unknown addresses', () => {
    expect(pageTitle('/')).toBe('Overview · Pramaan')
    expect(pageTitle('/verify')).toBe('Verify · Pramaan')
    expect(pageTitle('/prescriptions/new/')).toBe('New prescription · Pramaan')
    expect(pageTitle('/login')).toBe('Sign in · Pramaan')
    expect(pageTitle('/account')).toBe('Account · Pramaan')
    expect(pageTitle('/nope')).toBe('Page not found · Pramaan')
  })
})

describe('verdicts', () => {
  it('has a label, tone, icon and summary for every pipeline result', () => {
    expect(VERDICTS).toHaveLength(9)
    for (const v of VERDICTS) {
      const meta = VERDICT_META[v]
      expect(meta.label.length).toBeGreaterThan(0)
      expect(meta.summary.length).toBeGreaterThan(0)
      expect(meta.icon).toBeTruthy()
      expect(['verified', 'danger', 'warning']).toContain(meta.tone)
    }
  })
  it('uses the verified tone only for VALID', () => {
    const verified = VERDICTS.filter((v) => VERDICT_META[v].tone === 'verified')
    expect(verified).toEqual(['VALID'])
  })
})

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
  })
  it('defaults to system when nothing is stored', () => {
    expect(getStoredPref()).toBe('system')
  })
  it('reads a stored explicit preference', () => {
    localStorage.setItem('pramaan-theme', 'dark')
    expect(getStoredPref()).toBe('dark')
  })
  it('toggles the dark class', () => {
    applyTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    applyTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })
})
