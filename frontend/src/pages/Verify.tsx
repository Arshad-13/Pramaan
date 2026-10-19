import { FileUp, Loader2, QrCode, ScanLine, TextCursorInput, TriangleAlert } from 'lucide-react'
import { useCallback, useState, type FormEvent } from 'react'

import { DispensePanel } from '@/components/DispensePanel'
import { PageHeader } from '@/components/PageHeader'
import { QrScanner } from '@/components/QrScanner'
import { Seal } from '@/components/Seal'
import { TamperOverlay } from '@/components/TamperOverlay'
import { UploadDrop } from '@/components/UploadDrop'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { VerificationTimeline } from '@/components/VerificationTimeline'
import { VerifiedRecord } from '@/components/VerifiedRecord'
import { api, ApiError } from '@/lib/api'
import type { VerifyResult } from '@/lib/types'
import { reasonText } from '@/lib/verify'
import { VERDICT_META } from '@/lib/verdicts'
import { cn } from '@/lib/utils'

type Tab = 'scan' | 'upload' | 'paste'

const TONE_PANEL = {
  verified: 'border-verified-border bg-verified-soft',
  danger: 'border-danger-border bg-danger-soft',
  warning: 'border-warning-border bg-warning-soft',
} as const

function Verdict({ result }: { result: VerifyResult }) {
  const meta = VERDICT_META[result.result]
  const Icon = meta.icon
  return (
    <section aria-label="Verification result" aria-live="polite" className={cn('flex flex-wrap items-center gap-5 rounded-lg border p-5', TONE_PANEL[meta.tone])}>
      <Seal verdict={result.result} size={112} />
      <div className="min-w-0 flex-1">
        <Badge tone={meta.tone}>
          <Icon aria-hidden="true" /> {meta.label}
        </Badge>
        <h2 className="mt-2 font-serif text-2xl font-semibold tracking-tight md:text-3xl">{meta.label}</h2>
        <p className="mt-1 max-w-prose text-foreground">{meta.summary}</p>
        {result.result !== 'VALID' && result.reason_codes.length > 0 && (
          <ul className="mt-3 space-y-1 text-sm">
            {result.reason_codes.map((code) => (
              <li key={code}>{reasonText(code)}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

/** Why a prescription was flagged: plain-language reasons from the rule checks. */
function RiskNotes({ result }: { result: VerifyResult }) {
  const notes = result.risk?.explanations ?? []
  if (notes.length === 0) return null
  return (
    <section aria-labelledby="risk-notes-h" className="rounded-lg border border-warning-border bg-warning-soft p-5">
      <h3 id="risk-notes-h" className="flex items-center gap-2 text-sm font-semibold text-warning">
        <TriangleAlert className="size-4" aria-hidden="true" /> Why this was flagged
      </h3>
      <ul className="mt-2 space-y-1 text-sm text-foreground">
        {notes.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </section>
  )
}

export default function Verify() {
  const [tab, setTab] = useState<Tab>('scan')
  const [text, setText] = useState('')
  const [qr, setQr] = useState<string | null>(null)
  const [result, setResult] = useState<VerifyResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const run = useCallback(async (code: string) => {
    const trimmed = code.trim()
    if (!trimmed) return
    setPending(true)
    setError(null)
    try {
      setResult(await api<VerifyResult>('/verify/qr', { method: 'POST', body: { qr_string: trimmed } }))
      setQr(trimmed)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')
    } finally {
      setPending(false)
    }
  }, [])

  const runUpload = useCallback(async (file: File) => {
    setPending(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const outcome = await api<VerifyResult>('/verify/upload', { method: 'POST', body: form })
      setResult(outcome)
      setQr(outcome.qr_string ?? null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')
    } finally {
      setPending(false)
    }
  }, [])

  function reset() {
    setResult(null)
    setQr(null)
    setError(null)
    setText('')
  }

  function onPaste(e: FormEvent) {
    e.preventDefault()
    void run(text)
  }

  return (
    <>
      <PageHeader
        title="Verify"
        description="Scan a prescription's QR code, upload a photo or PDF of the page, or paste the code. You get a verdict and the evidence behind it."
        actions={
          result ? (
            <Button variant="outline" onClick={reset}>
              <ScanLine aria-hidden="true" /> Verify another
            </Button>
          ) : undefined
        }
      />

      {!result && (
        <div className="max-w-xl">
          <div role="tablist" aria-label="How to enter the code" className="mb-5 inline-flex rounded-md border border-border bg-surface-2 p-0.5">
            {(
              [
                ['scan', 'Scan', QrCode],
                ['upload', 'Upload photo or PDF', FileUp],
                ['paste', 'Paste code', TextCursorInput],
              ] as const
            ).map(([value, label, Icon]) => (
              <button
                key={value}
                role="tab"
                type="button"
                aria-selected={tab === value}
                onClick={() => setTab(value)}
                className={cn(
                  'inline-flex h-10 items-center gap-2 rounded-sm px-4 text-sm font-medium transition-colors duration-150',
                  tab === value ? 'bg-surface text-foreground shadow-[inset_0_0_0_1px_var(--border)]' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <Icon className="size-4" aria-hidden="true" /> {label}
              </button>
            ))}
          </div>

          {tab === 'scan' && <QrScanner onResult={run} />}
          {tab === 'upload' && <UploadDrop onFile={runUpload} pending={pending} />}
          {tab === 'paste' && (
            <form onSubmit={onPaste} className="space-y-3">
              <label htmlFor="qr-text" className="text-sm font-medium">
                Prescription code
              </label>
              <textarea
                id="qr-text"
                rows={4}
                spellCheck={false}
                autoComplete="off"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="PRM2...."
                className="w-full rounded-md border border-border-strong bg-surface px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground transition-colors duration-150 hover:border-foreground/40 focus-visible:border-ring"
              />
              <Button type="submit" size="lg" disabled={pending || !text.trim()} aria-busy={pending}>
                {pending && <Loader2 className="animate-spin" aria-hidden="true" />}
                Verify
              </Button>
            </form>
          )}

          {pending && tab === 'scan' && (
            <p role="status" className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Checking...
            </p>
          )}
          {error && (
            <p role="alert" className="mt-4 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
      )}

      {result && (
        <div className="space-y-6">
          <Verdict result={result} />
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] lg:items-start">
            <div className="space-y-6 lg:order-2">
              <VerifiedRecord result={result} />
              <RiskNotes result={result} />
              {result.can_dispense && qr && <DispensePanel result={result} qr={qr} onReset={reset} />}
            </div>
            <div className="space-y-6 lg:order-1">
              <div>
                <h3 className="mb-3 text-sm font-semibold">Checks</h3>
                <VerificationTimeline result={result} />
              </div>
              {result.overlay && <TamperOverlay overlay={result.overlay} zones={result.content_zones ?? []} />}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
