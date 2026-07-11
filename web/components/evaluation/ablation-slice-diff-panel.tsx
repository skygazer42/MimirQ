'use client'

import { Layers3 } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { RagasRegressionRunDiffResponse, RegressionRunMetricDiff, RegressionRunSliceBucketDiff } from '@/types'

const KEY_METRICS = ['retrieval_recall', 'retrieval_mrr', 'retrieval_ndcg_at_10', 'retrieval_hit_at_20']

function toNumber(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function metricDelta(metrics: RegressionRunMetricDiff[], key: string): number | null {
  const match = metrics.find((metric) => metric.key === key)
  if (!match) return null
  return toNumber(match.delta)
}

function bestMetric(bucket: RegressionRunSliceBucketDiff): { key: string; delta: number | null } {
  for (const key of KEY_METRICS) {
    const delta = metricDelta(bucket.metrics, key)
    if (delta !== null) return { key, delta }
  }
  const first = bucket.metrics[0]
  return first ? { key: first.key, delta: toNumber(first.delta) } : { key: 'metric', delta: null }
}

function formatDelta(value: number | null): string {
  if (value === null) return '-'
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`
}

export function AblationSliceDiffPanel({
  diff,
}: Readonly<{
  diff: RagasRegressionRunDiffResponse | null
}>) {
  const sliceEntries = Object.entries(diff?.slice_diffs ?? {})
    .map(([dimension, slice]) => ({
      dimension,
      truncated: slice.truncated_before || slice.truncated_after,
      buckets: slice.buckets
        .map((bucket) => ({ ...bucket, primary: bestMetric(bucket) }))
        .sort((a, b) => Math.abs(b.primary.delta ?? 0) - Math.abs(a.primary.delta ?? 0))
        .slice(0, 4),
    }))
    .filter((entry) => entry.buckets.length)

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Layers3 className="size-4 text-primary" />
            切片差异
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            直接读取 diff.slice_diffs，按文件类型、目录、语言、pipeline 等切片看 retrieval_recall / MRR 的局部退化，避免聚合指标掩盖问题。
          </p>
        </div>
        <div className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary">
          Slice-based eval
        </div>
      </div>

      {sliceEntries.length ? (
        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          {sliceEntries.map((entry) => (
            <div key={entry.dimension} className="rounded-2xl border border-border bg-muted/50 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="font-mono text-xs font-semibold text-foreground">{entry.dimension}</div>
                {entry.truncated ? (
                  <div className="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] font-medium text-warning">已截断</div>
                ) : null}
              </div>
              <div className="mt-2 space-y-2">
                {entry.buckets.map((bucket) => {
                  const delta = bucket.primary.delta
                  return (
                    <div key={bucket.key} className="rounded-xl border border-border bg-background px-3 py-2">
                      <div className="flex items-center justify-between gap-3 text-xs">
                        <div className="min-w-0">
                          <div className="truncate font-medium text-foreground">{bucket.key || '-'}</div>
                          <div className="mt-1 text-[11px] text-muted-foreground">
                            before {bucket.items_before} · after {bucket.items_after}
                          </div>
                        </div>
                        <div className={cn('font-mono font-semibold', delta === null ? 'text-muted-foreground' : delta >= 0 ? 'text-success' : 'text-destructive')}>
                          {formatDelta(delta)}
                        </div>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-1.5 text-[10px] text-muted-foreground md:grid-cols-4">
                        {KEY_METRICS.map((metric) => {
                          const metricValue = metricDelta(bucket.metrics, metric)
                          return (
                            <div key={metric} className="rounded-lg bg-muted/50 px-2 py-1">
                              <div className="truncate">{metric}</div>
                              <div className={cn('font-mono', metricValue === null ? 'text-muted-foreground/70' : metricValue >= 0 ? 'text-success' : 'text-destructive')}>
                                {formatDelta(metricValue)}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-dashed border-border bg-muted/50 px-3 py-8 text-center text-xs text-muted-foreground">
          暂无切片 diff。生成 base vs target diff 后，如果后端返回 slice_diffs，这里会显示局部退化切片。
        </div>
      )}
    </section>
  )
}
