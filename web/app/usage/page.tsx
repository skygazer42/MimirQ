'use client'

import { Suspense, useSyncExternalStore } from 'react'
import { Code, Copy, RefreshCw } from '@/components/icons'
import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { PageLoading } from '@/components/ui/page-loading'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { cn } from '@/lib/utils'
import { QuotaDetails, QuotaSummary } from './quota-summary'
import { UsageTable } from './usage-table'
import { useUsage } from './use-usage'
import {
  USAGE_WINDOW_DAYS,
  averageRetrievalMs,
  formatUsageDateTime,
  formatCount,
  formatDuration,
  formatWindow,
  buildUsageLocation,
  type UsageScope,
} from './usage-model'
import styles from './usage.module.css'

function replaceUsageLocation(next: Partial<UsageScope>) {
  window.history.replaceState(null, '', buildUsageLocation(window.location.href, next))
}

export default function UsagePage() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return (
    <TenantPermissionGate permission={TENANT_PERMISSIONS.USAGE_READ} pageName="用量／配额">
      <Suspense fallback={<PageLoading message="正在加载用量与配额…" srMessage="正在加载用量与配额" />}>
        <UsageOverview key={sessionKey} sessionKey={sessionKey} />
      </Suspense>
    </TenantPermissionGate>
  )
}

function UsageOverview({ sessionKey }: Readonly<{ sessionKey: string }>) {
  const {
    scope,
    summaryQuery,
    costQuery,
    summarySnapshot,
    costSnapshot,
    summary,
    cost,
    rows,
    attributionWindowDays,
    hasCompleteAttribution,
    quotas,
    quotaPending,
    rawQuota,
    hasQuotaData,
    errors,
    quotaOpen,
    setQuotaOpen,
    copying,
    refresh,
    retryRead,
    copyQuota,
    refreshing,
  } = useUsage(sessionKey)
  const { windowDays, view, page } = scope
  const windowSource = summarySnapshot ?? costSnapshot
  const displayedWindow =
    windowSource === undefined ? undefined : formatWindow(windowSource.data.window_start, windowSource.data.window_end)
  const resourceWindow =
    costSnapshot === undefined ? undefined : formatWindow(costSnapshot.data.window_start, costSnapshot.data.window_end)
  const showResourceWindow =
    costSnapshot !== undefined &&
    summarySnapshot !== undefined &&
    (costSnapshot.windowDays !== summarySnapshot.windowDays || resourceWindow !== displayedWindow)
  const updatedAt = windowSource?.receivedAt
  const incompleteEmptyAttribution = rows.length === 0 && !hasCompleteAttribution
  const tableFailed =
    view === 'resources'
      ? costSnapshot === undefined && costQuery.isError
      : incompleteEmptyAttribution && (summaryQuery.isError || costQuery.isError)
  const tablePending =
    !tableFailed &&
    (view === 'resources'
      ? costSnapshot === undefined && costQuery.isPending
      : incompleteEmptyAttribution && (summaryQuery.isPending || costQuery.isPending))

  return (
    <AppFrame>
      <section className={styles.workspace} data-usage-overview="a">
        <Dialog open={quotaOpen} onOpenChange={setQuotaOpen}>
          <header className={styles.header}>
            <div className={styles.heading}>
              <PageTitleIcon name="usage-quota" />
              <h1>用量／配额</h1>
            </div>
            <div className={styles.headerActions}>
              <DialogTrigger asChild>
                <Button variant="ghost" aria-label="查看原始配额" disabled={!hasQuotaData}>
                  <Code />
                  <span className={styles.actionLabel}>原始配额</span>
                </Button>
              </DialogTrigger>
              <LoadingButton
                variant="ghost"
                aria-label="复制配额"
                disabled={!hasQuotaData}
                loading={copying}
                onClick={() => {
                  void copyQuota()
                }}
              >
                <Copy />
                <span className={styles.actionLabel}>复制配额</span>
              </LoadingButton>
              <LoadingButton
                variant="outline"
                aria-label="刷新用量"
                loading={refreshing}
                onClick={() => {
                  void refresh()
                }}
              >
                <RefreshCw />
                <span className={styles.actionLabel}>刷新用量</span>
              </LoadingButton>
            </div>
          </header>
          <DialogContent className={styles.rawDialog}>
            <div className={styles.dialogHeading}>
              <DialogTitle>原始配额</DialogTitle>
              <DialogDescription>仅包含已取得的聊天 token 与租户资源配额响应。</DialogDescription>
            </div>
            <pre tabIndex={0} aria-label="原始配额 JSON">
              {rawQuota}
            </pre>
            <div className={styles.dialogActions}>
              <LoadingButton
                variant="outline"
                loading={copying}
                onClick={() => {
                  void copyQuota()
                }}
              >
                <Copy />
                复制配额
              </LoadingButton>
              <DialogClose asChild>
                <Button>关闭</Button>
              </DialogClose>
            </div>
          </DialogContent>
        </Dialog>
        <div className={styles.scrollArea}>
          <div className={styles.scopeBar}>
            <span>统计窗口</span>
            <div className={styles.windowPresets} role="group" aria-label="用量统计窗口">
              {USAGE_WINDOW_DAYS.map((days) => (
                <button
                  key={days}
                  type="button"
                  aria-pressed={windowDays === days}
                  onClick={() => replaceUsageLocation({ windowDays: days, page: 1 })}
                >
                  近 {days} 天
                </button>
              ))}
            </div>
            <span className={styles.window}>
              {windowSource
                ? `近 ${windowSource.windowDays} 天 · ${displayedWindow}`
                : tablePending
                  ? '正在读取统计窗口…'
                  : '统计窗口未取得'}
            </span>
            <span className={styles.tenant}>当前租户</span>
          </div>
          {summarySnapshot !== undefined && summarySnapshot.windowDays !== windowDays ? (
            <p className={styles.resourceWindow} role="status">
              助手用量仍显示近 {summarySnapshot.windowDays} 天的结果；当前选择为近 {windowDays} 天。
            </p>
          ) : null}
          {showResourceWindow ? (
            <p className={styles.resourceWindow}>
              链路资源 · 近 {costSnapshot.windowDays} 天 · {resourceWindow}
            </p>
          ) : null}
          {costSnapshot !== undefined && costSnapshot.windowDays !== windowDays ? (
            <p className={styles.resourceWindow} role="status">
              链路资源仍显示近 {costSnapshot.windowDays} 天的结果；当前选择为近 {windowDays} 天。
            </p>
          ) : null}
          {errors.length ? (
            <div className={styles.errors} aria-label="数据读取状态">
              {errors.map((read) => (
                <div key={read.label} role="alert">
                  <span>
                    <strong>{read.label}读取失败</strong> · {formatApiError(read.query.error, '请重试')}
                    {read.hasResult ? '，显示上次读取结果' : null}
                  </span>
                  <Button
                    variant="ghost"
                    disabled={read.query.isFetching}
                    onClick={() => {
                      void retryRead(read)
                    }}
                  >
                    重试{read.label}
                  </Button>
                </div>
              ))}
            </div>
          ) : null}
          <dl
            className={styles.metrics}
            aria-label="累计用量"
            aria-busy={summaryQuery.isPending || costQuery.isPending}
          >
            <Metric
              label="助手消息"
              value={formatCount(summary?.total_assistant_messages)}
              unit={summary ? '条' : undefined}
            />
            <Metric label="助手 token" value={formatCount(summary?.total_assistant_tokens)} />
            <Metric label="向量查询 token" value={formatCount(cost?.total_embedding_query_tokens)} />
            <Metric
              label="每条助手消息平均检索耗时"
              value={formatDuration(
                averageRetrievalMs(cost?.total_retrieval_elapsed_sec, cost?.total_assistant_messages),
              )}
            />
          </dl>
          <QuotaSummary quotas={quotas} pending={quotaPending} />
          <Tabs
            value={view}
            onValueChange={(view) => {
              if (view === 'attribution' || view === 'resources' || view === 'quotas')
                replaceUsageLocation({ view, page: 1 })
            }}
            className={styles.tabsRoot}
          >
            <TabsList aria-label="用量视图" className={styles.tabs}>
              <TabsTrigger value="attribution" className={styles.tab}>
                用量归因
              </TabsTrigger>
              <TabsTrigger value="resources" className={styles.tab}>
                链路资源
              </TabsTrigger>
              <TabsTrigger value="quotas" className={styles.tab}>
                配额状态
              </TabsTrigger>
            </TabsList>
            <TabsContent value="attribution" className={styles.tabBody}>
              <UsageTable
                rows={rows}
                mode="attribution"
                page={page}
                onPageChange={(page) => replaceUsageLocation({ page })}
                pending={tablePending}
                failed={tableFailed}
                windowDays={attributionWindowDays}
              />
            </TabsContent>
            <TabsContent value="resources" className={styles.tabBody}>
              <dl className={styles.resourceMetrics} aria-label="链路资源汇总">
                <Metric label="LLM 输入 token" value={formatCount(cost?.total_llm_prompt_tokens)} />
                <Metric label="LLM 输出 token" value={formatCount(cost?.total_llm_completion_tokens)} />
                <Metric label="LLM 合计 token" value={formatCount(cost?.total_llm_total_tokens)} />
                <Metric label="向量查询字符" value={formatCount(cost?.total_embedding_query_chars)} />
                <Metric
                  label="检索总耗时"
                  value={formatDuration(cost === undefined ? undefined : cost.total_retrieval_elapsed_sec * 1000)}
                />
                <Metric
                  label="重排总耗时"
                  value={formatDuration(cost === undefined ? undefined : cost.total_rerank_elapsed_sec * 1000)}
                />
              </dl>
              <UsageTable
                rows={rows}
                mode="resources"
                page={page}
                onPageChange={(page) => replaceUsageLocation({ page })}
                pending={tablePending}
                failed={tableFailed}
                windowDays={costSnapshot === undefined ? windowDays : costSnapshot.windowDays}
              />
            </TabsContent>
            <TabsContent value="quotas" className={styles.tabBody}>
              <QuotaDetails quotas={quotas} pending={quotaPending} />
            </TabsContent>
          </Tabs>
        </div>
        <footer className={styles.footer} data-task-center-dock>
          <span>
            当前租户{windowSource === undefined ? '' : ` · 显示近 ${windowSource.windowDays} 天`}
            {refreshing ? ' · 正在更新' : ''}
          </span>
          <span className={styles.spacer} />
          <span>配额按各自窗口统计</span>
          {updatedAt !== undefined ? (
            <time dateTime={new Date(updatedAt).toISOString()}>读取于 {formatUsageDateTime(updatedAt)}</time>
          ) : null}
        </footer>
      </section>
    </AppFrame>
  )
}

function Metric({ label, value, unit }: Readonly<{ label: string; value: string; unit?: string }>) {
  const duration = unit === undefined ? /^(.+) (ms|s)$/.exec(value) : null
  const displayUnit = unit === undefined ? duration?.[2] : unit
  return (
    <div>
      <dt>{label}</dt>
      <dd className={cn(value === '—' && styles.missingValue)}>
        {duration === null ? value : duration[1]}
        {displayUnit !== undefined ? <small>{duration === null ? displayUnit : ` ${displayUnit}`}</small> : null}
      </dd>
    </div>
  )
}
