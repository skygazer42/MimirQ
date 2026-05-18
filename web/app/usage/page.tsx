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

const GLASS_CARD =
  'bg-card/80 backdrop-blur-md rounded-2xl border border-border/40 shadow-[0_8px_32px_rgba(0,0,0,0.04)] overflow-hidden transition-all duration-300'
const GLOW_CARD =
  'group relative bg-card rounded-2xl border border-slate-200/60 p-6 shadow-sm hover:shadow-[0_20px_40px_rgba(59,130,246,0.08)] hover:-translate-y-1 transition-all duration-300'
const NUMBER_ACCENT =
  'text-2xl font-black text-slate-900 font-mono bg-clip-text'
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
    blue: 'bg-blue-500',
    green: 'bg-emerald-500',
    indigo: 'bg-indigo-500',
    slate: 'bg-slate-300',
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
          <div className="size-10 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-center text-slate-400 group-hover:bg-blue-600 group-hover:text-info-foreground group-hover:rotate-6 transition-all duration-300 shadow-sm">
            <Icon className="size-5" />
          </div>
          <span className="text-[12px] font-black text-slate-400 uppercase">
            {label}
          </span>
        </div>
        <div className="size-6 rounded-full bg-slate-50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
          <ArrowUpRight className="size-3 text-blue-500" />
        </div>
      </div>

      <div className="flex flex-col pl-2">
        <span className={NUMBER_ACCENT}>{value}</span>
        {detail && (
          <div className="mt-3 flex items-center gap-1.5">
            <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 uppercase">
              {detail}
            </span>
            <TrendingUp className="size-3 text-emerald-500 opacity-50" />
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
    blue: 'border-blue-100 bg-blue-50/70 text-blue-700',
    green: 'border-emerald-100 bg-emerald-50/70 text-emerald-700',
    red: 'border-rose-100 bg-rose-50/70 text-rose-700',
    slate: 'border-slate-200/70 bg-white/75 text-slate-700',
  }[tone]
  return (
    <div
      className={cn(
        'min-w-[104px] rounded-2xl border px-3 py-2 shadow-[0_1px_0_rgba(15,23,42,0.03)]',
        toneClass
      )}
    >
      <span className="block text-[10px] font-bold tracking-[0.12em] text-slate-400">
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
      <span className="shrink-0 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">
        {label}
      </span>
      <span className="truncate text-[12px] font-semibold text-slate-700">
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
        iconColor="text-blue-600"
        size="full"
        bodyClassName="bg-[#F8FAFC] relative"
      >
        {/* Ambient background glow */}
        <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
          <div className="absolute -left-[10%] -top-[10%] size-[40%] rounded-full bg-blue-400/5 blur-[120px]" />
          <div className="absolute -right-[5%] top-[20%] size-[30%] rounded-full bg-indigo-400/5 blur-[100px]" />
        </div>

        <div className="relative z-10 flex flex-col gap-6 pb-24">
          <section
            data-usage-overview="compact"
            className="overflow-hidden rounded-3xl border border-slate-200/80 bg-white/85 shadow-[0_14px_40px_rgba(15,23,42,0.05)] backdrop-blur-xl"
          >
            {loadErrorMessage && (
              <span className="sr-only" role="status">
                {loadErrorMessage}
              </span>
            )}
            <div className="flex flex-col gap-4 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-[220px] items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-2xl border border-blue-100 bg-blue-50 text-blue-600 shadow-inner">
                  <Coins className="size-4" />
                </div>
                <div className="min-w-0">
                  <h2 className="text-[15px] font-black leading-tight text-slate-950">
                    租户用量与配额
                  </h2>
                  <p className="mt-1 text-[11px] font-semibold text-slate-500">
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
                  <SelectTrigger className="h-9 w-[96px] rounded-2xl border-slate-200 bg-white text-[12px] font-bold shadow-sm transition-all hover:bg-blue-50/70">
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
                  className="size-9 rounded-2xl border-slate-200 bg-white shadow-sm transition-all hover:bg-blue-50 hover:text-blue-700"
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
                      'size-4 text-slate-600',
                      loading && 'animate-spin'
                    )}
                  />
                </Button>
              </div>
            </div>

            <div className="border-t border-slate-100 bg-slate-50/55 px-4 py-2.5">
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
                'xl:col-span-5 flex flex-col border-blue-100/30'
              )}
            >
              <div className="px-8 py-6 border-b border-slate-100/50 flex items-center justify-between from-blue-50/50 to-transparent">
                <div>
                  <h3 className="text-[14px] font-black text-slate-900 uppercase flex items-center gap-2">
                    <TrendingUp className="size-4 text-blue-500" />
                    数据集用量排行
                  </h3>
                  <p className="text-[10px] text-slate-400 font-bold uppercase mt-1">
                    按 dataset_id 归因 · {formatWindow(summary?.window_start, summary?.window_end)}
                  </p>
                </div>
                <div className="size-8 rounded-lg bg-card border border-slate-100 flex items-center justify-center text-slate-200">
                  <LayoutGrid className="size-4" />
                </div>
              </div>
              <div className="overflow-auto max-h-[520px]">
                <table className="w-full text-left">
                  <thead>
                    <tr className="bg-slate-50/30 border-b border-slate-100/50">
                      <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">
                        数据集
                      </th>
                      <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">
                        消息
                      </th>
	                      <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">
	                        消耗
	                      </th>
	                      <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">
	                        操作
	                      </th>
	                    </tr>
	                  </thead>
	                  <tbody className="divide-y divide-slate-50/50">
	                    {rows.map((r) => {
	                      const datasetId = r.dataset_id || ''
	                      const datasetName = datasetNameById[datasetId] || ''
	                      const canOpenDataset = Boolean(datasetId && datasetName)
	                      return (
	                        <tr
	                          key={datasetId || 'unbound'}
	                          className="hover:bg-blue-50/30 transition-all duration-200 group"
	                        >
	                          <td className="px-8 py-5">
	                            <p className="text-[13px] font-bold text-slate-700 truncate max-w-[200px] group-hover:text-blue-600 transition-colors">
	                              {datasetName || (datasetId ? '已删除或无权限数据集' : '未绑定数据集')}
	                            </p>
	                            <p className="text-[9px] font-mono text-slate-300 group-hover:text-slate-400 uppercase">
	                              {datasetId ? shortId(datasetId) : 'NO DATASET ID'}
	                            </p>
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono text-slate-500 text-right">
	                            {formatNumber(r.assistant_messages)}
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono font-black text-slate-900 text-right">
	                            {formatNumber(r.assistant_tokens)}
	                          </td>
	                          <td className="px-8 py-5 text-right">
	                            {canOpenDataset ? (
	                              <Link
	                                href={buildDatasetKnowledgeHref(datasetId)}
	                                className="inline-flex items-center gap-1.5 rounded-lg border border-blue-100 bg-blue-50 px-2.5 py-1.5 text-[11px] font-semibold text-blue-700 transition-colors hover:border-blue-200 hover:bg-blue-100"
	                              >
	                                查看
	                                <ArrowUpRight className="size-3" />
	                              </Link>
	                            ) : (
	                              <span className="text-[11px] font-medium text-slate-300">
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
                'xl:col-span-7 flex flex-col border-indigo-100/30'
              )}
            >
              <div className="px-8 py-6 border-b border-slate-100/50 flex items-center justify-between from-indigo-50/50 to-transparent">
                <div>
                  <h3 className="text-[14px] font-black text-slate-900 uppercase flex items-center gap-2">
                    <Zap className="size-4 text-indigo-500 fill-current" />
                    数据集成本归因（估算）
                  </h3>
                  <p className="text-[10px] text-slate-400 font-bold uppercase mt-1">
                    聊天与检索链路聚合 · {formatWindow(cost?.window_start, cost?.window_end)}
                  </p>
                </div>
                <div className="size-8 rounded-lg bg-card border border-slate-100 flex items-center justify-center text-slate-200">
                  <BarChart3 className="size-4" />
                </div>
              </div>
              <div className="overflow-auto max-h-[520px]">
                <table className="w-full text-left">
                  <thead>
                    <tr className="bg-slate-50/30 border-b border-slate-100/50">
                      <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">
                        分析维度
                      </th>
                      <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">
                        LLM TOKEN
                      </th>
                      <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">
                        向量 TOKEN
                      </th>
	                      <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">
	                        平均检索
	                      </th>
	                      <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">
	                        操作
	                      </th>
	                    </tr>
	                  </thead>
	                  <tbody className="divide-y divide-slate-50/50">
	                    {costRows.map((r) => {
	                      const datasetId = r.dataset_id || ''
	                      const datasetName = datasetNameById[datasetId] || ''
	                      const canOpenDataset = Boolean(datasetId && datasetName)
	                      return (
	                        <tr
	                          key={datasetId || 'unbound-cost'}
	                          className="hover:bg-indigo-50/30 transition-all duration-200 group"
	                        >
	                          <td className="px-8 py-5">
	                            <p className="text-[13px] font-bold text-slate-700 truncate max-w-[240px] group-hover:text-indigo-600 transition-colors">
	                              {datasetName || (datasetId ? '已删除或无权限数据集' : '未绑定数据集')}
	                            </p>
	                            <p className="text-[9px] font-mono text-slate-300 group-hover:text-slate-400 uppercase">
	                              {datasetId ? shortId(datasetId) : 'NO DATASET ID'}
	                            </p>
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono font-black text-slate-800 text-right">
	                            {formatNumber(r.llm_total_tokens)}
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono text-slate-500 text-right">
	                            {formatNumber(r.embedding_query_tokens)}
	                          </td>
	                          <td className="px-8 py-5 text-[12px] font-mono text-slate-400 text-right">
	                            {formatSec(
	                              r.retrieval_elapsed_sec_sum /
	                                Math.max(1, r.assistant_messages || 0)
	                            )}
	                          </td>
	                          <td className="px-8 py-5 text-right">
	                            {canOpenDataset ? (
	                              <Link
	                                href={buildDatasetKnowledgeHref(datasetId)}
	                                className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-100 bg-indigo-50 px-2.5 py-1.5 text-[11px] font-semibold text-indigo-700 transition-colors hover:border-indigo-200 hover:bg-indigo-100"
	                              >
	                                查看
	                                <ArrowUpRight className="size-3" />
	                              </Link>
	                            ) : (
	                              <span className="text-[11px] font-medium text-slate-300">
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
            <div className="absolute inset-0 from-transparent via-white/5 to-white/10 rounded-3xl pointer-events-none" />
            <TenantQuotaPanel />
          </div>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
