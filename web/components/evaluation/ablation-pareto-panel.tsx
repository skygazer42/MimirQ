'use client'

import { CircleDot, Gauge } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { RegressionRun } from '@/types'

type ParetoPoint = {
  id: string
  metric: number
  latency: number
  x: number
  y: number
  pareto: boolean
}
type ParetoCandidate = Pick<ParetoPoint, 'id' | 'metric' | 'latency'>

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

function latency(run: RegressionRun): number | null {
  const summary = asRecord(run.summary)
  const candidates = [summary.latency_ms, summary.elapsed_ms, summary.duration_ms, summary.p95_latency_ms, summary.elapsed_sec]

  for (const candidate of candidates) {
    const n = toNumber(candidate)
    if (n === null) continue
    return candidate === summary.elapsed_sec && n < 1000 ? n * 1000 : n
  }
  return null
}

function isParetoCandidate(point: ParetoCandidate, points: ParetoCandidate[]): boolean {
  return !points.some((other) => {
    if (other.id === point.id) return false
    const dominates = other.metric >= point.metric && other.latency <= point.latency
    const strictlyBetter = other.metric > point.metric || other.latency < point.latency
    return dominates && strictlyBetter
  })
}

function shortId(value: string): string {
  return value ? `${value.slice(0, 8)}…` : '-'
}

function formatMetric(value: number): string {
  return value.toFixed(4)
}

function formatLatency(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`
  return `${Math.round(value)}ms`
}

export function AblationParetoPanel({
  runs,
  metricKey,
}: Readonly<{
  runs: RegressionRun[]
  metricKey: string
}>) {
  const rawPoints = runs
    .filter((run) => String(run.status || '') === 'completed')
    .map((run) => {
      const metric = metricValue(run, metricKey)
      const runLatency = latency(run)
      if (metric === null || runLatency === null) return null
      return { id: run.id, metric, latency: runLatency }
    })
    .filter((point): point is Pick<ParetoPoint, 'id' | 'metric' | 'latency'> => point !== null)

  const minMetric = rawPoints.length ? Math.min(...rawPoints.map((point) => point.metric)) : 0
  const maxMetric = rawPoints.length ? Math.max(...rawPoints.map((point) => point.metric)) : 1
  const minLatency = rawPoints.length ? Math.min(...rawPoints.map((point) => point.latency)) : 0
  const maxLatency = rawPoints.length ? Math.max(...rawPoints.map((point) => point.latency)) : 1
  const metricRange = maxMetric - minMetric || 1
  const latencyRange = maxLatency - minLatency || 1

  const points: ParetoPoint[] = rawPoints.map((point) => ({
    ...point,
    x: 8 + ((point.metric - minMetric) / metricRange) * 84,
    y: 8 + ((maxLatency - point.latency) / latencyRange) * 84,
    pareto: isParetoCandidate(point, rawPoints),
  }))

  const paretoPoints = points.filter((point) => point.pareto).sort((a, b) => a.metric - b.metric)

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <CircleDot className="size-4 text-info" />
            Pareto 前沿
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            横轴是 {metricKey}，纵轴是 latency；高指标、低延迟的点会被标记为候选，用来快速判断“提升是否值得”。
          </p>
        </div>
        <div className="rounded-xl border border-info/30 bg-info/10 px-3 py-2 text-right">
          <div className="text-[10px] uppercase tracking-[0.16em] text-info">Frontier</div>
          <div className="text-sm font-semibold text-info">{paretoPoints.length || '-'}</div>
        </div>
      </div>

      {points.length ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_240px]">
          <div className="rounded-2xl border border-border bg-[radial-gradient(circle_at_18%_20%,hsl(var(--info)/0.10),transparent_28%),linear-gradient(180deg,hsl(var(--card))_0%,hsl(var(--background))_100%)] p-3">
            <div className="relative h-64 overflow-hidden rounded-xl border border-border bg-background/75">
              <div className="absolute left-3 top-3 rounded-full bg-background/90 px-2 py-1 text-[10px] font-medium text-muted-foreground shadow-sm">低 latency</div>
              <div className="absolute bottom-3 right-3 rounded-full bg-background/90 px-2 py-1 text-[10px] font-medium text-muted-foreground shadow-sm">高 {metricKey}</div>
              <div className="absolute inset-x-8 top-1/2 h-px bg-border/70" />
              <div className="absolute inset-y-8 left-1/2 w-px bg-border/70" />
              {paretoPoints.length > 1 ? (
                <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
                  <polyline
                    fill="none"
                    stroke="hsl(var(--info) / 0.42)"
                    strokeDasharray="5 5"
                    strokeWidth="2"
                    points={paretoPoints.map((point) => `${point.x},${point.y}`).join(' ')}
                    vectorEffect="non-scaling-stroke"
                  />
                </svg>
              ) : null}
              {points.map((point) => (
                <div
                  key={point.id}
                  className={cn(
                    'absolute -translate-x-1/2 -translate-y-1/2 rounded-full border shadow-sm transition-transform hover:z-10 hover:scale-125',
                    point.pareto ? 'size-4 border-info bg-info ring-4 ring-info/20' : 'size-3 border-border bg-muted-foreground/70',
                  )}
                  style={{ left: `${point.x}%`, top: `${point.y}%` }}
                  title={`${shortId(point.id)} ${metricKey}=${formatMetric(point.metric)} latency=${formatLatency(point.latency)}`}
                />
              ))}
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
              <span>{metricKey}: {formatMetric(minMetric)}</span>
              <span>{formatMetric(maxMetric)}</span>
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-muted/50 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
              <Gauge className="size-4 text-info" />
              候选 run
            </div>
            <div className="mt-3 space-y-2">
              {paretoPoints.slice(0, 6).map((point) => (
                <div key={point.id} className="rounded-xl border border-border bg-background px-3 py-2 text-xs shadow-sm">
                  <div className="font-mono font-semibold text-foreground">{shortId(point.id)}</div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                    <span>{metricKey}</span>
                    <span className="font-mono text-foreground">{formatMetric(point.metric)}</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                    <span>latency</span>
                    <span className="font-mono text-foreground">{formatLatency(point.latency)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-dashed border-border bg-muted/50 px-3 py-8 text-center text-xs text-muted-foreground">
          暂无带 {metricKey} 与 latency 的 completed runs。完成消融后这里会显示轻量 Pareto 视图。
        </div>
      )}
    </section>
  )
}
