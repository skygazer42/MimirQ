'use client'

import { Layers3 } from '@/components/icons'

import { cn } from '@/lib/utils'
import type { RagasRegressionRunDiffResponse, RegressionRunMetricDiff } from '@/types'

const KEY_METRICS = ['retrieval_recall', 'retrieval_mrr', 'retrieval_ndcg_at_10', 'retrieval_hit_at_20']

function metricDelta(metrics: readonly RegressionRunMetricDiff[], key: string): number | null {
  return metrics.find((metric) => metric.key === key)?.delta ?? null
}

function formatDelta(value: number | null): string {
  if (value === null) return '-'
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`
}

export function AblationSliceDiffPanel({
  diff,
  metricKey,
}: Readonly<{
  diff: RagasRegressionRunDiffResponse | null
  metricKey: string
}>) {
  const metricKeys = [...new Set([metricKey, ...KEY_METRICS])]
  const sliceEntries =
    diff === null
      ? []
      : Object.entries(diff.slice_diffs)
          .map(([dimension, slice]) => ({
            dimension,
            truncatedBefore: slice.truncated_before,
            truncatedAfter: slice.truncated_after,
            buckets: slice.buckets
              .map((bucket) => ({ ...bucket, delta: metricDelta(bucket.metrics, metricKey) }))
              .sort((left, right) => {
                if (left.delta === null) return right.delta === null ? 0 : 1
                if (right.delta === null) return -1
                return Math.abs(right.delta) - Math.abs(left.delta)
              }),
          }))
          .filter((entry) => entry.buckets.length > 0)

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Layers3 className="size-4 text-primary" />
            切片差异
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            按 {metricKey} 的变化幅度排列全部已返回分组，未提供该指标的分组排在末尾；同时展示关键检索指标。
          </p>
        </div>
        <div className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary">
          Slice-based eval
        </div>
      </div>

      {sliceEntries.length > 0 ? (
        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          {sliceEntries.map((entry) => (
            <div key={entry.dimension} className="rounded-2xl border border-border bg-muted/50 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="font-mono text-xs font-semibold text-foreground">{entry.dimension}</div>
                {entry.truncatedBefore || entry.truncatedAfter ? (
                  <div className="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] font-medium text-warning">
                    {entry.truncatedBefore ? '基线分组已截断' : null}
                    {entry.truncatedBefore && entry.truncatedAfter ? ' · ' : null}
                    {entry.truncatedAfter ? '候选分组已截断' : null}
                  </div>
                ) : null}
              </div>
              <div className="mt-2 space-y-2">
                {entry.buckets.map((bucket) => {
                  const delta = bucket.delta
                  return (
                    <div key={bucket.key} className="rounded-xl border border-border bg-background px-3 py-2">
                      <div className="flex items-center justify-between gap-3 text-xs">
                        <div className="min-w-0">
                          <div className="break-words font-medium text-foreground">{bucket.key}</div>
                          <div className="mt-1 text-[11px] text-muted-foreground">
                            基线 {bucket.items_before} · 候选 {bucket.items_after}
                          </div>
                        </div>
                        <div
                          className={cn(
                            'font-mono font-semibold text-muted-foreground',
                            delta !== null && delta > 0 && 'text-success',
                            delta !== null && delta < 0 && 'text-destructive',
                          )}
                        >
                          {formatDelta(delta)}
                        </div>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-1.5 text-[10px] text-muted-foreground md:grid-cols-4">
                        {metricKeys.map((metric) => {
                          const metricValue = metricDelta(bucket.metrics, metric)
                          return (
                            <div key={metric} className="rounded-lg bg-muted/50 px-2 py-1">
                              <div className="truncate">{metric}</div>
                              <div
                                className={cn(
                                  'font-mono text-muted-foreground/70',
                                  metricValue !== null && metricValue > 0 && 'text-success',
                                  metricValue !== null && metricValue < 0 && 'text-destructive',
                                )}
                              >
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
          {diff === null ? '生成运行对比后查看切片差异。' : '本次对比没有返回切片分组。'}
        </div>
      )}
    </section>
  )
}
