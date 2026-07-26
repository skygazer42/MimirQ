'use client'

import {
  AlertCircle,
  ArrowRightLeft,
  CheckCircle2,
  CircleDashed,
} from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

import {
  INLINE_STAT_TONE_CLASSES,
  INLINE_STAT_VALUE_TONE_CLASSES,
} from '../constants'

export function getHashPairIcon(hasA: boolean, hasB: boolean): ReactNode {
  if (hasA && hasB) return <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
  if (hasA || hasB) return <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
  return <CircleDashed className="h-3.5 w-3.5" aria-hidden="true" />
}

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
  tone?: 'muted' | 'neutral' | 'positive' | 'negative' | 'warning'
  valueTitle?: string
  valueClassName?: string
}>) {
  const toneClasses = INLINE_STAT_TONE_CLASSES[tone]
  const valueTone = INLINE_STAT_VALUE_TONE_CLASSES[tone]

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1',
        toneClasses
      )}
    >
      {icon ? (
        <span className="flex h-3.5 w-3.5 items-center justify-center opacity-80">
          {icon}
        </span>
      ) : null}
      <span className="text-[10.5px] font-medium uppercase tracking-[0.1em] opacity-80">
        {label}
      </span>
      <span
        title={valueTitle}
        className={cn(
          'font-mono text-[11px] font-semibold tabular-nums',
          valueTone,
          valueClassName
        )}
      >
        {value}
      </span>
    </div>
  )
}

export function WorkspaceSection({
  icon,
  label,
  hint,
  children,
}: Readonly<{
  icon?: ReactNode
  label: string
  hint?: string
  children: ReactNode
}>) {
  return (
    <section className="space-y-2.5 rounded-xl border border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.18))] p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {icon ? (
            <span className="flex h-3.5 w-3.5 items-center justify-center text-primary/70">
              {icon}
            </span>
          ) : null}
          {label}
        </div>
        {hint ? (
          <span className="text-[10px] text-muted-foreground/70">{hint}</span>
        ) : null}
      </div>
      {children}
    </section>
  )
}

export function SectionHeading({
  eyebrow,
  title,
  description,
  icon,
  extra,
}: Readonly<{
  eyebrow: string
  title: string
  description?: string
  icon?: ReactNode
  extra?: ReactNode
}>) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        {icon ? (
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)),hsl(var(--muted)/0.30))] text-primary shadow-sm">
            {icon}
          </div>
        ) : null}
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {eyebrow}
          </div>
          <div className="mt-0.5 text-[15px] font-semibold tracking-[-0.01em] text-foreground md:text-base">
            {title}
          </div>
          {description ? (
            <div className="mt-1 max-w-[640px] text-[12px] leading-5 text-muted-foreground">
              {description}
            </div>
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
    <div className="flex h-full min-h-[280px] items-center justify-center px-6 py-10">
      <div className="flex max-w-[440px] flex-col items-center text-center">
        <div className="relative">
          <div
            className="absolute inset-0 -z-0 rounded-full bg-[radial-gradient(circle,hsl(var(--primary)/0.18),transparent_60%)] blur-xl"
            aria-hidden
          />
          <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)),hsl(var(--muted)/0.30))] text-primary shadow-sm">
            <ArrowRightLeft
              className="h-7 w-7"
              strokeWidth={1.5}
              aria-hidden="true"
            />
          </div>
        </div>
        <h3 className="mt-4 text-[15px] font-semibold text-foreground">
          {title}
        </h3>
        <p className="mt-1.5 text-[12px] leading-5 text-muted-foreground">
          {description}
        </p>
        {hint ? (
          <div className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] text-muted-foreground">
            <CircleDashed
              className="h-3.5 w-3.5 text-primary/60"
              aria-hidden="true"
            />
            {hint}
          </div>
        ) : null}
      </div>
    </div>
  )
}
