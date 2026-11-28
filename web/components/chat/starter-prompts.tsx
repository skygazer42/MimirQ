'use client'

import { useTranslations } from 'next-intl'

import { FileSearch, GitCompare, Network, ShieldCheck, ArrowRight } from '@/components/icons'

const STARTER_PROMPTS = [
  { key: 'summary', Icon: FileSearch },
  { key: 'compare', Icon: GitCompare },
  { key: 'relationships', Icon: Network },
  { key: 'citations', Icon: ShieldCheck },
] as const

export function StarterPrompts({ onSelect }: Readonly<{ onSelect: (prompt: string) => void }>) {
  const t = useTranslations('Chat')

  return (
    <section aria-label={t('starters.label')} className="mt-4 grid grid-cols-1 gap-3 @min-[32rem]:grid-cols-2">
      {STARTER_PROMPTS.map(({ key, Icon }) => (
        <button
          key={key}
          type="button"
          onClick={() => onSelect(t(`starters.${key}.prompt`))}
          className="group flex min-h-11 items-center gap-2.5 rounded-xl border border-border/85 bg-card px-4 py-3 text-left transition-colors hover:border-foreground/20 hover:bg-muted/40 focus-ring motion-reduce:transition-none"
        >
          <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            <span className="text-sm font-normal text-foreground">{t(`starters.${key}.title`)}</span>
            <span className="sr-only">{t(`starters.${key}.description`)}</span>
          </span>
          <ArrowRight
            className="size-3.5 shrink-0 text-muted-foreground/60 transition-colors group-hover:text-foreground group-focus-visible:text-foreground motion-reduce:transition-none"
            aria-hidden="true"
          />
        </button>
      ))}
    </section>
  )
}
