import type { ReactNode } from 'react'

import { Logo } from '@/components/Logo'
import { Seal } from '@/components/Seal'

/** Split layout shared by sign-in, register and activate: brand panel + a form column. */
export function AuthLayout({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden overflow-hidden bg-[oklch(0.2_0.05_258)] p-12 text-[oklch(0.96_0.006_255)] lg:flex lg:flex-col">
        <div aria-hidden="true" className="absolute -bottom-24 -right-24 opacity-[0.14]">
          <Seal verdict="VALID" size={520} />
        </div>
        <Logo inverted />
        <div className="mt-auto max-w-md">
          <h2 className="font-serif text-3xl font-semibold leading-tight">
            Every prescription carries proof of who issued it, and that it was never altered.
          </h2>
          <p className="mt-4 text-[oklch(0.82_0.02_255)]">
            Pramaan (प्रमाण) means proof. Signed by the doctor, checked by the pharmacist, recorded in a
            log nobody can quietly rewrite.
          </p>
        </div>
      </aside>

      <main className="flex items-center justify-center px-4 py-10">
        <div className="w-full max-w-sm">
          <Logo className="mb-8 lg:hidden" />
          <h1 className="font-serif text-2xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="mt-1.5 text-muted-foreground">{description}</p>}
          <div className="mt-8">{children}</div>
          <p className="mt-10 text-xs text-muted-foreground">Academic demo. Not for clinical use.</p>
        </div>
      </main>
    </div>
  )
}
