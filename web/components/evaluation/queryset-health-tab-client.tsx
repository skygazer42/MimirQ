'use client'

import { useMemo, useState } from 'react'
import { skipToken, useQuery } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import { GitCompare, Scale, ChartLine, ShieldAlert } from '@/components/icons'

import { Button } from '@/components/ui/button'
import { WorkspaceNotice, WorkspaceNoticeStack } from '@/components/ui/operational-workspace'
import { PageLoading } from '@/components/ui/page-loading'
import { Panel } from '@/components/ui/panel'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import evaluationStyles from './evaluation-panels.module.css'
import { observabilityApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

const QUERYSET_DELTA_METRICS = [
  {
    key: 'hit_at_k',
    label: '命中率（Hit@K）',
    kind: 'percent',
    lowerIsBetter: false,
  },
  { key: 'mrr', label: 'MRR', kind: 'number', lowerIsBetter: false },
  {
    key: 'ndcg_at_k',
    label: 'NDCG@K',
    kind: 'number',
    lowerIsBetter: false,
  },
  {
    key: 'p95_latency_ms',
    label: 'P95 延迟',
    kind: 'ms',
    lowerIsBetter: true,
  },
  {
    key: 'miss_rate',
    label: '漏检率',
    kind: 'percent',
    lowerIsBetter: true,
  },
  {
    key: 'weak_hit_rate',
    label: '弱命中率',
    kind: 'percent',
    lowerIsBetter: true,
  },
] as const
const SNAPSHOT_COMPARISON_FIELDS = ['profile_hash', 'fixture_hash', 'policy_hash', 'retrieval_mode'] as const

function formatDateTick(tsMs: number) {
  return new Date(tsMs).toLocaleDateString([], { month: '2-digit', day: '2-digit' }).replace('/', '-')
}

function formatPercent(value: number | null | undefined) {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`
}

function formatNumber(value: number | null | undefined, digits: number) {
  return value == null ? '—' : value.toFixed(digits)
}

function formatMilliseconds(value: number | null | undefined) {
  return value == null ? '—' : `${Math.round(value)}ms`
}

function formatSignedDelta(value: number, kind: (typeof QUERYSET_DELTA_METRICS)[number]['kind']) {
  const sign = value > 0 ? '+' : ''
  if (kind === 'percent') return `${sign}${(value * 100).toFixed(1)}%`
  if (kind === 'ms') return `${sign}${value.toFixed(1)}ms`
  return `${sign}${value.toFixed(3)}`
}

function deltaState(value: number | null, lowerIsBetter: boolean) {
  if (value === null || value === 0) {
    return { label: value === null ? '缺少读数' : '持平', className: 'bg-muted text-muted-foreground' }
  }
  const improved = lowerIsBetter ? value < 0 : value > 0
  if (improved) {
    return { label: '改善', className: 'bg-success/10 text-success' }
  }
  return { label: '退化', className: 'bg-destructive/10 text-destructive' }
}

function QuerysetChartEmptyState() {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <div className="px-4 py-3 text-center">
        <div className="mx-auto mb-2 flex h-7 w-7 items-center justify-center text-muted-foreground">
          <ChartLine className="h-4 w-4" aria-hidden="true" />
        </div>
        <div className="text-[14px] font-medium text-foreground">暂无趋势数据</div>
      </div>
    </div>
  )
}

export function QuerysetHealthTab() {
  const [baselineTs, setBaselineTs] = useState<string>()
  const [currentTs, setCurrentTs] = useState<string>()
  const [showAllRuns, setShowAllRuns] = useState(false)
  const runsParams = { limit: 90 }
  const runsQuery = useQuery({
    queryKey: queryKeys.evaluations.querysetHealthRuns(runsParams),
    queryFn: ({ signal }) => observabilityApi.getQuerysetHealthRuns(runsParams, { signal }),
  })
  const runs = runsQuery.data
  const timestamps = runs?.items.flatMap(({ generated_at }) => {
    if (typeof generated_at !== 'string' || generated_at.length === 0 || generated_at !== generated_at.trim()) {
      return []
    }
    return [generated_at]
  })
  const runTimestamps = [...new Set(timestamps)]
  const baselineGeneratedAt = baselineTs ?? runTimestamps[1] ?? runTimestamps[0]
  const currentGeneratedAt = currentTs ?? runTimestamps[0]
  const baselineAvailable = baselineGeneratedAt !== undefined && runTimestamps.includes(baselineGeneratedAt)
  const currentAvailable = currentGeneratedAt !== undefined && runTimestamps.includes(currentGeneratedAt)
  const baselineIndex = runs?.items.findIndex((run) => run.generated_at === baselineGeneratedAt) ?? -1
  const currentIndex = runs?.items.findIndex((run) => run.generated_at === currentGeneratedAt) ?? -1
  const baselineRun = runs?.items[baselineIndex]
  const currentRun = runs?.items[currentIndex]
  const hasSnapshotPair =
    baselineAvailable &&
    currentAvailable &&
    baselineIndex !== currentIndex &&
    baselineRun !== undefined &&
    currentRun !== undefined
  const comparableSnapshots =
    hasSnapshotPair &&
    SNAPSHOT_COMPARISON_FIELDS.every((field) => {
      const value = baselineRun[field]
      return typeof value === 'string' && value.trim() !== '' && value === currentRun[field]
    }) &&
    typeof baselineRun.top_k === 'number' &&
    baselineRun.top_k > 0 &&
    baselineRun.top_k === currentRun.top_k
  const diffParams = comparableSnapshots
    ? { baseline_generated_at: baselineGeneratedAt, current_generated_at: currentGeneratedAt, max_hard_case_ids: 20 }
    : undefined
  const diffQuery = useQuery({
    queryKey: queryKeys.evaluations.querysetHealthDiff(diffParams),
    queryFn: diffParams ? ({ signal }) => observabilityApi.getQuerysetHealthDiff(diffParams, { signal }) : skipToken,
  })

  const timeseries = runs?.timeseries
  const chartData = useMemo(() => {
    if (!timeseries) return []
    return timeseries.ts_ms.map((timestamp, index) => ({
      dateLabel: formatDateTick(timestamp),
      hit_at_k: timeseries.hit_at_k[index],
      mrr: timeseries.mrr[index],
      ndcg_at_k: timeseries.ndcg_at_k[index],
      p95_latency_ms: timeseries.p95_latency_ms[index],
      miss_rate: timeseries.miss_rate[index],
      weak_hit_rate: timeseries.weak_hit_rate[index],
    }))
  }, [timeseries])

  const runsError = runsQuery.isError ? (
    <WorkspaceNotice retry={() => void runsQuery.refetch()} pending={runsQuery.isFetching}>
      {formatApiError(runsQuery.error, '加载检索集健康度历史失败')}
    </WorkspaceNotice>
  ) : null
  if (!runs) {
    return <div className={evaluationStyles.health}>{runsError ?? <PageLoading message="正在读取健康度历史…" />}</div>
  }

  const runItems = runs.items
  const latest = runItems[0]
  // The API lists snapshots newest first and reports the same window's trend oldest first.
  const latestMetrics = chartData.at(-1)
  const degradationFlags = latest?.degradation_flags
  const latestFlags =
    Array.isArray(degradationFlags) && degradationFlags.every((flag: unknown) => typeof flag === 'string')
      ? degradationFlags
      : undefined
  const diffMetricDeltas = diffQuery.data?.diff.metric_deltas
  const baselineMetrics = chartData.at(-1 - baselineIndex)
  const currentMetrics = chartData.at(-1 - currentIndex)
  const hasQualityChartData = chartData.some((row) => row.hit_at_k != null || row.mrr != null || row.ndcg_at_k != null)
  const hasRiskChartData = chartData.some(
    (row) => row.p95_latency_ms != null || row.miss_rate != null || row.weak_hit_rate != null,
  )
  return (
    <div className={evaluationStyles.health}>
      {runsQuery.isError || diffQuery.isError ? (
        <WorkspaceNoticeStack ariaLabel="检索集健康度提示">
          {runsQuery.isError ? (
            <WorkspaceNotice
              tone="warning"
              title="检索集健康度历史更新失败"
              error={runsQuery.error}
              fallbackMessage="加载检索集健康度历史失败"
              retry={() => void runsQuery.refetch()}
              pending={runsQuery.isFetching}
            />
          ) : null}
          {diffQuery.isError ? (
            <WorkspaceNotice
              tone="warning"
              title="检索集健康度差异读取失败"
              error={diffQuery.error}
              fallbackMessage="加载检索集健康度差异失败"
              retry={() => void diffQuery.refetch()}
              pending={diffQuery.isFetching}
            />
          ) : null}
        </WorkspaceNoticeStack>
      ) : null}

      <Panel variant="seamless" padding="none" className={evaluationStyles.healthSection}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-sm font-semibold text-foreground">最新快照</div>
            {typeof latest?.generated_at === 'string' ? (
              <div className="mt-0.5 text-[13px] text-muted-foreground">生成时间={latest.generated_at}</div>
            ) : null}
          </div>
          <div className="text-xs text-muted-foreground">
            {runs.path && (
              <details>
                <summary>数据源</summary>
                <span className="break-all">{runs.path}</span>
              </details>
            )}
          </div>
        </div>

        <div className="mt-2">
          <dl className={evaluationStyles.healthMetrics}>
            {[
              ['命中率 Hit@K', formatPercent(latestMetrics?.hit_at_k)],
              ['MRR', formatNumber(latestMetrics?.mrr, 3)],
              ['NDCG@K', formatNumber(latestMetrics?.ndcg_at_k, 3)],
              ['P95 延迟', formatMilliseconds(latestMetrics?.p95_latency_ms)],
              ['漏检率', formatPercent(latestMetrics?.miss_rate)],
              ['弱命中率', formatPercent(latestMetrics?.weak_hit_rate)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>
                  <span className={evaluationStyles.metricIcon} aria-hidden="true">
                    <ChartLine />
                  </span>
                  {label}
                </dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>

          {latestFlags && latestFlags.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {latestFlags.map((flag) => (
                <span
                  key={flag}
                  className="text-[13px] px-2 py-0.5 rounded-full bg-destructive/10 text-destructive border border-destructive/20"
                >
                  {flag}
                </span>
              ))}
            </div>
          ) : null}
          {!latest && <div className="mt-2 text-[13px] text-muted-foreground">暂无快照</div>}
          {latestFlags?.length === 0 && <div className="mt-2 text-[13px] text-muted-foreground">无退化标记</div>}
        </div>
      </Panel>

      <div className={evaluationStyles.healthCharts}>
        <Panel padding="sm" variant="seamless" className={evaluationStyles.healthChart}>
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold text-foreground">质量趋势</div>
            <span className="text-xs text-muted-foreground">Hit@K / MRR / NDCG</span>
          </div>
          <div className="relative h-[145px]">
            {hasQualityChartData ? (
              <SafeResponsiveChart className="h-full" minHeight={145}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="dateLabel" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} domain={[0, 1]} />
                  <Tooltip />
                  <Line type="monotone" dataKey="hit_at_k" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="mrr" stroke="hsl(var(--info))" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="ndcg_at_k" stroke="hsl(var(--success))" strokeWidth={2} dot={false} />
                </LineChart>
              </SafeResponsiveChart>
            ) : (
              <QuerysetChartEmptyState />
            )}
          </div>
        </Panel>

        <Panel padding="sm" variant="seamless" className={evaluationStyles.healthChart}>
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold text-foreground">延迟与风险趋势</div>
            <span className="text-xs text-muted-foreground">P95 / 漏检 / 弱命中</span>
          </div>
          <div className="relative h-[145px]">
            {hasRiskChartData ? (
              <SafeResponsiveChart className="h-full" minHeight={145}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="dateLabel" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
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
                  <Line type="monotone" dataKey="weak_hit_rate" stroke="hsl(var(--info))" strokeWidth={2} dot={false} />
                </LineChart>
              </SafeResponsiveChart>
            ) : (
              <QuerysetChartEmptyState />
            )}
          </div>
        </Panel>
      </div>

      <Panel variant="seamless" padding="none" className={evaluationStyles.healthSection}>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.72fr)]">
          <div>
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <GitCompare className="h-4 w-4 text-muted-foreground" />
                <div className="text-sm font-semibold text-foreground">差异对比</div>
              </div>
              <div className="text-xs text-muted-foreground">{diffQuery.isFetching ? '计算中…' : null}</div>
            </div>

            <div className="mt-2 grid grid-cols-1 gap-2.5 lg:grid-cols-2">
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">基线快照</div>
                <Select
                  value={baselineAvailable ? baselineGeneratedAt : ''}
                  onValueChange={setBaselineTs}
                  disabled={runTimestamps.length === 0}
                >
                  <SelectTrigger aria-label="基线快照">
                    <SelectValue placeholder="选择基线快照" />
                  </SelectTrigger>
                  <SelectContent>
                    {runTimestamps.map((timestamp) => (
                      <SelectItem key={timestamp} value={timestamp}>
                        {timestamp}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">当前快照</div>
                <Select
                  value={currentAvailable ? currentGeneratedAt : ''}
                  onValueChange={setCurrentTs}
                  disabled={runTimestamps.length === 0}
                >
                  <SelectTrigger aria-label="当前快照">
                    <SelectValue placeholder="选择当前快照" />
                  </SelectTrigger>
                  <SelectContent>
                    {runTimestamps.map((timestamp) => (
                      <SelectItem key={timestamp} value={timestamp}>
                        {timestamp}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {hasSnapshotPair && !comparableSnapshots && (
              <p role="status" className="mt-2 text-sm text-muted-foreground">
                快照缺少可核对的信息，或评测配置、策略、样本集不同，无法比较。
              </p>
            )}
            {diffMetricDeltas && (
              <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-1.5 text-xs">
                {QUERYSET_DELTA_METRICS.map((metric) => {
                  const value =
                    baselineMetrics?.[metric.key] == null || currentMetrics?.[metric.key] == null
                      ? null
                      : diffMetricDeltas[`${metric.key}_delta`]
                  const state = deltaState(value, metric.lowerIsBetter)
                  return (
                    <div
                      key={metric.key}
                      className="flex items-center justify-between gap-3 rounded-lg border border-info/15 bg-info/[0.025] px-3 py-2"
                    >
                      <span className="font-medium text-muted-foreground">{metric.label}</span>
                      <span className="flex items-center gap-2">
                        <span className="font-mono tabular-nums text-foreground/90">
                          {value === null ? '—' : formatSignedDelta(value, metric.kind)}
                        </span>
                        <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-semibold', state.className)}>
                          {state.label}
                        </span>
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div className="flex items-start gap-3 py-3">
            <span className="inline-flex shrink-0 pt-0.5 text-muted-foreground">
              <Scale className="size-4" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">如何解读差异</div>
              <div className="mt-1 text-[13px] leading-5 text-muted-foreground">
                命中率、MRR、NDCG 为正表示提升；P95 延迟、漏检率、弱命中率为负表示改善。
                仅对相同评测配置的快照进行可比对。
              </div>
            </div>
          </div>
        </div>
      </Panel>

      <Panel variant="seamless" padding="none" className={evaluationStyles.healthSection}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-foreground">最近运行</div>
            <div className="text-xs text-muted-foreground mt-0.5">最近 {runItems.length} 条（按时间倒序）</div>
          </div>
          {runItems.length > 30 ? (
            <Button
              variant="outline"
              size="sm"
              className="px-2 text-[13px]"
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
                      <div className="mb-1.5 flex h-8 w-8 items-center justify-center rounded-xl bg-info/[0.04] text-info/70">
                        <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                      </div>
                      <div className="text-sm font-medium text-muted-foreground">暂无运行记录</div>
                      <div className="mt-0.5 text-xs">运行评测后结果将在此显示</div>
                    </div>
                  </td>
                </tr>
              ) : (
                (showAllRuns ? runItems : runItems.slice(0, 30)).map((run, index) => {
                  const metrics = chartData.at(-1 - index)
                  const timestamp = typeof run.generated_at === 'string' ? run.generated_at : '—'
                  const status = run.status
                  let statusLabel = '未知'
                  if (status === 'degraded') {
                    statusLabel = '退化'
                  } else if (status === 'healthy') {
                    statusLabel = '健康'
                  } else if (typeof status === 'string' && status !== 'unknown') {
                    statusLabel = status
                  }
                  return (
                    <tr key={`${timestamp}:${index}`} className="border-b border-border/40">
                      <td className="py-1.5 pr-4 font-mono text-xs text-muted-foreground">{timestamp}</td>
                      <td className="py-1.5 pr-4 text-xs">
                        <span className={evaluationStyles.runStatus} data-status={status}>
                          {statusLabel}
                        </span>
                      </td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">{formatPercent(metrics?.hit_at_k)}</td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">{formatNumber(metrics?.mrr, 3)}</td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">{formatNumber(metrics?.ndcg_at_k, 3)}</td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">
                        {formatNumber(metrics?.p95_latency_ms, 1)}
                      </td>
                      <td className="py-1.5 pr-4 text-right tabular-nums">{formatPercent(metrics?.miss_rate)}</td>
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
