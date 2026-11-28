import type { CleanPreviewRuleStat } from '@/types/processing'

import { Panel } from '@/components/ui/panel'

type CleanPreviewRuleStatsPanelProps = {
  ruleStats: readonly CleanPreviewRuleStat[] | null | undefined
}

export function CleanPreviewRuleStatsPanel({ ruleStats }: Readonly<CleanPreviewRuleStatsPanelProps>) {
  const matchedRules = ruleStats?.filter((rule) => rule.hits > 0)
  const totalHits = matchedRules?.reduce((total, rule) => total + rule.hits, 0)

  return (
    <Panel padding="md" className="rounded-2xl">
      <div className="text-sm font-semibold text-foreground">规则命中</div>
      <div className="mt-1 text-[11px] text-muted-foreground">
        {matchedRules === undefined ? (
          '未返回规则统计'
        ) : (
          <>
            命中 <span className="font-mono">{totalHits}</span> 次 · 规则{' '}
            <span className="font-mono">
              {matchedRules.length}/{ruleStats?.length}
            </span>
          </>
        )}
      </div>

      {matchedRules === undefined ? null : matchedRules.length > 0 ? (
        <div className="mt-3 space-y-1">
          {matchedRules.map((rule) => (
            <div key={rule.index} className="flex items-start justify-between gap-3 rounded-xl bg-muted/20 px-3 py-2">
              <div className="min-w-0">
                <div className="text-[11px] font-mono text-foreground break-all">{rule.pattern}</div>
                <div className="mt-1 text-[11px] text-muted-foreground font-mono">
                  {rule.source != null && `来源 ${rule.source}`}
                  {rule.source === 'pack' && rule.pack != null && ` ${rule.pack}`}
                  {rule.flags !== undefined && ` · flags ${rule.flags}`}
                  {rule.repl !== undefined && rule.repl !== '' && ` · 替换为 ${rule.repl}`}
                </div>
              </div>
              <div className="shrink-0 text-[11px] font-mono rounded-full border border-border/60 bg-background px-2 py-0.5">
                {rule.hits}
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
