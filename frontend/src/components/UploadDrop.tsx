import { FileUp, Loader2 } from 'lucide-react'
import { useId, useState, type DragEvent } from 'react'

import { acceptedType, MAX_UPLOAD_BYTES, prepareUpload } from '@/lib/image'
import { cn } from '@/lib/utils'

interface Props {
  onFile: (file: File) => void
  pending: boolean
}

/** Drop a photo or PDF of the prescription, or choose one (on a phone the file chooser offers the camera). */
export function UploadDrop({ onFile, pending }: Props) {
  const inputId = useId()
  const hint = useId()
  const [over, setOver] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  async function take(file: File | undefined) {
    if (!file) return
    setProblem(null)
    if (!acceptedType(file)) {
      setProblem('Choose a JPEG or PNG photo, or a PDF.')
      return
    }
    const ready = await prepareUpload(file)
    if (ready.size > MAX_UPLOAD_BYTES) {
      setProblem('That file is larger than 5 MB. Use a lower-resolution photo.')
      return
    }
    onFile(ready)
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    void take(e.dataTransfer.files[0])
  }

  return (
    <div>
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cn(
          'flex min-h-48 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border-strong bg-surface px-6 py-8 text-center transition-colors duration-150 hover:border-foreground/50 focus-within:border-ring',
          over && 'border-ring bg-surface-2',
          pending && 'pointer-events-none opacity-70',
        )}
      >
        {pending ? (
          <Loader2 className="size-7 animate-spin text-muted-foreground" aria-hidden="true" />
        ) : (
          <FileUp className="size-7 text-muted-foreground" aria-hidden="true" />
        )}
        <span className="text-sm font-medium">{pending ? 'Checking the page...' : 'Drop a photo or PDF here, or choose a file'}</span>
        <span id={hint} className="max-w-xs text-sm text-muted-foreground">
          Photograph the whole page flat, in good light, with all four corners in view.
        </span>
      </label>
      <input
        id={inputId}
        type="file"
        accept="image/jpeg,image/png,image/webp,application/pdf"
        aria-describedby={hint}
        className="sr-only"
        disabled={pending}
        onChange={(e) => {
          void take(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      {problem && (
        <p role="alert" className="mt-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
          {problem}
        </p>
      )}
    </div>
  )
}
