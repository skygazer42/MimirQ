'use client'

import type { LucideIcon } from 'lucide-react'
import { ShieldCheck, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'

import { PageTitleIcon, type PageTitleIconName } from '@/components/ui/page-title-icon'
import { cn } from '@/lib/utils'

export const KNOWLEDGE_OPS_BACKGROUND_CLASS =
  'flex min-h-0 flex-1 flex-col overflow-hidden bg-background'

export const MANAGEMENT_HERO_PANEL_CLASS =
  'relative overflow-hidden rounded-none border-x-0 border-t-0 border-b border-foreground/15 bg-transparent px-1 py-2 shadow-none dark:bg-transparent'

export const KNOWLEDGE_OPS_HERO_PANEL_CLASS = MANAGEMENT_HERO_PANEL_CLASS

export const KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS =
  'flex min-w-0 flex-wrap items-center gap-2 rounded-md border border-foreground/10 bg-background/70 px-2.5 py-1.5 text-[11px] text-muted-foreground shadow-none'

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
  eyebrow,
  badge,
  summary,
  actions,
  className,
  titleClassName,
  descriptionClassName,
}: Readonly<KnowledgeOpsHeroProps>) {
  return (
    <div
      className={cn(
        'flex min-h-14 min-w-0 flex-col gap-2 lg:flex-row lg:items-center lg:justify-between',
        KNOWLEDGE_OPS_HERO_PANEL_CLASS,
        className
      )}
    >
      <div
        className="pointer-events-none absolute -bottom-px left-1 h-px w-12 bg-info/70"
        aria-hidden="true"
      />
      <div className="relative flex min-w-0 items-center gap-2.5">
        <div className="flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-md border border-foreground/10 bg-background/70 text-info shadow-none">
          <PageTitleIcon name={iconImage} className="size-6" />
        </div>
        <div className="min-w-0 lg:flex lg:items-center lg:gap-2.5">
          <h1
            className={cn(
              'text-[19px] font-semibold leading-6 tracking-[-0.02em] text-foreground',
              titleClassName
            )}
          >
            {title}
          </h1>
          <p
            className={cn(
              'text-[12px] leading-5 text-muted-foreground/85',
              descriptionClassName
            )}
          >
            {description}
          </p>
          {eyebrow || badge ? (
            <div className="mt-1 flex flex-wrap items-center gap-1.5 lg:mt-0">
              {eyebrow ? (
                <span className="inline-flex items-center gap-1 rounded-md border border-info/20 bg-info/5 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-info">
                  <Sparkles className="size-2.5" />
                  {eyebrow}
                </span>
              ) : null}
              {badge ? (
                <span className="inline-flex items-center rounded-md border border-success/20 bg-success/5 px-1.5 py-0.5 text-[9px] font-medium text-success">
                  <ShieldCheck className="mr-1 size-2.5" />
                  {badge}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      {summary || actions ? (
        <div className="relative flex min-w-0 flex-col gap-1.5 lg:max-w-[58%]">
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
