'use client'

import { type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

import { formatPct } from '../report-format'
import {
  REPORT_LABEL_CLASS,
  REPORT_METRIC_VALUE_CLASS,
  REPORT_SUBTEXT_CLASS,
  REPORT_TABLE_ROW_CLASS,
  REPORT_VALUE_CLASS,
} from '../report-tokens'

import type { DataPillTone } from '../types'

export function DataPill({
  icon: Icon,
  label,
  value,
  sub,
  tone = 'blue',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  sub?: string
  tone?: DataPillTone
}>) {
  const toneClass = {
    blue: 'bg-info/10 text-info ring-info/20',
    green: 'bg-success/10 text-success ring-success/20',
    amber: 'bg-warning/10 text-warning ring-warning/20',
    rose: 'bg-destructive/10 text-destructive ring-destructive/20',
    violet: 'bg-accent/10 text-accent ring-accent/20',
    slate: 'bg-muted/50 text-muted-foreground ring-border/50',
  }[tone]
  const valueToneClass = {
    blue: 'text-foreground',
    green: 'text-success',
    amber: 'text-warning',
    rose: 'text-destructive',
    violet: 'text-accent',
    slate: 'text-foreground',
  }[tone]

  return (
    <div className="flex h-full min-w-0 items-center gap-2 bg-background/72 px-2.5 py-1.5">
      <div
        className={cn(
          'flex size-7 shrink-0 items-center justify-center rounded-lg ring-1',
          toneClass
        )}
      >
        <Icon className="size-3.5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-baseline gap-1.5">
          <div className={cn('shrink-0', REPORT_LABEL_CLASS)}>{label}</div>
          <div className={cn('min-w-0', REPORT_VALUE_CLASS, valueToneClass)}>
            {value}
          </div>
        </div>
        {sub ? (
          <div className={cn('truncate', REPORT_SUBTEXT_CLASS)}>
            {sub}
          </div>
        ) : null}
      </div>
    </div>
  )
}

export function AuditMetricCard({
  icon: Icon,
  label,
  value,
  sub,
  tone = 'blue',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  sub: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
}>) {
  const toneClass = {
    blue: 'bg-info/10 text-info ring-info/20',
    green: 'bg-success/10 text-success ring-success/20',
    amber: 'bg-warning/10 text-warning ring-warning/20',
    rose: 'bg-destructive/10 text-destructive ring-destructive/20',
    violet: 'bg-accent/10 text-accent ring-accent/20',
    slate: 'bg-muted/50 text-muted-foreground ring-border/50',
  }[tone]

  return (
    <article className="min-w-0 bg-background/72 px-3 py-2">
      <div className="flex items-center gap-2">
        <div
          className={cn(
            'flex size-8 shrink-0 items-center justify-center rounded-lg ring-1',
            toneClass
          )}
        >
          <Icon className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className={REPORT_LABEL_CLASS}>{label}</div>
          <div className={cn('mt-0.5', REPORT_METRIC_VALUE_CLASS)}>
            {value}
          </div>
          <div className={cn('mt-0.5 truncate', REPORT_SUBTEXT_CLASS)} title={sub}>
            {sub}
          </div>
        </div>
      </div>
    </article>
  )
}

export function ReportSignalRow({
  label,
  value,
  sub,
  tone = 'blue',
}: Readonly<{
  label: string
  value: string
  sub: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
}>) {
  const toneClass = {
    blue: 'text-info',
    green: 'text-success',
    amber: 'text-warning',
    rose: 'text-destructive',
    violet: 'text-accent',
    slate: 'text-muted-foreground',
  }[tone]
  const dotClass = {
    blue: 'bg-info/100',
    green: 'bg-success/100',
    amber: 'bg-warning/100',
    rose: 'bg-destructive/100',
    violet: 'bg-accent/100',
    slate: 'bg-muted-foreground/60',
  }[tone]

  return (
    <div className="flex items-center gap-2 rounded-lg border border-info/15 bg-info/[0.025] px-2 py-1.5">
      <span className={cn('size-2 shrink-0 rounded-full', dotClass)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <div
            className="truncate text-[0.75rem] font-medium text-foreground/85"
            title={label}
          >
            {label}
          </div>
          <div
            className={cn(
              'shrink-0 text-[0.875rem] font-semibold tabular-nums',
              toneClass
            )}
          >
            {value}
          </div>
        </div>
        <div className={cn('mt-0.5 truncate', REPORT_SUBTEXT_CLASS)} title={sub}>
          {sub}
        </div>
      </div>
    </div>
  )
}

export function ReportInlineEmpty({
  title,
  description,
}: Readonly<{ title: string; description: string }>) {
  return (
    <div className="rounded-xl border border-dashed border-info/20 bg-info/[0.025] px-3 py-2">
      <div className="text-[0.8125rem] font-semibold tracking-[-0.01em] text-foreground/85">
        {title}
      </div>
      <div className={cn('mt-1 max-w-[32rem]', REPORT_SUBTEXT_CLASS)}>
        {description}
      </div>
    </div>
  )
}

export function CompactAuditFact({
  icon: Icon,
  label,
  value,
  sub,
  tone = 'slate',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  sub: string
  tone?: 'blue' | 'green' | 'amber' | 'rose' | 'violet' | 'slate'
}>) {
  const toneClass = {
    blue: {
      shell: 'border-info/20 bg-info/5',
      icon: 'bg-info/15 text-info ring-info/30',
      rail: 'bg-info/100',
      value:
        'border-info/20 bg-background/70 text-info',
    },
    green: {
      shell: 'border-success/20 bg-success/5',
      icon: 'bg-success/15 text-success ring-success/30',
      rail: 'bg-success/100',
      value:
        'border-success/20 bg-background/70 text-success',
    },
    amber: {
      shell: 'border-warning/20 bg-warning/5',
      icon: 'bg-warning/15 text-warning ring-warning/30',
      rail: 'bg-warning/100',
      value:
        'border-warning/20 bg-background/70 text-warning',
    },
    rose: {
      shell: 'border-destructive/20 bg-destructive/5',
      icon: 'bg-destructive/15 text-destructive ring-destructive/30',
      rail: 'bg-destructive/100',
      value:
        'border-destructive/20 bg-background/70 text-destructive',
    },
    violet: {
      shell: 'border-accent/20 bg-accent/5',
      icon: 'bg-accent/15 text-accent ring-accent/30',
      rail: 'bg-accent/100',
      value:
        'border-accent/20 bg-background/70 text-accent',
    },
    slate: {
      shell: 'border-border/60 bg-muted/40',
      icon: 'bg-muted text-muted-foreground ring-border',
      rail: 'bg-border',
      value:
        'border-border bg-background/70 text-muted-foreground',
    },
  }[tone]

  return (
    <div
      className={cn(
        'relative min-w-0 overflow-hidden rounded-xl border px-2.5 py-1.5',
        toneClass.shell
      )}
    >
      <span
        className={cn('absolute inset-y-2 left-0 w-1 rounded-r-full', toneClass.rail)}
        aria-hidden="true"
      />
      <div className="flex min-w-0 items-center gap-2 pl-1">
        <div
          className={cn(
            'flex size-6 shrink-0 items-center justify-center rounded-md ring-1',
            toneClass.icon
          )}
        >
          <Icon className="size-3" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[0.75rem] font-semibold tracking-[-0.01em] text-foreground">
            {label}
          </div>
          <div className="mt-0.5 truncate text-[0.6875rem] leading-4 text-muted-foreground" title={sub}>
            {sub}
          </div>
        </div>
        <div
          className={cn(
            'inline-flex h-6 max-w-[46%] shrink-0 items-center justify-center truncate rounded-full border px-2 text-center text-[0.75rem] font-semibold tracking-[-0.01em] tabular-nums',
            toneClass.value
          )}
          title={value}
        >
          {value}
        </div>
      </div>
    </div>
  )
}

export function AuditMetricPlaceholder({
  label,
  hint,
}: Readonly<{ label: string; hint: string }>) {
  return (
    <div className="rounded-lg border border-dashed border-info/15 bg-info/[0.025] px-2.5 py-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[0.75rem] font-semibold tracking-[-0.01em] text-foreground/85">
          {label}
        </span>
        <span className="rounded-full bg-muted px-2 py-0.5 text-[0.6875rem] font-medium text-muted-foreground">
          待运行
        </span>
      </div>
      <div className={cn('mt-1 truncate', REPORT_SUBTEXT_CLASS)} title={hint}>
        {hint}
      </div>
    </div>
  )
}

export function ProgressRow({
  label,
  value,
  max,
}: Readonly<{ label: string; value: number; max: number }>) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0
  return (
    <div
      className={cn(
        'grid grid-cols-[104px_1fr_42px] items-center gap-2',
        REPORT_TABLE_ROW_CLASS
      )}
    >
      <div className="truncate text-muted-foreground" title={label}>
        {label}
      </div>
      <div className="h-1.5 rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-info/100"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-right tabular-nums text-muted-foreground">
        {formatPct(value, max)}
      </div>
    </div>
  )
}
