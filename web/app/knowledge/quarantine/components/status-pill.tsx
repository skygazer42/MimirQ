'use client'

import { cn } from '@/lib/utils'
import type { Document } from '@/types'

import { STATUS_LABELS } from '../constants'

export function StatusPill({ status }: Readonly<{ status: Document['status'] }>) {
  const label = STATUS_LABELS[status] ?? STATUS_LABELS.cancelled

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium',
        status === 'completed' &&
          'border-success/20 bg-success/10 text-success',
        status === 'failed' &&
          'border-destructive/20 bg-destructive/10 text-destructive',
        status === 'quarantined' &&
          'border-warning/20 bg-warning/10 text-warning',
        status === 'pending' &&
          'border-info/20 bg-info/10 text-info',
        status === 'processing' &&
          'border-info/20 bg-info/10 text-info',
        status === 'cancelled' &&
          'border-border/60 bg-muted/60 text-muted-foreground'
      )}
    >
      {label}
    </span>
  )
}
