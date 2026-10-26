import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ErrorBoundary } from './ErrorBoundary'
import { HashChunks } from './HashChunks'
import { RouteEffects } from './RouteEffects'
import { Seal } from './Seal'
import { ThemeToggle } from './ThemeToggle'
import { VERDICT_META, VERDICTS } from '@/lib/verdicts'

describe('Seal', () => {
  it.each(VERDICTS)('exposes an accessible label for %s', (verdict) => {
    render(<Seal verdict={verdict} />)
    expect(screen.getByRole('img', { name: VERDICT_META[verdict].label })).toBeInTheDocument()
  })
})

describe('ErrorBoundary', () => {
  it('replaces a crashed page with a plain message and a reload button', () => {
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    function Boom(): never {
      throw new Error('boom')
    }
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
    quiet.mockRestore()
  })

  it('renders its children when nothing fails', () => {
    render(
      <ErrorBoundary>
        <p>All good</p>
      </ErrorBoundary>,
    )
    expect(screen.getByText('All good')).toBeInTheDocument()
  })
})

describe('RouteEffects', () => {
  it('names the tab after the page and moves focus to the main region on later navigations', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <RouteEffects />
        <main id="main" tabIndex={-1}>
          <Link to="/verify">go</Link>
        </main>
      </MemoryRouter>,
    )
    expect(document.title).toBe('Overview · Pramaan')
    expect(document.getElementById('main')).not.toHaveFocus() // first page: leave focus alone
    await userEvent.click(screen.getByRole('link', { name: 'go' }))
    expect(document.title).toBe('Verify · Pramaan')
    expect(document.getElementById('main')).toHaveFocus()
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
