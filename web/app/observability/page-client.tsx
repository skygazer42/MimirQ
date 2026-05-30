'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { observabilityApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import { toast } from 'sonner'
import { ObservabilityOpsPanel } from '@/components/observability/observability-ops-panel'
import {
  BarChart3,
  RefreshCw,
  AlertTriangle,
  Timer,
  Quote,
  Zap,
  Hash,
  SearchX,
  TriangleAlert,
  Copy,
} from 'lucide-react'
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

function formatTs(tsMs: number) {
  try {
    return new Date(tsMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return String(tsMs)
  }
}

function fmtPercent(v?: number | null, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(digits)}%`
}

function fmtSec(v?: number | null, digits = 3) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `${Number(v).toFixed(digits)}s`
}

function shortHash(value: string, opts?: { head?: number; tail?: number }) {
  const v = String(value || '').trim()
  if (!v) return ''
  const head = Math.max(1, Number(opts?.head ?? 8) || 8)
  const tail = Math.max(0, Number(opts?.tail ?? 4) || 4)
  if (v.length <= head + tail + 1) return v
  return `${v.slice(0, head)}...${v.slice(-tail)}`
}

async function copyText(text: string, okMsg: string) {
  const value = (text || '').trim()
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    toast.success(okMsg)
  } catch {
    toast.error('复制失败')
  }
}

export default function ObservabilityPage() {
  const [tab, setTab] = useState<'summary' | 'query_analytics'>('summary')
  const [windowMinutes, setWindowMinutes] = useState<number>(60)
  const [slowThresholdSec, setSlowThresholdSec] = useState<number>(2)

  const summaryQuery = useQuery({
    queryKey: ['observability', 'summary', windowMinutes],
    queryFn: () => observabilityApi.getRagMetricsSummary({ window_minutes: windowMinutes }),
    enabled: tab === 'summary',
    placeholderData: keepPreviousData,
  })

  const analyticsQuery = useQuery({
    queryKey: ['observability', 'query_analytics', windowMinutes, slowThresholdSec],
    queryFn: () =>
      observabilityApi.getRagQueryAnalytics({
        window_minutes: windowMinutes,
        slow_threshold_sec: slowThresholdSec,
      }),
    enabled: tab === 'query_analytics',
    placeholderData: keepPreviousData,
  })

  const summary = summaryQuery.data ?? null
  const analytics = analyticsQuery.data ?? null
  const loadingSummary = summaryQuery.isFetching
  const loadingAnalytics = analyticsQuery.isFetching
  const loading = tab === 'summary' ? loadingSummary : loadingAnalytics

  useEffect(() => {
    if (!summaryQuery.error) return
    toast.error(formatApiError(summaryQuery.error, '加载监控数据失败'))
  }, [summaryQuery.error, summaryQuery.errorUpdatedAt])

  useEffect(() => {
    if (!analyticsQuery.error) return
    toast.error(formatApiError(analyticsQuery.error, '加载 Query Analytics 失败'))
  }, [analyticsQuery.error, analyticsQuery.errorUpdatedAt])

  const chartData = useMemo(() => {
    if (!summary?.timeseries) return []
    const ts = summary.timeseries.ts_ms || []
    const ragTrace = summary.timeseries.rag_trace || []
    const rerankerApi = summary.timeseries.reranker_api || []
    const retrievalAvg = summary.timeseries.retrieval_avg_elapsed_sec || []
    const out = []
    for (let i = 0; i < ts.length; i++) {
      const t = Number(ts[i] || 0)
      out.push({
        t,
        time: formatTs(t),
        rag_trace: Number(ragTrace[i] || 0),
        reranker_api: Number(rerankerApi[i] || 0),
        retrieval_avg_elapsed_sec:
          retrievalAvg[i] == null ? null : Number(retrievalAvg[i] || 0),
      })
    }
    return out
  }, [summary?.timeseries])

  const topErrors = useMemo(() => {
    const raw: Record<string, number> = summary?.error_counts ?? {}
    const entries = Object.entries(raw).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    return entries.slice(0, 8)
  }, [summary?.error_counts])

  const analyticsChartData = useMemo(() => {
    if (!analytics?.timeseries) return []
    const ts = analytics.timeseries.ts_ms || []
    const requests = analytics.timeseries.requests || []
    const zeroHit = analytics.timeseries.zero_hit || []
    const slow = analytics.timeseries.slow || []
    const errors = analytics.timeseries.errors || []
    const out: Array<Record<string, any>> = []
    for (let i = 0; i < ts.length; i++) {
      const t = Number(ts[i] || 0)
      const req = Number(requests[i] || 0)
      const zh = Number(zeroHit[i] || 0)
      const sl = Number(slow[i] || 0)
      const er = Number(errors[i] || 0)
      out.push({
        t,
        time: formatTs(t),
        requests: req,
        zero_hit: zh,
        slow: sl,
        errors: er,
        zero_hit_rate: req > 0 ? zh / req : null,
        slow_rate: req > 0 ? sl / req : null,
      })
    }
    return out
  }, [analytics?.timeseries])

  const topErrorKinds = useMemo(() => {
    const raw: Record<string, number> = (analytics?.error_kind_counts as any) ?? {}
    const entries = Object.entries(raw).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    return entries.slice(0, 8)
  }, [analytics?.error_kind_counts])

  const topZeroHits = useMemo(() => {
    const raw = Array.isArray(analytics?.top_zero_hit_queries) ? analytics?.top_zero_hit_queries : []
    return raw
      .map((it: any) => ({ query_hash: String(it?.query_hash || ''), count: Number(it?.count || 0) }))
      .filter((it) => it.query_hash && Number.isFinite(it.count))
      .sort((a, b) => b.count - a.count)
      .slice(0, 20)
  }, [analytics?.top_zero_hit_queries])

  const topSlowQueries = useMemo(() => {
    const raw = Array.isArray(analytics?.top_slow_queries) ? analytics?.top_slow_queries : []
    return raw
      .map((it: any) => ({
        query_hash: String(it?.query_hash || ''),
        count: Number(it?.count || 0),
        max_elapsed_sec: it?.max_elapsed_sec == null ? null : Number(it.max_elapsed_sec),
      }))
      .filter((it) => it.query_hash && Number.isFinite(it.count))
      .sort((a, b) => b.count - a.count)
      .slice(0, 20)
  }, [analytics?.top_slow_queries])

  return (
    <AppFrame>
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <PageScaffold
          title="监控面板"
          description="检索 / 重排 / 引用的全链路指标（来自 metrics JSONL）"
          icon={BarChart3}
          iconColor="text-sky-600 dark:text-sky-400"
          size="7xl"
          actions={
            <div className="flex items-center gap-2">
              <div className="w-[140px]">
                <Select
                  value={String(windowMinutes)}
                  onValueChange={(v) => {
                    const next = Number.parseInt(v, 10)
                    setWindowMinutes(next)
                  }}
                >
                  <SelectTrigger className="h-9 rounded-xl">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WINDOW_PRESETS.map((p) => (
                      <SelectItem key={p.value} value={String(p.value)}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {tab === 'query_analytics' ? (
                <div className="w-[110px]">
                  <Select
                    value={String(slowThresholdSec)}
                    onValueChange={(v) => {
                      const next = Number(v)
                      setSlowThresholdSec(next)
                    }}
                  >
                    <SelectTrigger className="h-9 rounded-xl">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SLOW_PRESETS.map((p) => (
                        <SelectItem key={p.value} value={String(p.value)}>
                          {p.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}
              <Button
                size="sm"
                variant="outline"
                className="gap-2 rounded-xl"
                onClick={() => {
                  if (tab === 'summary') summaryQuery.refetch()
                  else analyticsQuery.refetch()
                }}
                disabled={loading}
              >
                <RefreshCw className={cn('size-4', loading && 'animate-spin motion-reduce:animate-none')} />
                刷新
              </Button>
              <Link
                href="/settings"
                className="inline-flex h-9 items-center justify-center rounded-xl border border-input bg-background px-3 text-xs font-medium shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                去设置开启/配置
              </Link>
            </div>
          }
        >
          <ObservabilityOpsPanel />

          <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)} className="space-y-4">
            <TabsList className="rounded-xl bg-muted/40">
              <TabsTrigger value="summary" className="rounded-lg text-xs">
                Summary
              </TabsTrigger>
              <TabsTrigger value="query_analytics" className="rounded-lg text-xs">
                Query Analytics
              </TabsTrigger>
            </TabsList>

            <TabsContent value="summary">
              {summary ? (
                <div className="space-y-6">
                  {!summary.enabled && (
                    <Alert className="mt-4">
                      <AlertTriangle className="size-4" />
                      <AlertTitle>Metrics 日志未开启</AlertTitle>
                      <AlertDescription>
                        当前 ENABLE_METRICS_LOG=false。你仍可能看到少量历史数据，但建议到“设置 → 观测与调试”开启。
                      </AlertDescription>
                    </Alert>
                  )}

                  {summary.truncated && (
                    <Alert className="mt-4">
                      <AlertTriangle className="size-4" />
                      <AlertTitle>数据可能不完整</AlertTitle>
                      <AlertDescription>
                        本次查询仅读取 metrics 文件尾部（max_bytes）。若窗口内数据量过大，请缩短时间窗口或调整后端 max_bytes。
                      </AlertDescription>
                    </Alert>
                  )}

                  <StatsGrid className="mt-2">
                    <StatCard
                      icon={Zap}
                      label="RAG Trace"
                      value={summary.rag_trace_count}
                      subValue={`${summary.window_minutes} 分钟`}
                      color="sky"
                    />
                    <StatCard
                      icon={Timer}
                      label="检索平均耗时"
                      value={summary.retrieval_avg_elapsed_sec == null ? '-' : `${summary.retrieval_avg_elapsed_sec.toFixed(3)}s`}
                      subValue={summary.retrieval_p95_elapsed_sec == null ? undefined : `p95 ${summary.retrieval_p95_elapsed_sec.toFixed(3)}s`}
                      color="teal"
                    />
                    <StatCard
                      icon={Timer}
                      label="重排平均耗时"
                      value={summary.rerank_avg_elapsed_sec == null ? '-' : `${summary.rerank_avg_elapsed_sec.toFixed(3)}s`}
                      subValue={`${summary.reranker_api_count} 次 reranker_api`}
                      color="amber"
                    />
                    <StatCard
                      icon={Quote}
                      label="平均引用数"
                      value={summary.citations_avg_count == null ? '-' : summary.citations_avg_count.toFixed(2)}
                      subValue="每次回答"
                      color="green"
                    />
                  </StatsGrid>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <Panel padding="lg" className="min-h-[320px]">
                      <div className="flex items-center justify-between mb-4">
                        <div className="text-sm font-semibold text-foreground">请求量（rag_trace）</div>
                        <div className="text-xs text-muted-foreground">按分钟聚合</div>
                      </div>
                      <SafeResponsiveChart className="h-[260px]" minHeight={260}>
                        <BarChart data={chartData}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                          <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                          <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                          <Tooltip />
                          <Bar dataKey="rag_trace" fill="hsl(var(--primary))" opacity={0.85} />
                        </BarChart>
                      </SafeResponsiveChart>
                    </Panel>

                    <Panel padding="lg" className="min-h-[320px]">
                      <div className="flex items-center justify-between mb-4">
                        <div className="text-sm font-semibold text-foreground">检索平均耗时</div>
                        <div className="text-xs text-muted-foreground">每分钟均值</div>
                      </div>
                      <SafeResponsiveChart className="h-[260px]" minHeight={260}>
                        <LineChart data={chartData}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                          <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                          <YAxis tick={{ fontSize: 10 }} />
                          <Tooltip />
                          <Line
                            type="monotone"
                            dataKey="retrieval_avg_elapsed_sec"
                            stroke="hsl(var(--info))"
                            strokeWidth={2}
                            dot={false}
                          />
                        </LineChart>
                      </SafeResponsiveChart>
                    </Panel>
                  </div>

                  <Panel padding="lg" variant="muted">
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                      <div>
                        <div className="text-sm font-semibold text-foreground mb-2">检索模式分布</div>
                        <pre className="text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">
                          {JSON.stringify(summary.retrieval_mode_counts || {}, null, 2)}
                        </pre>
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-foreground mb-2">命中类型分布</div>
                        <pre className="text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">
                          {JSON.stringify(summary.hit_type_counts || {}, null, 2)}
                        </pre>
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-foreground mb-2">Top Errors</div>
                        {topErrors.length ? (
                          <div className="space-y-2">
                            {topErrors.map(([k, v]) => (
                              <div key={k} className="flex items-center justify-between gap-3 text-xs">
                                <span className="font-mono text-muted-foreground truncate" title={k}>
                                  {k}
                                </span>
                                <span className="text-muted-foreground tabular-nums">{v}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-xs text-muted-foreground">无错误</div>
                        )}
                      </div>
                    </div>
                  </Panel>
                </div>
              ) : (
                <Alert variant="destructive" className="mt-4">
                  <AlertTriangle className="size-4" />
                  <AlertTitle>无法加载监控数据</AlertTitle>
                  <AlertDescription>
                    请确认你是 owner/admin，并且后端已更新到包含 /api/v1/observability 的版本。
                  </AlertDescription>
                </Alert>
              )}
            </TabsContent>

            <TabsContent value="query_analytics">
              {(() => {
    if (loadingAnalytics && !analytics) {
        return (<div className="space-y-6">
                  <StatsGrid className="mt-2">
                    {['stat-1', 'stat-2', 'stat-3', 'stat-4', 'stat-5'].map((key) => (<div key={key} className="rounded-xl border border-border bg-muted/20 px-4 py-3">
                        <Skeleton className="h-3 w-28"/>
                        <Skeleton className="mt-2 h-6 w-24"/>
                        <Skeleton className="mt-2 h-3 w-20"/>
                      </div>))}
                  </StatsGrid>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <Panel padding="lg" className="min-h-[320px]">
                      <Skeleton className="h-4 w-48"/>
                      <Skeleton className="mt-3 h-[260px] w-full"/>
                    </Panel>
                    <Panel padding="lg" className="min-h-[320px]">
                      <Skeleton className="h-4 w-56"/>
                      <Skeleton className="mt-3 h-[260px] w-full"/>
                    </Panel>
                  </div>
                </div>);
    }
    else if (analytics) {
            if (analytics.enabled) {
                if (analytics.rag_trace_count <= 0) {
                    return (<EmptyState title="暂无 Query Analytics 数据" description="提示：只有走到检索链路（rag_trace）时才会计入统计；可尝试先发起一次检索请求再刷新。" icon={TriangleAlert} iconClassName="text-sky-600 dark:text-sky-400">
                  <Button variant="outline" className="rounded-xl" onClick={() => analyticsQuery.refetch()} disabled={loadingAnalytics}>
                    <RefreshCw className={cn('size-4', loadingAnalytics && 'animate-spin motion-reduce:animate-none')}/>
                    刷新
                  </Button>
                </EmptyState>);
                }
                else {
                    return (<div className="space-y-6">
                  {analytics.truncated ? (<Alert className="mt-4">
                      <AlertTriangle className="size-4"/>
                      <AlertTitle>数据可能不完整</AlertTitle>
                      <AlertDescription>
                        本次查询仅读取 metrics 文件尾部（max_bytes）。若窗口内数据量过大，请缩短时间窗口或调整后端 max_bytes。
                      </AlertDescription>
                    </Alert>) : null}

                  <StatsGrid className="mt-2">
                    <StatCard icon={Zap} label="Requests" value={analytics.rag_trace_count} subValue={`${analytics.window_minutes} 分钟`} color="sky"/>
                    <StatCard icon={Hash} label="Unique query_hash" value={analytics.unique_query_hashes} subValue="16-char stable hash" color="teal"/>
                    <StatCard icon={SearchX} label="Zero-hit rate" value={fmtPercent(analytics.zero_hit_rate)} subValue={`${analytics.zero_hit_count} 次（citations=0）`} color="amber"/>
                    <StatCard icon={Timer} label="Slow rate" value={fmtPercent(analytics.slow_rate)} subValue={`${analytics.slow_count} 次（≥ ${analytics.slow_threshold_sec}s）`} color="orange"/>
                    <StatCard icon={Timer} label="Retrieval p95 / p99" value={`${fmtSec(analytics.retrieval_p95_elapsed_sec, 3)} · ${fmtSec(analytics.retrieval_p99_elapsed_sec, 3)}`} subValue={`p50 ${fmtSec(analytics.retrieval_p50_elapsed_sec, 3)}`} color="green"/>
                  </StatsGrid>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <Panel padding="lg" className="min-h-[320px]">
                      <div className="flex items-center justify-between mb-4">
                        <div className="text-sm font-semibold text-foreground">Zero-hit / Slow（rate）</div>
                        <div className="text-xs text-muted-foreground">按分钟聚合</div>
                      </div>
                      <SafeResponsiveChart className="h-[260px]" minHeight={260}>
                        <LineChart data={analyticsChartData}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.2}/>
                          <XAxis dataKey="time" tick={{ fontSize: 10 }}/>
                          <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(Number(v || 0) * 100)}%`} domain={[0, 1]}/>
                          <Tooltip formatter={(v: any, name: any) => {
                            if (name === 'zero-hit rate' || name === 'slow rate')
                                return [fmtPercent(Number(v), 2), name];
                            return [v, name];
                        }}/>
                          <Line type="monotone" dataKey="zero_hit_rate" name="zero-hit rate" stroke="hsl(var(--warning))" strokeWidth={2} dot={false}/>
                          <Line type="monotone" dataKey="slow_rate" name="slow rate" stroke="hsl(var(--info))" strokeWidth={2} dot={false}/>
                        </LineChart>
                      </SafeResponsiveChart>
                    </Panel>

                    <Panel padding="lg" className="min-h-[320px]">
                      <div className="flex items-center justify-between mb-4">
                        <div className="text-sm font-semibold text-foreground">Requests / zero-hit / slow / errors（count）</div>
                        <div className="text-xs text-muted-foreground">按分钟聚合</div>
                      </div>
                      <SafeResponsiveChart className="h-[260px]" minHeight={260}>
                        <LineChart data={analyticsChartData}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.2}/>
                          <XAxis dataKey="time" tick={{ fontSize: 10 }}/>
                          <YAxis tick={{ fontSize: 10 }} allowDecimals={false}/>
                          <Tooltip />
                          <Line type="monotone" dataKey="requests" name="requests" stroke="hsl(var(--muted-foreground))" strokeWidth={2} dot={false}/>
                          <Line type="monotone" dataKey="zero_hit" name="zero-hit" stroke="hsl(var(--warning))" strokeWidth={2} dot={false}/>
                          <Line type="monotone" dataKey="slow" name="slow" stroke="hsl(var(--info))" strokeWidth={2} dot={false}/>
                          <Line type="monotone" dataKey="errors" name="errors" stroke="hsl(var(--destructive))" strokeWidth={2} dot={false}/>
                        </LineChart>
                      </SafeResponsiveChart>
                    </Panel>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <Panel padding="lg" className="overflow-hidden">
                      <div className="flex items-center justify-between gap-3 mb-3">
                        <div className="text-sm font-semibold text-foreground">Top Zero-hit query_hash</div>
                        <div className="text-xs text-muted-foreground tabular-nums">top {topZeroHits.length}</div>
                      </div>
                      {topZeroHits.length ? (<div className="divide-y divide-border/60 rounded-xl border border-border/60 overflow-hidden">
                          {topZeroHits.map((it) => (<div key={it.query_hash} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                              <div className="min-w-0">
                                <div className="font-mono text-muted-foreground truncate" title={it.query_hash}>
                                  {shortHash(it.query_hash, { head: 10, tail: 6 })}
                                </div>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <div className="tabular-nums text-muted-foreground">{it.count}</div>
                                <Button size="icon" variant="ghost" className="size-8 rounded-lg" aria-label="复制 query_hash" onClick={() => detachPromise(copyText(it.query_hash, '已复制 query_hash'))}>
                                  <Copy className="size-4"/>
                                </Button>
                              </div>
                            </div>))}
                        </div>) : (<div className="text-xs text-muted-foreground">暂无 zero-hit（citations=0）记录</div>)}
                    </Panel>

                    <Panel padding="lg" className="overflow-hidden">
                      <div className="flex items-center justify-between gap-3 mb-3">
                        <div className="text-sm font-semibold text-foreground">Top Slow query_hash</div>
                        <div className="text-xs text-muted-foreground tabular-nums">top {topSlowQueries.length}</div>
                      </div>
                      {topSlowQueries.length ? (<div className="divide-y divide-border/60 rounded-xl border border-border/60 overflow-hidden">
                          {topSlowQueries.map((it) => (<div key={it.query_hash} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                              <div className="min-w-0">
                                <div className="font-mono text-muted-foreground truncate" title={it.query_hash}>
                                  {shortHash(it.query_hash, { head: 10, tail: 6 })}
                                </div>
                                <div className="mt-0.5 text-[11px] text-muted-foreground/80 tabular-nums">
                                  max {it.max_elapsed_sec != null && Number.isFinite(Number(it.max_elapsed_sec)) ? `${Number(it.max_elapsed_sec).toFixed(3)}s` : '—'}
                                </div>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <div className="tabular-nums text-muted-foreground">{it.count}</div>
                                <Button size="icon" variant="ghost" className="size-8 rounded-lg" aria-label="复制 query_hash" onClick={() => detachPromise(copyText(it.query_hash, '已复制 query_hash'))}>
                                  <Copy className="size-4"/>
                                </Button>
                              </div>
                            </div>))}
                        </div>) : (<div className="text-xs text-muted-foreground">暂无 slow（≥ threshold）记录</div>)}
                    </Panel>

                    <Panel padding="lg" variant="muted">
                      <div className="text-sm font-semibold text-foreground mb-3">Top Error Kinds</div>
                      {topErrorKinds.length ? (<div className="space-y-2">
                          {topErrorKinds.map(([k, v]) => (<div key={k} className="flex items-center justify-between gap-3 text-xs">
                              <span className="font-mono text-muted-foreground truncate" title={k}>
                                {k}
                              </span>
                              <span className="text-muted-foreground tabular-nums">{v}</span>
                            </div>))}
                        </div>) : (<div className="text-xs text-muted-foreground">无错误</div>)}
                    </Panel>
                  </div>
                </div>);
                }
            }
            else {
                return (<Alert className="mt-4">
                  <AlertTriangle className="size-4"/>
                  <AlertTitle>Metrics 日志未开启</AlertTitle>
                  <AlertDescription>
                    当前 ENABLE_METRICS_LOG=false。Query Analytics 只基于 rag_trace 指标聚合。
                  </AlertDescription>
                </Alert>);
            }
        }
        else {
            return (<Alert variant="destructive" className="mt-4">
                  <AlertTriangle className="size-4"/>
                  <AlertTitle>无法加载 Query Analytics</AlertTitle>
                  <AlertDescription>
                    请确认你是 owner/admin，并且后端已更新到包含 /api/v1/observability/rag-metrics/query-analytics 的版本。
                  </AlertDescription>
                </Alert>);
        }
})()}
            </TabsContent>
          </Tabs>
        </PageScaffold>
      </div>
    </AppFrame>
  )
}
