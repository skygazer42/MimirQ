'use client'

import type { LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

import { buildSparklinePath, buildSparklinePlaceholderPath } from './monitor-utils'

export function StatCard({
  label,
  value,
  icon: Icon,
  color,
  iconSurface,
  border,
  delta = null,
  deltaInverted = false,
  pulse = false,
  ringColor = '',
  sparklineMode,
  sparklineValues = [],
  sparklineColor,
}: Readonly<{
  label: string
  value: string | number
  icon: LucideIcon
  color: string
  iconSurface: string
  border: string
  delta?: number | null
  deltaInverted?: boolean
  pulse?: boolean
  ringColor?: string
  sparklineMode: 'real' | 'placeholder'
  sparklineValues?: number[]
  sparklineColor?: string
}>) {
  const deltaBad = deltaInverted ? delta !== null && delta > 0 : delta !== null && delta < 0
  const deltaGood = delta !== null && !deltaBad && delta !== 0
  const pulseActive = pulse && Number(value) > 0
  const pathData = sparklineMode === 'placeholder'
    ? buildSparklinePlaceholderPath()
    : buildSparklinePath(sparklineValues)

  return (
    <div
      className={cn(
        'group flex items-center gap-2.5 px-2.5 py-1.5 transition-all duration-200 motion-reduce:transition-none hover:bg-muted/50 rounded-lg',
        border
      )}
    >
      <div className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border/30 bg-background/50 shadow-sm', iconSurface)}>
        {pulseActive && (
          <span aria-hidden className={cn('pointer-events-none absolute h-5 w-5 rounded-md animate-pulse-ring motion-reduce:animate-none opacity-20', ringColor)} />
        )}
        <Icon className={cn('relative h-3.5 w-3.5', color, pulseActive && 'animate-heartbeat motion-reduce:animate-none')} />
      </div>

      <div className="flex min-w-0 flex-1 flex-col leading-tight">
        <div className="flex items-center gap-1 text-[9px] font-bold uppercase  text-muted-foreground/60">
          <span className="truncate">{label}</span>
          {delta !== null && (
            <span
              className={cn(
                'font-black',
                deltaGood ? 'text-emerald-600/80' : 'text-red-600/80'
              )}
            >
              {delta > 0 ? '+' : ''}{delta}%
            </span>
          )}
        </div>
        <div className={cn('text-sm font-bold  tabular-nums', color)}>{value}</div>
      </div>
      <svg viewBox="0 0 80 24" aria-hidden="true" className="ml-auto h-6 w-20 shrink-0 overflow-visible">
        <path
          d={pathData}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={sparklineMode === 'placeholder' ? '4 3' : undefined}
          className={cn(sparklineColor || color, sparklineMode === 'placeholder' && 'opacity-45')}
        />
      </svg>
    </div>
  )
}
