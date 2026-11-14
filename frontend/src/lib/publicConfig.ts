import { useQuery } from '@tanstack/react-query'

export interface PublicConfig {
  demo_mode: boolean
}

async function fetchPublicConfig(): Promise<PublicConfig> {
  const response = await fetch('/api/public-config', { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`public-config ${response.status}`)
  return (await response.json()) as PublicConfig
}

/**
 * What the server says the sign-in page may show. Demo shortcuts exist only when the server runs in
 * demo mode (`DEMO_MODE=true`), so a build cannot show throwaway passwords on a real deployment.
 * Until the answer arrives, and if it never does, nothing demo-related is shown.
 */
export function usePublicConfig(): PublicConfig {
  const { data } = useQuery({ queryKey: ['public-config'], queryFn: fetchPublicConfig, staleTime: Infinity, retry: 1 })
  return data ?? { demo_mode: false }
}
