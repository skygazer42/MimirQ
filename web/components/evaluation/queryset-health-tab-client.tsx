'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import {
  RefreshCw,
  GitCompare,
  Target,
  TrendingUp,
  ChartLine,
  Timer,
  SearchX,
  ShieldAlert,
  Scale,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { observabilityApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'
import type { JsonObject } from '@/types'

type QuerysetHealthRunItem = JsonObject & {
  generated_at?: string
  metrics?: JsonObject
  risk?: JsonObject
  degradation_flags?: unknown[]
  status?: string
}

type QuerysetTrendRow = {
  t: number
  time: string
  dateLabel: string
  hit_at_k: number | null
  mrr: number | null
  ndcg_at_k: number | null
  p95_latency_ms: number | null
  miss_rate: number | null
  weak_hit_rate: number | null
}

const QUERYSET_DELTA_METRICS = [
  {
    key: 'hit_at_k_delta',
    label: '命中率（Hit@K）',
    kind: 'percent',
    lowerIsBetter: false,
  },
  { key: 'mrr_delta', label: 'MRR', kind: 'number', lowerIsBetter: false },
  {
    key: 'ndcg_at_k_delta',
    label: 'NDCG@K',
    kind: 'number',
    lowerIsBetter: false,
  },
  {
    key: 'p95_latency_ms_delta',
    label: 'P95 延迟',
    kind: 'ms',
    lowerIsBetter: true,
  },
  {
    key: 'miss_rate_delta',
    label: '漏检率',
    kind: 'percent',
    lowerIsBetter: true,
  },
  {
    key: 'weak_hit_rate_delta',
    label: '弱命中率',
    kind: 'percent',
    lowerIsBetter: true,
  },
] as const

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function querysetRunItem(value: unknown): QuerysetHealthRunItem {
  return isJsonObject(value) ? value : {}
}
function formatTs(tsMs: number) {
  try {
    return new Date(tsMs).toLocaleString([], {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return String(tsMs)
  }
}

function formatDateTick(tsMs: number) {
  try {
    return new Date(tsMs)
      .toLocaleDateString([], { month: '2-digit', day: '2-digit' })
      .replace('/', '-')
  } catch {
    return String(tsMs)
  }
}

function buildQuerysetTrendSkeleton() {
  const dayMs = 24 * 60 * 60 * 1000
  const end = new Date()
  end.setHours(0, 0, 0, 0)

  return Array.from({ length: 7 }, (_, index) => {
    const t = end.getTime() - (6 - index) * dayMs
    return {
      t,
      time: formatTs(t),
      dateLabel: formatDateTick(t),
      hit_at_k: null,
      mrr: null,
      ndcg_at_k: null,
      p95_latency_ms: null,
      miss_rate: null,
      weak_hit_rate: null,
    }
  })
}

function fmtPercent(v?: unknown, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(digits)}%`
}

function fmtNum(v?: unknown, digits = 3) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return Number(v).toFixed(digits)
}

function fmtMs(v?: unknown) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `${Math.round(Number(v))}ms`
}

function formatSignedDelta(
  value: unknown,
  kind: (typeof QUERYSET_DELTA_METRICS)[number]['kind']
) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  const sign = numeric > 0 ? '+' : ''
  if (kind === 'percent') return `${sign}${(numeric * 100).toFixed(1)}%`
  if (kind === 'ms') return `${sign}${numeric.toFixed(1)}ms`
  return `${sign}${numeric.toFixed(3)}`
}

function deltaState(value: unknown, lowerIsBetter: boolean) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || Math.abs(numeric) < 1e-9) {
    return { label: '持平', className: 'bg-muted text-muted-foreground' }
  }
  const improved = lowerIsBetter ? numeric < 0 : numeric > 0
  if (improved) {
    return { label: '改善', className: 'bg-success/10 text-success' }
  }
  return { label: '退化', className: 'bg-destructive/10 text-destructive' }
}

function QuerysetChartEmptyState() {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <div className="rounded-2xl bg-card px-4 py-3 text-center shadow-none ring-1 ring-border/60">
        <div className="mx-auto mb-1.5 flex h-9 w-9 items-center justify-center rounded-xl bg-muted text-muted-foreground/70">
          <ChartLine className="h-4 w-4" aria-hidden="true" />
        </div>
        <div className="text-[12px] font-semibold text-foreground">暂无数据</div>
        <div className="mt-0.5 text-[11px] text-muted-foreground">
          当前筛选条件下暂无趋势数据
        </div>
      </div>
    </div>
  )
}

export function QuerysetHealthTab({
  embedded = false,
}: Readonly<{ embedded?: boolean }>) {
  const [baselineTs, setBaselineTs] = useState<string>('')
  const [currentTs, setCurrentTs] = useState<string>('')
  const [showAllRuns, setShowAllRuns] = useState(false)
  const runsQuery = useQuery({
    queryKey: queryKeys.evaluations.querysetHealthRuns({ limit: 90 }),
    queryFn: () => observabilityApi.getQuerysetHealthRuns({ limit: 90 }),
  })
  const diffQuery = useQuery({
    queryKey: queryKeys.evaluations.querysetHealthDiff({
      baseline_generated_at: baselineTs,
      current_generated_at: currentTs,
      max_hard_case_ids: 20,
    }),
    enabled: Boolean(baselineTs && currentTs && baselineTs !== currentTs),
    queryFn: () =>
      observabilityApi.getQuerysetHealthDiff({
        baseline_generated_at: baselineTs,
        current_generated_at: currentTs,
        max_hard_case_ids: 20,
      }),
  })

  const runs = runsQuery.data ?? null
  const diff = diffQuery.data ?? null
  const loadingRuns = runsQuery.isLoading || runsQuery.isFetching
  const loadingDiff = diffQuery.isLoading || diffQuery.isFetching

  useEffect(() => {
    if (!runsQuery.error) return
    toast.error(
      formatApiError(
        runsQuery.error,
        '加载检索集健康度历史失败（需要 owner/admin 权限）'
      )
    )
  }, [runsQuery.error])

  useEffect(() => {
    if (!diffQuery.error) return
    toast.error(formatApiError(diffQuery.error, '加载检索集健康度差异失败'))
  }, [diffQuery.error])

  useEffect(() => {
    const items = runsQuery.data?.items || []
    const latest = String(items?.[0]?.generated_at || '')
    const prev = String(items?.[1]?.generated_at || '')
    if (latest) setCurrentTs((p) => p || latest)
    if (latest || prev) setBaselineTs((p) => p || prev || latest)
  }, [runsQuery.data])

  const runItems = (runs?.items || []).map(querysetRunItem)
  const latest = runItems[0]
  const latestMetrics = isJsonObject(latest?.metrics) ? latest.metrics : {}
  const latestRisk = isJsonObject(latest?.risk) ? latest.risk : {}
  const latestFlags = Array.isArray(latest?.degradation_flags)
    ? latest?.degradation_flags
    : []

  const chartData = useMemo<QuerysetTrendRow[]>(() => {
    const ts = runs?.timeseries?.ts_ms || []
    const hit = runs?.timeseries?.hit_at_k || []
    const mrr = runs?.timeseries?.mrr || []
    const ndcg = runs?.timeseries?.ndcg_at_k || []
    const p95 = runs?.timeseries?.p95_latency_ms || []
    const miss = runs?.timeseries?.miss_rate || []
    const weak = runs?.timeseries?.weak_hit_rate || []
    const out: QuerysetTrendRow[] = []
    for (let i = 0; i < ts.length; i++) {
      const t = Number(ts[i] || 0)
      out.push({
        t,
        time: formatTs(t),
        dateLabel: formatDateTick(t),
        hit_at_k: hit[i] == null ? null : Number(hit[i] || 0),
        mrr: mrr[i] == null ? null : Number(mrr[i] || 0),
        ndcg_at_k: ndcg[i] == null ? null : Number(ndcg[i] || 0),
        p95_latency_ms: p95[i] == null ? null : Number(p95[i] || 0),
        miss_rate: miss[i] == null ? null : Number(miss[i] || 0),
        weak_hit_rate: weak[i] == null ? null : Number(weak[i] || 0),
      })
    }
    return out
  }, [runs?.timeseries])
  const chartDisplayData = chartData.length
    ? chartData
    : buildQuerysetTrendSkeleton()

  const diffMetricDeltas = useMemo(() => {
    const d = isJsonObject(diff?.diff) ? diff.diff : {}
    const deltas = d.metric_deltas
    return isJsonObject(deltas) ? deltas : {}
  }, [diff?.diff])
  const hasQualityChartData = chartData.some(
    (row) => row.hit_at_k != null || row.mrr != null || row.ndcg_at_k != null
  )
  const hasRiskChartData = chartData.some(
    (row) =>
      row.p95_latency_ms != null ||
      row.miss_rate != null ||
      row.weak_hit_rate != null
  )
  return (
    <div className={cn('space-y-2.5', embedded ? '' : 'p-5')}>
      {embedded ? (
        null
      ) : (
        <div className="flex items-start justify-between gap-2.5">
          <div>
            <h2 className="text-lg font-semibold text-foreground">
              检索集健康度
            </h2>
            <p className="text-sm text-muted-foreground mt-1">
              检索基准集健康度：趋势 + 差异 + 退化标记
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => runsQuery.refetch()}
            disabled={loadingRuns}
          >
            <RefreshCw
              className={cn(
                'h-4 w-4',
                loadingRuns && 'animate-spin motion-reduce:animate-none'
              )}
            />
            刷新
          </Button>
        </div>
      )}

      <Panel padding="sm" className="rounded-2xl border-border/60 bg-card shadow-none">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-sm font-semibold text-foreground">
              最新快照
            </div>
            {latest?.generated_at ? (
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                生成时间={String(latest.generated_at)}
              </div>
            ) : null}
          </div>
          <div className="text-xs text-muted-foreground">
            文件路径: <span className="font-mono">{runs?.path || '—'}</span>
          </div>
        </div>

        <div className="mt-2">
          <StatsGrid dense className="gap-2 xl:grid-cols-6">
            <StatCard
              dense
              icon={Target}
              label="命中率 Hit@K"
              value={fmtPercent(latestMetrics.hit_at_k, 1)}
              color="sky"
            />
            <StatCard
              dense
              icon={TrendingUp}
              label="MRR"
              value={fmtNum(latestMetrics.mrr, 3)}
              color="teal"
            />
            <StatCard
              dense
              icon={ChartLine}
              label="NDCG@K"
              value={fmtNum(latestMetrics.ndcg_at_k, 3)}
              color="teal"
            />
            <StatCard
              dense
              icon={Timer}
              label="P95 延迟"
              value={fmtMs(latestMetrics.p95_latency_ms)}
              color="amber"
            />
            <StatCard
              dense
              icon={SearchX}
              label="漏检率"
              value={fmtPercent(latestRisk.miss_rate, 1)}
              color="rose"
            />
            <StatCard
              dense
              icon={ShieldAlert}
              label="弱命中率"
              value={fmtPercent(latestRisk.weak_hit_rate, 1)}
              color="rose"
            />
          </StatsGrid>

          {latestFlags.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {latestFlags.slice(0, 12).map((f) => (
                <span
                  key={String(f)}
                  className="text-[11px] px-2 py-0.5 rounded-full bg-destructive/10 text-destructive border border-destructive/20"
                >
                  {String(f)}
                </span>
              ))}
            </div>
          ) : (
            <div className="mt-2 text-xs text-muted-foreground">无退化标记</div>
          )}
        </div>
      </Panel>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Panel
          padding="sm"
          className="rounded-2xl min-h-[205px] border-border/60 bg-card shadow-none"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold text-foreground">
              质量趋势
            </div>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>Hit@K / MRR / NDCG</span>
              <span className="inline-flex h-7 items-center rounded-lg border border-border px-2 text-[11px]">
                近 7 天
              </span>
            </div>
          </div>
          <div className="relative h-[145px]">
            <SafeResponsiveChart className="h-full" minHeight={145}>
              <LineChart data={chartDisplayData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="dateLabel" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} domain={[0, 1]} />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="hit_at_k"
                  stroke="hsl(var(--primary))"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="mrr"
                  stroke="hsl(var(--info))"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="ndcg_at_k"
                  stroke="hsl(var(--success))"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </SafeResponsiveChart>
            {hasQualityChartData ? null : <QuerysetChartEmptyState />}
          </div>
        </Panel>

        <Panel
          padding="sm"
          className="rounded-2xl min-h-[205px] border-border/60 bg-card shadow-none"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold text-foreground">
              延迟与风险趋势
            </div>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>P95 / 漏检 / 弱命中</span>
              <span className="inline-flex h-7 items-center rounded-lg border border-border px-2 text-[11px]">
                近 7 天
              </span>
            </div>
          </div>
          <div className="relative h-[145px]">
            <SafeResponsiveChart className="h-full" minHeight={145}>
              <LineChart data={chartDisplayData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="dateLabel" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="p95_latency_ms"
                  stroke="hsl(var(--warning))"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="miss_rate"
                  stroke="hsl(var(--destructive))"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="weak_hit_rate"
                  stroke="hsl(var(--info))"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </SafeResponsiveChart>
            {hasRiskChartData ? null : <QuerysetChartEmptyState />}
          </div>
        </Panel>
      </div>

      <Panel padding="sm" className="rounded-2xl border-border/60 bg-card shadow-none">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.72fr)]">
          <div>
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <GitCompare className="h-4 w-4 text-muted-foreground" />
                <div className="text-sm font-semibold text-foreground">
                  差异对比
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                {loadingDiff ? '计算中…' : diff?.diff ? '已加载' : '—'}
              </div>
            </div>

            <div className="mt-2 grid grid-cols-1 gap-2.5 lg:grid-cols-2">
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">
                  基线快照
                </div>
                <Select
                  value={baselineTs}
                  onValueChange={setBaselineTs}
                  disabled={!runs?.items?.length}
                >
                  <SelectTrigger className="h-9 rounded-xl">
                    <SelectValue placeholder="选择基线快照" />
                  </SelectTrigger>
                  <SelectContent>
                    {runItems.map((it) => (
                      <SelectItem
                        key={String(it.generated_at)}
                        value={String(it.generated_at)}
                      >
                        {String(it.generated_at)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">
                  当前快照
                </div>
                <Select
                  value={currentTs}
                  onValueChange={setCurrentTs}
                  disabled={!runs?.items?.length}
                >
                  <SelectTrigger className="h-9 rounded-xl">
                    <SelectValue placeholder="选择当前快照" />
                  </SelectTrigger>
                  <SelectContent>
                    {runItems.map((it) => (
                      <SelectItem
                        key={String(it.generated_at)}
                        value={String(it.generated_at)}
                      >
                        {String(it.generated_at)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {diffMetricDeltas && Object.keys(diffMetricDeltas).length ? (
              <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-1.5 text-xs">
                {QUERYSET_DELTA_METRICS.map((metric) => {
                  const value = diffMetricDeltas[metric.key]
                  const state = deltaState(value, metric.lowerIsBetter)
                  return (
                    <div
                      key={metric.key}
                      className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/30 px-3 py-2"
                    >
                      <span className="font-medium text-muted-foreground">
                        {metric.label}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="font-mono tabular-nums text-foreground/90">
                          {formatSignedDelta(value, metric.kind)}
                        </span>
                        <span
                          className={cn(
                            'rounded-full px-2 py-0.5 text-[10px] font-semibold',
                            state.className
                          )}
                        >
                          {state.label}
                        </span>
                      </span>
                    </div>
                  )
                })}
              </div>
            ) : null}
          </div>

          <div className="flex items-center gap-3 rounded-2xl border border-border bg-muted/40 px-4 py-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary ring-1 ring-primary/20">
              <Scale className="h-5 w-5" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">
                如何解读差异
              </div>
              <div className="mt-1 text-[12px] leading-5 text-muted-foreground">
                命中率、MRR、NDCG 为正表示提升；P95 延迟、漏检率、弱命中率为负表示改善。
                仅对相同评测配置的快照进行可比对。
              </div>
            </div>
          </div>
        </div>
      </Panel>

      <Panel padding="sm" className="rounded-2xl border-border/60 bg-card shadow-none">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-foreground">
              最近运行
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              展示最近 {runs?.items?.length ?? 0} 条（按时间倒序）
            </div>
          </div>
          {runItems.length > 30 ? (
            <Button
              variant="outline"
              size="sm"
              className="h-7 rounded-lg border-border px-2 text-[11px]"
              aria-expanded={showAllRuns}
              onClick={() => setShowAllRuns((showAll) => !showAll)}
            >
              {showAllRuns ? '收起' : '查看全部'}
            </Button>
          ) : null}
        </div>

        <div className="mt-2 max-h-[190px] overflow-auto">
          <table aria-label="检索集健康度指标列表" className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-xs text-muted-foreground">
                <th className="text-left py-2 pr-4">生成时间</th>
                <th className="text-left py-2 pr-4">状态</th>
                <th className="text-right py-2 pr-4">命中率</th>
                <th className="text-right py-2 pr-4">MRR</th>
                <th className="text-right py-2 pr-4">NDCG</th>
                <th className="text-right py-2 pr-4">p95(ms)</th>
                <th className="text-right py-2 pr-4">漏检率</th>
              </tr>
            </thead>
            <tbody>
              {runItems.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-4 text-center">
                    <div className="mx-auto flex w-fit flex-col items-center text-muted-foreground">
                      <div className="mb-1.5 flex h-8 w-8 items-center justify-center rounded-xl bg-muted text-muted-foreground/70">
                        <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                      </div>
                      <div className="text-sm font-medium text-muted-foreground">
                        暂无运行记录
                      </div>
                      <div className="mt-0.5 text-xs">
                        运行评测后结果将在此显示
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                (showAllRuns ? runItems : runItems.slice(0, 30)).map((it) => {
                  const m = isJsonObject(it.metrics) ? it.metrics : {}
                  const r = isJsonObject(it.risk) ? it.risk : {}
                  const st = String(it?.status || 'unknown')
                  const isDegraded = st === 'degraded'
                  const stLabel =
                    st === 'degraded'
                      ? '退化'
                      : st === 'healthy'
                        ? '健康'
                        : st === 'unknown'
                          ? '未知'
                          : st
                  return (
                    <tr
                      key={String(it.generated_at)}
                      className="border-b border-border/40"
                    >
                      <td className="py-1.5 pr-4 font-mono text-xs text-muted-foreground">
                        {String(it.generated_at || '')}
                      </td>
                      <td
                        className={cn(
                          'py-1.5 pr-4 text-xs',
                          isDegraded ? 'text-destructive' : 'text-success'
                        )}
                      >
                        {stLabel}
                      </td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">
                        {fmtPercent(m.hit_at_k, 1)}
                      </td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">
                        {fmtNum(m.mrr, 3)}
                      </td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">
                        {fmtNum(m.ndcg_at_k, 3)}
                      </td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">
                        {fmtNum(m.p95_latency_ms, 1)}
                      </td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">
                        {fmtPercent(r.miss_rate, 1)}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
