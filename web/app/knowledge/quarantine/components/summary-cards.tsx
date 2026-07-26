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
        'relative flex h-full min-h-[104px] flex-col justify-between overflow-hidden rounded-[1.15rem] border bg-background/92 px-3.5 py-3 shadow-[0_18px_44px_-38px_hsl(var(--foreground)/0.20)] backdrop-blur-sm',
        tone === 'neutral' && 'border-primary/12',
        tone === 'success' && 'border-success/12',
        tone === 'warning' && 'border-warning/14',
        tone === 'danger' && 'border-destructive/12',
        tone === 'info' && 'border-accent/12'
      )}
    >
      <div
        className={cn(
          'pointer-events-none absolute inset-0 opacity-95',
          tone === 'neutral' &&
            'bg-[radial-gradient(circle_at_top_right,hsl(var(--primary)/0.12),transparent_58%)]',
          tone === 'success' &&
            'bg-[radial-gradient(circle_at_top_right,rgba(16,185,129,0.14),transparent_58%)]',
          tone === 'warning' &&
            'bg-[radial-gradient(circle_at_top_right,rgba(245,158,11,0.18),transparent_58%)]',
          tone === 'danger' &&
            'bg-[radial-gradient(circle_at_top_right,rgba(239,68,68,0.14),transparent_58%)]',
          tone === 'info' &&
            'bg-[radial-gradient(circle_at_top_right,rgba(124,58,237,0.14),transparent_58%)]'
        )}
      />
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
            'flex size-9 shrink-0 items-center justify-center rounded-[0.9rem] border shadow-[0_14px_30px_-22px_currentColor]',
            tone === 'neutral' &&
              'border-primary/10 bg-primary/10 text-primary',
            tone === 'success' &&
              'border-success/10 bg-success/10 text-success',
            tone === 'warning' &&
              'border-warning/10 bg-warning/10 text-warning',
            tone === 'danger' && 'border-destructive/10 bg-destructive/10 text-destructive',
            tone === 'info' &&
              'border-accent/10 bg-accent/10 text-accent'
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
    <div className="h-full min-h-[178px] rounded-[1.1rem] border border-border/60 bg-background/92 p-3.5 shadow-[0_18px_44px_-38px_rgba(15,23,42,0.18)] backdrop-blur-sm">
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
            <div className="rounded-2xl border border-dashed border-border/70 bg-muted/20 px-4 py-4 text-center text-[12px] text-muted-foreground">
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
      className="flex min-h-[62px] items-start gap-2.5 rounded-[0.9rem] border border-border/60 bg-background/88 px-3 py-2 text-left transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:bg-primary/10 hover:shadow-[0_18px_35px_-30px_hsl(var(--primary)/0.5)]"
    >
      <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[0.8rem] border border-primary/10 bg-primary/10 text-primary">
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
