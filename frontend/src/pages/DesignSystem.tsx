import { ShieldCheck } from 'lucide-react'

import { HashChunks } from '@/components/HashChunks'
import { PageHeader } from '@/components/PageHeader'
import { Seal } from '@/components/Seal'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { VERDICTS, VERDICT_META } from '@/lib/verdicts'

const SWATCHES = [
  ['background', 'bg-background'],
  ['surface', 'bg-surface'],
  ['surface-2', 'bg-surface-2'],
  ['border', 'bg-border'],
  ['primary', 'bg-primary'],
  ['verified', 'bg-verified-solid'],
  ['danger', 'bg-danger-solid'],
  ['warning', 'bg-warning-solid'],
]

/** Development-only reference for the visual vocabulary. Not linked in production builds. */
export default function DesignSystem() {
  return (
    <>
      <PageHeader title="Design system" description="Tokens and components used across Pramaan." />

      <section className="mb-12">
        <h2 className="mb-4 text-lg font-semibold">Verdicts</h2>
        <ul className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
          {VERDICTS.map((v) => {
            const meta = VERDICT_META[v]
            const Icon = meta.icon
            return (
              <li key={v} className="flex gap-4 bg-surface p-4">
                <Seal verdict={v} size={72} />
                <div className="min-w-0">
                  <Badge tone={meta.tone}>
                    <Icon aria-hidden="true" /> {meta.label}
                  </Badge>
                  <p className="mt-2 text-sm text-muted-foreground">{meta.summary}</p>
                </div>
              </li>
            )
          })}
        </ul>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 text-lg font-semibold">Colour</h2>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {SWATCHES.map(([name, cls]) => (
            <li key={name}>
              <div className={`h-14 rounded-md border border-border ${cls}`} />
              <p className="mt-1.5 text-xs text-muted-foreground">{name}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 text-lg font-semibold">Type</h2>
        <div className="space-y-3 rounded-lg border border-border bg-surface p-5">
          <p className="font-serif text-3xl font-semibold">Serif display: page titles and verdicts</p>
          <p>Inter for interface text, labels, tables and body copy.</p>
          <p className="text-sm text-muted-foreground">Muted text keeps at least 4.5:1 contrast.</p>
          <HashChunks value="9a1c0e77b2d4f6053f0c1b2e8d7a4c19" />
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 text-lg font-semibold">Controls</h2>
        <div className="flex flex-wrap items-center gap-3">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Revoke</Button>
          <Button disabled>Disabled</Button>
          <Button size="lg">
            <ShieldCheck aria-hidden="true" /> Dispense
          </Button>
        </div>
        <div className="mt-5 max-w-sm">
          <Input placeholder="Patient email" aria-label="Patient email" />
        </div>
      </section>
    </>
  )
}
