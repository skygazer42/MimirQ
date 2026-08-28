'use client'

import type { ReactNode } from 'react'
import { AlertTriangle, ChevronDown, CircleHelp } from 'lucide-react'

import { cn } from '@/lib/utils'

type DangerZonePanelProps = {
  title: string
  impact: string
  badge?: string
  children: ReactNode
  className?: string
  compact?: boolean
  tone?: 'danger' | 'neutral'
  icon?: 'alert' | 'help'
}

export function DangerZonePanel({
  title,
  impact,
  badge = '危险维护',
  children,
  className,
  compact = false,
  tone = 'danger',
  icon = 'alert',
}: Readonly<DangerZonePanelProps>) {
  const isNeutral = tone === 'neutral'
  const Icon = icon === 'help' ? CircleHelp : AlertTriangle

  return (
    <details
      data-testid="danger-zone-panel"
      className={cn(
        'group rounded-xl p-0',
        isNeutral
          ? 'border border-info/15 bg-info/[0.025] shadow-none'
          : 'border border-destructive/20 bg-destructive/[0.025] shadow-none',
        className
      )}
    >
      <summary
        className={cn(
          'flex cursor-pointer list-none justify-between gap-3 marker:hidden',
          compact ? 'items-center px-2.5 py-2' : 'items-start px-3 py-2.5'
        )}
      >
        <div className={cn('flex min-w-0', compact ? 'gap-2' : 'gap-2.5')}>
          <div
            className={cn(
              'shrink-0 items-center justify-center rounded-lg',
              isNeutral
                ? 'border border-info/15 bg-info/[0.06] text-info'
                : 'border border-destructive/20 bg-destructive/[0.08] text-destructive',
              compact ? 'mt-0 flex size-6' : 'mt-0.5 flex size-7'
            )}
          >
            <Icon className={cn(compact ? 'h-3 w-3' : 'h-3.5 w-3.5')} />
          </div>
          <div className="min-w-0">
            <div className={cn('flex flex-wrap items-center', compact ? 'gap-1.5' : 'gap-2')}>
              <span className={cn('font-medium tracking-[-0.005em] text-foreground', compact ? 'text-[11.5px]' : 'text-[12px]')}>{title}</span>
              <span
                className={cn(
                  'rounded-full font-semibold',
                  isNeutral
                    ? 'border border-info/15 bg-info/[0.04] text-muted-foreground'
                    : 'border border-destructive/20 bg-destructive/[0.04] text-destructive',
                  compact ? 'px-1.5 py-0.5 text-[9px]' : 'px-1.5 py-0.5 text-[10px]'
                )}
              >
                {badge}
              </span>
            </div>
            <p className={cn('text-muted-foreground/90', compact ? 'mt-0.5 text-[10px] leading-3.5' : 'mt-0.5 text-[11px] leading-4')}>
              {impact}
            </p>
          </div>
        </div>
        <ChevronDown className={cn('shrink-0 text-muted-foreground transition-transform group-open:rotate-180', compact ? 'mt-0 h-3.5 w-3.5' : 'mt-1 h-4 w-4')} />
      </summary>
      <div
        className={cn(
          'px-3 pb-3 pt-3',
          isNeutral
            ? 'border-t border-info/15 bg-info/[0.025]'
            : 'border-t border-destructive/10 bg-destructive/[0.025]'
        )}
      >
        {children}
      </div>
    </details>
  )
}
