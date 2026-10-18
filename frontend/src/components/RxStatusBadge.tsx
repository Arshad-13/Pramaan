import { Ban, Clock, FileCheck2, PackageCheck, TriangleAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { RxStatus } from '@/lib/types'

/** Prescription lifecycle status. Icon + text always; never colour alone. */
export function RxStatusBadge({ status, readable = true }: { status: RxStatus; readable?: boolean }) {
  if (!readable)
    return (
      <Badge tone="danger">
        <TriangleAlert aria-hidden="true" /> Integrity check failed
      </Badge>
    )
  switch (status) {
    case 'ISSUED':
      return (
        <Badge>
          <FileCheck2 aria-hidden="true" /> Issued
        </Badge>
      )
    case 'DISPENSED':
      return (
        <Badge>
          <PackageCheck aria-hidden="true" /> Dispensed
        </Badge>
      )
    case 'EXPIRED':
      return (
        <Badge tone="warning">
          <Clock aria-hidden="true" /> Expired
        </Badge>
      )
    case 'REVOKED':
      return (
        <Badge tone="danger">
          <Ban aria-hidden="true" /> Revoked
        </Badge>
      )
  }
}
