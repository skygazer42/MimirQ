'use client'

import { GitCompareArrows } from '@/components/icons'

import { cn } from '@/lib/utils'
import { WorkspaceTableScroll } from '@/components/ui/operational-workspace'
import { formatRunDuration, type RegressionRunStatistics } from '@/lib/regression-run-statistics'

export function AblationComparisonMatrix({
  runs,
  baseRunId,
  metricKeys,
  primaryMetricKey,
  paretoRunIds,
}: Readonly<{
  runs: readonly RegressionRunStatistics[]
  baseRunId: string
  metricKeys: readonly string[]
  primaryMetricKey: string
  paretoRunIds: ReadonlySet<string>
}>) {
  const base = runs.find((entry) => entry.run.id === baseRunId)

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <GitCompareArrows className="size-4 text-accent" />
            多运行对比矩阵
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            比较本页已加载的完成运行与选定基准。Pareto 使用 {primaryMetricKey} 和运行总耗时；
            总耗时按运行记录中的开始、完成时间计算。
          </p>
          {base === undefined ? (
            <p role="status" className="mt-1 text-xs text-muted-foreground">
              {baseRunId === ''
                ? '尚未选择基准运行，暂不计算差值。'
                : `基准 ${baseRunId} 不在当前有效完成运行中，暂不计算差值。`}
            </p>
          ) : null}
        </div>
        <div className="rounded-xl border border-accent/30 bg-accent/10 px-3 py-2 text-right">
          <div className="text-[10px] uppercase tracking-[0.16em] text-accent">Pareto</div>
          <div className="text-sm font-semibold text-accent">{paretoRunIds.size}</div>
        </div>
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-border">
        <WorkspaceTableScroll label="已加载运行指标对比">
          <table className="w-full min-w-[720px] text-xs">
            <caption className="sr-only">已加载完成运行的指标、相对所选基准的差值和运行总耗时</caption>
            <thead className="bg-muted/50 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  运行
                </th>
                {metricKeys.map((metric) => (
                  <th key={metric} scope="col" className="min-w-[110px] px-3 py-2 text-right font-medium">
                    {metric}
                  </th>
                ))}
                <th scope="col" className="min-w-[110px] px-3 py-2 text-right font-medium">
                  运行总耗时
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.length > 0 ? (
                runs.map((entry) => {
                  const pareto = paretoRunIds.has(entry.run.id)
                  return (
                    <tr key={entry.run.id} className="border-t border-border/50">
                      <th
                        scope="row"
                        className={cn(
                          'px-3 py-2 text-left font-mono font-normal',
                          pareto ? 'text-accent' : 'text-foreground',
                        )}
                      >
                        <span className="block max-w-[140px] truncate" title={entry.run.id}>
                          {entry.run.id}
                        </span>
                        {pareto ? <span className="text-[10px]">Pareto 候选</span> : null}
                      </th>
                      {metricKeys.map((metric) => {
                        const value = entry.metrics[metric]
                        const baseValue = base?.metrics[metric]
                        const delta = value !== null && baseValue != null ? value - baseValue : null
                        return (
                          <td
                            key={metric}
                            className="px-3 py-2 text-right font-mono"
                            style={
                              value === null ? undefined : { backgroundColor: `hsl(var(--info) / ${value * 0.32})` }
                            }
                          >
                            <span className="text-foreground">{value === null ? '未提供' : value.toFixed(4)}</span>
                            {delta !== null ? (
                              <span
                                className={cn(
                                  'ml-1 text-[10px] text-muted-foreground',
                                  delta > 0 && 'text-success',
                                  delta < 0 && 'text-destructive',
                                )}
                              >
                                {delta >= 0 ? '+' : ''}
                                {delta.toFixed(3)}
                              </span>
                            ) : null}
                          </td>
                        )
                      })}
                      <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                        {formatRunDuration(entry.elapsedMs)}
                      </td>
                    </tr>
                  )
                })
              ) : (
                <tr>
                  <td colSpan={metricKeys.length + 2} className="px-3 py-8 text-center text-muted-foreground">
                    当前没有可比较的有效完成运行。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </WorkspaceTableScroll>
      </div>
    </section>
  )
}
