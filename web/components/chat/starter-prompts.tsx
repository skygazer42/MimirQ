'use client'

import { useTranslations } from 'next-intl'

import { FileSearch, GitCompare, Network, ShieldCheck, ArrowUpRight } from '@/components/icons'

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
          className="group flex items-start gap-3 rounded-xl border border-border/60 bg-card/80 p-4 text-left transition-colors hover:border-ring/40 hover:bg-card focus-ring motion-reduce:transition-none"
        >
          <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-muted/80 text-muted-foreground group-hover:bg-ring/10 group-hover:text-ring">
            <Icon className="size-4" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-foreground">{t(`starters.${key}.title`)}</span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {t(`starters.${key}.tag`)}
              </span>
            </span>
            <span className="mt-1 block text-xs leading-5 text-muted-foreground">
              {t(`starters.${key}.description`)}
            </span>
          </span>
          <ArrowUpRight
            className="mt-1 size-3.5 shrink-0 text-ring opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none"
            aria-hidden="true"
          />
        </button>
      ))}
    </section>
  )
}
