import { QrCode } from 'lucide-react'
import { useEffect, useState } from 'react'

import { addDays, dateTimeUtc, medicineCells, MAX_MEDICINES, patientLine } from '@/lib/rx'
import type { Medicine } from '@/lib/types'

export interface RxPreviewProps {
  clinic: string
  doctorName: string
  licenseNo: string
  patientName: string | null
  ageYears?: number | null
  validityDays: number
  maxFills: number
  medicines: Medicine[]
  notes: string
  /** Fixed "now" for the preview; the real time is stamped when the doctor signs. */
  now?: Date
}

/** A live preview of the prescription page. It uses the same wording as the signed PDF
 *  (what you see is what you sign), but is clearly marked as unsigned. */
export function RxPreview(props: RxPreviewProps) {
  // The real time is stamped when the doctor signs; keep the preview roughly current meanwhile.
  const [clock, setClock] = useState(() => new Date())
  useEffect(() => {
    if (props.now) return
    const id = setInterval(() => setClock(new Date()), 30_000)
    return () => clearInterval(id)
  }, [props.now])
  const now = props.now ?? clock
  const rows = props.medicines.filter((m) => m.name.trim())
  const valid = Number.isFinite(props.validityDays) && props.validityDays > 0

  return (
    <figure
      aria-label="Prescription preview"
      className="relative aspect-[1/1.414] w-full overflow-hidden rounded-md border border-border-strong bg-white text-[oklch(0.2_0.05_258)] shadow-[0_1px_0_var(--border)]"
    >
      {/* corner fiducials, as printed */}
      {['left-2.5 top-2.5', 'right-2.5 top-2.5', 'bottom-2.5 left-2.5'].map((pos) => (
        <span key={pos} aria-hidden="true" className={`absolute size-2 bg-black ${pos}`} />
      ))}

      <div className="flex h-full flex-col px-[7%] pb-[5%] pt-[8%] text-[0.62rem] leading-snug sm:text-[0.7rem]">
        <p className="min-h-[1.5em] border-b border-black/15 pb-1.5 text-[1.45em] font-bold">
          {props.clinic || ' '}
        </p>

        <div className="mt-2 grid grid-cols-[1fr_auto] gap-x-4">
          <div>
            <p className="font-bold">{props.doctorName}</p>
            <p className="text-black/60">Reg. No. {props.licenseNo}</p>
          </div>
          <div className="space-y-0.5 text-right">
            <p>Issued: {dateTimeUtc(now)}</p>
            <p>Valid until: {valid ? dateTimeUtc(addDays(now, props.validityDays)) : '-'}</p>
            <p>Fills allowed: {props.maxFills}</p>
          </div>
        </div>

        <p className="mt-2.5 min-h-[1.4em] font-bold">
          {props.patientName ? patientLine(props.patientName, props.ageYears) : (
            <span className="font-normal text-black/40">Patient: choose a patient</span>
          )}
        </p>

        <table className="mt-2 w-full table-fixed border-collapse">
          <thead>
            <tr className="text-left text-[0.8em] tracking-wide text-black/55">
              <th className="w-[38%] border-b border-black/20 py-1 font-bold">MEDICINE</th>
              <th className="w-[16%] border-b border-black/20 py-1 font-bold">DOSE</th>
              <th className="w-[22%] border-b border-black/20 py-1 font-bold">FREQUENCY</th>
              <th className="w-[24%] border-b border-black/20 py-1 font-bold">DURATION</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={4} className="py-2 text-black/40">
                  Medicines you add appear here.
                </td>
              </tr>
            )}
            {rows.slice(0, MAX_MEDICINES).map((m, i) => (
              <tr key={i} className="border-b border-black/10">
                {medicineCells(m).map((cell, j) => (
                  <td key={j} className="truncate py-1 pr-1">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>

        <p className="mt-3 whitespace-pre-line">{props.notes}</p>

        <div className="mt-auto flex items-end justify-between gap-3">
          <div className="space-y-0.5 text-black/60">
            <p>Rx ID: assigned when signed</p>
            <p>Fingerprint: assigned when signed</p>
          </div>
          <div className="text-center">
            <div className="grid size-[4.5em] place-items-center border border-dashed border-black/30 text-black/35">
              <QrCode className="size-[2.4em]" aria-hidden="true" />
            </div>
            <p className="mt-0.5 text-[0.7em] text-black/50">Scan with Pramaan to verify</p>
          </div>
        </div>
      </div>

      <figcaption className="absolute right-2 top-2 rounded-sm bg-[oklch(0.96_0.04_85)] px-1.5 py-0.5 text-[0.6rem] font-semibold text-[oklch(0.45_0.1_65)]">
        Preview · not signed yet
      </figcaption>
    </figure>
  )
}
