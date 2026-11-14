import QrScannerLib from 'qr-scanner'
import { CameraOff, FileUp, FlipHorizontal2, Flashlight, FlashlightOff, TextCursorInput } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'

/** Live camera scanner. Calls `onResult` once with the decoded text, then stops the camera. */
export function QrScanner({
  onResult,
  onFallback,
}: {
  onResult: (text: string) => void
  /** Offered when the camera cannot be used: switch to another way of entering the code. */
  onFallback?: (way: 'upload' | 'paste') => void
}) {
  const video = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(true)
  const handler = useRef(onResult)
  const scannerRef = useRef<QrScannerLib | null>(null)
  const [hasTorch, setHasTorch] = useState(false)
  const [torchOn, setTorchOn] = useState(false)
  const [cameras, setCameras] = useState<{ id: string; label: string }[]>([])
  const [cameraIndex, setCameraIndex] = useState(0)
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
    scannerRef.current = scanner
    scanner
      .start()
      .then(async () => {
        setStarting(false)
        // Torch and camera choice are conveniences: absent on desktops and in older browsers.
        try {
          setHasTorch(Boolean(await scanner.hasFlash?.()))
          if (typeof QrScannerLib.listCameras === 'function') setCameras(await QrScannerLib.listCameras(true))
        } catch {
          /* optional */
        }
      })
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
      scannerRef.current = null
      scanner.stop()
      scanner.destroy()
    }
  }, [])

  async function toggleTorch() {
    try {
      await scannerRef.current?.toggleFlash()
      setTorchOn(scannerRef.current?.isFlashOn() ?? false)
    } catch {
      setHasTorch(false)
    }
  }

  async function nextCamera() {
    if (cameras.length < 2) return
    const next = (cameraIndex + 1) % cameras.length
    try {
      await scannerRef.current?.setCamera(cameras[next].id)
      setCameraIndex(next)
      setTorchOn(false)
      setHasTorch(Boolean(await scannerRef.current?.hasFlash()))
    } catch {
      /* keep the current camera */
    }
  }

  if (error)
    return (
      <div className="max-w-md rounded-lg border border-border-strong bg-surface p-5">
        <CameraOff className="size-6 text-muted-foreground" aria-hidden="true" />
        <p role="alert" className="mt-3 text-sm text-foreground">
          {error}
        </p>
        {onFallback && (
          <div className="mt-4 flex flex-wrap gap-2">
            <Button type="button" onClick={() => onFallback('upload')}>
              <FileUp aria-hidden="true" /> Upload a photo or PDF
            </Button>
            <Button type="button" variant="outline" onClick={() => onFallback('paste')}>
              <TextCursorInput aria-hidden="true" /> Paste the code
            </Button>
          </div>
        )}
      </div>
    )

  return (
    <div>
      <div className="relative aspect-[4/3] w-full max-w-md overflow-hidden rounded-lg border border-border-strong bg-black">
        <video ref={video} muted playsInline className="size-full object-cover" aria-label="Camera view" />
        {starting && (
          <p role="status" className="absolute inset-0 grid place-items-center text-sm text-white/80">
            Starting camera...
          </p>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <p className="mr-auto text-sm text-muted-foreground">Hold the prescription's QR code inside the frame.</p>
        {hasTorch && (
          <Button type="button" size="sm" variant="outline" aria-pressed={torchOn} onClick={toggleTorch}>
            {torchOn ? <FlashlightOff aria-hidden="true" /> : <Flashlight aria-hidden="true" />} Light
          </Button>
        )}
        {cameras.length > 1 && (
          <Button type="button" size="sm" variant="outline" onClick={nextCamera}>
            <FlipHorizontal2 aria-hidden="true" /> Switch camera
          </Button>
        )}
      </div>
    </div>
  )
}
