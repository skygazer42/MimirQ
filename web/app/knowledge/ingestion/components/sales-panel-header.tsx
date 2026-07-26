'use client'

import { ChevronRight, LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

export type SalesPanelHeaderProps = {
  actionLabel?: string
  icon: LucideIcon
  iconTone?: string
  onAction?: () => void
  subtitle?: string
  title: string
}

export function SalesPanelHeader({
  actionLabel,
  icon: Icon,
  iconTone = 'text-muted-foreground/65',
  onAction,
  subtitle,
  title,
}: Readonly<SalesPanelHeaderProps>) {
  return (
    <div className="flex min-h-[1.5rem] items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex min-h-4 items-center gap-1.5 text-[10px] font-medium tracking-[-0.01em] text-foreground">
          <Icon className={cn('h-3 w-3 shrink-0', iconTone)} />
          <span className="truncate">{title}</span>
        </div>
        {subtitle ? (
          <div className="mt-0.5 pl-[18px] text-[8px] leading-3 text-muted-foreground">
            {subtitle}
          </div>
        ) : null}
      </div>
      {actionLabel ? (
        <button
          type="button"
          onClick={onAction}
          className="inline-flex min-h-4 shrink-0 items-center gap-0.5 text-[8px] font-medium text-info transition-colors hover:text-info"
        >
          <span>{actionLabel}</span>
          <ChevronRight className="h-3 w-3" />
        </button>
      ) : null}
    </div>
  )
}
