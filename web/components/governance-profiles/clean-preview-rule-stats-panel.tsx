import React from 'react'

import type { CleanPreviewRuleStat } from '@/types'

import { Panel } from '@/components/ui/panel'
import { cn } from '@/lib/utils'

export function CleanPreviewRuleStatsPanel({
  ruleStats,
  className,
}: Readonly<{
  ruleStats: CleanPreviewRuleStat[] | null | undefined
  className?: string
}>) {
  const stats = Array.isArray(ruleStats) ? ruleStats : []
  const hitsOnly = stats.filter((it) => (Number(it.hits) || 0) > 0)
  const totalHits = hitsOnly.reduce((acc, it) => acc + (Number(it.hits) || 0), 0)

  return (
    <Panel padding="md" className={cn('rounded-2xl', className)}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-foreground">规则命中</div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            hits: <span className="font-mono">{totalHits}</span> · rules:{' '}
            <span className="font-mono">
              {hitsOnly.length}/{stats.length}
            </span>
          </div>
        </div>
      </div>

      {hitsOnly.length ? (
        <div className="mt-3 space-y-1">
          {hitsOnly.map((it) => (
            <div
              key={it.index}
              className="flex items-start justify-between gap-3 rounded-xl bg-muted/20 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="text-[11px] font-mono text-foreground break-all">{it.pattern}</div>
                <div className="mt-1 text-[11px] text-muted-foreground font-mono">
                  {it.source ? `source: ${it.source === 'pack' ? 'pack:' + (it.pack || 'unknown') : it.source} · ` : ''}
                  flags: {Number(it.flags) || 0}
                  {typeof it.repl === 'string' && it.repl ? ` · repl: ${it.repl}` : ''}
                </div>
              </div>
              <div className="shrink-0 text-[11px] font-mono rounded-full border border-border/60 bg-background px-2 py-0.5">
                {Number(it.hits) || 0}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-3 text-[12px] text-muted-foreground">无命中</div>
      )}
    </Panel>
  )
}
