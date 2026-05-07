'use client'

/**
 * RAGAS 评测页面 - 支持 Tab 切换
 * Tab 1: 对话评测（基于对话历史）
 * Tab 2: 回归测试（基于测试用例）
 * Tab 3: Queryset Health（检索基准集健康度）
 */

import { Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'next/navigation'
import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AnalysisPageShell } from '@/components/ui/analysis-page-shell'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { evaluationApi, chatApi, type RagasRun, type RagasRunDetail } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { Conversation } from '@/types'
import {
  BarChart3,
  ChevronDown,
  CheckCircle2,
  Clock3,
  CircleDollarSign,
  Database,
  Filter,
  Gauge,
  Info,
  Loader2,
  ListChecks,
  PlayCircle,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  MessageSquare,
  TestTube2,
  TrendingUp,
  XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { RegressionTestTab } from '@/components/evaluation/regression-tab'
import { QuerysetHealthTab } from '@/components/evaluation/queryset-health-tab'
import { RagasMetricSelector, ragasMetricLabel } from '@/components/evaluation/ragas-metric-selector'

type TabType = 'conversation' | 'regression' | 'queryset_health'

const TAB_META: Array<{
  id: TabType
  label: string
  title: string
  description: string
  icon: typeof MessageSquare
}> = [
  {
    id: 'conversation',
    label: '对话评测',
    title: '实时会话评分',
    description: '基于已有对话和引用上下文，快速拉起一轮 RAGAS 评测。',
    icon: MessageSquare,
  },
  {
    id: 'regression',
    label: 'Golden 评测集',
    title: 'Golden 回归评测',
    description: '用数据集级标准问答和标准证据持续评估当前 RAG pipeline。',
    icon: TestTube2,
  },
  {
    id: 'queryset_health',
    label: '检索集健康度',
    title: '检索集健康度',
    description: '查看趋势、差异与退化标记，定位检索集层面的异常波动。',
    icon: BarChart3,
  },
]

function metricLabel(key: string): string {
  return ragasMetricLabel(key)
}

function parseEvaluationTab(value: string | null | undefined): TabType | null {
  const tab = (value || '').trim().toLowerCase()
  if (tab === 'regression' || tab === 'conversation' || tab === 'queryset_health') return tab as TabType
  return null
}

function formatCompactCount(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}

function formatMoney(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  if (n === 0) return '¥0'
  if (Math.abs(n) < 0.01) return `¥${n.toFixed(4)}`
  return `¥${n.toFixed(2)}`
}

function formatPercentValue(value: number | null | undefined, digits = 1): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  return `${(value * 100).toFixed(digits)}%`
}

function formatDateTime(value: string | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatRunDuration(run: RagasRun): string {
  const started = new Date(run.started_at || run.created_at).getTime()
  const finished = new Date(run.finished_at || '').getTime()
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) return '-'
  const seconds = Math.max(1, Math.round((finished - started) / 1000))
  return `${seconds} 秒`
}

function shortConversationTitle(conversation: Conversation | null, fallbackId?: string): string {
  if (conversation?.title) return conversation.title
  if (fallbackId) return `对话 ${String(fallbackId).slice(0, 8)}…`
  return '未选择'
}

function runStatusLabel(status: string | undefined): string {
  if (status === 'completed') return '完成'
  if (status === 'failed') return '失败'
  if (status === 'pending') return '待运行'
  return '运行中'
}

function runStatusTone(status: string | undefined): 'completed' | 'failed' | 'processing' {
  if (status === 'completed') return 'completed'
  if (status === 'failed') return 'failed'
  return 'processing'
}

function numericSummaryValue(run: RagasRun | null | undefined, key: string): number | null {
  const value = run?.summary?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function averageCost(runs: RagasRun[]): number | null {
  const costs = runs
    .map((run) => numericSummaryValue(run, 'total_cost'))
    .filter((value): value is number => typeof value === 'number')
  if (!costs.length) return null
  return costs.reduce((sum, value) => sum + value, 0) / costs.length
}

function totalCost(runs: RagasRun[]): number | null {
  const costs = runs
    .map((run) => numericSummaryValue(run, 'total_cost'))
    .filter((value): value is number => typeof value === 'number')
  if (!costs.length) return null
  return costs.reduce((sum, value) => sum + value, 0)
}

function percentile(values: number[], percentileValue: number): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((percentileValue / 100) * sorted.length) - 1))
  return sorted[index]
}

function scoreRowsFor(detail: RagasRunDetail | null, summary: Record<string, any>) {
  const metrics = detail?.run?.metrics?.length
    ? detail.run.metrics
    : Object.entries(summary)
      .filter(([, value]) => typeof value === 'number')
      .map(([key]) => key)
      .filter((key) => !['items', 'total_tokens', 'total_cost'].includes(key))

  return metrics.map((key) => {
    const itemValues = (detail?.items || [])
      .map((item) => item.scores?.[key])
      .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
    const mean = itemValues.length ? itemValues.reduce((sum, value) => sum + value, 0) / itemValues.length : Number(summary[key])
    const passCount = itemValues.filter((value) => value >= 0.8).length

    return {
      key,
      label: metricLabel(key),
      mean: Number.isFinite(mean) ? mean : null,
      p50: percentile(itemValues, 50),
      p90: percentile(itemValues, 90),
      passRate: itemValues.length ? passCount / itemValues.length : null,
    }
  })
}

function itemHasLowScore(item: RagasRunDetail['items'][number], metricKeys: string[]): boolean {
  return metricKeys.some((key) => {
    const value = item.scores?.[key]
    return typeof value === 'number' && value < 0.8
  })
}

function EvaluationConfigSection({
  title,
  description,
  children,
  className,
  icon: Icon,
}: Readonly<{
  title: string
  description?: string
  children: ReactNode
  className?: string
  icon?: typeof MessageSquare
}>) {
  return (
    <section className={cn('border-b border-slate-200/80 px-3 py-2.5 last:border-b-0', className)}>
      <div className="flex items-start gap-2.5">
        {Icon ? (
          <span className="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-md border border-sky-200/60 bg-sky-100/70 text-sky-700">
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
        ) : null}
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{title}</div>
          {description ? <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      <div className="mt-2">{children}</div>
    </section>
  )
}

function EvaluationInlineStat({
  label,
  value,
}: Readonly<{
  label: string
  value: ReactNode
}>) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-md border border-slate-200/80 bg-card/90 px-2 py-0.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]">
      <span className="text-[9px] font-medium uppercase tracking-[0.14em] text-muted-foreground">{label}</span>
      <span className="font-mono text-[11px] font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  )
}

function EvaluationHeroEmptyState({
  title,
  description,
  density = 'default',
}: Readonly<{
  title: string
  description: string
  density?: 'default' | 'compact'
}>) {
  const compact = density === 'compact'

  return (
    <div
      className={cn(
        'flex rounded-xl border border-dashed border-slate-200 bg-slate-50/55',
        compact
          ? 'min-h-[148px] flex-row items-center justify-start gap-3 px-3 py-2.5 text-left'
          : 'min-h-[188px] flex-col items-center justify-center px-6 py-8 text-center'
      )}
    >
      {compact ? (
        <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-blue-100 bg-white text-blue-600 shadow-[0_8px_20px_rgba(37,99,235,0.10)]">
          <BarChart3 className="h-4 w-4" aria-hidden="true" />
        </span>
      ) : (
        <div className="relative mb-3 h-16 w-20">
          <div className="absolute left-5 top-1 h-14 w-12 rounded-xl border border-blue-100 bg-white shadow-[0_10px_28px_rgba(37,99,235,0.12)]" />
          <div className="absolute left-8 top-0 h-4 w-6 rounded-md bg-blue-100 ring-1 ring-blue-200" />
          <div className="absolute left-9 top-9 h-3 w-2 rounded-sm bg-blue-300" />
          <div className="absolute left-12 top-7 h-5 w-2 rounded-sm bg-blue-400" />
          <div className="absolute left-[60px] top-5 h-7 w-2 rounded-sm bg-blue-500" />
        </div>
      )}
      <div className={cn(compact && 'min-w-0')}>
        <div className={cn('font-semibold text-slate-950', compact ? 'text-[13px]' : 'text-[14px]')}>{title}</div>
        <p className={cn('max-w-xl text-[12px] text-slate-500', compact ? 'mt-1 leading-4' : 'mt-2 leading-5')}>{description}</p>
      </div>
    </div>
  )
}

function DashboardStatCard({
  icon: Icon,
  label,
  value,
  helper,
  tone = 'blue',
  sparkline = false,
}: Readonly<{
  icon: LucideIcon
  label: string
  value: ReactNode
  helper?: ReactNode
  tone?: 'blue' | 'green' | 'red' | 'slate'
  sparkline?: boolean
}>) {
  const toneClass = {
    blue: 'bg-blue-50 text-blue-600 ring-blue-100',
    green: 'bg-emerald-50 text-emerald-600 ring-emerald-100',
    red: 'bg-rose-50 text-rose-600 ring-rose-100',
    slate: 'bg-slate-100 text-slate-600 ring-slate-200',
  }[tone]

  return (
    <div className="relative min-h-[76px] rounded-xl border border-slate-200 bg-white p-2.5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex items-start gap-1.5">
        <span className={cn('inline-flex h-6 w-6 items-center justify-center rounded-full ring-1', toneClass)}>
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        {sparkline ? (
          <svg className="absolute right-2.5 top-8 h-6 w-14 text-blue-300" viewBox="0 0 64 28" aria-hidden="true">
            <path d="M2 20 C 9 20, 9 10, 15 14 S 25 24, 32 12 S 42 6, 48 13 S 55 24, 62 17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <path d="M2 22 C 9 22, 9 12, 15 16 S 25 26, 32 14 S 42 8, 48 15 S 55 26, 62 19 L62 28 L2 28 Z" fill="currentColor" opacity="0.16" />
          </svg>
        ) : null}
        <div className="min-w-0">
          <div className="text-[12px] font-medium text-slate-600">{label}</div>
          <div className="mt-0.5 whitespace-nowrap text-[16px] font-semibold leading-tight tracking-tight text-slate-950">{value}</div>
          {helper ? <div className="mt-1 text-[11px] text-slate-500">{helper}</div> : null}
        </div>
      </div>
    </div>
  )
}

function RunRecordCard({
  active,
  conversation,
  run,
  onClick,
}: Readonly<{
  active: boolean
  conversation: Conversation | null
  run: RagasRun
  onClick: () => void
}>) {
  const samples = run.summary?.items ?? run.params?.max_turns ?? '-'
  const metrics = run.metrics?.length || '-'
  const progress = run.status === 'running' || run.status === 'pending' ? 60 : null

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full rounded-xl border bg-white p-3 text-left shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all hover:border-blue-200 hover:bg-blue-50/25 focus-ring',
        active ? 'border-blue-300 ring-1 ring-blue-100' : 'border-slate-200'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 text-[12px] font-semibold text-slate-950">
          <div className="truncate">{shortConversationTitle(conversation, run.conversation_id)}</div>
        </div>
        <StatusBadge status={runStatusTone(run.status)} label={runStatusLabel(run.status)} dense />
      </div>
      <div className="mt-2 space-y-1 text-[11px] leading-4 text-slate-500">
        <div>运行时间：{formatDateTime(run.created_at)}</div>
        <div className="flex items-center gap-5">
          <span>轮次：{samples}</span>
          <span>指标：{metrics}</span>
        </div>
      </div>
      {progress !== null ? (
        <div className="mt-3 flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-blue-600" style={{ width: `${progress}%` }} />
          </div>
          <span className="text-[11px] tabular-nums text-slate-500">{progress}%</span>
        </div>
      ) : null}
      {run.status === 'failed' && run.error_message ? (
        <div className="mt-2 line-clamp-1 text-[11px] font-medium text-rose-600">错误：{run.error_message}</div>
      ) : (
        <div className="mt-2 text-right text-[11px] text-slate-500">耗时：{formatRunDuration(run)}</div>
      )}
    </button>
  )
}

function ScoreDetailsCard({
  rows,
}: Readonly<{
  rows: ReturnType<typeof scoreRowsFor>
}>) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-2">
        <div className="text-[13px] font-semibold text-slate-950">评分明细</div>
        <Info className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
      </div>
      {rows.length ? (
        <div className="overflow-auto">
          <table className="w-full text-left text-[12px]">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-3 py-1.5 font-medium">指标</th>
                <th className="px-3 py-1.5 font-medium">平均分</th>
                <th className="px-3 py-1.5 font-medium">P50</th>
                <th className="px-3 py-1.5 font-medium">P90</th>
                <th className="px-3 py-1.5 font-medium">通过率（≥0.8）</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((row) => (
                <tr key={row.key}>
                  <td className="px-3 py-1.5 font-medium text-slate-900">{row.label}</td>
                  <td className="px-3 py-1.5 tabular-nums text-slate-700">{row.mean === null ? '-' : row.mean.toFixed(3)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-slate-700">{row.p50 === null ? '-' : row.p50.toFixed(3)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-slate-700">{row.p90 === null ? '-' : row.p90.toFixed(3)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-slate-700">{formatPercentValue(row.passRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-3 py-2.5">
          <EvaluationHeroEmptyState density="compact" title="暂无评分数据" description="运行完成后将在此处展示各指标的汇总得分与统计。" />
        </div>
      )}
    </section>
  )
}

function IterationDetailsCard({
  items,
  metricKeys,
  onlyFailures,
  onOnlyFailuresChange,
  onExport,
}: Readonly<{
  items: RagasRunDetail['items']
  metricKeys: string[]
  onlyFailures: boolean
  onOnlyFailuresChange: (checked: boolean) => void
  onExport: () => void
}>) {
  const visibleItems = onlyFailures ? items.filter((item) => itemHasLowScore(item, metricKeys)) : items

  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="text-[13px] font-semibold text-slate-950">逐轮明细</div>
          <Info className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
        </div>
        <div className="flex items-center gap-2">
          <label className="inline-flex items-center gap-2 text-[12px] text-slate-500">
            仅看异常
            <Checkbox checked={onlyFailures} onCheckedChange={(value) => onOnlyFailuresChange(value === true)} />
          </label>
          <Button variant="outline" className="h-7 rounded-lg border-slate-200 bg-white px-2.5 text-[12px]" disabled={!items.length} onClick={onExport}>
            导出
          </Button>
        </div>
      </div>
      {visibleItems.length ? (
        <div className="max-h-[276px] overflow-auto">
          <table aria-label="逐轮评分明细" className="w-full min-w-[760px] text-left text-[12px]">
            <thead className="sticky top-0 z-10 bg-slate-50 text-slate-500">
              <tr>
                <th className="w-16 px-3 py-1.5 font-medium">轮次</th>
                <th className="min-w-[160px] px-3 py-1.5 font-medium">问题</th>
                <th className="min-w-[180px] px-3 py-1.5 font-medium">答案摘要</th>
                {metricKeys.map((metricKey) => (
                  <th key={metricKey} className="w-28 px-3 py-1.5 font-medium">
                    {metricLabel(metricKey)}
                  </th>
                ))}
                <th className="w-20 px-3 py-1.5 font-medium">状态</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visibleItems.map((item) => {
                const anomaly = itemHasLowScore(item, metricKeys)
                return (
                  <tr key={item.id} className="align-top hover:bg-slate-50/80">
                    <td className="px-3 py-1.5 tabular-nums text-slate-500">{item.turn_index}</td>
                    <td className="px-3 py-1.5">
                      <div className="line-clamp-2 text-slate-800">{item.user_input}</div>
                    </td>
                    <td className="px-3 py-1.5">
                      <div className="line-clamp-2 text-slate-600">{item.response}</div>
                    </td>
                    {metricKeys.map((metricKey) => {
                      const value = item.scores?.[metricKey]
                      const isNum = typeof value === 'number' && Number.isFinite(value)
                      return (
                        <td key={metricKey} className="px-3 py-1.5 tabular-nums text-slate-700">
                          {isNum ? value.toFixed(3) : '-'}
                        </td>
                      )
                    })}
                    <td className="px-3 py-1.5">
                      <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-medium', anomaly ? 'bg-rose-50 text-rose-600' : 'bg-emerald-50 text-emerald-600')}>
                        {anomaly ? '异常' : '正常'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-3 py-2.5">
          <EvaluationHeroEmptyState density="compact" title="暂无轮次数据" description="运行完成后将按轮展示详细评分。" />
        </div>
      )}
    </section>
  )
}

export default function EvaluationsPage() {
  return (
    <AppFrame>
      <Suspense fallback={<EvaluationsLoading />}>
        <EvaluationsPageContent />
      </Suspense>
    </AppFrame>
  )
}

function EvaluationsLoading() {
  return (
    <PageLoading message="正在加载评测数据..." srMessage="Loading evaluations" />
  )
}

function EvaluationsPageContent() {
  const searchParams = useSearchParams()
  const [activeTab, setActiveTab] = useState<TabType>(() => parseEvaluationTab(searchParams.get('tab')) || 'conversation')
  const isActiveTab = (tab: TabType) => activeTab === tab
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConversationId, setSelectedConversationId] = useState<string>('')

  const [runs, setRuns] = useState<RagasRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [runDetail, setRunDetail] = useState<RagasRunDetail | null>(null)

  const [metricKeys, setMetricKeys] = useState<string[]>([
    'faithfulness',
    'response_relevancy',
  ])
  const [maxTurns, setMaxTurns] = useState(20)
  const [skipEmptyContexts, setSkipEmptyContexts] = useState(true)
  const [onlyFailureItems, setOnlyFailureItems] = useState(false)
  const [isRunRecordsCollapsed, setIsRunRecordsCollapsed] = useState(false)

  const [isLoading, setIsLoading] = useState(false)
  const [isStarting, setIsStarting] = useState(false)

  // Support deep-linking: /evaluations?conversation_id=...
  useEffect(() => {
    const cid = searchParams.get('conversation_id')
    if (cid) setSelectedConversationId(cid)
  }, [searchParams])

  // Support deep-linking: /evaluations?tab=regression|conversation
  useEffect(() => {
    const tab = parseEvaluationTab(searchParams.get('tab'))
    if (tab) setActiveTab(tab)
  }, [searchParams])

  const loadConversations = useCallback(async () => {
    try {
      const res = await chatApi.listConversations({ limit: 100 })
      setConversations(res.items || [])
      setSelectedConversationId((prev) => prev || res.items?.[0]?.id || '')
    } catch (e) {
      console.error('Failed to load conversations', e)
    }
  }, [])

  const loadRuns = useCallback(async (conversationId?: string) => {
    try {
      const res = await evaluationApi.listRagasRuns({
        limit: 50,
        conversation_id: conversationId || undefined,
      })
      setRuns(res.items || [])
    } catch (e) {
      console.error('Failed to load runs', e)
    }
  }, [])

  // Initial data
  useEffect(() => {
    setIsLoading(true)
    Promise.all([loadConversations(), loadRuns()]).finally(() => setIsLoading(false))
  }, [loadConversations, loadRuns])

  // When switching conversation, reset the detail area but keep the right rail on real recent runs.
  useEffect(() => {
    if (!selectedConversationId) return
    setSelectedRunId('')
    setRunDetail(null)
  }, [selectedConversationId])

  // Poll run detail
  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null)
      return
    }

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const fetchDetail = async () => {
      try {
        const detail = await evaluationApi.getRagasRun(selectedRunId, {
          include_items: true,
          include_contexts: false,
        })
        if (cancelled) return
        setRunDetail(detail)
        const status = detail?.run?.status
        if (status === 'pending' || status === 'running') {
          timer = setTimeout(fetchDetail, 2000)
        }
      } catch (e) {
        if (!cancelled) console.error('Failed to load run detail', e)
      }
    }

    fetchDetail()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [selectedRunId])

  const handleStart = async () => {
    if (!selectedConversationId) return
    setIsStarting(true)
    try {
      const run = await evaluationApi.createRagasRun({
        conversation_id: selectedConversationId,
        metrics: metricKeys,
        max_turns: maxTurns,
        skip_empty_contexts: skipEmptyContexts,
        include_contexts_in_response: false,
      })
      await loadRuns()
      setSelectedRunId(run.id)
    } catch (e) {
      console.error('Failed to start evaluation', e)
      toast.error(formatApiError(e, '启动评测失败'))
    } finally {
      setIsStarting(false)
    }
  }

  const summary = useMemo(() => runDetail?.run?.summary || {}, [runDetail?.run?.summary])
  const displayMetrics = useMemo(() => {
    const ignore = new Set(['items', 'total_tokens', 'total_cost'])
    return Object.entries(summary)
      .filter(([k, v]) => !ignore.has(k) && typeof v === 'number')
      .map(([k, v]) => ({ key: k, value: Number(v) }))
  }, [summary])

  const runErrorMessage = String(runDetail?.run?.error_message || '').trim()

  const runStatus = runDetail?.run?.status
  const statusBadge = useMemo(() => {
    if (!runStatus) return null

    const status = runStatus === 'completed' ? 'completed' : runStatus === 'failed' ? 'failed' : 'processing'
    const label = runStatus === 'completed' ? '已完成' : runStatus === 'failed' ? '失败' : '运行中'
    const badge = <StatusBadge status={status} label={label} dense />

    if (runStatus === 'failed' && runErrorMessage) {
      return (
        <span className="inline-flex cursor-help" title={runErrorMessage} aria-label="失败原因，悬停查看">
          {badge}
        </span>
      )
    }

    return badge
  }, [runErrorMessage, runStatus])

  const activeTabMeta = TAB_META.find((item) => item.id === activeTab) || TAB_META[0]
  const ActiveTabIcon = activeTabMeta.icon
  const selectedConversation = conversations.find((conversation) => conversation.id === selectedConversationId) || null
  const runStatusCounts = useMemo(() => {
    return runs.reduce(
      (acc, run) => {
        if (run.status === 'completed') acc.completed += 1
        else if (run.status === 'failed') acc.failed += 1
        else acc.running += 1
        return acc
      },
      { completed: 0, failed: 0, running: 0 }
    )
  }, [runs])
  const selectedRun = runDetail?.run || runs.find((run) => run.id === selectedRunId) || null
  const scoreRows = useMemo(() => scoreRowsFor(runDetail, summary), [runDetail, summary])
  const detailMetricKeys = runDetail?.run?.metrics?.length ? runDetail.run.metrics : metricKeys
  const visibleRuns = runs
  const topAverageCost = averageCost(runs)
  const topTotalCost = totalCost(runs)
  const completedRate = runs.length ? runStatusCounts.completed / runs.length : null
  const runningRate = runs.length ? runStatusCounts.running / runs.length : null
  const failedRate = runs.length ? runStatusCounts.failed / runs.length : null
  const selectedRunConversation = selectedRun?.conversation_id
    ? conversations.find((conversation) => conversation.id === selectedRun.conversation_id) || null
    : selectedConversation
  const selectedRunTitle = shortConversationTitle(selectedRunConversation, selectedRun?.conversation_id || selectedConversationId)

  const handleConversationChange = (conversationId: string) => {
    setSelectedConversationId(conversationId)
    setSelectedRunId('')
    setRunDetail(null)
  }

  const handleExportItems = () => {
    const blob = new Blob([JSON.stringify(runDetail?.items || [], null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `ragas-run-items.${selectedRunId || 'latest'}.json`
    anchor.click()
    globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden bg-slate-50/70">
      <AnalysisPageShell
        title="评测中心"
        description="把实时会话评测、回归测试与检索集健康度放到同一个工作台里，减少来回切页。"
        icon={BarChart3}
        iconColor="text-primary"
        badge="评测"
        size="full"
        showHeader={false}
        bodyGutter="none"
        bodyClassName="!pb-0"
        bodyContainerClassName="max-w-none"
      >
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto px-5 py-2">
          <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
              <div className="text-[12px] font-medium text-slate-500">评测中心 · 统一工作台</div>
              <h1 className="mt-1 text-[24px] font-semibold tracking-tight text-slate-950">{activeTabMeta.title}</h1>
              <p className="mt-1 text-[13px] leading-5 text-slate-500">选择评测指标及参数，在同一工作区完成参数配置、运行快捷与结果评估。</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex h-8 items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 text-[12px] font-semibold text-blue-700">
                <ActiveTabIcon className="h-3.5 w-3.5" aria-hidden="true" />
                {activeTabMeta.label}
              </span>
              <EvaluationInlineStat label="会话" value={conversations.length} />
              <EvaluationInlineStat label="运行中" value={runStatusCounts.running} />
              <EvaluationInlineStat label="完成" value={runStatusCounts.completed} />
              <EvaluationInlineStat label="失败" value={runStatusCounts.failed} />
            </div>
          </header>

          <nav className="flex items-center gap-6 border-b border-slate-200">
            {TAB_META.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'relative inline-flex h-10 items-center gap-2 text-[13px] font-medium transition-colors',
                  isActiveTab(tab.id) ? 'text-blue-700' : 'text-slate-500 hover:text-slate-900'
                )}
              >
                <tab.icon className="h-3.5 w-3.5" aria-hidden="true" />
                {tab.label}
                {isActiveTab(tab.id) ? <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-blue-600" /> : null}
              </button>
            ))}
          </nav>

          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8">
            <DashboardStatCard icon={MessageSquare} label="模式" value={activeTab === 'conversation' ? '实时会话' : activeTabMeta.label} helper="当前模式" />
            <DashboardStatCard icon={Database} label="会话数" value={conversations.length} helper="近 7 天" tone="slate" />
            <DashboardStatCard icon={ListChecks} label="运行数" value={runs.length} helper="近 7 天" tone="slate" />
            <DashboardStatCard icon={CheckCircle2} label="完成" value={runStatusCounts.completed} helper={formatPercentValue(completedRate)} tone="green" />
            <DashboardStatCard icon={Gauge} label="运行中" value={runStatusCounts.running} helper={formatPercentValue(runningRate)} />
            <DashboardStatCard icon={XCircle} label="失败" value={runStatusCounts.failed} helper={formatPercentValue(failedRate)} tone="red" />
            <DashboardStatCard icon={TrendingUp} label="平均开销" value={`${formatMoney(topAverageCost)}/轮`} helper="按返回 runs 计算" sparkline />
            <DashboardStatCard icon={CircleDollarSign} label="LLM 成本" value={formatMoney(topTotalCost)} helper="近 7 天" tone="slate" />
          </div>

          {activeTab === 'conversation' ? (
            <div className="grid min-h-[650px] gap-3 xl:grid-cols-[270px_minmax(0,1fr)_280px]">
              <aside className="flex min-h-0 max-h-[calc(100vh-282px)] flex-col rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
                <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2.5">
                  <div className="inline-flex items-center gap-2 text-[14px] font-semibold text-slate-950">
                    <SlidersHorizontal className="h-4 w-4 text-slate-500" aria-hidden="true" />
                    参数设置
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 rounded-md px-2 text-[11px] text-slate-500"
                    onClick={() => {
                      setMetricKeys(['faithfulness', 'response_relevancy'])
                      setMaxTurns(20)
                      setSkipEmptyContexts(true)
                    }}
                  >
                    <RefreshCw className="mr-1 h-3.5 w-3.5" />
                    重置
                  </Button>
                </div>

                <div className="min-h-0 flex-1 divide-y divide-slate-200 overflow-y-auto">
                  <EvaluationConfigSection
                    icon={Database}
                    title="对话来源"
                    description="从已有会话里选一条对话，评测会按用户-助手轮次重建上下文。"
                  >
                    <Select value={selectedConversationId} onValueChange={handleConversationChange}>
                      <SelectTrigger className="h-9 rounded-lg border-slate-200 bg-white text-xs">
                        <SelectValue placeholder="请选择会话或查询" />
                      </SelectTrigger>
                      <SelectContent>
                        {conversations.map((conversation) => (
                          <SelectItem key={conversation.id} value={conversation.id}>
                            {conversation.title || conversation.id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <EvaluationInlineStat label="已选" value={selectedConversation ? '1' : '0'} />
                      <EvaluationInlineStat label="总数" value={conversations.length} />
                    </div>
                  </EvaluationConfigSection>

                  <EvaluationConfigSection
                    icon={Sparkles}
                    title="评测指标（至少选择 1 项）"
                    description="指标越多，耗时与 token 成本越高。默认保留最核心两项。"
                  >
                    <RagasMetricSelector
                      metricKeys={metricKeys}
                      onMetricKeysChange={setMetricKeys}
                      scope="conversation"
                      className="space-y-1.5"
                      itemClassName="rounded-lg border border-slate-200 bg-white px-2 py-1 shadow-sm"
                      labelClassName="text-[11px]"
                      hintClassName="text-[10px] leading-3"
                    />
                  </EvaluationConfigSection>

                  <EvaluationConfigSection
                    icon={Filter}
                    title="过滤条件"
                    description="控制抽取最近多少轮，以及是否过滤掉无引用上下文的轮次。"
                    className="border-b-0"
                  >
                    <div className="grid gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="max-turns" className="text-[12px] font-medium text-slate-600">
                          最近轮次
                        </Label>
                        <Input
                          id="max-turns"
                          type="number"
                          min={1}
                          max={200}
                          value={maxTurns}
                          onChange={(e) => setMaxTurns(Number(e.target.value))}
                          className="h-9 rounded-lg border-slate-200 bg-white text-xs"
                        />
                      </div>

                      <label className="flex items-start gap-2.5 rounded-lg border border-slate-200 bg-white px-2.5 py-2 shadow-sm">
                        <Checkbox checked={skipEmptyContexts} onCheckedChange={(value) => setSkipEmptyContexts(value === true)} />
                        <span className="space-y-0.5">
                          <span className="block text-[12px] font-medium text-slate-900">跳过无引用轮次</span>
                          <span className="block text-[11px] leading-4 text-slate-500">减少空样本干扰，让结果更接近真实 RAG 场景。</span>
                        </span>
                      </label>
                    </div>
                  </EvaluationConfigSection>
                </div>

                <div className="shrink-0 border-t border-slate-200 p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <EvaluationInlineStat label="指标数" value={metricKeys.length} />
                    <EvaluationInlineStat label="轮次" value={maxTurns} />
                    <EvaluationInlineStat label="过滤" value={skipEmptyContexts ? '已启用' : '关闭'} />
                  </div>
                  <Button className="h-9 w-full rounded-lg bg-blue-600 text-[13px] font-semibold text-white hover:bg-blue-700" disabled={isStarting || !selectedConversationId || !metricKeys.length} onClick={handleStart}>
                    {isStarting ? <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" /> : <PlayCircle className="mr-2 h-4 w-4" />}
                    开始评测
                  </Button>
                  <Button
                    variant="outline"
                    className="mt-2 h-8 w-full rounded-lg border-slate-200 bg-white text-[12px]"
                    onClick={() => {
                      setIsLoading(true)
                      Promise.all([loadConversations(), loadRuns()]).finally(() => setIsLoading(false))
                    }}
                  >
                    <RefreshCw className={cn('mr-2 h-3.5 w-3.5', isLoading && 'animate-spin motion-reduce:animate-none')} />
                    刷新会话与运行
                  </Button>
                </div>
              </aside>

              <main className="min-w-0 space-y-3">
                <section className="grid overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] sm:grid-cols-4">
                  <div className="border-b border-slate-200 px-3 py-2.5 sm:border-b-0 sm:border-r">
                    <div className="inline-flex items-center gap-1.5 text-[12px] font-medium text-blue-700"><MessageSquare className="h-3.5 w-3.5" />当前对话</div>
                    <div className="mt-1 truncate text-[13px] font-semibold text-slate-950">{selectedRunTitle}</div>
                  </div>
                  <div className="border-b border-slate-200 px-3 py-2.5 sm:border-b-0 sm:border-r">
                    <div className="inline-flex items-center gap-1.5 text-[12px] font-medium text-slate-600"><ListChecks className="h-3.5 w-3.5" />样本数</div>
                    <div className="mt-1 text-[15px] font-semibold tabular-nums text-slate-950">{formatCompactCount(summary.items)}</div>
                  </div>
                  <div className="border-b border-slate-200 px-3 py-2.5 sm:border-b-0 sm:border-r">
                    <div className="inline-flex items-center gap-1.5 text-[12px] font-medium text-blue-700"><BarChart3 className="h-3.5 w-3.5" />令牌开销</div>
                    <div className="mt-1 text-[15px] font-semibold tabular-nums text-slate-950">{formatCompactCount(summary.total_tokens)}</div>
                  </div>
                  <div className="px-3 py-2.5">
                    <div className="inline-flex items-center gap-1.5 text-[12px] font-medium text-slate-600"><Sparkles className="h-3.5 w-3.5" />LLM 成本（本次运行）</div>
                    <div className="mt-1 text-[15px] font-semibold tabular-nums text-slate-950">{formatMoney(summary.total_cost)}</div>
                  </div>
                </section>

                <section className="rounded-xl border border-slate-200 bg-white p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-[14px] font-semibold text-slate-950">运行详情</div>
                    {statusBadge}
                  </div>
                  {displayMetrics.length ? (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                      {displayMetrics.map((metric) => (
                        <div key={metric.key} className="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2">
                          <div className="text-[12px] text-slate-500">{metricLabel(metric.key)}</div>
                          <div className="mt-1 text-[18px] font-semibold tabular-nums text-slate-950">{metric.value.toFixed(3)}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-3">
                      <EvaluationHeroEmptyState
                        title={selectedRunId ? '暂无运行记录' : '暂无运行记录'}
                        description={selectedRunId ? '这条 run 可能仍在处理中，或者后端尚未返回 summary 分数。' : '请先在左侧选择对话、指标与参数，然后点击「开始评测」运行。'}
                      />
                    </div>
                  )}
                  <div className="mx-auto mt-3 grid max-w-xl grid-cols-3 overflow-hidden rounded-lg border border-slate-200 bg-white text-center text-[12px] text-slate-500">
                    <div className="px-3 py-2">
                      <div className="font-semibold text-blue-700">1 选择会话来源</div>
                      <div className="mt-1">从已有会话或查询中选择</div>
                    </div>
                    <div className="border-l border-slate-200 px-3 py-2">
                      <div className="font-semibold text-blue-700">2 配置评测参数</div>
                      <div className="mt-1">选择指标与过滤规则</div>
                    </div>
                    <div className="border-l border-slate-200 px-3 py-2">
                      <div className="font-semibold text-blue-700">3 开始评测</div>
                      <div className="mt-1">流程完成后查看结果</div>
                    </div>
                  </div>
                </section>

                <div className="grid gap-3 xl:grid-cols-[0.85fr_1.25fr]">
                  <ScoreDetailsCard rows={scoreRows} />
                  <IterationDetailsCard
                    items={runDetail?.items || []}
                    metricKeys={detailMetricKeys}
                    onlyFailures={onlyFailureItems}
                    onOnlyFailuresChange={setOnlyFailureItems}
                    onExport={handleExportItems}
                  />
                </div>
              </main>

              <aside className="flex max-h-[calc(100vh-282px)] min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
                <div className="mb-3 flex shrink-0 items-center justify-between gap-3">
                  <button
                    type="button"
                    className="inline-flex min-w-0 items-center gap-2 text-left text-[14px] font-semibold text-slate-950 focus-ring"
                    onClick={() => setIsRunRecordsCollapsed((value) => !value)}
                    aria-expanded={!isRunRecordsCollapsed}
                    aria-controls="ragas-run-records-list"
                  >
                    <ListChecks className="h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
                    <span className="truncate">运行记录</span>
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                      {runs.length}
                    </span>
                    <ChevronDown className={cn('h-3.5 w-3.5 text-slate-400 transition-transform', isRunRecordsCollapsed && '-rotate-90')} aria-hidden="true" />
                  </button>
                  <Button variant="ghost" className="h-7 shrink-0 px-2 text-[12px] text-blue-700" onClick={() => loadRuns()}>
                    刷新
                  </Button>
                </div>

                <div
                  id="ragas-run-records-list"
                  className={cn(
                    'grid min-h-0 transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none',
                    isRunRecordsCollapsed ? 'grid-rows-[0fr] opacity-0' : 'grid-rows-[1fr] opacity-100'
                  )}
                >
                  <div className="min-h-0 overflow-hidden">
                    {visibleRuns.length ? (
                      <div className="max-h-[520px] min-h-0 space-y-2 overflow-y-auto overscroll-contain pr-1 no-scrollbar">
                        {visibleRuns.map((run) => (
                          <RunRecordCard
                            key={run.id}
                            active={selectedRunId === run.id}
                            run={run}
                            conversation={run.conversation_id ? conversations.find((conversation) => conversation.id === run.conversation_id) || null : null}
                            onClick={() => setSelectedRunId(run.id)}
                          />
                        ))}
                      </div>
                    ) : (
                      <EvaluationHeroEmptyState title="暂无评测记录" description="运行一次评测后，这里会出现真实 run 记录。" />
                    )}
                  </div>
                </div>

                {isRunRecordsCollapsed ? (
                  <div className="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-[11px] text-slate-500">
                    已收起 {runs.length} 条运行记录，点击标题展开后在列表内上滑查看。
                  </div>
                ) : null}
              </aside>
            </div>
          ) : activeTab === 'regression' ? (
            <div className="flex h-[calc(100vh-285px)] min-h-[650px] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <RegressionTestTab embedded />
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <QuerysetHealthTab embedded />
            </div>
          )}

        </div>
      </AnalysisPageShell>
    </div>
  )
}
