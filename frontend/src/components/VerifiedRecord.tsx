import { dateTimeUtc } from '@/lib/rx'
import type { VerifyResult } from '@/lib/types'

/** The signed record: the authority for dispensing. Shown only when the signature verified. */
export function VerifiedRecord({ result }: { result: VerifyResult }) {
  if (!result.doctor || !result.medicines) return null
  return (
    <section aria-labelledby="record-h" className="rounded-lg border border-border bg-surface">
      <div className="border-b border-border px-5 py-3">
        <h3 id="record-h" className="text-sm font-semibold">
          Verified record
        </h3>
        <p className="mt-0.5 text-sm text-muted-foreground">Dispense according to this verified record, not the paper.</p>
      </div>
      <dl className="grid gap-x-6 gap-y-3 px-5 py-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">Doctor</dt>
          <dd className="font-medium">{result.doctor.name}</dd>
          <dd className="text-muted-foreground">Reg. No. {result.doctor.license_no}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Patient</dt>
          <dd className="font-medium">{result.patient?.name}</dd>
        </div>
        {result.issued_at && (
          <div>
            <dt className="text-muted-foreground">Issued</dt>
            <dd>{dateTimeUtc(new Date(result.issued_at))}</dd>
          </div>
        )}
        {result.expires_at && (
          <div>
            <dt className="text-muted-foreground">Valid until</dt>
            <dd>{dateTimeUtc(new Date(result.expires_at))}</dd>
          </div>
        )}
        {result.checks?.fills_remaining != null && (
          <div>
            <dt className="text-muted-foreground">Fills remaining</dt>
            <dd>{result.checks.fills_remaining}</dd>
          </div>
        )}
      </dl>
      <div className="overflow-x-auto border-t border-border">
        <table className="w-full min-w-[22rem] text-left text-sm">
          <caption className="sr-only">Prescribed medicines</caption>
          <thead className="bg-surface-2 text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-5 py-2 font-medium">Medicine</th>
              <th scope="col" className="px-3 py-2 font-medium">Dose</th>
              <th scope="col" className="px-3 py-2 font-medium">Frequency</th>
              <th scope="col" className="px-5 py-2 font-medium">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {result.medicines.map((m, i) => (
              <tr key={i}>
                <td className="px-5 py-2.5 font-medium">{m.name}</td>
                <td className="whitespace-nowrap px-3 py-2.5">{m.dose_mg} mg</td>
                <td className="px-3 py-2.5">{m.frequency}</td>
                <td className="whitespace-nowrap px-5 py-2.5">{m.duration_days} days</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
