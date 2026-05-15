'use client'

import { FileText, MessageSquare, Scissors, ShieldCheck } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Link, usePathname } from '@/i18n/navigation'
import { cn } from '@/lib/utils'
import type { ComponentType } from 'react'

type Step = {
  key: 'parsing' | 'governance' | 'chunk' | 'chat'
  label: string
  href: string
  icon: ComponentType<{ className?: string }>
  match: (pathname: string) => boolean
}

function getSteps(t: ReturnType<typeof useTranslations<'CommonUi'>>): Step[] {
  return [
    {
      key: 'parsing',
      label: t("ingestionWorkflow.parsing"),
      href: '/parsing',
      icon: FileText,
      match: (p) => p === '/parsing' || p.startsWith('/parsing/'),
    },
    {
      key: 'governance',
      label: t("ingestionWorkflow.governance"),
      href: '/data-governance',
      icon: ShieldCheck,
      match: (p) => p === '/data-governance' || p.startsWith('/data-governance/'),
    },
    {
      key: 'chunk',
      label: t("ingestionWorkflow.chunk"),
      href: '/chunk-preview',
      icon: Scissors,
      match: (p) => p === '/chunk-preview' || p.startsWith('/chunk-preview/'),
    },
    {
      key: 'chat',
      label: t("ingestionWorkflow.chat"),
      href: '/',
      icon: MessageSquare,
      match: (p) => p === '/' || p.startsWith('/history'),
    },
  ]
}

function getCurrentStepIndex(pathname: string, steps: Step[]) {
  const p = pathname || '/'
  const idx = steps.findIndex((s) => s.match(p))
  return idx >= 0 ? idx : 0
}

export function IngestionWorkflowStepper({
  className,
  compact = true,
}: Readonly<{
  className?: string
  compact?: boolean
}>) {
  const t = useTranslations('CommonUi')
  const pathname = usePathname() || '/'
  const steps = getSteps(t)
  const currentIndex = getCurrentStepIndex(pathname, steps)

  return (
    <nav
      aria-label={t("ingestionWorkflow.navLabel")}
      className={cn(
        'flex items-center',
        compact ? 'gap-2' : 'min-w-[640px] gap-0',
        className
      )}
    >
      {steps.map((step, index) => {
        const Icon = step.icon
        const isActive = index === currentIndex
        const isDone = index < currentIndex

        return (
          <div
            key={step.key}
            className={cn('flex items-center', compact ? 'gap-2' : 'flex-1 gap-0')}
          >
            <Link
              href={step.href}
              aria-current={isActive ? 'step' : undefined}
              className={cn(
                'inline-flex items-center rounded-full border font-medium transition-colors focus-ring',
                compact
                  ? 'h-7 gap-1.5 px-3 py-1.5 text-[11px]'
                  : 'h-10 min-w-[142px] justify-center gap-2 px-4 text-[13px]',
                isActive &&
                  (compact
                    ? 'border-primary/25 bg-primary/10 text-primary'
                    : 'border-info/18 bg-[linear-gradient(90deg,hsl(var(--info)/0.16),hsl(var(--info)/0.06))] text-info shadow-[0_12px_30px_-24px_hsl(var(--info)/0.75)]'),
                isDone &&
                  !isActive &&
                  (compact
                    ? 'border-border/60 bg-card/70 text-foreground hover:border-primary/20 hover:bg-primary/5'
                    : 'border-transparent bg-transparent text-foreground/82 hover:bg-info/[0.045] hover:text-info'),
                !isDone &&
                  !isActive &&
                  (compact
                    ? 'border-border/60 bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground'
                    : 'border-transparent bg-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground')
              )}
              title={step.label}
            >
              {compact ? (
                <Icon
                  className={cn(
                    'h-3.5 w-3.5',
                    isActive && 'text-primary',
                    isDone && !isActive && 'text-foreground/80',
                    !isDone && !isActive && 'text-muted-foreground'
                  )}
                />
              ) : (
                <span
                  className={cn(
                    'flex size-5 items-center justify-center rounded-full border text-[11px] font-semibold tabular-nums',
                    isActive &&
                      'border-info bg-info text-info-foreground shadow-[0_8px_18px_-10px_hsl(var(--info)/0.85)]',
                    isDone &&
                      !isActive &&
                      'border-info/20 bg-info/[0.08] text-info',
                    !isDone &&
                      !isActive &&
                      'border-border bg-background text-muted-foreground'
                  )}
                >
                  {index + 1}
                </span>
              )}
              <span className="whitespace-nowrap">{step.label}</span>
            </Link>
            {index < steps.length - 1 ? (
              <span
                className={cn(
                  'select-none text-muted-foreground/40',
                  compact ? 'text-xs' : 'mx-2 text-sm'
                )}
              >
                →
              </span>
            ) : null}
          </div>
        )
      })}
    </nav>
  )
}
