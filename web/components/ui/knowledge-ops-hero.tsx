'use client'

import type { LucideIcon } from 'lucide-react'
import { ShieldCheck, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'

import { PageTitleIcon, type PageTitleIconName } from '@/components/ui/page-title-icon'
import { cn } from '@/lib/utils'

export const KNOWLEDGE_OPS_BACKGROUND_CLASS =
  'bg-white bg-[radial-gradient(circle_at_top,hsl(var(--info)/0.10),transparent_34rem)] dark:bg-background'

export const KNOWLEDGE_OPS_HERO_PANEL_CLASS =
  'relative overflow-hidden rounded-[28px] border border-sky-200/55 bg-[linear-gradient(135deg,rgba(248,253,255,0.92),rgba(229,245,255,0.72)_45%,rgba(255,255,255,0.82))] px-4 py-3 shadow-[0_24px_70px_-48px_rgba(14,116,144,0.55)] backdrop-blur-2xl dark:border-sky-300/15 dark:bg-[linear-gradient(135deg,rgba(8,21,34,0.82),rgba(8,47,73,0.36)_48%,rgba(15,23,42,0.72))]'

type KnowledgeOpsHeroProps = {
  iconImage: PageTitleIconName
  title: ReactNode
  description: ReactNode
  eyebrow?: ReactNode
  badge?: ReactNode
  summary?: ReactNode
  actions?: ReactNode
  className?: string
  titleClassName?: string
  descriptionClassName?: string
}

export function KnowledgeOpsHero({
  iconImage,
  title,
  description,
  eyebrow = 'Knowledge Ops',
  badge = '文档资产治理中枢',
  summary,
  actions,
  className,
  titleClassName,
  descriptionClassName,
}: Readonly<KnowledgeOpsHeroProps>) {
  return (
    <div
      className={cn(
        'flex min-w-0 flex-col gap-4 lg:flex-row lg:items-center lg:justify-between',
        KNOWLEDGE_OPS_HERO_PANEL_CLASS,
        className
      )}
    >
      <div
        className="pointer-events-none absolute -right-10 -top-14 size-44 rounded-full bg-sky-300/22 blur-3xl"
        aria-hidden="true"
      />
      <div
        className="pointer-events-none absolute bottom-0 left-8 right-8 h-px bg-gradient-to-r from-transparent via-sky-300/65 to-transparent"
        aria-hidden="true"
      />
      <div className="relative flex min-w-0 items-center gap-3">
        <div className="relative flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-[22px] border border-info/20 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.12))] text-info shadow-[inset_0_1px_0_hsl(var(--background)),0_18px_36px_-24px_hsl(var(--info)/0.9)]">
          <span
            className="absolute inset-x-2 top-1 h-px bg-card/70"
            aria-hidden="true"
          />
          <PageTitleIcon name={iconImage} className="size-9" />
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-200/70 bg-sky-50/70 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-sky-700 dark:border-sky-300/20 dark:bg-sky-300/10 dark:text-sky-200">
              <Sparkles className="size-3" />
              {eyebrow}
            </span>
            <span className="inline-flex items-center rounded-full border border-emerald-200/65 bg-emerald-50/70 px-2.5 py-1 text-[10px] font-medium text-emerald-700 dark:border-emerald-300/15 dark:bg-emerald-300/10 dark:text-emerald-200">
              <ShieldCheck className="mr-1.5 size-3" />
              {badge}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1
              className={cn(
                'text-[22px] font-semibold tracking-[-0.025em] text-foreground',
                titleClassName
              )}
            >
              <span className="bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent">
                {title}
              </span>
            </h1>
            <p
              className={cn(
                'text-[13px] leading-5 text-muted-foreground/85',
                descriptionClassName
              )}
            >
              {description}
            </p>
          </div>
        </div>
      </div>
      {summary || actions ? (
        <div className="relative flex min-w-0 flex-col gap-2 lg:min-w-[470px]">
          {summary}
          {actions ? (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {actions}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

type KnowledgeOpsFlowCardProps = {
  steps: Array<{ icon: LucideIcon; label: ReactNode }>
  className?: string
}

export function KnowledgeOpsFlowCard({
  steps,
  className,
}: Readonly<KnowledgeOpsFlowCardProps>) {
  return (
    <div
      className={cn(
        'flex min-w-0 items-center justify-between gap-2 rounded-2xl border border-sky-200/70 bg-white/64 px-3 py-2 text-[11px] text-muted-foreground shadow-[0_12px_28px_-24px_rgba(14,116,144,0.45)] backdrop-blur dark:border-sky-300/15 dark:bg-background/28',
        className
      )}
    >
      {steps.map((step, index) => {
        const Icon = step.icon
        return (
          <div
            key={`${String(step.label)}-${index}`}
            className="contents"
          >
            <span className="inline-flex items-center gap-1.5">
              <Icon className="size-3 text-sky-500" />
              {step.label}
            </span>
            {index < steps.length - 1 ? (
              <span
                className="size-3 shrink-0 text-muted-foreground/45"
                aria-hidden="true"
              >
                →
              </span>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
