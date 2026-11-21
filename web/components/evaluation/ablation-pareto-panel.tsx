'use client'

import { CircleDot, Gauge } from '@/components/icons'

import { cn } from '@/lib/utils'
import { formatRunDuration, type RegressionRunStatistics } from '@/lib/regression-run-statistics'

type ParetoPoint = {
  id: string
  metric: number
  elapsedMs: number
  pareto: boolean
  x: number
  y: number
}

type ParetoCandidate = Omit<ParetoPoint, 'x' | 'y'>

function formatMetric(value: number): string {
  return value.toFixed(4)
}

export function AblationParetoPanel({
  runs,
  metricKey,
  paretoRunIds,
}: Readonly<{
  runs: readonly RegressionRunStatistics[]
  metricKey: string
  paretoRunIds: ReadonlySet<string>
}>) {
  const rawPoints: ParetoCandidate[] = []
  for (const entry of runs) {
    const metric = entry.metrics[metricKey]
    const duration = entry.elapsedMs
    if (metric === null || duration === null) continue
    rawPoints.push({ id: entry.run.id, metric, elapsedMs: duration, pareto: paretoRunIds.has(entry.run.id) })
  }
  const bounds =
    rawPoints.length === 0
      ? null
      : {
          minMetric: Math.min(...rawPoints.map((point) => point.metric)),
          maxMetric: Math.max(...rawPoints.map((point) => point.metric)),
          minDuration: Math.min(...rawPoints.map((point) => point.elapsedMs)),
          maxDuration: Math.max(...rawPoints.map((point) => point.elapsedMs)),
        }
  const points: ParetoPoint[] =
    bounds === null
      ? []
      : rawPoints.map((point) => {
          const metricRange = bounds.maxMetric - bounds.minMetric
          const durationRange = bounds.maxDuration - bounds.minDuration
          return {
            ...point,
            x: metricRange === 0 ? 50 : 8 + ((point.metric - bounds.minMetric) / metricRange) * 84,
            y: durationRange === 0 ? 50 : 8 + ((point.elapsedMs - bounds.minDuration) / durationRange) * 84,
          }
        })
  const paretoPoints = points.filter((point) => point.pareto).sort((a, b) => a.metric - b.metric)

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <CircleDot className="size-4 text-info" />
            Pareto 前沿
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            横轴是 {metricKey}，纵轴是运行总耗时；仅比较本页已加载的有效完成运行。耗时按记录中的开始、完成时间计算。
          </p>
        </div>
        <div className="rounded-xl border border-info/30 bg-info/10 px-3 py-2 text-right">
          <div className="text-[10px] uppercase tracking-[0.16em] text-info">Frontier</div>
          <div className="text-sm font-semibold text-info">{paretoPoints.length}</div>
        </div>
      </div>

      {bounds !== null ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_240px]">
          <div className="rounded-2xl border border-border bg-[radial-gradient(circle_at_18%_20%,hsl(var(--info)/0.10),transparent_28%),linear-gradient(180deg,hsl(var(--card))_0%,hsl(var(--background))_100%)] p-3">
            <div className="relative h-64 overflow-hidden rounded-xl border border-border bg-background/75">
              <div className="absolute left-3 top-3 rounded-full bg-background/90 px-2 py-1 text-[10px] font-medium text-muted-foreground shadow-sm">
                低运行总耗时
              </div>
              <div className="absolute bottom-3 right-3 rounded-full bg-background/90 px-2 py-1 text-[10px] font-medium text-muted-foreground shadow-sm">
                高 {metricKey}
              </div>
              <div className="absolute inset-x-8 top-1/2 h-px bg-border/70" />
              <div className="absolute inset-y-8 left-1/2 w-px bg-border/70" />
              {paretoPoints.length > 1 ? (
                <svg
                  className="pointer-events-none absolute inset-0 h-full w-full"
                  viewBox="0 0 100 100"
                  preserveAspectRatio="none"
                  aria-hidden="true"
                >
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
                    point.pareto
                      ? 'size-4 border-info bg-info ring-4 ring-info/20'
                      : 'size-3 border-border bg-muted-foreground/70',
                  )}
                  style={{ left: `${point.x}%`, top: `${point.y}%` }}
                  role="img"
                  aria-label={`${point.id}，${metricKey}=${formatMetric(point.metric)}，运行总耗时 ${formatRunDuration(point.elapsedMs)}`}
                  title={`${point.id} ${metricKey}=${formatMetric(point.metric)} 运行总耗时=${formatRunDuration(point.elapsedMs)}`}
                />
              ))}
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
              <span>
                {metricKey}: {formatMetric(bounds.minMetric)}
              </span>
              <span>{formatMetric(bounds.maxMetric)}</span>
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-muted/50 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
              <Gauge className="size-4 text-info" />
              候选 run
            </div>
            <div className="mt-3 max-h-64 space-y-2 overflow-y-auto overscroll-contain">
              {paretoPoints.map((point) => (
                <div
                  key={point.id}
                  className="rounded-xl border border-border bg-background px-3 py-2 text-xs shadow-sm"
                >
                  <div className="break-all font-mono font-semibold text-foreground">{point.id}</div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                    <span>{metricKey}</span>
                    <span className="font-mono text-foreground">{formatMetric(point.metric)}</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                    <span>运行总耗时</span>
                    <span className="font-mono text-foreground">{formatRunDuration(point.elapsedMs)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-dashed border-border bg-muted/50 px-3 py-8 text-center text-xs text-muted-foreground">
          尚无同时提供 {metricKey} 与开始/完成时间的有效完成运行。
        </div>
      )}
    </section>
  )
}
