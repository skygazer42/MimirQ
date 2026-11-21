'use client'

import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'
import { workspaceStyles as ws } from '@/components/ui/operational-workspace'

import { INLINE_STAT_TONE_CLASSES, INLINE_STAT_VALUE_TONE_CLASSES } from '../constants'
import type { SnapshotInlineStatTone } from '../types'

export function SnapshotInlineStat({
  icon,
  label,
  value,
  tone = 'muted',
  valueTitle,
  valueClassName,
}: Readonly<{
  icon?: ReactNode
  label: string
  value: ReactNode
  tone?: SnapshotInlineStatTone
  valueTitle?: string
  valueClassName?: string
}>) {
  const toneClasses = INLINE_STAT_TONE_CLASSES[tone]
  const valueTone = INLINE_STAT_VALUE_TONE_CLASSES[tone]

  return (
    <div className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1', toneClasses)}>
      {icon ? <span className="flex h-3.5 w-3.5 items-center justify-center opacity-80">{icon}</span> : null}
      <span className="text-[10.5px] font-medium uppercase tracking-[0.1em] opacity-80">{label}</span>
      <span
        title={valueTitle}
        className={cn('font-mono text-[11px] font-semibold tabular-nums', valueTone, valueClassName)}
      >
        {value}
      </span>
    </div>
  )
}

export function SectionHeading({
  title,
  description,
  icon,
  extra,
}: Readonly<{
  title: string
  description?: string
  icon?: ReactNode
  extra?: ReactNode
}>) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        {icon ? <div className="flex size-6 shrink-0 items-center justify-center text-primary">{icon}</div> : null}
        <div className="min-w-0">
          <div className="mt-0.5 text-[15px] font-semibold tracking-[-0.01em] text-foreground md:text-base">
            {title}
          </div>
          {description ? (
            <div className="mt-1 max-w-[640px] text-[13px] leading-6 text-muted-foreground">{description}</div>
          ) : null}
        </div>
      </div>
      {extra ? <div className="shrink-0">{extra}</div> : null}
    </div>
  )
}

export function DiffEmptyState({
  title,
  description,
  hint,
}: Readonly<{
  title: string
  description: string
  hint?: string
}>) {
  return (
    <div className="flex min-h-[280px] items-center px-6 py-10">
      <div className={ws.empty}>
        <h3 className="text-lg font-semibold text-foreground">{title}</h3>
        <p className="text-sm leading-6 text-muted-foreground">{description}</p>
        {hint ? <div className="text-[13px] text-muted-foreground">{hint}</div> : null}
      </div>
    </div>
  )
}
