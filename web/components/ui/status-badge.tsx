import { useTranslations } from 'next-intl'

import { cn } from '@/lib/utils'

export type StatusBadgeStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'quarantined' | 'cancelled'

function getStatusMeta(
  t: ReturnType<typeof useTranslations<'CommonUi'>>,
): Record<StatusBadgeStatus, { label: string; dotColor: string; spin?: boolean }> {
  return {
    pending: {
      label: t('statusBadge.pending'),
      dotColor: 'bg-info',
    },
    processing: {
      label: t('statusBadge.processing'),
      dotColor: 'bg-warning',
      spin: true,
    },
    completed: {
      label: t('statusBadge.completed'),
      dotColor: 'bg-success',
    },
    failed: {
      label: t('statusBadge.failed'),
      dotColor: 'bg-destructive',
    },
    quarantined: {
      label: t('statusBadge.quarantined'),
      dotColor: 'bg-warning',
    },
    cancelled: {
      label: t('statusBadge.cancelled'),
      dotColor: 'bg-muted-foreground',
    },
  }
}

export function StatusBadge({
  status,
  className,
  label,
  dense = false,
}: Readonly<{
  status: StatusBadgeStatus
  className?: string
  label?: string
  showIcon?: boolean
  dense?: boolean
}>) {
  const t = useTranslations('CommonUi')
  const meta = getStatusMeta(t)[status]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md bg-foreground/[0.04] tracking-[-0.01em]',
        dense ? 'h-5 px-2 text-[11px] font-semibold' : 'px-2.5 py-1 text-xs font-medium',
        'text-foreground',
        className,
      )}
    >
      <span
        className={cn(
          'size-1.5 rounded-full shrink-0',
          meta.dotColor,
          meta.spin && 'animate-pulse motion-reduce:animate-none',
        )}
      />
      <span className="leading-none">{label ?? meta.label}</span>
    </span>
  )
}
