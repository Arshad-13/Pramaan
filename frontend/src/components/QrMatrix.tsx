/**
 * A QR code drawn from the module matrix the server sends. Always dark-on-white with a four-module
 * quiet zone, in both themes, because scanners need the contrast.
 */
export function QrMatrix({ matrix, label, size = 192 }: { matrix: boolean[][]; label: string; size?: number }) {
  const n = matrix.length
  const quiet = 4
  const cells: string[] = []
  matrix.forEach((row, y) =>
    row.forEach((on, x) => {
      if (on) cells.push(`M${x + quiet} ${y + quiet}h1v1h-1z`)
    }),
  )
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${n + quiet * 2} ${n + quiet * 2}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
      className="rounded-md border border-border"
    >
      <rect width="100%" height="100%" fill="#fff" />
      <path d={cells.join('')} fill="#111" />
    </svg>
  )
}
