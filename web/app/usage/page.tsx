'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart3,
  Clock3,
  Coins,
  Database,
  MessageSquareText,
  RefreshCw,
  Timer,
  UserRound,
  ArrowUpRight,
  LayoutGrid,
  Zap,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { PageScaffold } from '@/components/ui/page-scaffold'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { TenantQuotaPanel } from '@/components/usage/tenant-quota-panel'
import { Link } from '@/i18n/navigation'
import { datasetApi, usageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { cn } from '@/lib/utils'
import type {
  ChatCostUsageSummary,
  ChatTokenQuotaStatus,
  ChatTokenUsageSummary,
} from '@/types'

// --- Advanced Style Tokens ---

const USAGE_PANEL_CLASS =
  'overflow-hidden rounded-3xl border border-border/60 bg-card/82 shadow-[0_14px_40px_hsl(var(--primary)/0.06)] backdrop-blur-xl'
const USAGE_SURFACE_CLASS =
  'rounded-2xl border border-border/60 bg-background/70 shadow-[0_12px_30px_hsl(var(--primary)/0.05)]'
const GLASS_CARD = `${USAGE_SURFACE_CLASS} backdrop-blur-md overflow-hidden transition-all duration-300`
const GLOW_CARD =
  'group relative rounded-2xl border border-border/60 bg-card/82 p-6 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_20px_40px_hsl(var(--primary)/0.08)]'
const NUMBER_ACCENT =
  'text-2xl font-black text-foreground font-mono bg-clip-text'
const USAGE_TABLE_HEAD_CLASS = 'bg-muted/38 border-b border-border/50'
const USAGE_TABLE_HEADER_CLASS =
  'px-8 py-4 text-[10px] font-black text-muted-foreground uppercase tracking-[0.2em]'
const USAGE_LINK_CLASS =
  'inline-flex items-center gap-1.5 rounded-lg border border-primary/20 bg-primary/10 px-2.5 py-1.5 text-[11px] font-semibold text-primary transition-colors hover:border-primary/30 hover:bg-primary/15'
const WINDOW_PRESETS = [
  { value: 7, label: '7天' },
  { value: 14, label: '14天' },
  { value: 30, label: '30天' },
] as const

// --- Helper Functions ---

function shortId(id: string) {
  const v = (id || '').trim()
  if (!v) return ''
  return v.length > 12 ? `${v.slice(0, 6)}…${v.slice(-4)}` : v
}

function formatNumber(value: number | string | null | undefined) {
  if (value == null || value === '') return '0'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return n.toLocaleString()
}

function formatSec(sec: number | null | undefined) {
  if (sec == null || !Number.isFinite(sec)) return '0ms'
  if (sec < 1) return `${Math.round(sec * 1000)}ms`
  return `${sec.toFixed(2)}s`
}

function formatWindow(start?: string | null, end?: string | null) {
  if (!start || !end) return '---'
  try {
    const opts: Intl.DateTimeFormatOptions = {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }
    return `${new Date(start).toLocaleString('zh-CN', opts)} - ${new Date(end).toLocaleString('zh-CN', opts)}`
  } catch {
    return `${start} - ${end}`
  }
}

function buildDatasetKnowledgeHref(datasetId: string) {
  const params = new URLSearchParams({
    dataset: datasetId,
    lifecycle: 'all',
    status: 'all',
  })
  return `/knowledge?${params.toString()}`
}

// --- Specialized Components ---

function StylizedMetricCard({
  icon: Icon,
  label,
  value,
  detail,
  tone = 'blue',
}: {
  icon: LucideIcon
  label: string
  value: string | number
  detail?: string
  tone?: string
}) {
  const accentMap = {
    blue: 'bg-primary',
    green: 'bg-success',
    indigo: 'bg-accent',
    slate: 'bg-muted-foreground/45',
  }
  return (
    <div className={GLOW_CARD}>
      {/* Accent Strip */}
      <div
        className={cn(
          'absolute left-0 top-6 bottom-6 w-1 rounded-r-full transition-all group-hover:w-1.5',
          accentMap[tone as keyof typeof accentMap]
        )}
      />

      <div className="flex items-start justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="size-10 rounded-xl bg-background/70 border border-border/60 flex items-center justify-center text-muted-foreground group-hover:bg-primary group-hover:text-primary-foreground group-hover:rotate-6 transition-all duration-300 shadow-sm">
            <Icon className="size-5" />
          </div>
          <span className="text-[12px] font-black text-muted-foreground uppercase">
            {label}
          </span>
        </div>
        <div className="size-6 rounded-full bg-muted/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
          <ArrowUpRight className="size-3 text-primary" />
        </div>
      </div>

      <div className="flex flex-col pl-2">
        <span className={NUMBER_ACCENT}>{value}</span>
        {detail && (
          <div className="mt-3 flex items-center gap-1.5">
            <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-muted text-muted-foreground uppercase">
              {detail}
            </span>
            <TrendingUp className="size-3 text-success opacity-50" />
          </div>
        )}
      </div>
    </div>
  )
}

function OverviewStat({
  label,
  value,
  tone = 'slate',
}: {
  label: string
  value: string | number
  tone?: 'blue' | 'green' | 'red' | 'slate'
}) {
  const toneClass = {
    blue: 'border-primary/20 bg-primary/10 text-primary',
    green: 'border-success/20 bg-success/10 text-success',
    red: 'border-destructive/20 bg-destructive/10 text-destructive',
    slate: 'border-border/60 bg-card/72 text-foreground',
  }[tone]
  return (
    <div
      className={cn(
        'min-w-[104px] rounded-2xl border px-3 py-2 shadow-[0_1px_0_rgba(15,23,42,0.03)]',
        toneClass
      )}
    >
      <span className="block text-[10px] font-bold tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      <span className="mt-0.5 block truncate text-[14px] font-black leading-tight">
        {value}
      </span>
    </div>
  )
}

function OverviewMeta({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="shrink-0 text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </span>
      <span className="truncate text-[12px] font-semibold text-foreground">
        {value}
      </span>
    </div>
  )
}

// --- Main Page ---

export default function UsagePage() {
  return (
    <TenantPermissionGate
      permission={TENANT_PERMISSIONS.USAGE_READ}
      pageName="用量/配额"
    >
      <UsagePageContent />
    </TenantPermissionGate>
  )
}

function UsagePageContent() {
  const [windowDays, setWindowDays] = useState<number>(7)

  const windowParams = useMemo(
    () => ({ window_days: windowDays }),
    [windowDays]
  )

  const summaryQuery = useQuery<ChatTokenUsageSummary>({
    queryKey: queryKeys.usage.summary(windowParams),
    queryFn: () => usageApi.getChatTokenUsageSummary(windowParams),
    placeholderData: (previousData) => previousData,
  })

  const costQuery = useQuery<ChatCostUsageSummary | null>({
    queryKey: queryKeys.usage.cost(windowParams),
    queryFn: () =>
      usageApi.getChatCostUsageSummary(windowParams).catch(() => null),
    placeholderData: (previousData) => previousData,
  })

  const quotaQuery = useQuery<ChatTokenQuotaStatus | null>({
    queryKey: queryKeys.usage.quota,
    queryFn: () => usageApi.getChatTokenQuotaStatus().catch(() => null),
    staleTime: 60 * 1000,
  })

  const datasetLabelsQuery = useQuery<Record<string, string>>({
    queryKey: queryKeys.datasets.list({ limit: 200, purpose: 'usage-labels' }),
    queryFn: async () => {
      const datasets = await datasetApi.list({ limit: 200 })
      const nameMap: Record<string, string> = {}
      for (const ds of datasets.items || []) {
        if (ds?.id)
          nameMap[String(ds.id)] =
            String(ds.name || '').trim() || shortId(String(ds.id))
      }
      return nameMap
    },
    staleTime: 5 * 60 * 1000,
  })

  const summary = summaryQuery.data ?? null
  const cost = costQuery.data ?? null
  const quota = quotaQuery.data ?? null
  const datasetNameById = datasetLabelsQuery.data ?? {}
  const loading =
    summaryQuery.isFetching ||
    costQuery.isFetching ||
    quotaQuery.isFetching ||
    datasetLabelsQuery.isFetching
  const loadErrorMessage = summaryQuery.error
    ? formatApiError(summaryQuery.error, '数据拉取失败')
    : ''

  const rows = useMemo(() => {
    const list = summary?.by_dataset || []
    return [...list]
      .sort((a, b) => (b.assistant_tokens || 0) - (a.assistant_tokens || 0))
      .slice(0, 10)
  }, [summary])

  const costRows = useMemo(() => {
    const list = cost?.by_dataset || []
    return [...list]
      .sort((a, b) => (b.llm_total_tokens || 0) - (a.llm_total_tokens || 0))
      .slice(0, 10)
  }, [cost])

  const avgRetrieve = cost
    ? cost.total_retrieval_elapsed_sec /
      Math.max(1, cost.total_assistant_messages || 0)
    : null
  const quotaExceeded = quota?.enabled && quota.exceeded
  const quotaStatus = quota?.enabled
    ? quota.exceeded
      ? '已超额'
      : '运行正常'
    : '未启用'
  const dataStatus = summary ? '已就绪' : loading ? '同步中' : '未连接'

  return (
    <AppFrame>
      <PageScaffold
        title="用量/配额"
        description="管理员查看当前租户的总用量、数据集归因和租户级配额状态"
        iconImage="usage-quota"
        icon={Coins}
        iconColor="text-primary"
        size="full"
        bodyClassName="bg-transparent relative"
      >
        {/* Ambient background glow */}
        <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
          <div className="absolute -left-[10%] -top-[10%] size-[40%] rounded-full bg-primary/5 blur-[120px]" />
          <div className="absolute -right-[5%] top-[20%] size-[30%] rounded-full bg-accent/5 blur-[100px]" />
        </div>

        <div className="relative z-10 flex flex-col gap-6 pb-24">
          <section
            data-usage-overview="compact"
            className={USAGE_PANEL_CLASS}
          >
            {loadErrorMessage && (
              <span className="sr-only" role="status">
                {loadErrorMessage}
              </span>
            )}
            <div className="flex flex-col gap-4 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-[220px] items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-inner">
                  <Coins className="size-4" />
                </div>
                <div className="min-w-0">
                  <h2 className="text-[15px] font-black leading-tight text-foreground">
                    租户用量与配额
                  </h2>
                  <p className="mt-1 text-[11px] font-semibold text-muted-foreground">
                    当前租户 · 数据集归因 · 租户级配额
                  </p>
                </div>
              </div>

              <div className="grid flex-1 grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
                <OverviewStat
                  label="窗口"
                  value={windowDays === 1 ? '24小时' : `${windowDays}天`}
                  tone="blue"
                />
                <OverviewStat label="归因数据集" value={rows.length} />
                <OverviewStat
                  label="模型令牌"
                  value={formatNumber(cost?.total_llm_total_tokens)}
                />
                <OverviewStat
                  label="聊天配额"
                  value={quotaStatus}
                  tone={
                    quota?.enabled && !quota.exceeded
                      ? 'green'
                      : quotaExceeded
                        ? 'red'
                        : 'slate'
                  }
                />
                <OverviewStat
                  label="数据状态"
                  value={dataStatus}
                  tone={summary ? 'green' : 'slate'}
                />
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <Select
                  value={String(windowDays)}
                  onValueChange={(v) => setWindowDays(Number(v))}
                >
                  <SelectTrigger className="h-9 w-[96px] rounded-2xl border-border/60 bg-background/70 text-[12px] font-bold shadow-sm transition-all hover:bg-primary/10">
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
                <Button
                  variant="outline"
                  size="icon"
                  className="size-9 rounded-2xl border-border/60 bg-background/70 shadow-sm transition-all hover:bg-primary/10 hover:text-primary"
                  aria-label="刷新用量数据"
                  onClick={() => {
                    void summaryQuery.refetch()
                    void costQuery.refetch()
                    void quotaQuery.refetch()
                    void datasetLabelsQuery.refetch()
                  }}
                >
                  <RefreshCw
                    className={cn(
                      'size-4 text-muted-foreground',
                      loading && 'animate-spin'
                    )}
                  />
                </Button>
              </div>
            </div>

            <div className="border-t border-border/50 bg-muted/28 px-4 py-2.5">
              <div className="grid gap-2 md:grid-cols-3">
                <OverviewMeta label="统计范围" value="当前租户总量" />
                <OverviewMeta
                  label="归因口径"
                  value="按数据集拆分聊天与检索成本"
                />
                <OverviewMeta
                  label="分配方式"
                  value="租户级配额，暂不按用户分配"
                />
              </div>
            </div>
          </section>

          {/* Main Visual KPIs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-6">
            <StylizedMetricCard
              icon={UserRound}
              label="聊天输出令牌"
              value={formatNumber(summary?.total_assistant_tokens)}
              detail="ASSISTANT"
              tone="blue"
            />
            <StylizedMetricCard
              icon={Coins}
              label="LLM 总令牌"
              value={formatNumber(cost?.total_llm_total_tokens)}
              detail="LLM_EST"
              tone="indigo"
            />
            <StylizedMetricCard
              icon={Database}
              label="检索向量令牌"
              value={formatNumber(cost?.total_embedding_query_tokens)}
              detail="EMBEDDING"
              tone="blue"
            />
            <StylizedMetricCard
              icon={Timer}
              label="平均检索耗时"
              value={formatSec(avgRetrieve)}
              detail="LATENCY"
              tone="indigo"
            />
            <StylizedMetricCard
              icon={Clock3}
              label="聊天配额剩余"
              value={quota?.enabled ? formatNumber(quota.remaining) : '0'}
              detail="REMAINING"
              tone="green"
            />
            <StylizedMetricCard
              icon={MessageSquareText}
              label="助手消息数"
              value={formatNumber(summary?.total_assistant_messages)}
              detail="TOTAL_MSG"
              tone="slate"
            />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-12 gap-10">
            {/* Usage Table Section */}
            <div
              className={cn(
                GLASS_CARD,
                'xl:col-span-5 flex flex-col border-primary/10'
              )}
            >
              <div className="px-8 py-6 border-b border-border/50 flex items-center justify-between bg-primary/[0.025]">
                <div>
                  <h3 className="text-[14px] font-black text-foreground uppercase flex items-center gap-2">
                    <TrendingUp className="size-4 text-primary" />
                    数据集用量排行
                  </h3>
                  <p className="text-[10px] text-muted-foreground font-bold uppercase mt-1">
                    按 dataset_id 归因 · {formatWindow(summary?.window_start, summary?.window_end)}
                  </p>
                </div>
                <div className="size-8 rounded-lg bg-background/70 border border-border/60 flex items-center justify-center text-muted-foreground/55">
                  <LayoutGrid className="size-4" />
                </div>
              </div>
              <div className="overflow-auto max-h-[520px]">
                <table className="w-full text-left">
                  <thead>
                    <tr className={USAGE_TABLE_HEAD_CLASS}>
                      <th className={USAGE_TABLE_HEADER_CLASS}>
                        数据集
                      </th>
                      <th className={cn(USAGE_TABLE_HEADER_CLASS, 'text-right')}>
                        消息
                      </th>
	                      <th className={cn(USAGE_TABLE_HEADER_CLASS, 'text-right')}>
	                        消耗
	                      </th>
	                      <th className={cn(USAGE_TABLE_HEADER_CLASS, 'text-right')}>
	                        操作
	                      </th>
	                    </tr>
	                  </thead>
	                  <tbody className="divide-y divide-border/40">
	                    {rows.map((r) => {
	                      const datasetId = r.dataset_id || ''
	                      const datasetName = datasetNameById[datasetId] || ''
	                      const canOpenDataset = Boolean(datasetId && datasetName)
	                      return (
	                        <tr
	                          key={datasetId || 'unbound'}
	                          className="hover:bg-primary/[0.04] transition-all duration-200 group"
	                        >
	                          <td className="px-8 py-5">
	                            <p className="text-[13px] font-bold text-foreground truncate max-w-[200px] group-hover:text-primary transition-colors">
	                              {datasetName || (datasetId ? '已删除或无权限数据集' : '未绑定数据集')}
	                            </p>
	                            <p className="text-[9px] font-mono text-muted-foreground/55 group-hover:text-muted-foreground uppercase">
	                              {datasetId ? shortId(datasetId) : 'NO DATASET ID'}
	                            </p>
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono text-muted-foreground text-right">
	                            {formatNumber(r.assistant_messages)}
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono font-black text-foreground text-right">
	                            {formatNumber(r.assistant_tokens)}
	                          </td>
	                          <td className="px-8 py-5 text-right">
	                            {canOpenDataset ? (
	                              <Link
	                                href={buildDatasetKnowledgeHref(datasetId)}
	                                className={USAGE_LINK_CLASS}
	                              >
	                                查看
	                                <ArrowUpRight className="size-3" />
	                              </Link>
	                            ) : (
	                              <span className="text-[11px] font-medium text-muted-foreground/55">
	                                不可跳转
	                              </span>
	                            )}
	                          </td>
	                        </tr>
	                      )
	                    })}
	                  </tbody>
	                </table>
	              </div>
	            </div>

            {/* Cost Attribution Table Section */}
            <div
              className={cn(
                GLASS_CARD,
                'xl:col-span-7 flex flex-col border-accent/10'
              )}
            >
              <div className="px-8 py-6 border-b border-border/50 flex items-center justify-between bg-accent/[0.025]">
                <div>
                  <h3 className="text-[14px] font-black text-foreground uppercase flex items-center gap-2">
                    <Zap className="size-4 text-accent fill-current" />
                    数据集成本归因（估算）
                  </h3>
                  <p className="text-[10px] text-muted-foreground font-bold uppercase mt-1">
                    聊天与检索链路聚合 · {formatWindow(cost?.window_start, cost?.window_end)}
                  </p>
                </div>
                <div className="size-8 rounded-lg bg-background/70 border border-border/60 flex items-center justify-center text-muted-foreground/55">
                  <BarChart3 className="size-4" />
                </div>
              </div>
              <div className="overflow-auto max-h-[520px]">
                <table className="w-full text-left">
                  <thead>
                    <tr className={USAGE_TABLE_HEAD_CLASS}>
                      <th className={USAGE_TABLE_HEADER_CLASS}>
                        分析维度
                      </th>
                      <th className={cn(USAGE_TABLE_HEADER_CLASS, 'text-right')}>
                        LLM TOKEN
                      </th>
                      <th className={cn(USAGE_TABLE_HEADER_CLASS, 'text-right')}>
                        向量 TOKEN
                      </th>
	                      <th className={cn(USAGE_TABLE_HEADER_CLASS, 'text-right')}>
	                        平均检索
	                      </th>
	                      <th className={cn(USAGE_TABLE_HEADER_CLASS, 'text-right')}>
	                        操作
	                      </th>
	                    </tr>
	                  </thead>
	                  <tbody className="divide-y divide-border/40">
	                    {costRows.map((r) => {
	                      const datasetId = r.dataset_id || ''
	                      const datasetName = datasetNameById[datasetId] || ''
	                      const canOpenDataset = Boolean(datasetId && datasetName)
	                      return (
	                        <tr
	                          key={datasetId || 'unbound-cost'}
	                          className="hover:bg-accent/[0.04] transition-all duration-200 group"
	                        >
	                          <td className="px-8 py-5">
	                            <p className="text-[13px] font-bold text-foreground truncate max-w-[240px] group-hover:text-accent transition-colors">
	                              {datasetName || (datasetId ? '已删除或无权限数据集' : '未绑定数据集')}
	                            </p>
	                            <p className="text-[9px] font-mono text-muted-foreground/55 group-hover:text-muted-foreground uppercase">
	                              {datasetId ? shortId(datasetId) : 'NO DATASET ID'}
	                            </p>
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono font-black text-foreground text-right">
	                            {formatNumber(r.llm_total_tokens)}
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono text-muted-foreground text-right">
	                            {formatNumber(r.embedding_query_tokens)}
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono text-muted-foreground text-right">
	                            {formatSec(
	                              r.retrieval_elapsed_sec_sum /
	                                Math.max(1, r.assistant_messages || 0)
	                            )}
	                          </td>
	                          <td className="px-8 py-5 text-right">
	                            {canOpenDataset ? (
	                              <Link
	                                href={buildDatasetKnowledgeHref(datasetId)}
	                                className={USAGE_LINK_CLASS}
	                              >
	                                查看
	                                <ArrowUpRight className="size-3" />
	                              </Link>
	                            ) : (
	                              <span className="text-[11px] font-medium text-muted-foreground/55">
	                                不可跳转
	                              </span>
	                            )}
	                          </td>
	                        </tr>
	                      )
	                    })}
	                  </tbody>
	                </table>
              </div>
            </div>
          </div>

          {/* Bottom Custom Panel */}
          <div className="relative">
            <div className="absolute inset-0 rounded-3xl pointer-events-none bg-[radial-gradient(circle_at_50%_0%,hsl(var(--primary)/0.05),transparent_58%)]" />
            <TenantQuotaPanel />
          </div>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
