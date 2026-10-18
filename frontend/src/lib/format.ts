/** Group a hex string into fixed-size chunks so hashes are readable and comparable by eye. */
export function chunkHash(hex: string, size = 4): string {
  const clean = hex.replace(/\s+/g, '')
  const parts: string[] = []
  for (let i = 0; i < clean.length; i += size) parts.push(clean.slice(i, i + size))
  return parts.join(' ')
}

/** Short fingerprint shown on the printed prescription: first 12 hex chars as 4-4-4. */
export function fingerprint(hashHex: string): string {
  return chunkHash(hashHex.slice(0, 12), 4)
}
