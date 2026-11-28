'use client'

import { useTranslations } from 'next-intl'

import { FileSearch, GitCompare, Network, ShieldCheck, ArrowRight } from '@/components/icons'

const STARTER_PROMPTS = [
  {
    key: 'summary',
    Icon: FileSearch,
    trayClassName:
      'border-[hsl(var(--icon-knowledge)/0.18)] bg-[hsl(var(--icon-knowledge)/0.08)] text-[hsl(var(--icon-knowledge))]',
  },
  {
    key: 'compare',
    Icon: GitCompare,
    trayClassName:
      'border-[hsl(var(--icon-process)/0.18)] bg-[hsl(var(--icon-process)/0.08)] text-[hsl(var(--icon-process))]',
  },
  {
    key: 'relationships',
    Icon: Network,
    trayClassName:
      'border-[hsl(var(--icon-analysis)/0.18)] bg-[hsl(var(--icon-analysis)/0.08)] text-[hsl(var(--icon-analysis))]',
  },
  {
    key: 'citations',
    Icon: ShieldCheck,
    trayClassName:
      'border-[hsl(var(--icon-governance)/0.18)] bg-[hsl(var(--icon-governance)/0.08)] text-[hsl(var(--icon-governance))]',
  },
] as const

export function StarterPrompts({ onSelect }: Readonly<{ onSelect: (prompt: string) => void }>) {
  const t = useTranslations('Chat')

  return (
    <section aria-label={t('starters.label')} className="mt-4 grid grid-cols-1 gap-3 @min-[32rem]:grid-cols-2">
      {STARTER_PROMPTS.map(({ key, Icon, trayClassName }) => (
        <button
          key={key}
          type="button"
          onClick={() => onSelect(t(`starters.${key}.prompt`))}
          className="group flex min-h-11 items-center gap-2.5 rounded-xl border border-border/90 bg-card px-4 py-3 text-left shadow-[0_1px_2px_hsl(var(--foreground)/0.04)] transition-[border-color,box-shadow,transform,background-color] duration-150 hover:-translate-y-px hover:border-accent/40 hover:bg-card hover:shadow-[0_4px_12px_-2px_hsl(var(--foreground)/0.08)] focus-ring motion-reduce:transition-none motion-reduce:hover:translate-y-0"
        >
          <span
            className={`inline-flex size-7 shrink-0 items-center justify-center rounded-lg border ${trayClassName}`}
          >
            <Icon className="size-4" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="text-sm font-normal text-foreground">{t(`starters.${key}.title`)}</span>
            <span className="sr-only">{t(`starters.${key}.description`)}</span>
          </span>
          <ArrowRight
            className="size-3.5 shrink-0 text-muted-foreground/60 transition-[color,transform] duration-150 group-hover:translate-x-0.5 group-hover:text-accent group-focus-visible:text-accent motion-reduce:transition-none motion-reduce:group-hover:translate-x-0"
            aria-hidden="true"
          />
        </button>
      ))}
    </section>
  )
}
