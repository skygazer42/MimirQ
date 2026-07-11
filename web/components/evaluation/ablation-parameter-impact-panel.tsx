'use client'

import { SlidersHorizontal } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { RegressionRun } from '@/types'

type Scalar = string | number | boolean | null

type ImpactRow = {
  key: string
  values: number
  bestLabel: string
  bestMetric: number
  worstLabel: string
  worstMetric: number
  spread: number
  samples: number
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function toNumber(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function metricValue(run: RegressionRun, metricKey: string): number | null {
  const summary = asRecord(run.summary)
  const candidates = [
    summary[metricKey],
    asRecord(summary.metrics)[metricKey],
    asRecord(summary.metric_values)[metricKey],
    asRecord(summary.retrieval_metrics)[metricKey],
    asRecord(summary.aggregate_metrics)[metricKey],
  ]

  for (const candidate of candidates) {
    const n = toNumber(candidate)
    if (n !== null) return n
  }
  return null
}

function isScalar(value: unknown): value is Scalar {
  return value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
}

function compactValue(value: Scalar): string {
  if (value === null) return 'null'
  const text = String(value)
  return text.length > 48 ? `${text.slice(0, 47)}…` : text
}

function collectScalars(source: Record<string, unknown>, prefix = '', depth = 0): Record<string, Scalar> {
  const result: Record<string, Scalar> = {}
  if (depth > 2) return result

  for (const [key, value] of Object.entries(source)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (isScalar(value)) {
      result[path] = value
    } else if (value && typeof value === 'object' && !Array.isArray(value)) {
      Object.assign(result, collectScalars(value as Record<string, unknown>, path, depth + 1))
    }
  }
  return result
}

function extractRunParams(run: RegressionRun): Record<string, Scalar> {
  const params = asRecord(run.params)
  const ragParams = asRecord(params.rag_params)
  const ablationVariant = asRecord(params.ablation_variant)
  const merged = {
    ...collectScalars(ragParams),
    ...collectScalars(ablationVariant),
  }

  return Object.fromEntries(
    Object.entries(merged).filter(([key]) => !['dataset_id', 'case_ids', 'metrics', 'ablation_id', 'ablation_label_prefix'].includes(key)),
  )
}

function buildImpactRows(runs: RegressionRun[], metricKey: string): ImpactRow[] {
  const groups = new Map<string, Map<string, { label: string; total: number; count: number }>>()

  for (const run of runs) {
    if (String(run.status || '') !== 'completed') continue
    const metric = metricValue(run, metricKey)
    if (metric === null) continue
    const params = extractRunParams(run)

    for (const [key, value] of Object.entries(params)) {
      const label = compactValue(value)
      const valueGroups = groups.get(key) ?? new Map<string, { label: string; total: number; count: number }>()
      const bucket = valueGroups.get(label) ?? { label, total: 0, count: 0 }
      bucket.total += metric
      bucket.count += 1
      valueGroups.set(label, bucket)
      groups.set(key, valueGroups)
    }
  }

  return Array.from(groups.entries())
    .map(([key, valueGroups]) => {
      const buckets = Array.from(valueGroups.values()).map((bucket) => ({
        label: bucket.label,
        mean: bucket.total / bucket.count,
        count: bucket.count,
      }))
      if (buckets.length < 2) return null
      const sorted = buckets.toSorted((a, b) => b.mean - a.mean)
      const best = sorted[0]
      const worst = sorted.at(-1)
      const worstMetric = worst?.mean ?? 0
      return {
        key,
        values: buckets.length,
        bestLabel: best.label,
        bestMetric: best.mean,
        worstLabel: worst?.label ?? '-',
        worstMetric,
        spread: best.mean - worstMetric,
        samples: buckets.reduce((sum, bucket) => sum + bucket.count, 0),
      }
    })
    .filter((row): row is ImpactRow => row !== null)
    .sort((a, b) => Math.abs(b.spread) - Math.abs(a.spread))
}

export function AblationParameterImpactPanel({
  runs,
  metricKey,
}: Readonly<{
  runs: RegressionRun[]
  metricKey: string
}>) {
  const rows = buildImpactRows(runs, metricKey).slice(0, 8)
  const maxSpread = rows.length ? Math.max(...rows.map((row) => Math.abs(row.spread))) || 1 : 1

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <SlidersHorizontal className="size-4 text-warning" />
            参数影响排序
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            基于已完成 runs 的 rag_params / ablation_variant 做观测相关排序，只用于定位下一轮调参重点，不当作 Sobol 或因果结论。
          </p>
        </div>
        <div className="rounded-full border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-medium text-warning">
          观测相关 · {metricKey}
        </div>
      </div>

      {rows.length ? (
        <div className="mt-3 space-y-2">
          {rows.map((row) => {
            const width = Math.max(8, (Math.abs(row.spread) / maxSpread) * 100)
            return (
              <div key={row.key} className="rounded-xl border border-border bg-muted/50 px-3 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <div className="min-w-0">
                    <div className="truncate font-mono font-semibold text-foreground">{row.key}</div>
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      {row.values} 个取值 · {row.samples} 个样本
                    </div>
                  </div>
                  <div className={cn('font-mono text-xs', row.spread >= 0 ? 'text-success' : 'text-destructive')}>
                    Δ {row.spread >= 0 ? '+' : ''}{row.spread.toFixed(4)}
                  </div>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-background">
                  <div className="h-full rounded-full bg-warning" style={{ width: `${width}%` }} />
                </div>
                <div className="mt-2 grid gap-2 text-[11px] text-muted-foreground sm:grid-cols-2">
                  <div className="rounded-lg bg-background px-2 py-1">
                    最好 <span className="font-mono text-foreground">{row.bestLabel}</span> · {row.bestMetric.toFixed(4)}
                  </div>
                  <div className="rounded-lg bg-background px-2 py-1">
                    最弱 <span className="font-mono text-foreground">{row.worstLabel}</span> · {row.worstMetric.toFixed(4)}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-dashed border-border bg-muted/50 px-3 py-8 text-center text-xs text-muted-foreground">
          暂无足够的 completed ablation_variant runs 计算参数影响；至少需要同一参数两个取值。
        </div>
      )}
    </section>
  )
}
