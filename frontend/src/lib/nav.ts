import {
  FilePlus2,
  Files,
  LayoutDashboard,
  ScanLine,
  ScrollText,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'

import type { Role } from '@/lib/types'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
  roles?: Role[] // omitted = every signed-in role
}

export const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/prescriptions/new', label: 'New prescription', icon: FilePlus2, roles: ['doctor'] },
  {
    to: '/prescriptions',
    label: 'My prescriptions',
    icon: Files,
    end: true,
    roles: ['doctor', 'patient'],
  },
  { to: '/verify', label: 'Verify', icon: ScanLine, roles: ['pharmacist'] },
  { to: '/admin', label: 'Administration', icon: UsersRound, roles: ['admin'] },
  { to: '/audit', label: 'Audit log', icon: ScrollText, roles: ['auditor'] },
]

const EXTRA_TITLES: Record<string, string> = {
  '/login': 'Sign in',
  '/register': 'Create an account',
  '/activate': 'Activate your account',
  '/account': 'Account',
}

/** The browser-tab title for a path, so each page has its own name (and history is readable). */
export function pageTitle(pathname: string): string {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  const name = EXTRA_TITLES[path] ?? NAV.find((item) => item.to === path)?.label ?? 'Page not found'
  return `${name} · Pramaan`
}

/** Navigation entries a role may see. The server enforces access; this only hides dead links. */
export function navFor(role: Role | undefined): NavItem[] {
  return NAV.filter((item) => !item.roles || (role && item.roles.includes(role)))
}
