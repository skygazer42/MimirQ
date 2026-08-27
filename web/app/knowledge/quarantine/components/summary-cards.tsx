'use client'

import type { LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

import { buildConicGradient } from '../quarantine-signals'

export function SummaryStatCard({
  label,
  value,
  hint,
  icon: Icon,
  delta,
  tone = 'neutral',
}: Readonly<{
  label: string
  value: string | number
  hint: string
  icon: LucideIcon
  delta?: { value: string; tone: 'up' | 'down' | 'neutral' }
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}>) {
  return (
    <div
      className={cn(
        'relative flex h-full min-h-[104px] flex-col justify-between rounded-lg border bg-background px-3.5 py-3 shadow-none',
        tone === 'neutral' && 'border-foreground/10',
        tone === 'success' && 'border-foreground/10',
        tone === 'warning' && 'border-foreground/10',
        tone === 'danger' && 'border-foreground/10',
        tone === 'info' && 'border-foreground/10'
      )}
    >
      <div className="relative flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="text-[10px] font-medium uppercase tracking-[0.14em] leading-none text-muted-foreground/80">
            {label}
          </div>
          <div className="text-[1.55rem] font-semibold leading-none text-foreground">
            {value}
          </div>
        </div>
        <div
          className={cn(
            'flex size-9 shrink-0 items-center justify-center rounded-md border border-foreground/10 bg-background/70 shadow-none',
            tone === 'neutral' &&
              'text-primary',
            tone === 'success' &&
              'text-success',
            tone === 'warning' &&
              'text-warning',
            tone === 'danger' && 'border-destructive/10 bg-destructive/10 text-destructive',
            tone === 'info' &&
              'text-accent'
          )}
        >
          <Icon className="size-4" />
        </div>
      </div>

      <div className="relative mt-2.5 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-medium text-muted-foreground">
            {hint}
          </div>
          {delta ? (
            <div
              className={cn(
                'mt-1 text-[12px] font-medium',
                delta.tone === 'up' && 'text-destructive',
                delta.tone === 'down' && 'text-success',
                delta.tone === 'neutral' && 'text-muted-foreground'
              )}
            >
              {delta.value}
            </div>
          ) : null}
        </div>
        <div className="flex items-end gap-0.5 opacity-85">
          {[0.32, 0.56, 0.4, 0.72, 0.48, 0.62, 0.78].map((height, index) => (
            <span
              key={`${label}-${index}`}
              className={cn(
                'w-[5px] rounded-full',
                tone === 'neutral' && 'bg-primary/70',
                tone === 'success' && 'bg-success',
                tone === 'warning' && 'bg-warning/80',
                tone === 'danger' && 'bg-destructive/70',
                tone === 'info' && 'bg-accent/70'
              )}
              style={{ height: `${5 + height * 16}px` }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

export function DonutSummaryCard({
  title,
  subtitle,
  items,
  colors,
}: Readonly<{
  title: string
  subtitle?: string
  items: Array<{ label: string; value: number; hint?: string }>
  colors: string[]
}>) {
  const values = items.map((item) => item.value)
  const gradient = buildConicGradient(values, colors)
  const total = values.reduce((sum, value) => sum + value, 0)

  return (
    <div className="h-full min-h-[178px] rounded-lg border border-foreground/10 bg-background p-3.5 shadow-none">
      <div className="text-[0.9rem] font-medium text-foreground">{title}</div>
      {subtitle ? (
        <div className="mt-1 text-[11px] text-muted-foreground">{subtitle}</div>
      ) : null}
      <div className="mt-3.5 grid gap-3.5 md:grid-cols-[100px_minmax(0,1fr)] md:items-center">
        <div className="flex items-center justify-center">
          <div
            className="relative h-[86px] w-[86px] rounded-full shadow-[inset_0_0_0_1px_rgba(148,163,184,0.18)]"
            style={{ backgroundImage: gradient }}
          >
            <div className="absolute inset-[16px] rounded-full bg-background shadow-[inset_0_0_0_1px_rgba(148,163,184,0.12)]" />
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-[1.2rem] font-semibold leading-none text-foreground">
                {total}
              </span>
              <span className="mt-1 text-[10px] font-medium text-muted-foreground/85">
                总量
              </span>
            </div>
          </div>
        </div>
        <div className="space-y-2">
          {items.length ? (
            items.map((item, index) => (
              <div
                key={item.label}
                className="flex items-center justify-between gap-3 text-[11px]"
              >
                <div className="flex min-w-0 items-center gap-2.5 text-muted-foreground">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: colors[index] }}
                  />
                  <span className="truncate">{item.label}</span>
                </div>
                <div className="shrink-0 text-right">
                  <span className="text-[12px] tabular-nums text-foreground">
                    {item.value}
                  </span>
                  {item.hint ? (
                    <span className="ml-1.5 text-[10px] text-muted-foreground">
                      {item.hint}
                    </span>
                  ) : null}
                  {!item.hint && total > 0 ? (
                    <span className="ml-1.5 text-[10px] text-muted-foreground">
                      ({((item.value / total) * 100).toFixed(1)}%)
                    </span>
                  ) : null}
                  {!item.hint && total === 0 ? (
                    <span className="ml-1.5 text-[10px] text-muted-foreground">
                      (0%)
                    </span>
                  ) : null}
                </div>
              </div>
            ))
          ) : (
            <div className="rounded-lg border border-dashed border-foreground/10 bg-muted/20 px-4 py-4 text-center text-[12px] text-muted-foreground">
              暂无数据
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function QuickActionCard({
  title,
  description,
  icon: Icon,
  onClick,
}: Readonly<{
  title: string
  description: string
  icon: LucideIcon
  onClick: () => void
}>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-[62px] items-start gap-2.5 rounded-lg border border-foreground/10 bg-background px-3 py-2 text-left transition-colors hover:border-foreground/15 hover:bg-muted/20"
    >
      <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-foreground/10 bg-background/70 text-primary">
        <Icon className="size-3.5" />
      </span>
      <span className="min-w-0">
        <span className="block text-[12px] font-medium text-foreground">
          {title}
        </span>
        <span className="mt-0.5 block text-[10px] leading-4 text-muted-foreground">
          {description}
        </span>
      </span>
    </button>
  )
}
