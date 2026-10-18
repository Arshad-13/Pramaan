import {
  FilePlus2,
  Files,
  LayoutDashboard,
  Menu,
  Palette,
  ScanLine,
  ScrollText,
  UsersRound,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { Logo } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'
import { cn } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
}

// Role filtering arrives with authentication (Phase 3); every entry is listed for now.
const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/prescriptions/new', label: 'New prescription', icon: FilePlus2 },
  { to: '/prescriptions', label: 'My prescriptions', icon: Files, end: true },
  { to: '/verify', label: 'Verify', icon: ScanLine },
  { to: '/admin', label: 'Administration', icon: UsersRound },
  { to: '/audit', label: 'Audit log', icon: ScrollText },
]
const DEV_NAV: NavItem[] = import.meta.env.DEV
  ? [{ to: '/design', label: 'Design system', icon: Palette }]
  : []

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {[...NAV, ...DEV_NAV].map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors duration-150',
              isActive
                ? 'bg-surface text-foreground shadow-[inset_0_0_0_1px_var(--border)]'
                : 'text-muted-foreground hover:bg-surface hover:text-foreground',
            )
          }
        >
          <Icon className="size-4 shrink-0" aria-hidden="true" />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}

/** App frame: sidebar on desktop, collapsible top bar on phones. Footer carries the disclaimer. */
export function AppShell() {
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_1fr]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[var(--z-toast)] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>

      <aside className="hidden border-r border-border bg-surface-2 md:sticky md:top-0 md:flex md:h-dvh md:flex-col md:px-3 md:py-4">
        <div className="px-3 pb-6 pt-1">
          <Logo />
        </div>
        <NavList />
        <div className="mt-auto flex items-center justify-between px-1 pt-4">
          <span className="px-2 text-xs text-muted-foreground">Not signed in</span>
          <ThemeToggle />
        </div>
      </aside>

      <header className="sticky top-0 z-[var(--z-sticky)] border-b border-border bg-surface-2 md:hidden">
        <div className="flex h-14 items-center justify-between px-4">
          <Logo />
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <button
              type="button"
              aria-expanded={open}
              aria-controls="mobile-nav"
              aria-label={open ? 'Close menu' : 'Open menu'}
              onClick={() => setOpen((v) => !v)}
              className="grid size-10 place-items-center rounded-md hover:bg-surface"
            >
              {open ? <X className="size-5" /> : <Menu className="size-5" />}
            </button>
          </div>
        </div>
        {open && (
          <div id="mobile-nav" className="border-t border-border px-3 py-3" key={pathname}>
            <NavList onNavigate={() => setOpen(false)} />
          </div>
        )}
      </header>

      <div className="flex min-w-0 flex-col">
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 md:px-10 md:py-10">
          <Outlet />
        </main>
        <footer className="border-t border-border px-4 py-4 text-xs text-muted-foreground md:px-10">
          Academic demo. Not for clinical use.
        </footer>
      </div>
    </div>
  )
}
