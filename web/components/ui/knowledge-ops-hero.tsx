'use client'

import type { LucideIcon } from 'lucide-react'
import { ShieldCheck, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'

import { PageTitleIcon, type PageTitleIconName } from '@/components/ui/page-title-icon'
import { cn } from '@/lib/utils'

export const KNOWLEDGE_OPS_BACKGROUND_CLASS =
  'flex min-h-0 flex-1 flex-col overflow-hidden bg-background bg-[radial-gradient(circle_at_top,hsl(var(--info)/0.04),transparent_34rem)]'

export const MANAGEMENT_HERO_PANEL_CLASS =
  'relative overflow-hidden rounded-[28px] border border-border/70 bg-[linear-gradient(135deg,hsl(var(--card)/0.98),hsl(var(--info)/0.045)_52%,hsl(var(--primary)/0.035))] px-4 py-3 shadow-[0_24px_70px_-50px_hsl(var(--info)/0.16)] backdrop-blur-2xl dark:border-border/80 dark:bg-[linear-gradient(135deg,hsl(var(--card)/0.96),hsl(var(--info)/0.07)_52%,hsl(var(--primary)/0.05))]'

export const KNOWLEDGE_OPS_HERO_PANEL_CLASS = MANAGEMENT_HERO_PANEL_CLASS

export const KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS =
  'flex min-w-0 flex-wrap items-center gap-2 rounded-2xl border border-info/14 bg-[linear-gradient(135deg,hsl(var(--card)/0.94),hsl(var(--info)/0.04))] px-3 py-2 text-[11px] text-muted-foreground shadow-[0_12px_28px_-24px_hsl(var(--info)/0.18)] backdrop-blur dark:border-info/12 dark:bg-[linear-gradient(135deg,hsl(var(--card)/0.78),hsl(var(--info)/0.06))]'

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
        className="pointer-events-none absolute -right-10 -top-14 size-44 rounded-full bg-info/10 blur-3xl dark:bg-info/[0.08]"
        aria-hidden="true"
      />
      <div
        className="pointer-events-none absolute bottom-0 left-8 right-8 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--info)/0.28),transparent)]"
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
            <span className="inline-flex items-center gap-1.5 rounded-full border border-info/30 bg-info/5 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-info dark:border-sky-300/20 dark:bg-sky-300/10 dark:text-sky-200">
              <Sparkles className="size-3" />
              {eyebrow}
            </span>
            <span className="inline-flex items-center rounded-full border border-success/30 bg-success/5 px-2.5 py-1 text-[10px] font-medium text-success dark:border-emerald-300/15 dark:bg-emerald-300/10 dark:text-emerald-200">
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
        KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS,
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
              <Icon className="size-3 text-info" />
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
