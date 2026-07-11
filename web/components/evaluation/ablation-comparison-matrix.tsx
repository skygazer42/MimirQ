'use client'

import { GitCompareArrows } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { RegressionRun } from '@/types'

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function metricValue(run: RegressionRun, key: string): number | null {
  const summary = asRecord(run.summary)
  const candidates = [
    summary[key],
    asRecord(summary.metrics)[key],
    asRecord(summary.metric_values)[key],
    asRecord(summary.retrieval_metrics)[key],
    asRecord(summary.aggregate_metrics)[key],
  ]
  for (const item of candidates) {
    const n = Number(item)
    if (Number.isFinite(n)) return n
  }
  return null
}

function latency(run: RegressionRun): number | null {
  const summary = asRecord(run.summary)
  const candidates = [summary.latency_ms, summary.elapsed_ms, summary.duration_ms, summary.elapsed_sec]
  for (const item of candidates) {
    const n = Number(item)
    if (Number.isFinite(n)) return String(item).includes('.') && n < 1000 ? n * 1000 : n
  }
  return null
}

function isPareto(run: RegressionRun, runs: RegressionRun[], metricKey: string): boolean {
  const ownMetric = metricValue(run, metricKey)
  const ownLatency = latency(run)
  if (ownMetric === null || ownLatency === null) return false
  return !runs.some((other) => {
    if (other.id === run.id) return false
    const otherMetric = metricValue(other, metricKey)
    const otherLatency = latency(other)
    if (otherMetric === null || otherLatency === null) return false
    return otherMetric >= ownMetric && otherLatency <= ownLatency && (otherMetric > ownMetric || otherLatency < ownLatency)
  })
}

function shortId(value: string): string {
  return value ? `${value.slice(0, 8)}…` : '-'
}

export function AblationComparisonMatrix({
  runs,
  baseRunId,
  metricKeys,
}: Readonly<{
  runs: RegressionRun[]
  baseRunId: string
  metricKeys: string[]
}>) {
  const completed = runs.filter((run) => String(run.status || '') === 'completed').slice(0, 8)
  const base = completed.find((run) => run.id === baseRunId) ?? completed[0] ?? null
  const primaryMetric = metricKeys[0] || 'retrieval_mrr'

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <GitCompareArrows className="size-4 text-accent" />
            N×M 多 Run 对比矩阵
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            行是 run，列是 metric；单元格显示 value 与相对 base 的 delta。右侧标记 Pareto 候选：更高主指标、更低 latency。
          </p>
        </div>
        <div className="rounded-xl border border-accent/30 bg-accent/10 px-3 py-2 text-right">
          <div className="text-[10px] uppercase tracking-[0.16em] text-accent">Pareto</div>
          <div className="text-sm font-semibold text-accent">
            {completed.filter((run) => isPareto(run, completed, primaryMetric)).length || '-'}
          </div>
        </div>
      </div>

      <div className="mt-3 overflow-auto rounded-xl border border-border">
        <div
          className="grid min-w-[720px] bg-muted/50 text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
          style={{ gridTemplateColumns: `140px repeat(${metricKeys.length}, minmax(110px, 1fr)) 110px` }}
        >
          <div className="px-3 py-2">Run</div>
          {metricKeys.map((metric) => (
            <div key={metric} className="px-3 py-2 text-right">{metric}</div>
          ))}
          <div className="px-3 py-2 text-right">latency</div>
        </div>
        {completed.length ? completed.map((run) => {
          const pareto = isPareto(run, completed, primaryMetric)
          return (
            <div
              key={run.id}
              className="grid min-w-[720px] border-t border-border/50 text-xs"
              style={{ gridTemplateColumns: `140px repeat(${metricKeys.length}, minmax(110px, 1fr)) 110px` }}
            >
              <div className={cn('px-3 py-2 font-mono', pareto ? 'text-accent' : 'text-foreground')}>
                {shortId(run.id)} {pareto ? '•' : ''}
              </div>
              {metricKeys.map((metric) => {
                const value = metricValue(run, metric)
                const baseValue = base ? metricValue(base, metric) : null
                const delta = value !== null && baseValue !== null ? value - baseValue : null
                const heat = value === null ? 0 : Math.max(0.08, Math.min(0.32, value))
                return (
                  <div
                    key={`${run.id}-${metric}`}
                    className="px-3 py-2 text-right font-mono"
                    style={{ backgroundColor: `hsl(var(--info) / ${heat})` }}
                  >
                    <span className="text-foreground">{value === null ? '-' : value.toFixed(4)}</span>
                    <span className={cn('ml-1 text-[10px]', delta && delta > 0 ? 'text-success' : delta && delta < 0 ? 'text-destructive' : 'text-muted-foreground')}>
                      {delta === null ? '' : delta >= 0 ? `+${delta.toFixed(3)}` : delta.toFixed(3)}
                    </span>
                  </div>
                )
              })}
              <div className="px-3 py-2 text-right font-mono text-muted-foreground">{latency(run) === null ? '-' : `${Math.round(latency(run) || 0)}ms`}</div>
            </div>
          )
        }) : (
          <div className="px-3 py-8 text-center text-xs text-muted-foreground">暂无 completed runs，刷新排行榜或先创建消融实验。</div>
        )}
      </div>
    </section>
  )
}
