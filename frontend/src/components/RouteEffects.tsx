import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

import { pageTitle } from '@/lib/nav'

/**
 * Per-navigation housekeeping for a single-page app, where the browser does none of it:
 * name the tab after the page (WCAG 2.4.2) and, after the first page, move focus to the main
 * region so keyboard and screen-reader users start at the new content instead of in the old menu.
 */
export function RouteEffects() {
  const { pathname } = useLocation()
  const first = useRef(true)

  useEffect(() => {
    document.title = pageTitle(pathname)
    if (first.current) {
      first.current = false
      return
    }
    document.getElementById('main')?.focus({ preventScroll: true })
  }, [pathname])

  return null
}
