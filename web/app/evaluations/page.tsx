'use client'

/**
 * RAGAS 评测页面 - 支持 Tab 切换
 * Tab 1: 对话评测（基于对话历史）
 * Tab 2: 回归测试（基于测试用例）
 * Tab 3: Queryset Health（检索基准集健康度）
 */

import {
  Suspense,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { AppFrame } from '@/components/app-frame'
import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { PageLoading } from '@/components/ui/page-loading'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AnalysisPageShell } from '@/components/ui/analysis-page-shell'
import { PageHeader } from '@/components/ui/page-header'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import {
  evaluationApi,
  chatApi,
  type RagasRun,
  type RagasRunDetail,
} from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { Link } from '@/i18n/navigation'
import { canShowAdminControlledNavigationModule } from '@/lib/navigation-visibility'
import type { Conversation, JsonObject, Message } from '@/types'
import {
  BarChart3,
  ChevronLeft,
  ChevronDown,
  ChevronRight,
  Database,
  Filter,
  Info,
  Loader2,
  ListChecks,
  PlayCircle,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  MessageSquare,
  TestTube2,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'
import { RegressionTestTab } from '@/components/evaluation/regression-tab'
import { QuerysetHealthTab } from '@/components/evaluation/queryset-health-tab'
import {
  RagasMetricSelector,
  ragasMetricLabel,
} from '@/components/evaluation/ragas-metric-selector'

type TabType = 'conversation' | 'regression' | 'queryset_health'
type ConversationEvidenceFilter = 'ready' | 'missing' | 'all'

const EMPTY_CONVERSATIONS: Conversation[] = []
const EMPTY_RUNS: RagasRun[] = []

const CONVERSATION_EVIDENCE_FILTERS: Array<{
  id: ConversationEvidenceFilter
  label: string
}> = [
  { id: 'ready', label: '可评测' },
  { id: 'missing', label: '缺证据' },
  { id: 'all', label: '全部' },
]

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
  if (
    tab === 'regression' ||
    tab === 'conversation' ||
    tab === 'queryset_health'
  )
    return tab
  return null
}

function formatCompactCount(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return Intl.NumberFormat('zh-CN', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(n)
}

function formatMoney(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  if (n === 0) return '¥0'
  if (Math.abs(n) < 0.01) return `¥${n.toFixed(4)}`
  return `¥${n.toFixed(2)}`
}

function formatPercentValue(
  value: number | null | undefined,
  digits = 1
): string {
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
  if (
    !Number.isFinite(started) ||
    !Number.isFinite(finished) ||
    finished < started
  )
    return '-'
  const seconds = Math.max(1, Math.round((finished - started) / 1000))
  return `${seconds} 秒`
}

function shortConversationTitle(
  conversation: Conversation | null,
  fallbackId?: string
): string {
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

function isMissingEvidenceError(message: string | null | undefined): boolean {
  return /missing contexts|missing.*citations|No evaluatable turns/i.test(
    String(message || '')
  )
}

function runStatusTone(
  status: string | undefined
): 'completed' | 'failed' | 'processing' {
  if (status === 'completed') return 'completed'
  if (status === 'failed') return 'failed'
  return 'processing'
}

function numericSummaryValue(
  run: RagasRun | null | undefined,
  key: string
): number | null {
  const value = run?.summary?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function percentile(values: number[], percentileValue: number): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil((percentileValue / 100) * sorted.length) - 1)
  )
  return sorted[index]
}

function scoreRowsFor(
  detail: RagasRunDetail | null,
  summary: JsonObject
) {
  const metrics = detail?.run?.metrics?.length
    ? detail.run.metrics
    : Object.entries(summary)
        .filter(([, value]) => typeof value === 'number')
        .map(([key]) => key)
        .filter((key) => !['items', 'total_tokens', 'total_cost'].includes(key))

  return metrics.map((key) => {
    const itemValues = (detail?.items || [])
      .map((item) => item.scores?.[key])
      .filter(
        (value): value is number =>
          typeof value === 'number' && Number.isFinite(value)
      )
    const mean = itemValues.length
      ? itemValues.reduce((sum, value) => sum + value, 0) / itemValues.length
      : Number(summary[key])
    const passCount = itemValues.filter((value) => value >= 0.8).length

    return {
      key,
      label: metricLabel(key),
      mean: Number.isFinite(mean) ? mean : null,
      p50: percentile(itemValues, 50),
      p90: percentile(itemValues, 90),
      passRate: itemValues.length ? passCount / itemValues.length : null,
    }
  }).filter(
    (row) =>
      row.mean !== null ||
      row.p50 !== null ||
      row.p90 !== null ||
      row.passRate !== null
  )
}

function summarizeConversationEvidence(messages: Message[]) {
  const assistantMessages = messages.filter(
    (message) => message.role === 'assistant'
  )
  const citationsCount = assistantMessages.reduce(
    (sum, message) => sum + (message.citations?.length || 0),
    0
  )
  const evaluableTurns = assistantMessages.filter(
    (message) => (message.citations?.length || 0) > 0
  ).length

  return {
    assistantTurns: assistantMessages.length,
    citationsCount,
    evaluableTurns,
    isEvaluable: evaluableTurns > 0,
  }
}

function itemHasLowScore(
  item: RagasRunDetail['items'][number],
  metricKeys: string[]
): boolean {
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
    <section
      className={cn(
        'border-b border-slate-200/80 px-3 py-2.5 last:border-b-0',
        className
      )}
    >
      <div className="flex items-start gap-2.5">
        {Icon ? (
          <span className="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-md border border-sky-200/60 bg-sky-100/70 text-sky-700">
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
        ) : null}
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
            {title}
          </div>
          {description ? (
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              {description}
            </p>
          ) : null}
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
    <div className="inline-flex items-center gap-2 rounded-full border border-sky-100/60 bg-gradient-to-r from-white to-sky-50/30 px-3 py-1.5 shadow-sm backdrop-blur-sm">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-sky-600/80">
        {label}
      </span>
      <span className="font-mono text-[12px] font-bold tabular-nums text-slate-800">
        {value}
      </span>
    </div>
  )
}

function buildEvidenceReadinessState({
  isChecking,
  isEvaluable,
  isMissingEvidenceFailure,
}: Readonly<{
  isChecking: boolean
  isEvaluable: boolean
  isMissingEvidenceFailure: boolean
}>) {
  const tone = isChecking ? 'checking' : isEvaluable ? 'ready' : 'missing'
  const label =
    tone === 'checking' ? '检查中' : tone === 'ready' ? '可评测' : '缺证据'
  const title =
    tone === 'ready'
      ? '这条会话可以计算忠实度'
      : tone === 'checking'
        ? '正在检查会话证据'
        : '这条会话不能计算忠实度'
  const description =
    tone === 'ready'
      ? 'assistant 消息已写入 citations，Faithfulness 会基于这些证据判断答案是否忠于上下文。'
      : tone === 'checking'
      ? '正在读取会话消息，确认是否有可用于评测的 citations / retrieved contexts。'
      : '这类历史会话可以阅读答案，但没有写入 citations / retrieved contexts；忠实度评测没有输入，不代表答案一定错。'

  return {
    tone,
    label,
    title,
    description,
    showMissingEvidenceFailure: isMissingEvidenceFailure,
  }
}

function EvaluationStageStat({
  label,
  value,
  helper,
}: Readonly<{
  label: string
  value: ReactNode
  helper: string
}>) {
  return (
    <div className="rounded-2xl border border-sky-100/70 bg-gradient-to-br from-white via-slate-50/80 to-sky-50/60 px-3.5 py-3 shadow-sm backdrop-blur-sm">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-slate-500">
        {label}
      </div>
      <div className="mt-1.5 text-[18px] font-bold leading-tight tabular-nums text-slate-900">
        {value}
      </div>
      <div className="mt-1 text-[11px] leading-4 text-slate-500">{helper}</div>
    </div>
  )
}

function EvaluationResultsStage({
  selectedRunTitle,
  statusBadge,
  isChecking,
  isEvaluable,
  assistantTurns,
  citationsCount,
  evaluableTurns,
  isMissingEvidenceFailure,
  summary,
  displayMetrics,
  emptyRunState,
  fillAvailableHeight = false,
  className,
}: Readonly<{
  selectedRunTitle: string
  statusBadge: ReactNode
  isChecking: boolean
  isEvaluable: boolean
  assistantTurns: number
  citationsCount: number
  evaluableTurns: number
  isMissingEvidenceFailure: boolean
  summary: JsonObject
  displayMetrics: Array<{ key: string; value: number }>
  emptyRunState: { title: string; description: string }
  fillAvailableHeight?: boolean
  className?: string
}>) {
  const readiness = buildEvidenceReadinessState({
    isChecking,
    isEvaluable,
    isMissingEvidenceFailure,
  })
  const readinessLabelClassName =
    readiness.tone === 'ready'
      ? 'bg-gradient-to-r from-emerald-100 to-teal-100 text-emerald-700'
      : readiness.tone === 'checking'
        ? 'bg-gradient-to-r from-sky-100 to-blue-100 text-sky-700'
        : 'bg-gradient-to-r from-amber-100 to-orange-100 text-amber-800'

  return (
    <section
      className={cn(
        'overflow-hidden rounded-[28px] border border-sky-100/50 bg-white/85 shadow-lg backdrop-blur-sm',
        'flex flex-col',
        fillAvailableHeight && 'min-h-0 flex-1',
        className
      )}
    >
      <div className="border-b border-sky-100/60 bg-gradient-to-r from-sky-50/45 via-white to-blue-50/30 px-4 py-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="inline-flex h-7 items-center rounded-full border border-sky-200/70 bg-white/85 px-3 text-[11px] font-semibold text-sky-700 shadow-sm">
            运行详情
          </span>
          {statusBadge}
        </div>
        <div className="mt-3 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="line-clamp-2 text-[18px] font-bold leading-tight text-slate-900">
              {selectedRunTitle}
            </div>
            <p className="mt-1.5 max-w-3xl text-[12.5px] leading-5 text-slate-600">
              把忠实度可评估性、当前 run 状态和结果输出收进同一个结果舞台，避免同一条线索被拆成多个孤立块。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <EvaluationInlineStat label="助手轮次" value={assistantTurns} />
            <EvaluationInlineStat label="可评轮次" value={evaluableTurns} />
            <EvaluationInlineStat label="证据" value={citationsCount} />
          </div>
        </div>
      </div>

      <div
        className={cn(
          'grid gap-5 px-4 py-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(240px,0.9fr)]',
          fillAvailableHeight && 'min-h-[420px] flex-1'
        )}
      >
        <div
          className={cn(
            'min-w-0 space-y-3',
            fillAvailableHeight && 'flex h-full flex-col'
          )}
        >
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
              忠实度可评估性
            </div>
            <span
              className={cn(
                'rounded-full px-3 py-1 text-[11px] font-bold shadow-sm',
                readinessLabelClassName
              )}
            >
              {readiness.label}
            </span>
          </div>
          <div className="text-[17px] font-semibold text-slate-900">
            {readiness.title}
          </div>
          <p className="max-w-3xl text-[12.5px] leading-5 text-slate-600">
            {readiness.description}
          </p>
          {readiness.showMissingEvidenceFailure ? (
            <p className="rounded-xl border border-amber-200/70 bg-amber-100/60 px-3 py-2 text-[11.5px] font-semibold leading-5 text-amber-900">
              当前 run 的失败原因是缺少证据，不是 RAGAS 算出低分。
            </p>
          ) : null}

          {!displayMetrics.length ? (
            <div
              className={cn(
                'rounded-2xl border border-dashed border-sky-200/70 bg-gradient-to-br from-slate-50/90 via-white to-sky-50/70 p-4',
                fillAvailableHeight && 'flex flex-1 flex-col justify-between'
              )}
            >
              <div className="text-[14px] font-semibold text-slate-900">
                {emptyRunState.title}
              </div>
              <p className="mt-1.5 max-w-2xl text-[12px] leading-5 text-slate-600">
                {emptyRunState.description}
              </p>
              <div className="mt-4 grid gap-2.5 sm:grid-cols-3">
                <div className="rounded-xl border border-sky-100/70 bg-white/90 px-3 py-2.5 shadow-sm">
                  <div className="text-[11px] font-bold text-sky-700">
                    1 选择会话来源
                  </div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-600">
                    从已有会话或查询中选择
                  </div>
                </div>
                <div className="rounded-xl border border-sky-100/70 bg-white/90 px-3 py-2.5 shadow-sm">
                  <div className="text-[11px] font-bold text-sky-700">
                    2 配置评测参数
                  </div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-600">
                    选择指标与过滤规则
                  </div>
                </div>
                <div className="rounded-xl border border-sky-100/70 bg-white/90 px-3 py-2.5 shadow-sm">
                  <div className="text-[11px] font-bold text-sky-700">
                    3 开始评测
                  </div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-600">
                    流程完成后查看结果
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-1">
          <EvaluationStageStat
            label="评测样本"
            value={formatCompactCount(summary.items)}
            helper="当前 run 纳入统计的轮次数"
          />
          <EvaluationStageStat
            label="令牌开销"
            value={formatCompactCount(summary.total_tokens)}
            helper="本次运行累计的 token 消耗"
          />
          <EvaluationStageStat
            label="LLM 成本"
            value={formatMoney(summary.total_cost)}
            helper="本次运行产生的模型成本"
          />
        </div>
      </div>

      {displayMetrics.length ? (
        <div className="border-t border-sky-100/60 bg-gradient-to-b from-slate-50/60 to-white px-4 py-4">
          <div className="mb-3 flex flex-wrap items-center gap-2.5">
            <div className="inline-flex items-center gap-2 text-[14px] font-bold text-slate-900">
              <BarChart3 className="h-4 w-4 text-sky-600" aria-hidden="true" />
              得分概览
            </div>
            <span className="rounded-full border border-sky-200/70 bg-white px-2.5 py-1 text-[10.5px] font-semibold text-sky-700 shadow-sm">
              {displayMetrics.length} 项指标
            </span>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2 2xl:grid-cols-3">
            {displayMetrics.map((metric) => (
              <div
                key={metric.key}
                className="rounded-2xl border border-sky-100/60 bg-white/90 px-3.5 py-3 shadow-sm"
              >
                <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-sky-700">
                  {metricLabel(metric.key)}
                </div>
                <div className="mt-1.5 text-[22px] font-bold leading-none tabular-nums text-slate-900">
                  {metric.value.toFixed(3)}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
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
        <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-blue-100 bg-card text-blue-600 shadow-[0_8px_20px_rgba(37,99,235,0.10)]">
          <BarChart3 className="h-4 w-4" aria-hidden="true" />
        </span>
      ) : (
        <div className="relative mb-3 h-16 w-20">
          <div className="absolute left-5 top-1 h-14 w-12 rounded-xl border border-blue-100 bg-card shadow-[0_10px_28px_rgba(37,99,235,0.12)]" />
          <div className="absolute left-8 top-0 h-4 w-6 rounded-md bg-blue-100 ring-1 ring-blue-200" />
          <div className="absolute left-9 top-9 h-3 w-2 rounded-sm bg-blue-300" />
          <div className="absolute left-12 top-7 h-5 w-2 rounded-sm bg-blue-400" />
          <div className="absolute left-[60px] top-5 h-7 w-2 rounded-sm bg-blue-500" />
        </div>
      )}
      <div className={cn(compact && 'min-w-0')}>
        <div
          className={cn(
            'font-semibold text-slate-950',
            compact ? 'text-[13px]' : 'text-[14px]'
          )}
        >
          {title}
        </div>
        <p
          className={cn(
            'max-w-xl text-[12px] text-slate-500',
            compact ? 'mt-1 leading-4' : 'mt-2 leading-5'
          )}
        >
          {description}
        </p>
      </div>
    </div>
  )
}

function EvaluationHeroCard({
  title,
  description,
  label,
  icon: Icon,
  conversationsCount,
  runsCount,
  focusLabel,
  focusValue,
  onRefresh,
  isLoading,
}: Readonly<{
  title: string
  description: string
  label: string
  icon: LucideIcon
  conversationsCount: number
  runsCount: number
  focusLabel: string
  focusValue: number
  onRefresh: () => void
  isLoading: boolean
}>) {
  return (
    <section className="relative overflow-hidden rounded-3xl border border-sky-200/60 bg-gradient-to-br from-white via-sky-50/40 to-blue-50/30 px-5 py-4 shadow-xl shadow-sky-200/30 backdrop-blur-xl">
      <div
        className="pointer-events-none absolute -right-10 -top-14 size-44 rounded-full bg-sky-300/22 blur-3xl"
        aria-hidden="true"
      />
      <div
        className="pointer-events-none absolute bottom-0 left-8 right-8 h-px bg-gradient-to-r from-transparent via-sky-300/65 to-transparent"
        aria-hidden="true"
      />

      <div className="relative flex min-w-0 flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 items-center gap-4">
          <div className="relative flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-sky-200/60 bg-gradient-to-br from-white to-sky-100 text-sky-600 shadow-lg shadow-sky-200/40">
            <span
              className="absolute inset-x-2 top-1.5 h-px bg-white/80"
              aria-hidden="true"
            />
            <PageTitleIcon name="ragas-evaluation" className="size-10" />
          </div>

          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-300/60 bg-gradient-to-r from-sky-100/80 to-blue-100/60 px-3 py-1.5 text-[10px] font-black uppercase tracking-[0.2em] text-sky-700 shadow-sm">
                <BarChart3 className="size-3.5" aria-hidden="true" />
                Evaluation Ops
              </span>
              <span className="inline-flex items-center rounded-full border border-emerald-300/60 bg-gradient-to-r from-emerald-100/80 to-teal-100/60 px-3 py-1.5 text-[10px] font-bold text-emerald-700 shadow-sm">
                <Icon className="mr-1.5 size-3.5" aria-hidden="true" />
                {label}
              </span>
            </div>

            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <h1 className="text-[26px] font-black tracking-tight text-slate-900">
                {title}
              </h1>
              <p className="text-[13px] font-semibold leading-5 text-sky-600/90">
                {description}
              </p>
            </div>
          </div>
        </div>

        <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_auto] xl:min-w-[560px]">
          <div className="flex min-w-0 flex-wrap items-center gap-2.5 rounded-2xl border border-sky-200/70 bg-white/80 px-4 py-3 text-[12px] shadow-md shadow-sky-200/20 backdrop-blur-sm">
            <span className="inline-flex items-center gap-2 font-bold text-slate-700">
              <span
                className="size-1.5 rounded-full bg-sky-500 shadow-sm shadow-sky-300"
                aria-hidden="true"
              />
              会话
            </span>
            <span className="font-mono font-black tabular-nums text-slate-900">
              {conversationsCount}
            </span>
            <span className="h-4 w-px bg-sky-200/70" />
            <span className="font-bold text-slate-600">运行</span>
            <span className="font-mono font-black tabular-nums text-sky-600">
              {runsCount}
            </span>
            <span className="h-4 w-px bg-sky-200/70" />
            <span className="font-bold text-slate-600">{focusLabel}</span>
            <span className="font-mono font-black tabular-nums text-emerald-600">
              {focusValue}
            </span>
          </div>

          <Button
            type="button"
            variant="outline"
            className="h-10 rounded-xl border-sky-200/60 bg-white/90 px-4 text-[13px] font-bold text-sky-700 shadow-sm hover:bg-gradient-to-r hover:from-sky-50 hover:to-blue-50 hover:shadow-md"
            onClick={onRefresh}
          >
            <RefreshCw
              className={cn(
                'mr-2 h-4 w-4',
                isLoading && 'animate-spin motion-reduce:animate-none'
              )}
            />
            刷新
          </Button>
        </div>
      </div>
    </section>
  )
}

function CollapsedWorkspaceRail({
  title,
  icon: Icon,
  badgeItems,
  onExpand,
  side,
}: Readonly<{
  title: string
  icon: LucideIcon
  badgeItems: Array<{ label: string; value: ReactNode }>
  onExpand: () => void
  side: 'left' | 'right'
}>) {
  const expandLabel = side === 'left' ? `展开${title}` : `展开${title}侧栏`
  const ExpandIcon = side === 'left' ? ChevronRight : ChevronLeft

  return (
    <aside className="hidden xl:flex min-h-0 flex-col items-center rounded-2xl border border-sky-100/50 bg-white/80 px-2 py-3 shadow-lg backdrop-blur-sm">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-9 w-9 rounded-xl border border-sky-200/60 bg-sky-50/70 text-sky-700 shadow-sm hover:bg-sky-100"
        onClick={onExpand}
        title={expandLabel}
        aria-label={expandLabel}
      >
        <Icon className="h-4 w-4" aria-hidden="true" />
      </Button>

      <div className="mt-3 text-center text-[10.5px] font-semibold leading-4 text-slate-600">
        {title}
      </div>

      <div className="mt-3 flex w-full flex-col gap-2">
        {badgeItems.map((item) => (
          <div
            key={item.label}
            className="rounded-xl border border-sky-100/70 bg-gradient-to-br from-white to-sky-50/60 px-1.5 py-2 text-center shadow-sm"
          >
            <div className="text-[11px] font-bold leading-none tabular-nums text-slate-900">
              {item.value}
            </div>
            <div className="mt-1 text-[9px] font-semibold leading-3 text-sky-700">
              {item.label}
            </div>
          </div>
        ))}
      </div>

      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="mt-auto h-8 w-8 rounded-full text-slate-500 hover:bg-sky-50 hover:text-sky-700"
        onClick={onExpand}
        title={expandLabel}
        aria-label={expandLabel}
      >
        <ExpandIcon className="h-4 w-4" aria-hidden="true" />
      </Button>
    </aside>
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
  const rawSamples = run.summary?.items ?? run.params?.max_turns
  const samples =
    typeof rawSamples === 'number' || typeof rawSamples === 'string'
      ? rawSamples
      : '-'
  const metrics = run.metrics?.length || '-'
  const progress =
    run.status === 'running' || run.status === 'pending' ? 60 : null
  const missingEvidence = isMissingEvidenceError(run.error_message)

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full rounded-xl border bg-white/80 p-3 text-left shadow-sm backdrop-blur-sm transition-all duration-200 hover:shadow-md hover:scale-[1.02] focus-ring',
        active ? 'border-sky-300 bg-gradient-to-br from-sky-50/90 to-blue-50/90 ring-2 ring-sky-100/50 shadow-sky-100/50' : 'border-sky-100/50 hover:border-sky-200'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 text-[13px] font-bold text-slate-900">
          <div className="truncate">
            {shortConversationTitle(conversation, run.conversation_id)}
          </div>
        </div>
        <span className="shrink-0 whitespace-nowrap">
          <StatusBadge
            status={runStatusTone(run.status)}
            label={missingEvidence ? '缺证据' : runStatusLabel(run.status)}
            dense
          />
        </span>
      </div>
      <div className="mt-2 space-y-1 text-[11px] leading-4 text-slate-600">
        <div>运行时间：{formatDateTime(run.created_at)}</div>
        <div className="flex items-center gap-4">
          <span className="font-medium">轮次：{samples}</span>
          <span className="font-medium">指标：{metrics}</span>
        </div>
      </div>
      {progress === null ? null : (
        <div className="mt-2.5 flex items-center gap-2">
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-sky-100/60">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sky-500 to-blue-500 transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-[11px] font-semibold tabular-nums text-sky-600">
            {progress}%
          </span>
        </div>
      )}
      {run.status === 'failed' && run.error_message ? (
        <div className="mt-2 line-clamp-2 rounded-lg bg-rose-50/80 px-2 py-1 text-[11px] font-medium text-rose-700">
          {missingEvidence
            ? '缺少 citations / retrieved contexts，无法计算忠实度。'
            : `错误：${run.error_message}`}
        </div>
      ) : (
        <div className="mt-2 text-right text-[10.5px] font-medium text-sky-600">
          耗时：{formatRunDuration(run)}
        </div>
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
    <section className="rounded-2xl border border-sky-100/50 bg-white/80 shadow-md backdrop-blur-sm">
      <div className="flex items-center gap-2.5 border-b border-sky-100/60 bg-gradient-to-r from-sky-50/40 to-blue-50/30 px-4 py-3">
        <div className="text-[14px] font-bold text-slate-900">评分明细</div>
        <Info className="h-4 w-4 text-sky-500" aria-hidden="true" />
      </div>
      {rows.length ? (
        <div className="overflow-auto">
          <table className="w-full text-left text-[12.5px]">
            <thead className="bg-gradient-to-r from-sky-50/50 to-blue-50/30 text-slate-700">
              <tr>
                <th className="px-4 py-2.5 font-bold">指标</th>
                <th className="px-4 py-2.5 font-bold">平均分</th>
                <th className="px-4 py-2.5 font-bold">P50</th>
                <th className="px-4 py-2.5 font-bold">P90</th>
                <th className="px-4 py-2.5 font-bold">通过率（≥0.8）</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-sky-100/40">
              {rows.map((row) => (
                <tr key={row.key} className="hover:bg-sky-50/30 transition-colors">
                  <td className="px-4 py-2.5 font-bold text-slate-900">
                    {row.label}
                  </td>
                  <td className="px-4 py-2.5 font-semibold tabular-nums text-slate-800">
                    {row.mean === null ? '-' : row.mean.toFixed(3)}
                  </td>
                  <td className="px-4 py-2.5 font-semibold tabular-nums text-slate-800">
                    {row.p50 === null ? '-' : row.p50.toFixed(3)}
                  </td>
                  <td className="px-4 py-2.5 font-semibold tabular-nums text-slate-800">
                    {row.p90 === null ? '-' : row.p90.toFixed(3)}
                  </td>
                  <td className="px-4 py-2.5 font-semibold tabular-nums text-slate-800">
                    {formatPercentValue(row.passRate)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-4 py-3">
          <EvaluationHeroEmptyState
            density="compact"
            title="暂无评分数据"
            description="运行完成后将在此处展示各指标的汇总得分与统计。"
          />
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
  const visibleItems = onlyFailures
    ? items.filter((item) => itemHasLowScore(item, metricKeys))
    : items

  return (
    <section className="rounded-xl border border-slate-200 bg-card shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="text-[13px] font-semibold text-slate-950">
            逐轮明细
          </div>
          <Info className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
        </div>
        <div className="flex items-center gap-2">
          <label className="inline-flex items-center gap-2 text-[12px] text-slate-500">
            仅看异常
            <Checkbox
              checked={onlyFailures}
              onCheckedChange={(value) => onOnlyFailuresChange(value === true)}
            />
          </label>
          <Button
            variant="outline"
            className="h-7 rounded-lg border-slate-200 bg-card px-2.5 text-[12px]"
            disabled={!items.length}
            onClick={onExport}
          >
            导出
          </Button>
        </div>
      </div>
      {visibleItems.length ? (
        <div className="max-h-[276px] overflow-auto">
          <table
            aria-label="逐轮评分明细"
            className="w-full min-w-[760px] text-left text-[12px]"
          >
            <thead className="sticky top-0 z-10 bg-slate-50 text-slate-500">
              <tr>
                <th className="w-16 px-3 py-1.5 font-medium">轮次</th>
                <th className="min-w-[160px] px-3 py-1.5 font-medium">问题</th>
                <th className="min-w-[180px] px-3 py-1.5 font-medium">
                  答案摘要
                </th>
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
                    <td className="px-3 py-1.5 tabular-nums text-slate-500">
                      {item.turn_index}
                    </td>
                    <td className="px-3 py-1.5">
                      <div className="line-clamp-2 text-slate-800">
                        {item.user_input}
                      </div>
                    </td>
                    <td className="px-3 py-1.5">
                      <div className="line-clamp-2 text-slate-600">
                        {item.response}
                      </div>
                    </td>
                    {metricKeys.map((metricKey) => {
                      const value = item.scores?.[metricKey]
                      const isNum =
                        typeof value === 'number' && Number.isFinite(value)
                      return (
                        <td
                          key={metricKey}
                          className="px-3 py-1.5 tabular-nums text-slate-700"
                        >
                          {isNum ? value.toFixed(3) : '-'}
                        </td>
                      )
                    })}
                    <td className="px-3 py-1.5">
                      <span
                        className={cn(
                          'rounded-full px-2 py-0.5 text-[11px] font-medium',
                          anomaly
                            ? 'bg-rose-50 text-rose-600'
                            : 'bg-emerald-50 text-emerald-600'
                        )}
                      >
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
          <EvaluationHeroEmptyState
            density="compact"
            title="暂无轮次数据"
            description="运行完成后将按轮展示详细评分。"
          />
        </div>
      )}
    </section>
  )
}

export default function EvaluationsPage() {
  return (
    <NavigationVisibilityGate moduleKey="ragas" pageName="RAGAS 评测">
      <AppFrame>
        <Suspense fallback={<EvaluationsLoading />}>
          <EvaluationsPageContent />
        </Suspense>
      </AppFrame>
    </NavigationVisibilityGate>
  )
}

function EvaluationsLoading() {
  return (
    <PageLoading
      message="正在加载评测数据..."
      srMessage="Loading evaluations"
    />
  )
}

function EvaluationsPageContent() {
  const searchParams = useSearchParams()
  const tenantAccess = useTenantAccess()
  const deepLinkedConversationId =
    searchParams.get('conversation_id')?.trim() || ''
  const [activeTab, setActiveTab] = useState<TabType>(
    () => parseEvaluationTab(searchParams.get('tab')) || 'conversation'
  )
  const isActiveTab = (tab: TabType) => activeTab === tab
  const [selectedConversationId, setSelectedConversationId] =
    useState<string>(() => deepLinkedConversationId)

  const [selectedRunId, setSelectedRunId] = useState<string>('')

  const [metricKeys, setMetricKeys] = useState<string[]>([
    'faithfulness',
    'response_relevancy',
  ])
  const [maxTurns, setMaxTurns] = useState(20)
  const [skipEmptyContexts, setSkipEmptyContexts] = useState(true)
  const [onlyFailureItems, setOnlyFailureItems] = useState(false)
  const [isRunRecordsCollapsed, setIsRunRecordsCollapsed] = useState(false)
  const [setupRailCollapsed, setSetupRailCollapsed] = useState(false)
  const [runsRailCollapsed, setRunsRailCollapsed] = useState(false)
  const [conversationEvidenceFilter, setConversationEvidenceFilter] =
    useState<ConversationEvidenceFilter>('ready')

  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const scopedConversationId = selectedConversationId || deepLinkedConversationId
  const runListParams = useMemo(
    () => ({
      limit: 50,
      ...(scopedConversationId
        ? { conversation_id: scopedConversationId }
        : {}),
    }),
    [scopedConversationId]
  )

  const conversationsQuery = useQuery({
    queryKey: queryKeys.chat.conversations({ limit: 100 }),
    queryFn: () => chatApi.listConversations({ limit: 100 }),
  })
  const conversations = conversationsQuery.data?.items ?? EMPTY_CONVERSATIONS
  const messagesQuery = useQuery({
    queryKey: queryKeys.chat.messages(scopedConversationId),
    enabled: Boolean(scopedConversationId),
    queryFn: () => chatApi.getMessages(scopedConversationId, { limit: 200 }),
  })
  const readinessConversationIds = useMemo(
    () => conversations.map((conversation) => conversation.id),
    [conversations]
  )
  const conversationReadinessQuery = useQuery({
    queryKey: queryKeys.evaluations.ragasConversationReadiness(
      readinessConversationIds
    ),
    enabled:
      activeTab === 'conversation' && readinessConversationIds.length > 0,
    queryFn: () =>
      evaluationApi.getRagasConversationReadiness({
        conversation_ids: readinessConversationIds,
      }),
    staleTime: 60_000,
  })
  const runsQuery = useQuery({
    queryKey: queryKeys.evaluations.ragasRuns(runListParams),
    queryFn: () => evaluationApi.listRagasRuns(runListParams),
  })
  const runDetailQuery = useQuery({
    queryKey: queryKeys.evaluations.ragasRunDetail(selectedRunId, {
      include_items: true,
      include_contexts: false,
    }),
    enabled: Boolean(selectedRunId),
    queryFn: () =>
      evaluationApi.getRagasRun(selectedRunId, {
        include_items: true,
        include_contexts: false,
      }),
    refetchInterval: (query) => {
      const detail = query.state.data as RagasRunDetail | undefined
      const status = detail?.run?.status
      return status === 'pending' || status === 'running' ? 2000 : false
    },
  })
  const runs = runsQuery.data?.items ?? EMPTY_RUNS
  const runDetail = runDetailQuery.data || null
  const isLoading = conversationsQuery.isLoading || runsQuery.isLoading || isRefreshing
  const evidenceSummary = useMemo(
    () => summarizeConversationEvidence(messagesQuery.data?.messages || []),
    [messagesQuery.data?.messages]
  )
  const conversationEvidenceById = useMemo(() => {
    const items = conversationReadinessQuery.data?.items || []
    return new Map(
      items.map((item) => [
        item.conversation_id,
        {
          assistantTurns: item.assistant_turns,
          evaluableTurns: item.evaluable_turns,
          citationsCount: item.citations_count,
          isEvaluable: item.is_evaluable,
          isChecking: false,
          isKnown: true,
        },
      ])
    )
  }, [conversationReadinessQuery.data?.items])
  const conversationEvidenceCounts = useMemo(() => {
    let ready = 0
    let missing = 0
    let checking = 0

    for (const conversation of conversations) {
      const evidence = conversationEvidenceById.get(conversation.id)
      if (!evidence?.isKnown || conversationReadinessQuery.isLoading) {
        checking += 1
      } else if (evidence.isEvaluable) {
        ready += 1
      } else {
        missing += 1
      }
    }

    return { ready, missing, checking, all: conversations.length }
  }, [conversationEvidenceById, conversationReadinessQuery.isLoading, conversations])
  const filteredConversations = useMemo(() => {
    if (conversationEvidenceFilter === 'all') return conversations
    return conversations.filter((conversation) => {
      const evidence = conversationEvidenceById.get(conversation.id)
      if (!evidence?.isKnown) return false
      return conversationEvidenceFilter === 'ready'
        ? evidence.isEvaluable
        : !evidence.isEvaluable
    })
  }, [conversationEvidenceById, conversationEvidenceFilter, conversations])
  const isEvidenceChecking =
    Boolean(scopedConversationId) &&
    (messagesQuery.isLoading || messagesQuery.isFetching)
  const isMissingEvidence =
    Boolean(scopedConversationId) &&
    !isEvidenceChecking &&
    messagesQuery.isSuccess &&
    !evidenceSummary.isEvaluable

  // Support deep-linking: /evaluations?conversation_id=...
  useEffect(() => {
    if (deepLinkedConversationId) setSelectedConversationId(deepLinkedConversationId)
  }, [deepLinkedConversationId])

  // Support deep-linking: /evaluations?tab=regression|conversation
  useEffect(() => {
    const tab = parseEvaluationTab(searchParams.get('tab'))
    if (tab) setActiveTab(tab)
  }, [searchParams])

  useEffect(() => {
    if (deepLinkedConversationId) return
    setSelectedConversationId((prev) => {
      if (
        prev &&
        filteredConversations.some((conversation) => conversation.id === prev)
      )
        return prev
      return filteredConversations[0]?.id || ''
    })
  }, [deepLinkedConversationId, filteredConversations])

  // Keep the detail panel scoped to the selected conversation, including deep links from history.
  useEffect(() => {
    if (!scopedConversationId) return

    if (!runs.length) {
      setSelectedRunId('')
      return
    }

    setSelectedRunId((prev) => {
      if (prev && runs.some((run) => run.id === prev)) return prev
      return runs[0]?.id || ''
    })
  }, [runs, scopedConversationId])

  const handleStart = async () => {
    if (!scopedConversationId) return
    setIsStarting(true)
    try {
      const run = await evaluationApi.createRagasRun({
        conversation_id: scopedConversationId,
        metrics: metricKeys,
        max_turns: maxTurns,
        skip_empty_contexts: skipEmptyContexts,
        include_contexts_in_response: false,
      })
      await runsQuery.refetch()
      setSelectedRunId(run.id)
    } catch (e) {
      reportClientError('Failed to start evaluation', e)
      toast.error(formatApiError(e, '启动评测失败'))
    } finally {
      setIsStarting(false)
    }
  }

  const summary = useMemo<JsonObject>(
    () => runDetail?.run?.summary || {},
    [runDetail?.run?.summary]
  )
  const displayMetrics = useMemo(() => {
    const ignore = new Set(['items', 'total_tokens', 'total_cost'])
    return Object.entries(summary)
      .filter(([k, v]) => !ignore.has(k) && typeof v === 'number')
      .map(([k, v]) => ({ key: k, value: Number(v) }))
  }, [summary])

  const activeTabMeta =
    TAB_META.find((item) => item.id === activeTab) || TAB_META[0]
  const ActiveTabIcon = activeTabMeta.icon
  const showAblationsEntry =
    !tenantAccess.isLoading &&
    canShowAdminControlledNavigationModule(tenantAccess.data, 'ablations')
  const selectedConversation =
    conversations.find(
      (conversation) => conversation.id === scopedConversationId
    ) || null
  const selectedConversationHiddenByFilter = Boolean(
    scopedConversationId &&
      !filteredConversations.some(
        (conversation) => conversation.id === scopedConversationId
      )
  )
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
  const selectedRun =
    runDetail?.run || runs.find((run) => run.id === selectedRunId) || null
  const runErrorMessage = String(
    runDetail?.run?.error_message || selectedRun?.error_message || ''
  ).trim()
  const isMissingEvidenceFailure = isMissingEvidenceError(runErrorMessage)

  const runStatus = runDetail?.run?.status || selectedRun?.status
  const statusBadge = useMemo(() => {
    if (!runStatus) return null

    const status =
      runStatus === 'completed'
        ? 'completed'
        : runStatus === 'failed'
          ? 'failed'
          : 'processing'
    const label =
      runStatus === 'completed'
        ? '已完成'
        : runStatus === 'failed'
          ? '失败'
          : '运行中'
    const badge = <StatusBadge status={status} label={label} dense />

    if (runStatus === 'failed' && runErrorMessage) {
      return (
        <span
          className="inline-flex cursor-help"
          title={runErrorMessage}
          aria-label="失败原因，悬停查看"
        >
          {badge}
        </span>
      )
    }

    return badge
  }, [runErrorMessage, runStatus])
  const emptyRunState = useMemo(() => {
    if (!selectedRunId) {
      return {
        title: '暂无评测结果',
        description: '请先在左侧选择对话、指标与参数，然后点击「开始评测」运行。',
      }
    }
    if (runStatus === 'failed') {
      return {
        title: isMissingEvidenceFailure
          ? '缺少证据，无法计算忠实度'
          : '评测失败，暂无分数',
        description:
          (isMissingEvidenceFailure
            ? '这条会话没有可评估的 citations / retrieved contexts。请用 MimirQ 对话或 Dify HTTP 回写证据链后再评测。'
            : runErrorMessage) ||
          '该运行失败，后端未生成 summary 分数；请检查会话是否带有 citations / retrieved contexts。',
      }
    }
    if (runStatus === 'pending' || runStatus === 'running') {
      return {
        title: '评测运行中',
        description: '后端正在计算评分，完成后会自动刷新运行详情。',
      }
    }
    return {
      title: '暂无评分数据',
      description: '这条 run 已返回，但后端尚未生成 summary 分数或逐轮 scores。',
    }
  }, [isMissingEvidenceFailure, runErrorMessage, runStatus, selectedRunId])
  const scoreRows = useMemo(
    () => scoreRowsFor(runDetail, summary),
    [runDetail, summary]
  )
  const detailMetricKeys = runDetail?.run?.metrics?.length
    ? runDetail.run.metrics
    : metricKeys
  const detailItems = runDetail?.items || []
  const hasScoreBreakdown = scoreRows.length > 0
  const hasItemBreakdown = detailItems.length > 0
  const showBreakdownPanels = hasScoreBreakdown || hasItemBreakdown
  const visibleRuns = runs
  const selectedRunConversation = selectedRun?.conversation_id
    ? conversations.find(
        (conversation) => conversation.id === selectedRun.conversation_id
      ) || null
    : selectedConversation
  const selectedRunTitle = shortConversationTitle(
    selectedRunConversation,
    selectedRun?.conversation_id || scopedConversationId
  )
  const conversationDesktopGridClass =
    setupRailCollapsed && runsRailCollapsed
      ? 'xl:grid-cols-[56px_minmax(0,1fr)_56px]'
      : setupRailCollapsed
        ? 'xl:grid-cols-[56px_minmax(0,1fr)_280px]'
        : runsRailCollapsed
          ? 'xl:grid-cols-[280px_minmax(0,1fr)_56px]'
          : 'xl:grid-cols-[280px_minmax(0,1fr)_280px]'

  const handleConversationChange = (conversationId: string) => {
    setSelectedConversationId(conversationId)
    setSelectedRunId('')
  }

  const refreshEvaluationWorkspace = async () => {
    setIsRefreshing(true)
    try {
      await Promise.all([conversationsQuery.refetch(), runsQuery.refetch()])
    } finally {
      setIsRefreshing(false)
    }
  }

  const handleExportItems = () => {
    const blob = new Blob([JSON.stringify(runDetail?.items || [], null, 2)], {
      type: 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `ragas-run-items.${selectedRunId || 'latest'}.json`
    anchor.click()
    globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const heroFocusLabel =
    activeTab === 'conversation' ? '缺证据' : '失败'
  const heroFocusValue =
    activeTab === 'conversation'
      ? conversationEvidenceCounts.missing
      : runStatusCounts.failed

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden bg-gradient-to-br from-sky-50/40 via-blue-50/30 to-cyan-50/40">
      <AnalysisPageShell
        title="评测中心"
        description="把实时会话评测、回归测试与检索集健康度放到同一个工作台里，减少来回切页。"
        icon={BarChart3}
        iconColor="text-sky-600"
        badge="评测"
        size="full"
        showHeader={false}
        bodyGutter="none"
        bodyClassName="!pb-0"
        bodyContainerClassName="max-w-none"
      >
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto px-6 py-4">
          <PageHeader
            title={activeTabMeta.title}
            description={activeTabMeta.description}
            iconImage="ragas-evaluation"
            icon={ActiveTabIcon}
            iconColor="text-sky-600"
            badge="评测中心"
            compact
            className="sr-only"
          />

          <EvaluationHeroCard
            title={activeTabMeta.title}
            description={activeTabMeta.description}
            label={activeTabMeta.label}
            icon={ActiveTabIcon}
            conversationsCount={conversations.length}
            runsCount={runs.length}
            focusLabel={heroFocusLabel}
            focusValue={heroFocusValue}
            onRefresh={refreshEvaluationWorkspace}
            isLoading={isLoading}
          />

          <section className="overflow-hidden rounded-2xl border border-sky-100/50 bg-white/80 shadow-md backdrop-blur-sm">
            <div className="flex items-center gap-3 bg-gradient-to-r from-sky-50/45 to-blue-50/25 px-4 py-3">
              <nav className="flex items-center gap-1 rounded-xl bg-white/65 p-1 shadow-sm backdrop-blur-sm">
                {TAB_META.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      'relative inline-flex h-8 items-center gap-2 rounded-lg px-3.5 text-[12px] font-medium transition-all duration-200',
                      isActiveTab(tab.id)
                        ? 'bg-gradient-to-r from-sky-500 to-blue-500 text-white shadow-md shadow-sky-200/50'
                        : 'text-slate-600 hover:bg-sky-50/70 hover:text-sky-700'
                    )}
                  >
                    <tab.icon className="h-4 w-4" aria-hidden="true" />
                    {tab.label}
                  </button>
                ))}
                {showAblationsEntry ? (
                  <Link
                    href="/evaluations/ablations"
                    className="inline-flex h-8 items-center gap-2 rounded-lg border border-sky-200/60 bg-white/80 px-3.5 text-[12px] font-medium text-slate-600 transition-all duration-200 hover:bg-sky-50/70 hover:text-sky-700"
                  >
                    <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
                    检索调参对比
                  </Link>
                ) : null}
              </nav>
            </div>
          </section>

          {activeTab === 'conversation' ? (
            <div className={cn('grid min-h-[610px] gap-3', conversationDesktopGridClass)}>
              {setupRailCollapsed ? (
                <CollapsedWorkspaceRail
                  title="参数栏"
                  icon={SlidersHorizontal}
                  badgeItems={[
                    { label: '总数', value: conversations.length },
                    {
                      label: '证据',
                      value:
                        isEvidenceChecking
                          ? '...'
                          : evidenceSummary.isEvaluable
                            ? evidenceSummary.citationsCount
                            : 0,
                    },
                  ]}
                  onExpand={() => setSetupRailCollapsed(false)}
                  side="left"
                />
              ) : (
                <aside className="flex min-h-0 max-h-[calc(100vh-246px)] flex-col rounded-2xl border border-sky-100/50 bg-white/80 shadow-lg backdrop-blur-sm">
                  <div className="flex items-center justify-between border-b border-sky-100/60 bg-gradient-to-r from-sky-50/50 to-blue-50/30 px-4 py-3">
                    <div className="inline-flex items-center gap-2.5 text-[14px] font-bold text-slate-900">
                      <SlidersHorizontal
                        className="h-4.5 w-4.5 text-sky-600"
                        aria-hidden="true"
                      />
                      参数设置
                    </div>
                    <div className="flex items-center gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 rounded-lg px-2.5 text-[11px] font-semibold text-sky-600 hover:bg-sky-50"
                        onClick={() => {
                          setMetricKeys(['faithfulness', 'response_relevancy'])
                          setMaxTurns(20)
                          setSkipEmptyContexts(true)
                        }}
                      >
                        <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                        重置
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="hidden h-7 w-7 rounded-lg text-slate-500 hover:bg-sky-50 hover:text-sky-700 xl:inline-flex"
                        onClick={() => setSetupRailCollapsed(true)}
                        aria-label="收起参数栏"
                        title="收起参数栏"
                      >
                        <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </div>
                  </div>

                  <div className="min-h-0 flex-1 divide-y divide-sky-100/60 overflow-y-auto">
                    <EvaluationConfigSection
                      icon={Database}
                      title="对话来源"
                      description="从已有会话里选一条对话，评测会按用户-助手轮次重建上下文。"
                    >
                      <Select
                        value={scopedConversationId}
                        onValueChange={handleConversationChange}
                      >
                        <SelectTrigger className="h-10 rounded-xl border-sky-200/60 bg-white text-[13px] shadow-sm">
                          <SelectValue placeholder="请选择会话或查询" />
                        </SelectTrigger>
                        <SelectContent>
                          {scopedConversationId &&
                          (!selectedConversation || selectedConversationHiddenByFilter) ? (
                            <SelectItem value={scopedConversationId}>
                              {shortConversationTitle(
                                selectedConversation,
                                scopedConversationId
                              )}{' '}
                              · 当前
                            </SelectItem>
                          ) : null}
                          {!filteredConversations.length ? (
                            <SelectItem value="__empty_conversation_filter__" disabled>
                              当前筛选暂无会话
                            </SelectItem>
                          ) : null}
                          {filteredConversations.map((conversation) => {
                            const evidence = conversationEvidenceById.get(
                              conversation.id
                            )
                            const evidenceLabel = !evidence?.isKnown
                              ? '检查中'
                              : evidence.isEvaluable
                                ? `${evidence.citationsCount} 条证据`
                                : '缺证据'
                            return (
                            <SelectItem
                              key={conversation.id}
                              value={conversation.id}
                            >
                              <span className="flex min-w-0 items-center justify-between gap-3">
                                <span className="truncate">
                                  {conversation.title || conversation.id}
                                </span>
                                <span
                                  className={cn(
                                    'shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold',
                                    !evidence?.isKnown
                                      ? 'bg-slate-100 text-slate-600'
                                      : evidence.isEvaluable
                                        ? 'bg-emerald-100 text-emerald-700'
                                        : 'bg-amber-100 text-amber-700'
                                  )}
                                >
                                  {evidenceLabel}
                                </span>
                              </span>
                            </SelectItem>
                            )
                          })}
                        </SelectContent>
                      </Select>
                      <div className="mt-2.5 grid grid-cols-3 gap-1.5 rounded-xl border border-sky-200/60 bg-gradient-to-br from-sky-50/50 to-blue-50/30 p-1.5">
                        {CONVERSATION_EVIDENCE_FILTERS.map((filter) => {
                          const count =
                            filter.id === 'ready'
                              ? conversationEvidenceCounts.ready
                              : filter.id === 'missing'
                                ? conversationEvidenceCounts.missing
                                : conversationEvidenceCounts.all
                          const active = conversationEvidenceFilter === filter.id
                          return (
                            <button
                              key={filter.id}
                              type="button"
                              onClick={() => setConversationEvidenceFilter(filter.id)}
                              className={cn(
                                'rounded-lg px-2 py-1.5 text-[11.5px] font-bold transition-all duration-200',
                                active
                                  ? 'bg-white text-sky-700 shadow-md ring-1 ring-sky-100'
                                  : 'text-slate-600 hover:bg-white/70 hover:text-slate-900'
                              )}
                            >
                              {filter.label}
                              <span className="ml-1.5 font-mono tabular-nums">
                                {count}
                              </span>
                            </button>
                          )
                        })}
                      </div>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <EvaluationInlineStat
                          label="已选"
                          value={scopedConversationId ? '1' : '0'}
                        />
                        <EvaluationInlineStat
                          label="总数"
                          value={conversations.length}
                        />
                        <EvaluationInlineStat
                          label="证据"
                          value={
                            isEvidenceChecking
                              ? '检查中'
                              : evidenceSummary.isEvaluable
                                ? evidenceSummary.citationsCount
                                : '缺失'
                          }
                        />
                        <EvaluationInlineStat
                          label="可评轮次"
                          value={evidenceSummary.evaluableTurns}
                        />
                        {conversationEvidenceCounts.checking ? (
                          <EvaluationInlineStat
                            label="检查中"
                            value={conversationEvidenceCounts.checking}
                          />
                        ) : null}
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
                        itemClassName="rounded-lg border border-slate-200 bg-card px-2 py-1 shadow-sm"
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
                          <Label
                            htmlFor="max-turns"
                            className="text-[12px] font-medium text-slate-600"
                          >
                            最近轮次
                          </Label>
                          <Input
                            id="max-turns"
                            type="number"
                            min={1}
                            max={200}
                            value={maxTurns}
                            onChange={(e) => setMaxTurns(Number(e.target.value))}
                            className="h-9 rounded-lg border-slate-200 bg-card text-xs"
                          />
                        </div>

                        <label className="flex items-start gap-2.5 rounded-lg border border-slate-200 bg-card px-2.5 py-2 shadow-sm">
                          <Checkbox
                            checked={skipEmptyContexts}
                            onCheckedChange={(value) =>
                              setSkipEmptyContexts(value === true)
                            }
                          />
                          <span className="space-y-0.5">
                            <span className="block text-[12px] font-medium text-slate-900">
                              跳过无引用轮次
                            </span>
                            <span className="block text-[11px] leading-4 text-slate-500">
                              减少空样本干扰，让结果更接近真实 RAG 场景。
                            </span>
                          </span>
                        </label>
                      </div>
                    </EvaluationConfigSection>
                  </div>

                  <div className="shrink-0 border-t border-sky-100/60 bg-gradient-to-r from-sky-50/30 to-blue-50/20 p-3">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <EvaluationInlineStat
                        label="指标数"
                        value={metricKeys.length}
                      />
                      <EvaluationInlineStat label="轮次" value={maxTurns} />
                      <EvaluationInlineStat
                        label="过滤"
                        value={skipEmptyContexts ? '已启用' : '关闭'}
                      />
                    </div>
                    <Button
                      className="h-10 w-full rounded-full bg-gradient-to-r from-sky-500 to-blue-600 text-[13px] font-bold text-white shadow-lg shadow-sky-200/50 transition-all duration-200 hover:from-sky-600 hover:to-blue-700 hover:shadow-xl hover:shadow-sky-300/50"
                      disabled={
                        isStarting ||
                        !scopedConversationId ||
                        isMissingEvidence ||
                        !metricKeys.length
                      }
                      onClick={handleStart}
                    >
                      {isStarting ? (
                        <Loader2 className="mr-2 h-4.5 w-4.5 animate-spin motion-reduce:animate-none" />
                      ) : (
                        <PlayCircle className="mr-2 h-4.5 w-4.5" />
                      )}
                      {isMissingEvidence ? '缺证据，不能评测' : '开始评测'}
                    </Button>
                    <Button
                      variant="outline"
                      className="mt-2 h-8 w-full rounded-full border-sky-200/60 bg-white/80 text-[12px] font-semibold text-sky-700 shadow-sm backdrop-blur-sm hover:bg-sky-50"
                      onClick={() => refreshEvaluationWorkspace()}
                    >
                      <RefreshCw
                        className={cn(
                          'mr-2 h-3.5 w-3.5',
                          isLoading && 'animate-spin motion-reduce:animate-none'
                        )}
                      />
                      刷新会话与运行
                    </Button>
                  </div>
                </aside>
              )}

              <main className="flex min-h-0 min-w-0 flex-col gap-3">
                <EvaluationResultsStage
                  selectedRunTitle={selectedRunTitle}
                  statusBadge={statusBadge}
                  isChecking={isEvidenceChecking}
                  isEvaluable={evidenceSummary.isEvaluable}
                  assistantTurns={evidenceSummary.assistantTurns}
                  citationsCount={evidenceSummary.citationsCount}
                  evaluableTurns={evidenceSummary.evaluableTurns}
                  isMissingEvidenceFailure={isMissingEvidenceFailure}
                  summary={summary}
                  displayMetrics={displayMetrics}
                  emptyRunState={emptyRunState}
                  fillAvailableHeight={!showBreakdownPanels}
                />

                {showBreakdownPanels ? (
                  <div
                    className={cn(
                      'grid gap-3',
                      hasScoreBreakdown && hasItemBreakdown
                        ? 'xl:grid-cols-[0.85fr_1.25fr]'
                        : 'xl:grid-cols-1'
                    )}
                  >
                    {hasScoreBreakdown ? (
                      <ScoreDetailsCard rows={scoreRows} />
                    ) : null}
                    {hasItemBreakdown ? (
                      <IterationDetailsCard
                        items={detailItems}
                        metricKeys={detailMetricKeys}
                        onlyFailures={onlyFailureItems}
                        onOnlyFailuresChange={setOnlyFailureItems}
                        onExport={handleExportItems}
                      />
                    ) : null}
                  </div>
                ) : null}
              </main>

              {runsRailCollapsed ? (
                <CollapsedWorkspaceRail
                  title="运行记录"
                  icon={ListChecks}
                  badgeItems={[
                    { label: '运行', value: runs.length },
                    { label: '失败', value: runStatusCounts.failed },
                  ]}
                  onExpand={() => setRunsRailCollapsed(false)}
                  side="right"
                />
              ) : (
                <aside className="flex max-h-[calc(100vh-246px)] min-h-0 flex-col overflow-hidden rounded-2xl border border-sky-100/50 bg-white/80 p-3 shadow-lg backdrop-blur-sm">
                  <div className="mb-2.5 flex shrink-0 items-center justify-between gap-3">
                    <button
                      type="button"
                      className="inline-flex min-w-0 items-center gap-2.5 text-left text-[14px] font-bold text-slate-900 focus-ring"
                      onClick={() => setIsRunRecordsCollapsed((value) => !value)}
                      aria-expanded={!isRunRecordsCollapsed}
                      aria-controls="ragas-run-records-list"
                    >
                      <ListChecks
                        className="h-5 w-5 shrink-0 text-sky-600"
                        aria-hidden="true"
                      />
                      <span className="truncate">运行记录</span>
                      <span className="rounded-full border border-sky-200/60 bg-gradient-to-r from-sky-50 to-blue-50 px-2 py-0.5 text-[11px] font-bold text-sky-700">
                        {runs.length}
                      </span>
                      <ChevronDown
                        className={cn(
                          'h-4 w-4 text-slate-400 transition-transform duration-200',
                          isRunRecordsCollapsed && '-rotate-90'
                        )}
                        aria-hidden="true"
                      />
                    </button>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        className="h-8 shrink-0 px-2.5 text-[12px] font-semibold text-sky-700 hover:bg-sky-50"
                        onClick={() => runsQuery.refetch()}
                      >
                        刷新
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="hidden h-8 w-8 shrink-0 rounded-lg text-slate-500 hover:bg-sky-50 hover:text-sky-700 xl:inline-flex"
                        onClick={() => setRunsRailCollapsed(true)}
                        aria-label="收起运行记录侧栏"
                        title="收起运行记录侧栏"
                      >
                        <ChevronRight className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </div>
                  </div>

                  <div
                    id="ragas-run-records-list"
                    className={cn(
                      'grid min-h-0 transition-[grid-template-rows,opacity] duration-300 ease-out motion-reduce:transition-none',
                      isRunRecordsCollapsed
                        ? 'grid-rows-[0fr] opacity-0'
                        : 'grid-rows-[1fr] opacity-100'
                    )}
                  >
                    <div className="min-h-0 overflow-hidden">
                      {visibleRuns.length ? (
                        <div className="max-h-[560px] min-h-0 space-y-2 overflow-y-auto overscroll-contain pr-1 no-scrollbar">
                          {visibleRuns.map((run) => (
                            <RunRecordCard
                              key={run.id}
                              active={selectedRunId === run.id}
                              run={run}
                              conversation={
                                run.conversation_id
                                  ? conversations.find(
                                      (conversation) =>
                                        conversation.id === run.conversation_id
                                    ) || null
                                  : null
                              }
                              onClick={() => setSelectedRunId(run.id)}
                            />
                          ))}
                        </div>
                      ) : (
                        <EvaluationHeroEmptyState
                          title="暂无评测记录"
                          description="运行一次评测后，这里会出现真实 run 记录。"
                        />
                      )}
                    </div>
                  </div>

                  {isRunRecordsCollapsed ? (
                    <div className="rounded-xl border border-sky-200/60 bg-gradient-to-br from-sky-50/40 to-blue-50/30 px-3 py-2.5 text-[11px] font-medium text-slate-600">
                      已收起 {runs.length}{' '}
                      条运行记录，点击标题展开后在列表内上滑查看。
                    </div>
                  ) : null}
                </aside>
              )}
            </div>
          ) : activeTab === 'regression' ? (
            <div className="flex h-[calc(100vh-255px)] min-h-[610px] flex-col overflow-hidden rounded-xl border border-slate-200 bg-card p-2.5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <RegressionTestTab embedded />
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-card p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <QuerysetHealthTab embedded />
            </div>
          )}
        </div>
      </AnalysisPageShell>
    </div>
  )
}
