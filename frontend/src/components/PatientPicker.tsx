import { useMutation } from '@tanstack/react-query'
import { Check, Loader2, Search, UserRound, X } from 'lucide-react'
import { useState, type KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api, ApiError } from '@/lib/api'
import type { PatientMatch } from '@/lib/types'
import { cn } from '@/lib/utils'

type Mode = 'email' | 'code'

/** Doctors find a patient by their exact email or patient code. There is no browse or partial
 *  search: the server only answers an exact match, so patient lists are never exposed. */
export function PatientPicker({
  selected,
  onSelect,
}: {
  selected: PatientMatch | null
  onSelect: (patient: PatientMatch | null) => void
}) {
  const [mode, setMode] = useState<Mode>('email')
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  const lookup = useMutation({
    mutationFn: () =>
      api<PatientMatch>(`/patients/lookup?${mode === 'email' ? 'email' : 'code'}=${encodeURIComponent(value.trim())}`),
    onSuccess: (patient) => {
      setError(null)
      onSelect(patient)
    },
    onError: (e) => {
      onSelect(null)
      setError(e instanceof ApiError && e.status === 404 ? 'No patient matches that. Check the spelling.' : 'Could not search. Try again.')
    },
  })

  function search() {
    if (value.trim()) lookup.mutate()
  }

  // Not a <form>: this component lives inside the prescription form, and forms cannot nest.
  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      search()
    }
  }

  if (selected) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface-2 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-surface text-muted-foreground">
            <UserRound className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium">{selected.name}</p>
            <p className="font-mono text-xs text-muted-foreground">{selected.patient_code}</p>
          </div>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={() => onSelect(null)} aria-label="Choose a different patient">
          <X aria-hidden="true" /> Change
        </Button>
      </div>
    )
  }

  return (
    <div>
      <div role="radiogroup" aria-label="Find patient by" className="mb-2 inline-flex rounded-md border border-border bg-surface-2 p-0.5">
        {(['email', 'code'] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={mode === m}
            onClick={() => {
              setMode(m)
              setValue('')
              setError(null)
            }}
            className={cn(
              'h-8 rounded-sm px-3 text-sm font-medium transition-colors duration-150',
              mode === m ? 'bg-surface text-foreground shadow-[inset_0_0_0_1px_var(--border)]' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {m === 'email' ? 'Email' : 'Patient code'}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <Input
          aria-label={mode === 'email' ? 'Patient email' : 'Patient code'}
          type={mode === 'email' ? 'email' : 'text'}
          placeholder={mode === 'email' ? 'name@example.com' : 'K7M2-Q9XD'}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          className={mode === 'code' ? 'font-mono uppercase' : ''}
        />
        <Button type="button" variant="outline" onClick={search} disabled={lookup.isPending || !value.trim()}>
          {lookup.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Search aria-hidden="true" />}
          Find
        </Button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm font-medium text-danger">
          {error}
        </p>
      )}
      {!error && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Check className="size-3.5" aria-hidden="true" /> Enter the exact email or the code the patient shows in their account.
        </p>
      )}
    </div>
  )
}
