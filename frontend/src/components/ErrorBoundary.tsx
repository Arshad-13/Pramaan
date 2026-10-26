import { TriangleAlert } from 'lucide-react'
import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'

interface State {
  failed: boolean
}

/**
 * Last line of defence: a render error, or a page chunk that no longer exists after a redeploy,
 * would otherwise leave a blank screen. Say what happened and offer the one thing that fixes it.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Pramaan UI error', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main className="mx-auto grid min-h-dvh max-w-md place-content-center gap-4 px-6 text-center">
        <TriangleAlert className="mx-auto size-8 text-warning" aria-hidden="true" />
        <h1 className="font-serif text-2xl font-semibold">Something went wrong</h1>
        <p className="text-muted-foreground">
          This page could not be shown. Nothing you did was lost or changed. Reload to try again.
        </p>
        <Button className="mx-auto" onClick={() => window.location.reload()}>
          Reload
        </Button>
      </main>
    )
  }
}
