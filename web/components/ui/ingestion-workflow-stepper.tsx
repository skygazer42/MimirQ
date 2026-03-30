'use client'

import { FileText, MessageSquare, Scissors, ShieldCheck } from 'lucide-react'

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

const STEPS: Step[] = [
  {
    key: 'parsing',
    label: '解析',
    href: '/parsing',
    icon: FileText,
    match: (p) => p === '/parsing' || p.startsWith('/parsing/'),
  },
  {
    key: 'governance',
    label: '治理',
    href: '/data-governance',
    icon: ShieldCheck,
    match: (p) => p === '/data-governance' || p.startsWith('/data-governance/'),
  },
  {
    key: 'chunk',
    label: '切块',
    href: '/chunk-preview',
    icon: Scissors,
    match: (p) => p === '/chunk-preview' || p.startsWith('/chunk-preview/'),
  },
  {
    key: 'chat',
    label: '对话',
    href: '/',
    icon: MessageSquare,
    match: (p) => p === '/' || p.startsWith('/history'),
  },
]

function getCurrentStepIndex(pathname: string) {
  const p = pathname || '/'
  const idx = STEPS.findIndex((s) => s.match(p))
  return idx >= 0 ? idx : 0
}

export function IngestionWorkflowStepper({
  className,
  compact = true,
}: Readonly<{
  className?: string
  compact?: boolean
}>) {
  const pathname = usePathname() || '/'
  const currentIndex = getCurrentStepIndex(pathname)

  return (
    <nav aria-label="入库流程" className={cn('flex items-center gap-2', className)}>
      {STEPS.map((step, index) => {
        const Icon = step.icon
        const isActive = index === currentIndex
        const isDone = index < currentIndex

        return (
          <div key={step.key} className="flex items-center gap-2">
            <Link
              href={step.href}
              aria-current={isActive ? 'step' : undefined}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-medium transition-colors focus-ring',
                compact ? 'h-7' : 'h-8',
                (() => {
    if (isActive) {
        return 'bg-primary/10 text-primary border-primary/25';
    }
    else if (isDone) {
            return 'bg-card/70 text-foreground border-border/60 hover:bg-primary/5 hover:border-primary/20';
        }
        else {
            return 'bg-muted/60 text-muted-foreground border-border/60 hover:bg-muted hover:text-foreground';
        }
})()
              )}
              title={step.label}
            >
              <Icon className={cn('w-3.5 h-3.5', (() => {
    if (isActive) {
        return 'text-primary';
    }
    else if (isDone) {
            return 'text-foreground/80';
        }
        else {
            return 'text-muted-foreground';
        }
})())} />
              <span className="whitespace-nowrap">{step.label}</span>
            </Link>
            {index < STEPS.length - 1 ? (
              <span className="text-muted-foreground/40 text-xs select-none">→</span>
            ) : null}
          </div>
        )
      })}
    </nav>
  )
}
