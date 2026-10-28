'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Code, Copy, Loader2, RefreshCw } from '@/components/icons'
import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { datasetApi, usageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { cn } from '@/lib/utils'
import { QuotaDetails, QuotaSummary } from './quota-summary'
import { UsageTable } from './usage-table'
import { averageRetrievalMs, buildQuotaReadings, buildUsageRows, dateTime, formatCount, formatDuration, formatWindow, parseUsageLocation, type UsageView } from './usage-model'
import styles from './usage.module.css'

const WINDOW_DAYS = [7, 14, 30] as const

export default function UsagePage() {
  return <TenantPermissionGate permission={TENANT_PERMISSIONS.USAGE_READ} pageName="用量／配额"><UsageOverview /></TenantPermissionGate>
}

function UsageOverview() {
  const [scope, setScope] = useState(() => parseUsageLocation(typeof window === 'undefined' ? '' : window.location.search))
  const { windowDays, view, page } = scope
  useEffect(() => {
    const restoreScope = () => setScope(parseUsageLocation(window.location.search))
    window.addEventListener('popstate', restoreScope)
    return () => window.removeEventListener('popstate', restoreScope)
  }, [])
  function updateScope(next: Partial<typeof scope>) {
    const updated = { ...scope, ...next }
    setScope(updated)
    const url = new URL(window.location.href)
    url.searchParams.set('window_days', String(updated.windowDays))
    if (updated.view === 'attribution') url.searchParams.delete('view')
    else url.searchParams.set('view', updated.view)
    if (updated.page === 1) url.searchParams.delete('page')
    else url.searchParams.set('page', String(updated.page))
    window.history.replaceState(window.history.state, '', url)
  }
  const refreshingRef = useRef(false)
  const params = useMemo(() => ({ window_days: windowDays }), [windowDays])
  const summaryQuery = useQuery({ queryKey: queryKeys.usage.summary(params), queryFn: () => usageApi.getChatTokenUsageSummary(params) })
  const costQuery = useQuery({ queryKey: queryKeys.usage.cost(params), queryFn: () => usageApi.getChatCostUsageSummary(params) })
  const chatQuotaQuery = useQuery({ queryKey: queryKeys.usage.quota, queryFn: () => usageApi.getChatTokenQuotaStatus(), staleTime: 60_000 })
  const tenantQuotaQuery = useQuery({ queryKey: queryKeys.usage.tenantQuotaSummary, queryFn: () => usageApi.getTenantQuotaSummary(), staleTime: 60_000 })
  const labelsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive({ purpose: 'usage-labels' }),
    queryFn: async () => {
      const datasets = await datasetApi.listAll()
      return Object.fromEntries(datasets.filter(d => d.id).map(d => [String(d.id), String(d.name || '').trim() || String(d.id)]))
    }, staleTime: 300_000,
  })
  const summary = summaryQuery.data, cost = costQuery.data
  const rows = useMemo(() => buildUsageRows(summary, cost, labelsQuery.data ?? {}, labelsQuery.isError ? 'error' : labelsQuery.isSuccess ? 'ready' : 'pending'), [summary, cost, labelsQuery.data, labelsQuery.isError, labelsQuery.isSuccess])
  const costRows = useMemo(() => rows.filter(row => row.cost).sort((a, b) => (b.cost?.llm_total_tokens ?? 0) - (a.cost?.llm_total_tokens ?? 0)), [rows])
  const quotas = useMemo(() => buildQuotaReadings(chatQuotaQuery.data, tenantQuotaQuery.data), [chatQuotaQuery.data, tenantQuotaQuery.data])
  const quotaPending = { chat: chatQuotaQuery.isPending, tenant: tenantQuotaQuery.isPending }
  const queries = [summaryQuery, costQuery, chatQuotaQuery, tenantQuotaQuery, labelsQuery]
  const refreshing = queries.some(q => q.isFetching)
  const windowSource = summary ?? cost
  const rawQuota = useMemo(() => JSON.stringify({ chat_token_quota: chatQuotaQuery.data ?? null, tenant_quotas: tenantQuotaQuery.data ?? null }, null, 2), [chatQuotaQuery.data, tenantQuotaQuery.data])
  const hasQuotaData = Boolean(chatQuotaQuery.data || tenantQuotaQuery.data)
  const errors = [
    { label: '助手用量', query: summaryQuery }, { label: '链路资源', query: costQuery },
    { label: '聊天配额', query: chatQuotaQuery }, { label: '租户资源配额', query: tenantQuotaQuery },
    { label: '数据集名称', query: labelsQuery },
  ].filter(item => item.query.isError)
  const tablePending = view === 'resources' ? costQuery.isPending : summaryQuery.isPending || costQuery.isPending
  const tableFailed = view === 'resources' ? costQuery.isError : summaryQuery.isError || costQuery.isError
  const updatedAt = Math.max(summaryQuery.dataUpdatedAt, costQuery.dataUpdatedAt)

  async function refresh() {
    if (refreshingRef.current) return
    refreshingRef.current = true
    try {
      const results = await Promise.all(queries.map(query => query.refetch({ cancelRefetch: false })))
      if (results.every(result => !result.isError)) toast.success('用量已刷新')
    } finally { refreshingRef.current = false }
  }

  async function copyQuota() {
    try { await navigator.clipboard.writeText(rawQuota); toast.success('配额已复制') }
    catch { toast.error('复制失败，请重试') }
  }

  return <AppFrame><section className={styles.workspace} data-usage-overview="a">
    <Dialog>
      <header className={styles.header}>
        <div className={styles.heading}><PageTitleIcon name="usage-quota" /><h1>用量／配额</h1></div>
        <div className={styles.headerActions}>
          <DialogTrigger asChild><Button variant="ghost" aria-label="查看原始配额" disabled={!hasQuotaData}><Code /><span>原始配额</span></Button></DialogTrigger>
          <Button variant="ghost" aria-label="复制配额" disabled={!hasQuotaData} onClick={() => { void copyQuota() }}><Copy /><span>复制配额</span></Button>
          <Button variant="outline" aria-label="刷新用量" disabled={refreshing} onClick={() => { void refresh() }}>{refreshing ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <RefreshCw />}<span>刷新用量</span></Button>
        </div>
      </header>
      <DialogContent className={styles.rawDialog}>
        <div className={styles.dialogHeading}><DialogTitle>原始配额</DialogTitle><DialogDescription>聊天 token 与租户资源的当前响应；未取得的响应为 null。</DialogDescription></div>
        <pre tabIndex={0} aria-label="原始配额 JSON">{rawQuota}</pre>
        <div className={styles.dialogActions}><Button variant="outline" onClick={() => { void copyQuota() }}><Copy />复制配额</Button><DialogClose asChild><Button>关闭</Button></DialogClose></div>
      </DialogContent>
    </Dialog>
    <div className={styles.scrollArea}>
      <div className={styles.scopeBar}>
        <span>统计窗口</span><div className={styles.windowPresets} role="group" aria-label="用量统计窗口">
          {WINDOW_DAYS.map(days => <button key={days} type="button" aria-pressed={windowDays === days} onClick={() => updateScope({ windowDays: days, page: 1 })}>近 {days} 天</button>)}
        </div>
        <span className={styles.window}>{windowSource ? formatWindow(windowSource.window_start, windowSource.window_end) : summaryQuery.isPending || costQuery.isPending ? '正在读取统计窗口…' : '统计窗口未取得'}</span>
        <span className={styles.tenant}>当前租户</span>
      </div>
      {errors.length ? <div className={styles.errors} aria-label="数据读取状态">
        {errors.map(({ label, query }) => <div key={label} role="alert"><span><strong>{label}读取失败</strong> · {formatApiError(query.error, '请重试')}{query.data ? '，显示上次读取结果' : ''}</span><Button variant="ghost" disabled={query.isFetching} onClick={() => { void query.refetch({ cancelRefetch: false }) }}>重试{label}</Button></div>)}
      </div> : null}
      <dl className={styles.metrics} aria-label="累计用量" aria-busy={summaryQuery.isPending || costQuery.isPending}>
        <Metric label="助手消息" value={formatCount(summary?.total_assistant_messages)} unit={summary ? '条' : undefined} />
        <Metric label="助手 token" value={formatCount(summary?.total_assistant_tokens)} />
        <Metric label="向量查询 token" value={formatCount(cost?.total_embedding_query_tokens)} />
        <Metric label="平均检索" value={formatDuration(averageRetrievalMs(cost?.total_retrieval_elapsed_sec, cost?.total_assistant_messages))} />
      </dl>
      <QuotaSummary quotas={quotas} pending={quotaPending} />
      <Tabs value={view} onValueChange={value => updateScope({ view: value as UsageView, page: 1 })} className={styles.tabsRoot}>
        <TabsList aria-label="用量视图" className={styles.tabs}>
          <TabsTrigger value="attribution" className={styles.tab}>用量归因</TabsTrigger>
          <TabsTrigger value="resources" className={styles.tab}>链路资源</TabsTrigger>
          <TabsTrigger value="quotas" className={styles.tab}>配额状态</TabsTrigger>
        </TabsList>
        <TabsContent value="attribution" className={styles.tabBody}>
          <UsageTable rows={rows} mode="attribution" page={page} onPageChange={page => updateScope({ page })} pending={tablePending} failed={tableFailed} windowDays={windowDays} />
        </TabsContent>
        <TabsContent value="resources" className={styles.tabBody}>
          <dl className={styles.resourceMetrics} aria-label="链路资源汇总">
            <Metric label="LLM 输入 token" value={formatCount(cost?.total_llm_prompt_tokens)} />
            <Metric label="LLM 输出 token" value={formatCount(cost?.total_llm_completion_tokens)} />
            <Metric label="LLM 合计 token" value={formatCount(cost?.total_llm_total_tokens)} />
            <Metric label="向量查询字符" value={formatCount(cost?.total_embedding_query_chars)} />
            <Metric label="检索总耗时" value={formatDuration(cost?.total_retrieval_elapsed_sec == null ? null : cost.total_retrieval_elapsed_sec * 1000)} />
            <Metric label="重排总耗时" value={formatDuration(cost?.total_rerank_elapsed_sec == null ? null : cost.total_rerank_elapsed_sec * 1000)} />
          </dl>
          {cost && windowSource && formatWindow(cost.window_start, cost.window_end) !== formatWindow(windowSource.window_start, windowSource.window_end) ? <p className={styles.resourceWindow}>资源统计 · {formatWindow(cost.window_start, cost.window_end)}</p> : null}
          <UsageTable rows={costRows} mode="resources" page={page} onPageChange={page => updateScope({ page })} pending={tablePending} failed={tableFailed} windowDays={windowDays} />
        </TabsContent>
        <TabsContent value="quotas" className={styles.tabBody}><QuotaDetails quotas={quotas} pending={quotaPending} /></TabsContent>
      </Tabs>
    </div>
    <footer className={styles.footer} data-task-center-dock><span>当前租户 · 近 {windowDays} 天{refreshing ? ' · 正在更新' : ''}</span><span className={styles.spacer} /><span>配额按各自窗口统计</span>{updatedAt ? <time dateTime={new Date(updatedAt).toISOString()}>读取于 {dateTime(updatedAt)}</time> : null}</footer>
  </section></AppFrame>
}

function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  const duration = !unit ? /^(.+) (ms|s)$/.exec(value) : null
  const displayUnit = unit ?? duration?.[2]
  return <div><dt>{label}</dt><dd className={cn(value === '—' && styles.missingValue)}>{duration?.[1] ?? value}{displayUnit ? <small>{duration ? ` ${displayUnit}` : displayUnit}</small> : null}</dd></div>
}
