import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { HashChunks } from './HashChunks'
import { Seal } from './Seal'
import { ThemeToggle } from './ThemeToggle'
import { VERDICT_META, VERDICTS } from '@/lib/verdicts'

describe('Seal', () => {
  it.each(VERDICTS)('exposes an accessible label for %s', (verdict) => {
    render(<Seal verdict={verdict} />)
    expect(screen.getByRole('img', { name: VERDICT_META[verdict].label })).toBeInTheDocument()
  })
})

describe('HashChunks', () => {
  it('renders grouped hex and keeps the full value in the title', () => {
    render(<HashChunks value="9a1c0e77b2d4f605" />)
    const el = screen.getByText('9a1c 0e77 b2d4 f605')
    expect(el).toHaveAttribute('title', '9a1c0e77b2d4f605')
  })
})

describe('ThemeToggle', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
  })
  it('switches to dark, applies the class and persists the choice', async () => {
    render(<ThemeToggle />)
    await userEvent.click(screen.getByRole('radio', { name: 'Dark theme' }))
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('pramaan-theme')).toBe('dark')
    expect(screen.getByRole('radio', { name: 'Dark theme' })).toBeChecked()
  })
})
