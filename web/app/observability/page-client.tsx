'use client'
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { AppFrame } from '@/components/app-frame';
import { OperationalWorkspace, WorkspaceMetrics, WorkspaceNotice, WorkspaceTableScroll, workspaceStyles as ws } from '@/components/ui/operational-workspace';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { observabilityApi } from '@/lib/api';
import { formatApiError } from '@/lib/api-errors';
import { toTrimmedPrimitiveString } from '@/lib/primitive-text';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { ObservabilityOpsPanel } from '@/components/observability/observability-ops-panel';
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar } from 'recharts';

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

type AnalyticsChartPoint = {
  t: number
  time: string
  requests: number
  zero_hit: number
  slow: number
  errors: number
  zero_hit_rate: number | null
  slow_rate: number | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function queryCountItem(value: unknown): { query_hash: string; count: number } {
  const item = isRecord(value) ? value : {}
  return {
    query_hash: toTrimmedPrimitiveString(item.query_hash),
    count: Number(item.count || 0),
  }
}

function slowQueryItem(value: unknown): {
  query_hash: string
  count: number
  max_elapsed_sec: number | null
} {
  const item = isRecord(value) ? value : {}
  return {
    query_hash: toTrimmedPrimitiveString(item.query_hash),
    count: Number(item.count || 0),
    max_elapsed_sec: item.max_elapsed_sec == null ? null : Number(item.max_elapsed_sec),
  }
}

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
  const [opsOpen, setOpsOpen] = useState(false)
  const [selectedQuery, setSelectedQuery] = useState<{ query: string; kind: string; count: number; elapsed: number | null } | null>(null)
  const [tab, setTab] = useState<'summary' | 'query_analytics'>('summary')
  const [windowMinutes, setWindowMinutes] = useState<number>(60)
  const [slowThresholdSec, setSlowThresholdSec] = useState<number>(2)

  const summaryQuery = useQuery({
    queryKey: ['observability', 'summary', windowMinutes],
    queryFn: () => observabilityApi.getRagMetricsSummary({ window_minutes: windowMinutes }),
    enabled: tab === 'summary',
  })

  const analyticsQuery = useQuery({
    queryKey: ['observability', 'query_analytics', windowMinutes, slowThresholdSec],
    queryFn: () =>
      observabilityApi.getRagQueryAnalytics({
        window_minutes: windowMinutes,
        slow_threshold_sec: slowThresholdSec,
      }),
    enabled: tab === 'query_analytics',
  })

  const summary = summaryQuery.data ?? null
  const analytics = analyticsQuery.data ?? null
  const loadingSummary = summaryQuery.isFetching
  const loadingAnalytics = analyticsQuery.isFetching
  const loading = tab === 'summary' ? loadingSummary : loadingAnalytics



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
    const out: AnalyticsChartPoint[] = []
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
    const raw: Record<string, number> = analytics?.error_kind_counts ?? {}
    const entries = Object.entries(raw).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    return entries.slice(0, 8)
  }, [analytics?.error_kind_counts])

  const topZeroHits = useMemo(() => {
    const raw = Array.isArray(analytics?.top_zero_hit_queries) ? analytics?.top_zero_hit_queries : []
    return raw
      .map(queryCountItem)
      .filter((it) => it.query_hash && Number.isFinite(it.count))
      .sort((a, b) => b.count - a.count)
      .slice(0, 20)
  }, [analytics?.top_zero_hit_queries])

  const topSlowQueries = useMemo(() => {
    const raw = Array.isArray(analytics?.top_slow_queries) ? analytics?.top_slow_queries : []
    return raw
      .map(slowQueryItem)
      .filter((it) => it.query_hash && Number.isFinite(it.count))
      .sort((a, b) => b.count - a.count)
      .slice(0, 20)
  }, [analytics?.top_slow_queries])


  const currentQuery = tab === 'summary' ? summaryQuery : analyticsQuery
  const queryRows = [
    ...topZeroHits.map(item => ({ query: item.query_hash, kind: '零命中', count: item.count, elapsed: null as number | null })),
    ...topSlowQueries.map(item => ({ query: item.query_hash, kind: '慢查询', count: item.count, elapsed: item.max_elapsed_sec })),
  ]
  return <AppFrame showBackground={false}><OperationalWorkspace title="可观测性" icon="diagnostics" context={`最近 ${windowMinutes} 分钟`} actions={<><Button variant="outline" onClick={() => setOpsOpen(true)}>运维操作</Button><Button variant="ghost" disabled={loading} onClick={() => { void currentQuery.refetch() }}>{loading ? '正在读取…' : '重新读取'}</Button></>} toolbar={<>
    <label className="flex items-center gap-2 text-[13px]">时间范围<select aria-label="观测时间范围" value={windowMinutes} onChange={event => { setSelectedQuery(null); setWindowMinutes(Number(event.target.value)) }} className="h-10 rounded-md border border-input bg-background px-3">{WINDOW_PRESETS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
    {tab === 'query_analytics' ? <label className="flex items-center gap-2 text-[13px]">慢查询阈值<select value={slowThresholdSec} onChange={event => { setSelectedQuery(null); setSlowThresholdSec(Number(event.target.value)) }} className="h-10 rounded-md border border-input bg-background px-3">{SLOW_PRESETS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label> : null}
  </>}>
    <Tabs value={tab} onValueChange={value => { setSelectedQuery(null); setTab(value as typeof tab) }}><TabsList className={ws.tabList}><TabsTrigger value="summary">指标总览</TabsTrigger><TabsTrigger value="query_analytics">查询分析</TabsTrigger></TabsList>
      {currentQuery.isError ? <WorkspaceNotice retry={() => { void currentQuery.refetch() }} pending={loading}>{formatApiError(currentQuery.error, '观测数据读取失败')}</WorkspaceNotice> : null}
      {loading && !currentQuery.data ? <p role="status" className="py-12 text-sm text-muted-foreground">正在读取当前时间范围的观测数据…</p> : null}
      <TabsContent value="summary" className={ws.tabContent}>
        {summary ? <>
          {!summary.enabled ? <div className={ws.empty}><h2>指标记录未开启</h2><p>当前接口未启用指标记录，可在设置中配置观测选项。</p><Button asChild variant="outline"><Link href="/settings">前往设置</Link></Button></div> : null}
          {summary.truncated ? <p role="status" className="border-b border-border py-3 text-[13px] text-muted-foreground">当前数据已截断；可缩短时间范围查看更完整的记录。</p> : null}
          <WorkspaceMetrics items={[{ label: '检索请求', value: summary.rag_trace_count }, { label: '检索平均耗时', value: fmtSec(summary.retrieval_avg_elapsed_sec), detail: `P95 ${fmtSec(summary.retrieval_p95_elapsed_sec)}` }, { label: '重排平均耗时', value: fmtSec(summary.rerank_avg_elapsed_sec), detail: `${summary.reranker_api_count} 次调用` }, { label: '平均引用数', value: summary.citations_avg_count?.toFixed(2) ?? '—' }]} />
          {summary.record_count === 0 ? <div className={ws.empty}><h2>当前时间范围暂无观测记录</h2><p>有检索请求后，可在这里查看耗时、引用和异常。</p></div> : <>
            {chartData.length ? <div className="grid gap-x-10 lg:grid-cols-2"><section className={ws.section}><h2 className={ws.sectionTitle}>请求量</h2>{chartData.length ? <SafeResponsiveChart className="mt-5 h-[260px]" minHeight={260}><BarChart data={chartData}><CartesianGrid strokeDasharray="3 3" opacity={0.2} /><XAxis dataKey="time" tick={{ fontSize: 12 }} /><YAxis tick={{ fontSize: 12 }} allowDecimals={false} /><Tooltip /><Bar name="检索" dataKey="rag_trace" fill="hsl(var(--primary))" /><Bar name="重排" dataKey="reranker_api" fill="hsl(var(--muted-foreground))" /></BarChart></SafeResponsiveChart> : <p className="py-8 text-sm text-muted-foreground">接口未返回分钟趋势</p>}</section>
            <section className={ws.section}><h2 className={ws.sectionTitle}>检索耗时趋势</h2>{chartData.length ? <SafeResponsiveChart className="mt-5 h-[260px]" minHeight={260}><LineChart data={chartData}><CartesianGrid strokeDasharray="3 3" opacity={0.2} /><XAxis dataKey="time" tick={{ fontSize: 12 }} /><YAxis tick={{ fontSize: 12 }} /><Tooltip /><Line name="平均耗时（秒）" dataKey="retrieval_avg_elapsed_sec" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} /></LineChart></SafeResponsiveChart> : <p className="py-8 text-sm text-muted-foreground">接口未返回耗时趋势</p>}</section></div> : <p className="border-b border-border py-4 text-[13px] text-muted-foreground">当前范围未返回分钟趋势</p>}
            <div className="grid gap-x-10 lg:grid-cols-3">{[['检索模式', Object.entries(summary.retrieval_mode_counts)], ['命中类型', Object.entries(summary.hit_type_counts)], ['错误记录', topErrors]].map(([title, entries]) => <section key={String(title)} className={ws.section}><h2 className={ws.sectionTitle}>{String(title)}</h2><dl className="mt-4 divide-y divide-border">{(entries as Array<[string, number]>).map(([name, count]) => <div className="flex items-center justify-between gap-3 py-3 text-[13px]" key={name}><dt className="break-words">{name}</dt><dd className="tabular-nums">{count}</dd></div>)}</dl>{!(entries as unknown[]).length ? <p className="py-5 text-sm text-muted-foreground">当前范围未记录此类数据</p> : null}</section>)}</div>
          </>}
          <details className="py-5 text-[13px]"><summary className="cursor-pointer font-medium">完整指标数据</summary><pre tabIndex={0} className="mt-4 max-h-96 overflow-auto bg-muted/30 p-4 text-xs leading-6">{JSON.stringify(summary, null, 2)}</pre></details>
        </> : !loadingSummary && !summaryQuery.isError ? <div className={ws.empty}><h2>暂无指标汇总</h2><p>重新读取当前时间范围后查看。</p></div> : null}
      </TabsContent>
      <TabsContent value="query_analytics" className={ws.tabContent}>
        {analytics ? <>
          {!analytics.enabled ? <p className="border-b border-border py-4 text-sm text-muted-foreground">查询指标记录未开启</p> : null}
          {analytics.truncated ? <p role="status" className="py-3 text-[13px] text-muted-foreground">当前查询分析已截断，可缩短时间范围。</p> : null}
          <WorkspaceMetrics items={[{ label: '检索请求', value: analytics.rag_trace_count }, { label: '查询标识', value: analytics.unique_query_hashes }, { label: '零命中率', value: fmtPercent(analytics.zero_hit_rate), detail: `${analytics.zero_hit_count} 次` }, { label: '慢查询比例', value: fmtPercent(analytics.slow_rate), detail: `${analytics.slow_count} 次` }, { label: 'P50 / P95 / P99', value: fmtSec(analytics.retrieval_p50_elapsed_sec), detail: `${fmtSec(analytics.retrieval_p95_elapsed_sec)} / ${fmtSec(analytics.retrieval_p99_elapsed_sec)}` }]} />
          <section className={ws.section}><h2 className={cn(ws.sectionTitle, 'mb-5')}>需要检查的查询</h2>{queryRows.length ? <WorkspaceTableScroll label="查询分析表格" stickyActions><table className={cn(ws.table, 'min-w-[620px]')} aria-label="查询分析"><thead><tr><th>查询标识</th><th>记录类型</th><th>次数</th><th>最长耗时</th><th>操作</th></tr></thead><tbody>{queryRows.map(row => <tr key={`${row.kind}:${row.query}`}><td className="max-w-[340px] truncate font-mono text-xs" title={row.query}>{row.query}</td><td className="whitespace-nowrap">{row.kind}</td><td className="tabular-nums">{row.count}</td><td className="tabular-nums">{fmtSec(row.elapsed)}</td><td><Button variant="ghost" aria-label={`查看统计 ${row.query}`} onClick={() => setSelectedQuery(row)}>查看统计</Button></td></tr>)}</tbody></table></WorkspaceTableScroll> : <p className="py-8 text-sm text-muted-foreground">当前窗口未返回零命中或慢查询记录</p>}</section>
          {analyticsChartData.length ? <div className="grid gap-x-10 lg:grid-cols-2"><section className={ws.section}><h2 className={ws.sectionTitle}>请求与异常趋势</h2><SafeResponsiveChart className="mt-5 h-[260px]" minHeight={260}><LineChart data={analyticsChartData}><CartesianGrid strokeDasharray="3 3" opacity={0.2} /><XAxis dataKey="time" tick={{ fontSize: 12 }} /><YAxis tick={{ fontSize: 12 }} allowDecimals={false} /><Tooltip /><Line name="请求" dataKey="requests" stroke="hsl(var(--primary))" dot={false} /><Line name="零命中" dataKey="zero_hit" stroke="hsl(var(--warning))" dot={false} /><Line name="慢查询" dataKey="slow" stroke="hsl(var(--muted-foreground))" dot={false} /><Line name="错误" dataKey="errors" stroke="hsl(var(--destructive))" dot={false} /></LineChart></SafeResponsiveChart></section><section className={ws.section}><h2 className={ws.sectionTitle}>零命中与慢查询比例</h2><SafeResponsiveChart className="mt-5 h-[260px]" minHeight={260}><LineChart data={analyticsChartData}><CartesianGrid strokeDasharray="3 3" opacity={0.2} /><XAxis dataKey="time" tick={{ fontSize: 12 }} /><YAxis tickFormatter={value => fmtPercent(Number(value), 0)} tick={{ fontSize: 12 }} /><Tooltip /><Line name="零命中比例" dataKey="zero_hit_rate" stroke="hsl(var(--warning))" dot={false} /><Line name="慢查询比例" dataKey="slow_rate" stroke="hsl(var(--primary))" dot={false} /></LineChart></SafeResponsiveChart></section></div> : null}
          <section className={ws.section}><h2 className={ws.sectionTitle}>错误类型</h2><dl className="mt-4 divide-y divide-border">{topErrorKinds.map(([name, count]) => <div key={name} className="flex justify-between gap-4 py-3 text-[13px]"><dt>{name}</dt><dd>{count}</dd></div>)}</dl>{!topErrorKinds.length ? <p className="py-5 text-sm text-muted-foreground">当前窗口未记录错误类型</p> : null}</section>
          <details className="py-5 text-[13px]"><summary className="cursor-pointer font-medium">完整查询分析数据</summary><pre tabIndex={0} className="mt-4 max-h-96 overflow-auto bg-muted/30 p-4 text-xs leading-6">{JSON.stringify(analytics, null, 2)}</pre></details>
        </> : !loadingAnalytics && !analyticsQuery.isError ? <div className={ws.empty}><h2>当前范围暂无查询分析</h2><p>有检索记录后可查看零命中、慢查询与错误。</p></div> : null}
      </TabsContent>
    </Tabs>
    <Dialog open={opsOpen} onOpenChange={setOpsOpen}><DialogContent className={cn(ws.dialog, ws.wideDialog)} aria-describedby={undefined}><DialogHeader className={ws.dialogHeader}><DialogTitle>观测运维操作</DialogTitle></DialogHeader><div className={ws.dialogBody}><ObservabilityOpsPanel initialWindowMinutes={windowMinutes} /></div><DialogFooter className={ws.dialogFooter}><Button variant="outline" onClick={() => setOpsOpen(false)}>完成</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={selectedQuery !== null} onOpenChange={open => { if (!open) setSelectedQuery(null) }}><DialogContent className={ws.dialog} aria-describedby={undefined}><DialogHeader className={ws.dialogHeader}><DialogTitle>查询统计</DialogTitle></DialogHeader><div className={ws.dialogBody}>{selectedQuery ? <dl className="space-y-5 text-sm leading-6"><div><dt className="text-muted-foreground">查询标识</dt><dd className="mt-1 break-all font-mono text-xs">{selectedQuery.query}</dd></div><div><dt className="text-muted-foreground">记录类型</dt><dd>{selectedQuery.kind}</dd></div><div><dt className="text-muted-foreground">次数</dt><dd>{selectedQuery.count}</dd></div><div><dt className="text-muted-foreground">最长耗时</dt><dd>{fmtSec(selectedQuery.elapsed)}</dd></div></dl> : null}</div><DialogFooter className={ws.dialogFooter}><Button variant="outline" onClick={() => { if (selectedQuery) void copyText(selectedQuery.query, '已复制查询标识') }}>复制标识</Button><Button onClick={() => setSelectedQuery(null)}>完成</Button></DialogFooter></DialogContent></Dialog>
  </OperationalWorkspace></AppFrame>
}
