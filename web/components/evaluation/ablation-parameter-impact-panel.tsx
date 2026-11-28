'use client'

import { SlidersHorizontal } from '@/components/icons'

import { getRegressionRunParameters, type RegressionRunStatistics } from '@/lib/regression-run-statistics'
import { formatApiError } from '@/lib/api-errors'

type ImpactRow = {
  key: string
  values: number
  bestLabel: string
  bestMetric: number
  worstLabel: string
  worstMetric: number
  spread: number
  observations: number
}

type ParameterBucket = { total: number; count: number }

function buildImpactRows(runs: readonly RegressionRunStatistics[], metricKey: string) {
  const groups = new Map<string, Map<string, ParameterBucket>>()
  const errors: { runId: string; error: unknown }[] = []
  for (const entry of runs) {
    const metric = entry.metrics[metricKey]
    if (metric === null) continue
    try {
      const parameters = getRegressionRunParameters(entry.run)
      for (const parameter of parameters) {
        const key = parameter.key
        let valueGroups = groups.get(key)
        if (valueGroups === undefined) {
          valueGroups = new Map()
          groups.set(key, valueGroups)
        }
        const valueKey = JSON.stringify(parameter.value)
        let bucket = valueGroups.get(valueKey)
        if (bucket === undefined) {
          bucket = { total: 0, count: 0 }
          valueGroups.set(valueKey, bucket)
        }
        bucket.total += metric
        bucket.count += 1
      }
    } catch (error) {
      errors.push({ runId: entry.run.id, error })
    }
  }

  const rows: ImpactRow[] = []
  for (const [key, valueGroups] of groups) {
    const buckets = [...valueGroups].map(([label, bucket]) => ({
      label,
      mean: bucket.total / bucket.count,
      count: bucket.count,
    }))
    if (buckets.length < 2) continue
    buckets.sort((a, b) => b.mean - a.mean)
    const best = buckets[0]
    const worst = buckets[buckets.length - 1]
    rows.push({
      key,
      values: buckets.length,
      bestLabel: best.label,
      bestMetric: best.mean,
      worstLabel: worst.label,
      worstMetric: worst.mean,
      spread: best.mean - worst.mean,
      observations: buckets.reduce((sum, bucket) => sum + bucket.count, 0),
    })
  }
  rows.sort((a, b) => b.spread - a.spread)
  return { rows, errors }
}

export function AblationParameterImpactPanel({
  runs,
  metricKey,
}: Readonly<{
  runs: readonly RegressionRunStatistics[]
  metricKey: string
}>) {
  const { rows, errors } = buildImpactRows(runs, metricKey)
  const maxSpread = rows.reduce((maximum, row) => Math.max(maximum, row.spread), 0)

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <SlidersHorizontal className="size-4 text-warning" />
            参数影响排序
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            按本页已加载完成运行记录中的检索参数分组，比较平均指标，仅作关联观察。
          </p>
        </div>
        <div className="rounded-full border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-medium text-warning">
          观测相关 · {metricKey}
        </div>
      </div>

      {errors.length > 0 ? (
        <div role="alert" className="mt-3 text-sm text-destructive">
          {errors.map((issue) => (
            <p key={issue.runId} className="break-words">
              运行 {issue.runId} 的参数未参与比较：{formatApiError(issue.error, '参数结构无效')}
            </p>
          ))}
        </div>
      ) : null}
      {rows.length > 0 ? (
        <div className="mt-3 space-y-2">
          {rows.map((row) => {
            const width = maxSpread === 0 ? 0 : (row.spread / maxSpread) * 100
            return (
              <div key={row.key} className="rounded-xl border border-border bg-muted/50 px-3 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <div className="min-w-0">
                    <div className="truncate font-mono font-semibold text-foreground" title={row.key}>
                      {row.key}
                    </div>
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      {row.values} 个取值 · {row.observations} 次运行观测
                    </div>
                  </div>
                  <div className="font-mono text-xs text-foreground">均值差 {row.spread.toFixed(4)}</div>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-background">
                  <div className="h-full rounded-full bg-warning" style={{ width: `${width}%` }} />
                </div>
                <div className="mt-2 grid gap-2 text-[11px] text-muted-foreground sm:grid-cols-2">
                  <div className="rounded-lg bg-background px-2 py-1">
                    最高均值 <span className="break-all font-mono text-foreground">{row.bestLabel}</span> ·{' '}
                    {row.bestMetric.toFixed(4)}
                  </div>
                  <div className="rounded-lg bg-background px-2 py-1">
                    最低均值 <span className="break-all font-mono text-foreground">{row.worstLabel}</span> ·{' '}
                    {row.worstMetric.toFixed(4)}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-dashed border-border bg-muted/50 px-3 py-8 text-center text-xs text-muted-foreground">
          当前有效运行不足以比较参数取值；同一参数至少需要两个实际取值。
        </div>
      )}
    </section>
  )
}
