import QrScannerLib from 'qr-scanner'
import { useEffect, useRef, useState } from 'react'

/** Live camera scanner. Calls `onResult` once with the decoded text, then stops the camera. */
export function QrScanner({ onResult }: { onResult: (text: string) => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(true)
  const handler = useRef(onResult)
  useEffect(() => {
    handler.current = onResult
  }, [onResult])

  useEffect(() => {
    const el = video.current
    if (!el) return
    let handled = false
    const scanner = new QrScannerLib(
      el,
      (found) => {
        if (handled) return
        handled = true
        scanner.stop()
        handler.current(found.data)
      },
      { returnDetailedScanResult: true, preferredCamera: 'environment', highlightScanRegion: true, maxScansPerSecond: 8 },
    )
    scanner
      .start()
      .then(() => setStarting(false))
      .catch((e: unknown) => {
        setStarting(false)
        const name = e instanceof Error ? e.name : ''
        const message = typeof e === 'string' ? e : e instanceof Error ? e.message : ''
        if (name === 'NotAllowedError' || /denied|permission/i.test(message))
          setError('Camera access was blocked. Allow it in your browser settings, or paste the code instead.')
        else if (/no camera/i.test(message)) setError('No camera was found on this device. Paste the code instead.')
        else setError('The camera could not start. Paste the code instead.')
      })
    return () => {
      scanner.stop()
      scanner.destroy()
    }
  }, [])

  return (
    <div>
      <div className="relative aspect-[4/3] w-full max-w-md overflow-hidden rounded-lg border border-border-strong bg-black">
        <video ref={video} muted playsInline className="size-full object-cover" aria-label="Camera view" />
        {starting && !error && (
          <p role="status" className="absolute inset-0 grid place-items-center text-sm text-white/80">
            Starting camera...
          </p>
        )}
      </div>
      {error ? (
        <p role="alert" className="mt-3 max-w-md rounded-md border border-warning-border bg-warning-soft px-3 py-2 text-sm text-warning">
          {error}
        </p>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">Hold the prescription's QR code inside the frame.</p>
      )}
    </div>
  )
}
