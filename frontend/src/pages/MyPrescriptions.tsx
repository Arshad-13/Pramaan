import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileDown, FilePlus2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { PageHeader } from '@/components/PageHeader'
import { RxStatusBadge } from '@/components/RxStatusBadge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api, ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { formatDate, medicineSummary } from '@/lib/rx'
import type { Prescription } from '@/lib/types'

function EmptyState({ isDoctor }: { isDoctor: boolean }) {
  return (
    <div className="flex max-w-xl flex-col items-start gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-6">
      <FilePlus2 className="size-6 text-muted-foreground" aria-hidden="true" />
      {isDoctor ? (
        <>
          <p>You have not issued any prescriptions yet.</p>
          <Button asChild>
            <Link to="/prescriptions/new">Write the first one</Link>
          </Button>
        </>
      ) : (
        <p>
          Prescriptions your doctor issues to you will appear here, with a PDF you can show at the pharmacy.
        </p>
      )}
    </div>
  )
}

export default function MyPrescriptions() {
  const { user } = useAuth()
  const isDoctor = user?.role === 'doctor'
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState<string | null>(null)

  const { data, isPending, isError } = useQuery({
    queryKey: ['prescriptions', 'mine'],
    queryFn: () => api<Prescription[]>('/prescriptions/mine'),
  })

  const revoke = useMutation({
    mutationFn: (id: string) => api<Prescription>(`/prescriptions/${id}/revoke`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Prescription revoked. It will no longer verify.')
      setConfirming(null)
      void queryClient.invalidateQueries({ queryKey: ['prescriptions'] })
    },
    onError: (e) => {
      toast.error(e instanceof ApiError ? e.message : 'Could not revoke. Try again.')
      setConfirming(null)
    },
  })

  return (
    <>
      <PageHeader
        title="My prescriptions"
        description={isDoctor ? 'Prescriptions you have issued.' : 'Prescriptions issued to you.'}
        actions={
          isDoctor ? (
            <Button asChild>
              <Link to="/prescriptions/new">
                <FilePlus2 aria-hidden="true" /> New prescription
              </Link>
            </Button>
          ) : undefined
        }
      />

      {isPending && <Skeleton className="h-40 w-full" />}
      {isError && (
        <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger">
          Could not load your prescriptions. Refresh to try again.
        </p>
      )}
      {data && data.length === 0 && <EmptyState isDoctor={isDoctor} />}

      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <caption className="sr-only">Prescriptions</caption>
            <thead className="bg-surface-2 text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">Issued</th>
                <th scope="col" className="px-4 py-2.5 font-medium">{isDoctor ? 'Patient' : 'Doctor'}</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Medicines</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Fills</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.map((rx) => (
                <tr key={rx.id} className="align-top">
                  <td className="whitespace-nowrap px-4 py-3">
                    {formatDate(rx.issued_at)}
                    <p className="text-xs text-muted-foreground">until {formatDate(rx.expires_at)}</p>
                  </td>
                  <td className="px-4 py-3">{(isDoctor ? rx.patient_name : rx.doctor_name) ?? 'Unavailable'}</td>
                  <td className="px-4 py-3">
                    {rx.medicines.length === 0 ? (
                      <span className="text-muted-foreground">Unavailable</span>
                    ) : (
                      <ul className="space-y-0.5">
                        {rx.medicines.map((m, i) => (
                          <li key={i}>{medicineSummary(m)}</li>
                        ))}
                      </ul>
                    )}
                    <p className="mt-1 font-mono text-xs tracking-wide text-muted-foreground" title="Fingerprint">
                      {rx.fingerprint}
                    </p>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    {rx.fills_used} of {rx.max_fills}
                  </td>
                  <td className="px-4 py-3">
                    <RxStatusBadge status={rx.status} readable={rx.readable} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex flex-wrap justify-end gap-2">
                      <Button asChild size="sm" variant="outline">
                        <a href={`/api/prescriptions/${rx.id}/pdf`} target="_blank" rel="noopener">
                          <FileDown aria-hidden="true" /> PDF
                        </a>
                      </Button>
                      {isDoctor &&
                        rx.status === 'ISSUED' &&
                        (confirming === rx.id ? (
                          <>
                            <Button size="sm" variant="destructive" disabled={revoke.isPending} onClick={() => revoke.mutate(rx.id)}>
                              Confirm revoke
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                              Cancel
                            </Button>
                          </>
                        ) : (
                          <Button size="sm" variant="ghost" onClick={() => setConfirming(rx.id)}>
                            Revoke
                          </Button>
                        ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
