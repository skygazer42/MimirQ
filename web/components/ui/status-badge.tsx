import type { LucideIcon } from "lucide-react"
import { AlertCircle, AlertTriangle, Ban, CheckCircle2, Clock, Loader2 } from "lucide-react"
import { useTranslations } from 'next-intl'

import { cn } from "@/lib/utils"

export type StatusBadgeStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "quarantined"
  | "cancelled"

function getStatusMeta(
  t: ReturnType<typeof useTranslations<'CommonUi'>>
): Record<
  StatusBadgeStatus,
  { label: string; icon: LucideIcon; className: string; spin?: boolean }
> {
  return {
    pending: {
      label: t('statusBadge.pending'),
      icon: Clock,
      className: "bg-info/10 text-info border-info/25",
    },
    processing: {
      label: t('statusBadge.processing'),
      icon: Loader2,
      className: "bg-info/10 text-info border-info/25",
      spin: true,
    },
    completed: {
      label: t('statusBadge.completed'),
      icon: CheckCircle2,
      className: "bg-success/10 text-success border-success/25",
    },
    failed: {
      label: t('statusBadge.failed'),
      icon: AlertCircle,
      className: "bg-destructive/10 text-destructive border-destructive/25",
    },
    quarantined: {
      label: t('statusBadge.quarantined'),
      icon: AlertTriangle,
      className: "bg-warning/10 text-warning border-warning/25",
    },
    cancelled: {
      label: t('statusBadge.cancelled'),
      icon: Ban,
      className: "bg-muted/60 text-muted-foreground border-border/60",
    },
  }
}

export function StatusBadge({
  status,
  className,
  label,
  showIcon = true,
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
  const Icon = meta.icon
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-medium",
        dense ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs",
        meta.className,
        className
      )}
    >
      {showIcon ? (
        <Icon
          className={cn(
            dense ? "h-3.5 w-3.5" : "h-4 w-4",
            meta.spin && "animate-spin motion-reduce:animate-none"
          )}
        />
      ) : null}
      <span className="leading-none">{label ?? meta.label}</span>
    </span>
  )
}
