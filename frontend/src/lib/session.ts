/** When to warn that a session is about to end, and whether it can still be renewed. */

/** Warn this long before the session token ends. */
export const WARN_BEFORE_MS = 2 * 60_000
/** Renewing is pointless if the hard limit is hardly later than the current expiry. */
const MIN_USEFUL_RENEWAL_MS = 30_000

export interface WarningPlan {
  /** Milliseconds from now until the warning should appear (0 = now). */
  delayMs: number
  /** False once the hard limit is about to be reached: renewing would not help. */
  canRenew: boolean
}

export function planSessionWarning(expiresAt: string, endsBy: string | undefined, now: number = Date.now()): WarningPlan {
  const expires = new Date(expiresAt).getTime()
  const hardLimit = endsBy ? new Date(endsBy).getTime() : expires
  return {
    delayMs: Math.max(0, expires - WARN_BEFORE_MS - now),
    canRenew: hardLimit - expires > MIN_USEFUL_RENEWAL_MS,
  }
}
