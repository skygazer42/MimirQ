'use client'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import Link from 'next/link'
import { ChevronDown } from '@/components/icons'
import { AppFrame } from '@/components/app-frame'
import {
  OperationalWorkspace,
  WorkspaceMetrics,
  WorkspaceNotice,
  WorkspaceTableScroll,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { observabilityApi } from '@/lib/api/observability'
import { formatApiError } from '@/lib/api-errors'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import { ObservabilityOpsPanel } from '@/components/observability/observability-ops-panel'
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar } from 'recharts'

const WINDOW_PRESETS = [
  { label: '15 分钟', value: 15 },
  { label: '1 小时', value: 60 },
  { label: '4 小时', value: 240 },
  { label: '24 小时', value: 1440 },
]

const SLOW_PRESETS = [
  { label: '≥ 1s', value: 1 },
  { label: '≥ 2s', value: 2 },
  { label: '≥ 5s', value: 5 },
]

type QueryRow = {
  queryHash: string
  kind: string
  count: number
  maxElapsedSec: number | null
}

function formatBucketTime(timestampMs: number) {
  return new Date(timestampMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatPercent(value: number | null, digits = 1) {
  return value === null ? '—' : `${(value * 100).toFixed(digits)}%`
}

function formatSeconds(value: number | null | undefined) {
  return value == null ? '—' : `${value.toFixed(3)}s`
}

async function copyQueryHash(queryHash: string) {
  try {
    await navigator.clipboard.writeText(queryHash)
    toast.success('已复制查询标识')
  } catch {
    toast.error('复制失败')
  }
}

export default function ObservabilityPage() {
  const [opsOpen, setOpsOpen] = useState(false)
  const [selectedQuery, setSelectedQuery] = useState<QueryRow | null>(null)
  const [tab, setTab] = useState<'summary' | 'query_analytics'>('summary')
  const [windowMinutes, setWindowMinutes] = useState<number>(60)
  const [slowThresholdSec, setSlowThresholdSec] = useState<number>(2)

  const summaryQuery = useQuery({
    queryKey: ['observability', 'summary', windowMinutes],
    queryFn: ({ signal }) => observabilityApi.getRagMetricsSummary({ window_minutes: windowMinutes }, { signal }),
    enabled: tab === 'summary',
  })

  const analyticsQuery = useQuery({
    queryKey: ['observability', 'query_analytics', windowMinutes, slowThresholdSec],
    queryFn: ({ signal }) =>
      observabilityApi.getRagQueryAnalytics(
        { window_minutes: windowMinutes, slow_threshold_sec: slowThresholdSec },
        { signal },
      ),
    enabled: tab === 'query_analytics',
  })

  const summary = summaryQuery.data
  const analytics = analyticsQuery.data
  const currentQuery = tab === 'summary' ? summaryQuery : analyticsQuery
  const loading = currentQuery.isFetching

  const chartData = useMemo(() => {
    const timeseries = summary?.timeseries
    if (timeseries?.ts_ms === undefined) return []
    return timeseries.ts_ms.map((timestampMs, index) => ({
      time: formatBucketTime(timestampMs),
      rag_trace: timeseries.rag_trace[index],
      reranker_api: timeseries.reranker_api[index],
      retrieval_avg_elapsed_sec: timeseries.retrieval_avg_elapsed_sec[index],
    }))
  }, [summary?.timeseries])

  const topErrors = useMemo(
    () =>
      Object.entries(summary?.error_counts ?? {})
        .sort((left, right) => right[1] - left[1])
        .slice(0, 8),
    [summary?.error_counts],
  )

  const analyticsChartData = useMemo(() => {
    const timeseries = analytics?.timeseries
    if (timeseries?.ts_ms === undefined) return []
    return timeseries.ts_ms.map((timestampMs, index) => {
      const requests = timeseries.requests[index]
      const zeroHits = timeseries.zero_hit[index]
      const slowRequests = timeseries.slow[index]
      return {
        time: formatBucketTime(timestampMs),
        requests,
        zero_hit: zeroHits,
        slow: slowRequests,
        errors: timeseries.errors[index],
        zero_hit_rate: requests > 0 ? zeroHits / requests : null,
        slow_rate: requests > 0 ? slowRequests / requests : null,
      }
    })
  }, [analytics?.timeseries])

  const topErrorKinds = useMemo(
    () =>
      Object.entries(analytics?.error_kind_counts ?? {})
        .sort((left, right) => right[1] - left[1])
        .slice(0, 8),
    [analytics?.error_kind_counts],
  )

  const queryRows: QueryRow[] =
    analytics === undefined
      ? []
      : [
          ...analytics.top_zero_hit_queries.map((item) => ({
            queryHash: item.query_hash,
            kind: '零命中',
            count: item.count,
            maxElapsedSec: null,
          })),
          ...analytics.top_slow_queries.map((item) => ({
            queryHash: item.query_hash,
            kind: '慢查询',
            count: item.count,
            maxElapsedSec: item.max_elapsed_sec,
          })),
        ]

  return (
    <AppFrame showBackground={false}>
      <OperationalWorkspace
        title="可观测性"
        icon="diagnostics"
        context={`最近 ${windowMinutes} 分钟`}
        actions={
          <>
            <Button variant="outline" onClick={() => setOpsOpen(true)}>
              运维操作
            </Button>
            <Button
              variant="ghost"
              disabled={loading}
              onClick={() => {
                void currentQuery.refetch()
              }}
            >
              {loading ? '正在读取…' : '重新读取'}
            </Button>
          </>
        }
        toolbar={
          <>
            <div className="flex items-center gap-2 text-[13px]">
              <span>时间范围</span>
              <Select
                value={String(windowMinutes)}
                onValueChange={(value) => {
                  setSelectedQuery(null)
                  setWindowMinutes(Number(value))
                }}
              >
                <SelectTrigger aria-label="观测时间范围" className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WINDOW_PRESETS.map((item) => (
                    <SelectItem key={item.value} value={String(item.value)}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {tab === 'query_analytics' ? (
              <div className="flex items-center gap-2 text-[13px]">
                <span>慢查询阈值</span>
                <Select
                  value={String(slowThresholdSec)}
                  onValueChange={(value) => {
                    setSelectedQuery(null)
                    setSlowThresholdSec(Number(value))
                  }}
                >
                  <SelectTrigger aria-label="慢查询阈值" className="w-28">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SLOW_PRESETS.map((item) => (
                      <SelectItem key={item.value} value={String(item.value)}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
          </>
        }
      >
        <Tabs
          value={tab}
          onValueChange={(value) => {
            if (value !== 'summary' && value !== 'query_analytics') return
            setSelectedQuery(null)
            setTab(value)
          }}
        >
          <TabsList className={ws.tabList}>
            <TabsTrigger value="summary">指标总览</TabsTrigger>
            <TabsTrigger value="query_analytics">查询分析</TabsTrigger>
          </TabsList>
          {currentQuery.isError ? (
            <WorkspaceNotice
              placement={currentQuery.data !== undefined ? 'floating' : 'inline'}
              tone={currentQuery.data !== undefined ? 'warning' : 'error'}
              title="观测数据读取失败"
              error={currentQuery.error}
              fallbackMessage="观测数据读取失败"
              retry={() => {
                void currentQuery.refetch()
              }}
              pending={loading}
            />
          ) : null}
          {currentQuery.isPending ? (
            <p role="status" className="py-12 text-sm text-muted-foreground">
              {currentQuery.isPaused ? '等待网络连接以读取观测数据…' : '正在读取当前时间范围的观测数据…'}
            </p>
          ) : null}
          <TabsContent value="summary" className={ws.tabContent}>
            {summary ? (
              <>
                {!summary.enabled && summary.record_count > 0 ? (
                  <p role="status" className="border-b border-border py-3 text-[13px] text-muted-foreground">
                    指标记录未开启，以下展示当前范围内的历史记录。
                    <Link href="/settings" className="underline underline-offset-4">
                      前往设置
                    </Link>
                  </p>
                ) : !summary.enabled ? (
                  <div className={ws.empty}>
                    <h2>指标记录未开启</h2>
                    <p>当前接口未启用指标记录，可在设置中配置观测选项。</p>
                    <Button asChild variant="outline">
                      <Link href="/settings">前往设置</Link>
                    </Button>
                  </div>
                ) : null}
                {summary.truncated ? (
                  <p role="status" className="border-b border-border py-3 text-[13px] text-muted-foreground">
                    当前数据已截断；可缩短时间范围查看更完整的记录。
                  </p>
                ) : null}
                {summary.enabled || summary.record_count > 0 ? (
                  <WorkspaceMetrics
                    items={[
                      { label: '检索请求', value: summary.rag_trace_count },
                      {
                        label: '检索平均耗时',
                        value: formatSeconds(summary.retrieval_avg_elapsed_sec),
                        detail: `P95 ${formatSeconds(summary.retrieval_p95_elapsed_sec)}`,
                      },
                      {
                        label: '重排平均耗时',
                        value: formatSeconds(summary.rerank_avg_elapsed_sec),
                        detail:
                          summary.rerank_avg_elapsed_sec == null
                            ? summary.reranker_api_count === 0
                              ? '暂无调用'
                              : `${summary.reranker_api_count} 次调用 · 暂未上报耗时`
                            : `${summary.reranker_api_count} 次调用`,
                      },
                      { label: '平均引用数', value: summary.citations_avg_count?.toFixed(2) ?? '—' },
                    ]}
                  />
                ) : null}
                {summary.record_count === 0 ? (
                  summary.enabled ? (
                    <div className={ws.empty}>
                      <h2>当前时间范围暂无观测记录</h2>
                      <p>有检索请求后，可在这里查看耗时、引用和异常。</p>
                    </div>
                  ) : null
                ) : (
                  <>
                    {chartData.length > 0 ? (
                      <div className="grid gap-x-10 lg:grid-cols-2">
                        <section className={ws.section}>
                          <h2 className={ws.sectionTitle}>请求量</h2>
                          <SafeResponsiveChart className="mt-5 h-[260px]" minHeight={260}>
                            <BarChart data={chartData}>
                              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                              <XAxis dataKey="time" tick={{ fontSize: 12 }} />
                              <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                              <Tooltip />
                              <Bar name="检索" dataKey="rag_trace" fill="hsl(var(--primary))" />
                              <Bar name="重排" dataKey="reranker_api" fill="hsl(var(--muted-foreground))" />
                            </BarChart>
                          </SafeResponsiveChart>
                        </section>
                        <section className={ws.section}>
                          <h2 className={ws.sectionTitle}>检索耗时趋势</h2>
                          <SafeResponsiveChart className="mt-5 h-[260px]" minHeight={260}>
                            <LineChart data={chartData}>
                              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                              <XAxis dataKey="time" tick={{ fontSize: 12 }} />
                              <YAxis tick={{ fontSize: 12 }} />
                              <Tooltip />
                              <Line
                                name="平均耗时（秒）"
                                dataKey="retrieval_avg_elapsed_sec"
                                stroke="hsl(var(--primary))"
                                strokeWidth={2}
                                dot={false}
                              />
                            </LineChart>
                          </SafeResponsiveChart>
                        </section>
                      </div>
                    ) : (
                      <p className="border-b border-border py-4 text-[13px] text-muted-foreground">
                        当前范围未返回分钟趋势
                      </p>
                    )}
                    <div className="grid gap-x-10 lg:grid-cols-3">
                      {(
                        [
                          ['检索模式', Object.entries(summary.retrieval_mode_counts)],
                          ['命中类型', Object.entries(summary.hit_type_counts)],
                          ['错误记录', topErrors],
                        ] as const
                      ).map(([title, entries]) => (
                        <section key={title} className={ws.section}>
                          <h2 className={ws.sectionTitle}>{title}</h2>
                          <dl className="mt-4 divide-y divide-border">
                            {entries.map(([name, count]) => (
                              <div className="flex items-center justify-between gap-3 py-3 text-[13px]" key={name}>
                                <dt className="break-words">{name}</dt>
                                <dd className="tabular-nums">{count}</dd>
                              </div>
                            ))}
                          </dl>
                          {entries.length === 0 ? (
                            <p className="py-5 text-sm text-muted-foreground">当前范围未记录此类数据</p>
                          ) : null}
                        </section>
                      ))}
                    </div>
                  </>
                )}
                <details className="group py-5 text-[13px]">
                  <summary className="flex cursor-pointer list-none items-center gap-2 font-medium [&::-webkit-details-marker]:hidden">
                    <ChevronDown
                      className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                      aria-hidden="true"
                    />
                    完整指标数据
                  </summary>
                  <pre tabIndex={0} className="mt-4 max-h-96 overflow-auto bg-muted/30 p-4 text-xs leading-6">
                    {JSON.stringify(summary, null, 2)}
                  </pre>
                </details>
              </>
            ) : null}
          </TabsContent>
          <TabsContent value="query_analytics" className={ws.tabContent}>
            {analytics ? (
              <>
                {!analytics.enabled && analytics.record_count > 0 ? (
                  <p role="status" className="border-b border-border py-3 text-[13px] text-muted-foreground">
                    查询指标记录未开启，以下展示当前范围内的历史记录。
                    <Link href="/settings" className="underline underline-offset-4">
                      前往设置
                    </Link>
                  </p>
                ) : !analytics.enabled ? (
                  <div className={ws.empty}>
                    <h2>查询指标记录未开启</h2>
                    <p>可在设置中启用指标记录，以查看查询命中、耗时和异常。</p>
                    <Button asChild variant="outline">
                      <Link href="/settings">前往设置</Link>
                    </Button>
                  </div>
                ) : null}
                {analytics.enabled || analytics.record_count > 0 ? (
                  <>
                    {analytics.truncated ? (
                      <p role="status" className="py-3 text-[13px] text-muted-foreground">
                        当前查询分析已截断，可缩短时间范围。
                      </p>
                    ) : null}
                    <WorkspaceMetrics
                      items={[
                        { label: '检索请求', value: analytics.rag_trace_count },
                        { label: '查询标识', value: analytics.unique_query_hashes },
                        {
                          label: '零命中率',
                          value: formatPercent(analytics.zero_hit_rate),
                          detail: `${analytics.zero_hit_count} 次`,
                        },
                        {
                          label: '慢查询比例',
                          value: formatPercent(analytics.slow_rate),
                          detail: `${analytics.slow_count} 次`,
                        },
                        {
                          label: 'P50 / P95 / P99',
                          value: formatSeconds(analytics.retrieval_p50_elapsed_sec),
                          detail: `${formatSeconds(analytics.retrieval_p95_elapsed_sec)} / ${formatSeconds(analytics.retrieval_p99_elapsed_sec)}`,
                        },
                      ]}
                    />
                    <section className={ws.section}>
                      <h2 className={cn(ws.sectionTitle, 'mb-5')}>需要检查的查询</h2>
                      {queryRows.length ? (
                        <WorkspaceTableScroll label="查询分析表格" stickyActions>
                          <table className={cn(ws.table, 'min-w-[620px]')} aria-label="查询分析">
                            <thead>
                              <tr>
                                <th>查询标识</th>
                                <th>记录类型</th>
                                <th>次数</th>
                                <th>最长耗时</th>
                                <th>操作</th>
                              </tr>
                            </thead>
                            <tbody>
                              {queryRows.map((row) => (
                                <tr key={`${row.kind}:${row.queryHash}`}>
                                  <td className="max-w-[340px] truncate font-mono text-xs" title={row.queryHash}>
                                    {row.queryHash}
                                  </td>
                                  <td className="whitespace-nowrap">{row.kind}</td>
                                  <td className="tabular-nums">{row.count}</td>
                                  <td className="tabular-nums">{formatSeconds(row.maxElapsedSec)}</td>
                                  <td>
                                    <Button
                                      variant="ghost"
                                      aria-label={`查看统计 ${row.queryHash}`}
                                      onClick={() => setSelectedQuery(row)}
                                    >
                                      查看统计
                                    </Button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </WorkspaceTableScroll>
                      ) : (
                        <p className="py-8 text-sm text-muted-foreground">当前窗口未返回零命中或慢查询记录</p>
                      )}
                    </section>
                    {analyticsChartData.length ? (
                      <div className="grid gap-x-10 lg:grid-cols-2">
                        <section className={ws.section}>
                          <h2 className={ws.sectionTitle}>请求与异常趋势</h2>
                          <SafeResponsiveChart className="mt-5 h-[260px]" minHeight={260}>
                            <LineChart data={analyticsChartData}>
                              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                              <XAxis dataKey="time" tick={{ fontSize: 12 }} />
                              <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                              <Tooltip />
                              <Line name="请求" dataKey="requests" stroke="hsl(var(--primary))" dot={false} />
                              <Line name="零命中" dataKey="zero_hit" stroke="hsl(var(--warning))" dot={false} />
                              <Line name="慢查询" dataKey="slow" stroke="hsl(var(--muted-foreground))" dot={false} />
                              <Line name="错误" dataKey="errors" stroke="hsl(var(--destructive))" dot={false} />
                            </LineChart>
                          </SafeResponsiveChart>
                        </section>
                        <section className={ws.section}>
                          <h2 className={ws.sectionTitle}>零命中与慢查询比例</h2>
                          <SafeResponsiveChart className="mt-5 h-[260px]" minHeight={260}>
                            <LineChart data={analyticsChartData}>
                              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                              <XAxis dataKey="time" tick={{ fontSize: 12 }} />
                              <YAxis
                                tickFormatter={(value: number) => formatPercent(value, 0)}
                                tick={{ fontSize: 12 }}
                              />
                              <Tooltip />
                              <Line
                                name="零命中比例"
                                dataKey="zero_hit_rate"
                                stroke="hsl(var(--warning))"
                                dot={false}
                              />
                              <Line name="慢查询比例" dataKey="slow_rate" stroke="hsl(var(--primary))" dot={false} />
                            </LineChart>
                          </SafeResponsiveChart>
                        </section>
                      </div>
                    ) : null}
                    <section className={ws.section}>
                      <h2 className={ws.sectionTitle}>错误类型</h2>
                      <dl className="mt-4 divide-y divide-border">
                        {topErrorKinds.map(([name, count]) => (
                          <div key={name} className="flex justify-between gap-4 py-3 text-[13px]">
                            <dt>{name}</dt>
                            <dd>{count}</dd>
                          </div>
                        ))}
                      </dl>
                      {!topErrorKinds.length ? (
                        <p className="py-5 text-sm text-muted-foreground">当前窗口未记录错误类型</p>
                      ) : null}
                    </section>
                  </>
                ) : null}
                <details className="py-5 text-[13px]">
                  <summary className="cursor-pointer font-medium">完整查询分析数据</summary>
                  <pre tabIndex={0} className="mt-4 max-h-96 overflow-auto bg-muted/30 p-4 text-xs leading-6">
                    {JSON.stringify(analytics, null, 2)}
                  </pre>
                </details>
              </>
            ) : null}
          </TabsContent>
        </Tabs>
        <Dialog open={opsOpen} onOpenChange={setOpsOpen}>
          <DialogContent className={cn(ws.dialog, ws.wideDialog)} aria-describedby={undefined}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle>观测运维操作</DialogTitle>
            </DialogHeader>
            <div className={ws.dialogBody}>
              <ObservabilityOpsPanel initialWindowMinutes={windowMinutes} />
            </div>
            <DialogFooter className={ws.dialogFooter}>
              <Button variant="outline" onClick={() => setOpsOpen(false)}>
                完成
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <Dialog
          open={selectedQuery !== null}
          onOpenChange={(open) => {
            if (!open) setSelectedQuery(null)
          }}
        >
          <DialogContent className={ws.dialog} aria-describedby={undefined}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle>查询统计</DialogTitle>
            </DialogHeader>
            <div className={ws.dialogBody}>
              {selectedQuery ? (
                <dl className="space-y-5 text-sm leading-6">
                  <div>
                    <dt className="text-muted-foreground">查询标识</dt>
                    <dd className="mt-1 break-all font-mono text-xs">{selectedQuery.queryHash}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">记录类型</dt>
                    <dd>{selectedQuery.kind}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">次数</dt>
                    <dd>{selectedQuery.count}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">最长耗时</dt>
                    <dd>{formatSeconds(selectedQuery.maxElapsedSec)}</dd>
                  </div>
                </dl>
              ) : null}
            </div>
            <DialogFooter className={ws.dialogFooter}>
              {selectedQuery && (
                <Button variant="outline" onClick={() => void copyQueryHash(selectedQuery.queryHash)}>
                  复制标识
                </Button>
              )}
              <Button onClick={() => setSelectedQuery(null)}>完成</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </OperationalWorkspace>
    </AppFrame>
  )
}
