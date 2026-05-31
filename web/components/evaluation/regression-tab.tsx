/**
 * 回归测试 Tab
 *
 * 功能：
 * - 测试用例管理
 * - AI 生成问题
 * - 批量运行回归测试
 */

'use client'

import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQuery } from '@tanstack/react-query'
import { datasetApi, evaluationApi } from '@/lib/api'
import type {
  Dataset,
  RegressionRun,
  RegressionRunCreate,
  RegressionRunDetail,
} from '@/types'
import { Button } from '@/components/ui/button'
import { TestCaseManager } from '@/components/test-case-manager'
import { TestGenerationDialog } from '@/components/test-generation-dialog'
import {
  Sparkles,
  Loader2,
  BarChart3,
  CheckCircle2,
  XCircle,
  Clock3,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { formatApiError } from '@/lib/api-errors'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  RAGAS_METRIC_OPTIONS,
  ragasMetricLabel,
} from '@/components/evaluation/ragas-metric-selector'
import { queryKeys } from '@/lib/query-keys'

const REGRESSION_DATASET_LIST_PARAMS = { limit: 200 } as const

function RegressionInlineStat({
  label,
  value,
  tone = 'neutral',
}: Readonly<{
  label: string
  value: ReactNode
  tone?: 'neutral' | 'success' | 'warning' | 'info'
}>) {
  const toneClass =
    tone === 'success'
      ? 'border-emerald-200/80 bg-emerald-50/90'
      : tone === 'warning'
        ? 'border-amber-200/80 bg-amber-50/90'
        : tone === 'info'
          ? 'border-sky-200/80 bg-sky-50/90'
          : 'border-slate-200/80 bg-card/90'

  const valueClass =
    tone === 'success'
      ? 'text-emerald-700'
      : tone === 'warning'
        ? 'text-amber-700'
        : tone === 'info'
          ? 'text-sky-700'
          : 'text-foreground'

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1',
        toneClass
      )}
    >
      <span className="text-[11px] font-medium leading-none text-muted-foreground">
        {label}
      </span>
      <span
        className={cn('text-[11px] font-semibold leading-none', valueClass)}
      >
        {value}
      </span>
    </div>
  )
}

function safeRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function primitiveText(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

function safeNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function EmbeddedSection({
  title,
  description,
  children,
  className,
}: Readonly<{
  title: string
  description?: string
  children: ReactNode
  className?: string
}>) {
  return (
    <section
      className={cn(
        'rounded-2xl border border-slate-200/80 bg-card px-2.5 py-2.5',
        className
      )}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {title}
      </div>
      {description ? (
        <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
          {description}
        </p>
      ) : null}
      <div className="mt-3">{children}</div>
    </section>
  )
}

function EmbeddedCollapsibleSection({
  summary,
  description,
  badge,
  children,
  className,
}: Readonly<{
  summary: string
  description?: string
  badge?: ReactNode
  children: ReactNode
  className?: string
}>) {
  return (
    <details
      className={cn(
        'group overflow-hidden rounded-2xl border border-slate-200/80 bg-card',
        className
      )}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-2.5 py-2.5 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
            {summary}
          </div>
          {description ? (
            <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-slate-200 bg-card px-2 py-1 text-[10px] font-medium text-slate-600">
          {badge}
          <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
        </span>
      </summary>
      <div className="border-t border-slate-200/80 bg-card/80 p-2.5">
        {children}
      </div>
    </details>
  )
}

function EmbeddedToggleCard({
  title,
  description,
  checked,
  onCheckedChange,
  disabled = false,
}: Readonly<{
  title: string
  description: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
}>) {
  return (
    <div
      className={cn(
        'rounded-xl border border-slate-200/80 bg-card/90 px-2.5 py-2',
        disabled && 'opacity-60'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground">{title}</div>
          <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
            {description}
          </div>
        </div>
        <Switch
          checked={checked}
          disabled={disabled}
          onCheckedChange={onCheckedChange}
        />
      </div>
    </div>
  )
}

const REGRESSION_CORE_METRIC_KEYS = new Set([
  'faithfulness',
  'response_relevancy',
  'context_precision',
])

function RegressionMetricPicker({
  disabled = false,
  metricKeys,
  onMetricKeysChange,
}: Readonly<{
  disabled?: boolean
  metricKeys: string[]
  onMetricKeysChange: (nextKeys: string[]) => void
}>) {
  const regressionMetrics = RAGAS_METRIC_OPTIONS.filter((metric) =>
    metric.scopes.includes('regression')
  )
  const coreMetrics = regressionMetrics.filter((metric) =>
    REGRESSION_CORE_METRIC_KEYS.has(metric.key)
  )
  const advancedMetrics = regressionMetrics.filter(
    (metric) => !REGRESSION_CORE_METRIC_KEYS.has(metric.key)
  )
  const selectedAdvancedMetrics = advancedMetrics.filter((metric) =>
    metricKeys.includes(metric.key)
  )

  const setMetricChecked = (key: string, checked: boolean) => {
    if (checked) {
      if (metricKeys.includes(key)) return
      onMetricKeysChange([...metricKeys, key])
      return
    }
    onMetricKeysChange(metricKeys.filter((item) => item !== key))
  }

  return (
    <TooltipProvider delayDuration={120}>
      <div className={cn('space-y-2', disabled && 'opacity-60')}>
        <div className="grid gap-1.5">
          {coreMetrics.map((metric) => (
            <RegressionMetricOption
              key={metric.key}
              compact
              checked={metricKeys.includes(metric.key)}
              disabled={disabled}
              metric={metric}
              onCheckedChange={(checked) =>
                setMetricChecked(metric.key, checked)
              }
            />
          ))}
        </div>

        <details className="group overflow-hidden rounded-xl border border-slate-200/80 bg-slate-50/60">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-2.5 py-2 [&::-webkit-details-marker]:hidden">
            <div className="min-w-0">
              <div className="text-[12px] font-semibold text-foreground">
                高级程序化指标
              </div>
              <div className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">
                默认收起，按需要补充引用归因、上下文利用与鲁棒性指标。
              </div>
              {selectedAdvancedMetrics.length ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {selectedAdvancedMetrics.slice(0, 3).map((metric) => (
                    <span
                      key={metric.key}
                      className="rounded-full border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[9px] font-medium text-blue-700"
                    >
                      {metric.label}
                    </span>
                  ))}
                  {selectedAdvancedMetrics.length > 3 ? (
                    <span className="rounded-full border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[9px] font-medium text-blue-700">
                      +{selectedAdvancedMetrics.length - 3}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-slate-200 bg-card px-2 py-1 text-[10px] font-medium text-slate-600">
              {selectedAdvancedMetrics.length
                ? `${selectedAdvancedMetrics.length} 已选`
                : `${advancedMetrics.length} 项`}
              <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
            </span>
          </summary>
          <div className="grid gap-1.5 border-t border-slate-200/80 bg-card p-2 md:grid-cols-2">
            {advancedMetrics.map((metric) => (
              <RegressionMetricOption
                key={metric.key}
                compact
                checked={metricKeys.includes(metric.key)}
                disabled={disabled}
                metric={metric}
                onCheckedChange={(checked) =>
                  setMetricChecked(metric.key, checked)
                }
              />
            ))}
          </div>
        </details>
      </div>
    </TooltipProvider>
  )
}

function RegressionMetricOption({
  checked,
  compact = false,
  disabled,
  metric,
  onCheckedChange,
}: Readonly<{
  checked: boolean
  compact?: boolean
  disabled: boolean
  metric: (typeof RAGAS_METRIC_OPTIONS)[number]
  onCheckedChange: (checked: boolean) => void
}>) {
  const detailLabel = `${metric.label}，${metric.kind}，${metric.category}，${metric.cost}。${metric.hint}`

  const metricText = (
    <>
      <span
        className={cn(
          'flex flex-wrap items-center gap-1.5 font-medium text-foreground',
          compact ? 'text-[11px]' : 'text-[12px]'
        )}
      >
        <span className="truncate">{metric.label}</span>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-slate-500">
          {metric.kind}
        </span>
        {compact ? null : (
          <>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium text-slate-500">
              {metric.category}
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium text-slate-500">
              {metric.cost}
            </span>
          </>
        )}
      </span>
      <span
        className={cn(
          'block text-muted-foreground',
          compact
            ? 'mt-0.5 line-clamp-1 text-[10px] leading-3'
            : 'mt-1 text-[11px] leading-4'
        )}
      >
        {metric.hint}
      </span>
    </>
  )

  return (
    <label
      className={cn(
        'flex items-start gap-2 rounded-xl border border-slate-200/80 bg-card/95 shadow-sm',
        compact ? 'px-2 py-1.5' : 'px-2.5 py-2',
        disabled && 'cursor-not-allowed'
      )}
    >
      <Checkbox
        checked={checked}
        disabled={disabled}
        onCheckedChange={(value) => onCheckedChange(value === true)}
      />
      <span className="min-w-0 flex-1">
        {compact ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                aria-label={detailLabel}
                className="block cursor-help outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30"
                tabIndex={disabled ? -1 : 0}
              >
                {metricText}
              </span>
            </TooltipTrigger>
            <TooltipContent
              align="start"
              className="max-w-[320px] rounded-xl border border-slate-200 bg-card px-3 py-2 text-left text-slate-700 shadow-strong"
              side="right"
              sideOffset={8}
            >
              <div className="text-[12px] font-semibold leading-5 text-slate-950">
                {metric.label}
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {[metric.kind, metric.category, metric.cost].map((item) => (
                  <span
                    key={item}
                    className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium text-slate-500"
                  >
                    {item}
                  </span>
                ))}
              </div>
              <div className="mt-2 text-[11px] leading-5 text-slate-600">
                {metric.hint}
              </div>
            </TooltipContent>
          </Tooltip>
        ) : (
          metricText
        )}
      </span>
    </label>
  )
}

const REGRESSION_METRIC_GUIDE = [
  ['命中率', '命中目标样本的比例，越高越好'],
  ['MRR', '首个命中位置的倒数，越高越好'],
  ['Recall', '检索到的相关项占比，越高越好'],
  ['NDCG@K', '综合考虑相关性与排序质量'],
  ['MAP@K', '多查询平均精度'],
]

function RegressionMetricGuideCard() {
  const tones = [
    'bg-blue-50 text-blue-600 border-blue-100',
    'bg-violet-50 text-violet-600 border-violet-100',
    'bg-emerald-50 text-emerald-600 border-emerald-100',
    'bg-green-50 text-green-600 border-green-100',
    'bg-rose-50 text-rose-600 border-rose-100',
  ]

  return (
    <div className="shrink-0 rounded-[28px] border border-slate-200/80 bg-card p-2">
      <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        Metric Guide
      </div>
      <div className="mt-1 text-sm font-semibold text-foreground">
        评测维度速览
      </div>
      <div className="mt-2 space-y-1.5">
        {REGRESSION_METRIC_GUIDE.map(([label, description], index) => (
          <div key={label} className="flex items-start gap-2">
            <span
              className={cn(
                'mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[9px] font-semibold',
                tones[index]
              )}
            >
              {index + 1}
            </span>
            <span className="min-w-0">
              <span className="block text-[12px] font-semibold text-foreground">
                {label}
              </span>
              <span className="mt-0.5 block text-[10px] leading-3 text-muted-foreground">
                {description}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function RegressionTestTab({
  embedded = false,
}: Readonly<{ embedded?: boolean }>) {
  const [showGenerationDialog, setShowGenerationDialog] = useState(false)

  // Dataset scope (required by backend for cases and runs)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('')
  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.list(REGRESSION_DATASET_LIST_PARAMS),
    queryFn: () => datasetApi.list(REGRESSION_DATASET_LIST_PARAMS),
    staleTime: 30_000,
  })
  const datasets = useMemo<Dataset[]>(() => {
    const items = datasetsQuery.data?.items
    return Array.isArray(items) ? items : []
  }, [datasetsQuery.data])
  const isLoadingDatasets = datasetsQuery.isLoading || datasetsQuery.isFetching

  // 运行配置
  const [metricKeys, setMetricKeys] = useState<string[]>([
    'faithfulness',
    'response_relevancy',
  ])
  const [retrievalOnly, setRetrievalOnly] = useState(false)
  const [useLlmJudge, setUseLlmJudge] = useState(false)

  // 运行历史
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [isConfigPanelCollapsed, setIsConfigPanelCollapsed] = useState(false)

  const runsQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionRuns({ limit: 50 }),
    queryFn: () => evaluationApi.listRegressionRuns({ limit: 50 }),
  })
  const runDetailQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionRunDetail(selectedRunId, {
      include_items: true,
      include_contexts: false,
    }),
    enabled: Boolean(selectedRunId),
    queryFn: () =>
      evaluationApi.getRegressionRun(selectedRunId, {
        include_items: true,
        include_contexts: false,
      }),
    refetchInterval: (query) => {
      const detail = query.state.data as RegressionRunDetail | undefined
      const status = detail?.run?.status
      return status === 'pending' || status === 'running' ? 2000 : false
    },
  })
  const runs = useMemo<RegressionRun[]>(() => {
    const items = runsQuery.data?.items
    return Array.isArray(items) ? items : []
  }, [runsQuery.data])
  const runDetail = runDetailQuery.data || null
  const isLoadingRuns = runsQuery.isLoading || runsQuery.isFetching

  const visibleRuns = useMemo(() => {
    if (!selectedDatasetId) return runs
    return (runs || []).filter(
      (r) => String(r?.dataset_id || '') === selectedDatasetId
    )
  }, [runs, selectedDatasetId])

  // Keep selected run in sync with dataset filtering.
  useEffect(() => {
    if (!selectedDatasetId) return
    if (selectedRunId && visibleRuns.some((r) => r?.id === selectedRunId))
      return
    setSelectedRunId(visibleRuns?.[0]?.id || '')
  }, [selectedDatasetId, selectedRunId, visibleRuns])

  useEffect(() => {
    const firstId = datasets[0]?.id
    if (!firstId) return
    setSelectedDatasetId((prev) => prev || firstId)
  }, [datasets])

  useEffect(() => {
    const firstRunId = runs[0]?.id
    if (!firstRunId) return
    setSelectedRunId((prev) => prev || firstRunId)
  }, [runs])

  useEffect(() => {
    if (!runsQuery.error) return
    console.error('加载运行历史失败:', runsQuery.error)
    toast.error(formatApiError(runsQuery.error, '加载运行历史失败'))
  }, [runsQuery.error])

  // 运行选中的测试
  const handleRunTests = async (caseIds: string[]) => {
    if (!selectedDatasetId) {
      toast.error('请先选择数据集')
      return
    }
    if (caseIds.length === 0) {
      toast.error('请至少选择一个评测样本')
      return
    }

    try {
      const params: RegressionRunCreate = {
        case_ids: caseIds,
        dataset_id: selectedDatasetId,
        metrics: retrievalOnly ? [] : metricKeys,
        use_llm_judge: Boolean(!retrievalOnly && useLlmJudge),
        skip_empty_contexts: true,
        max_cases: Math.min(Math.max(caseIds.length, 1), 500),
      }

      const run = await evaluationApi.createRegressionRun(params)
      toast.success('开始运行 Golden 评测')
      await runsQuery.refetch()
      setSelectedRunId(run.id)
    } catch (error) {
      console.error('运行 Golden 评测失败:', error)
      toast.error(formatApiError(error, '运行 Golden 评测失败'))
    }
  }

  // 生成完成回调
  const handleGenerated = () => {
    toast.success('问题生成完成')
    // 刷新用例列表会由 TestCaseManager 组件自动处理
  }

  const summary = runDetail?.run?.summary || {}
  const summaryItems = typeof summary.items === 'number' ? summary.items : '-'
  const summaryTokens =
    typeof summary.total_tokens === 'number' ? summary.total_tokens : '-'
  const summaryCost =
    typeof summary.total_cost === 'number' ||
    typeof summary.total_cost === 'string'
      ? summary.total_cost
      : '-'
  const displayMetrics = Object.entries(summary)
    .filter(
      ([k, v]) =>
        !['items', 'total_tokens', 'total_cost'].includes(k) &&
        typeof v === 'number'
    )
    .map(([k, v]) => ({ key: k, value: Number(v) }))
  const answerComparisonStatus = displayMetrics.some((m) =>
    ['answer_correctness', 'factual_correctness'].includes(m.key)
  )
    ? '有'
    : '待返回'
  const evidenceRecall =
    typeof (summary as any)?.retrieval_recall === 'number'
      ? Number((summary as any).retrieval_recall).toFixed(3)
      : '待返回'
  const multimodalSlices = safeRecord(summary.multimodal_slices)
  const multimodalSliceCounts = safeRecord(multimodalSlices.counts)
  const multimodalSliceEvaluatable = safeRecord(multimodalSlices.evaluatable)
  const multimodalSliceCoverage = safeRecord(multimodalSlices.coverage)
  const multimodalSliceRows = [
    { key: 'chart', label: 'Chart' },
    { key: 'formula', label: 'Formula' },
    { key: 'table_math', label: 'Table-Math' },
    { key: 'image', label: 'Image' },
    { key: 'text', label: 'Text' },
  ]
    .map((slice) => ({
      ...slice,
      count: safeNumber(multimodalSliceCounts[slice.key]),
      evaluatable: safeNumber(multimodalSliceEvaluatable[slice.key]),
      coverage: safeNumber(multimodalSliceCoverage[slice.key]),
    }))
    .filter(
      (slice) => slice.count > 0 || slice.evaluatable > 0 || slice.coverage > 0
    )

  const runStatus = runDetail?.run?.status
  const embeddedGridCols = isConfigPanelCollapsed
    ? 'xl:grid-cols-[0px_minmax(0,1fr)_300px] 2xl:grid-cols-[0px_minmax(0,1fr)_310px]'
    : 'xl:grid-cols-[320px_minmax(0,1fr)_300px] 2xl:grid-cols-[330px_minmax(0,1fr)_310px]'
  const statusBadge = runStatus
    ? (() => {
        if (runStatus === 'completed') {
          return (
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-success/10 text-success border border-success/20">
              <CheckCircle2 className="w-3.5 h-3.5" />
              已完成
            </span>
          )
        } else if (runStatus === 'failed') {
          return (
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-destructive/10 text-destructive border border-destructive/20">
              <XCircle className="w-3.5 h-3.5" />
              失败
            </span>
          )
        } else {
          return (
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-info/10 text-info border border-info/20">
              <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
              运行中
            </span>
          )
        }
      })()
    : null

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Inline header (when embedded in a parent PageScaffold) */}
      {embedded ? null : (
        <header className="px-8 py-6 border-b border-border bg-card">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-xl font-semibold text-foreground">
                Golden 评测集
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                维护数据集级标准问答和标准证据，批量运行当前 RAG pipeline
                并跟踪差距。
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                className="gap-2"
                onClick={() => setShowGenerationDialog(true)}
              >
                <Sparkles className="w-4 h-4" />
                AI 生成问题
              </Button>
            </div>
          </div>

          {/* 指标选择 */}
          <div className="bg-muted/40 rounded-xl p-4">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
              <div className="lg:col-span-5">
                <div className="text-xs font-medium text-muted-foreground mb-2">
                  数据集
                </div>
                <Select
                  value={selectedDatasetId}
                  onValueChange={setSelectedDatasetId}
                  disabled={isLoadingDatasets || !datasets.length}
                >
                  <SelectTrigger className="h-9">
                    <SelectValue
                      placeholder={
                        isLoadingDatasets ? '加载中...' : '选择数据集'
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {(datasets || []).map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name || d.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="lg:col-span-7">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xs font-medium text-muted-foreground">
                      仅检索评测（无 LLM / 无 RAGAS）
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1">
                      开启后将使用 `metrics=[]`，只计算
                      recall/hit@k/MRR/NDCG/abstain_rate。
                    </div>
                  </div>
                  <Switch
                    checked={retrievalOnly}
                    onCheckedChange={(checked) => {
                      setRetrievalOnly(checked)
                      if (checked) {
                        setUseLlmJudge(false)
                        setMetricKeys([])
                      } else if (!metricKeys.length) {
                        setMetricKeys(['faithfulness', 'response_relevancy'])
                      }
                    }}
                  />
                </div>

                <div className="flex items-start justify-between gap-3 mt-4">
                  <div>
                    <div className="text-xs font-medium text-muted-foreground">
                      LLM-as-Judge（可选）
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1">
                      为每个 case 生成 llm_judge（score / reason /
                      evidence_quotes；额外成本；检索-only 模式下不可用）。
                    </div>
                  </div>
                  <Switch
                    checked={useLlmJudge}
                    disabled={retrievalOnly}
                    onCheckedChange={(v) => setUseLlmJudge(Boolean(v))}
                  />
                </div>

                <div className="text-xs font-medium text-muted-foreground mt-4 mb-2">
                  评测指标
                </div>
                <div className="flex flex-wrap gap-2">
                  {RAGAS_METRIC_OPTIONS.map((m) => (
                    <label
                      key={m.key}
                      className={cn(
                        'flex items-center gap-2 text-sm',
                        retrievalOnly && 'opacity-50'
                      )}
                    >
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-border"
                        checked={metricKeys.includes(m.key)}
                        disabled={retrievalOnly}
                        onChange={(e) => {
                          setMetricKeys((prev) =>
                            e.target.checked
                              ? [...prev, m.key]
                              : prev.filter((x) => x !== m.key)
                          )
                        }}
                      />
                      <span className="text-foreground/80">{m.label}</span>
                    </label>
                  ))}
                  {retrievalOnly && (
                    <span className="text-[11px] text-muted-foreground">
                      （metrics 为空）
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </header>
      )}

      {/* 主内容区 */}
      <div
        className={
          embedded
            ? `min-h-0 flex-1 grid p-0 ${isConfigPanelCollapsed ? 'gap-0' : 'gap-2.5'} ${embeddedGridCols}`
            : 'flex-1 overflow-hidden flex gap-6 p-6'
        }
      >
        {embedded ? (
          isConfigPanelCollapsed ? (
            <aside className="group relative flex min-h-0 items-center justify-center rounded-[28px] border border-slate-200/80 bg-card shadow-[0_16px_40px_rgba(15,23,42,0.04)]">
              <button
                type="button"
                className="focus-ring relative h-full w-2.5 rounded-full transition-colors hover:bg-slate-200/70"
                onClick={() => setIsConfigPanelCollapsed(false)}
                title="展开回归配置"
                aria-label="展开回归配置"
              >
                <span
                  className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/70"
                  aria-hidden="true"
                />
                <span className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-border/70 bg-card/95 p-1 opacity-0 shadow-sm transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  <ChevronRight
                    className="h-3 w-3 text-muted-foreground"
                    aria-hidden="true"
                  />
                </span>
              </button>
            </aside>
          ) : (
            <aside className="flex min-h-0 flex-col overflow-hidden rounded-[28px] border border-slate-200/80 bg-card shadow-[0_16px_40px_rgba(15,23,42,0.04)]">
              <div className="shrink-0 border-b border-slate-200/80 bg-[radial-gradient(circle_at_15%_0%,rgba(37,99,235,0.14),transparent_30%),linear-gradient(180deg,rgba(248,251,255,0.98)_0%,rgba(255,255,255,0.94)_100%)] px-3 py-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                      Regression Studio
                    </div>
                    <div className="mt-1 text-sm font-semibold text-foreground">
                      Golden 评测配置
                    </div>
                    <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                      先锁定数据集，再维护 Golden 评测集并运行当前 RAG
                      pipeline。
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 gap-1.5 rounded-lg border-slate-200/80 bg-card/90 px-2 text-[11px]"
                      onClick={() => setShowGenerationDialog(true)}
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      生成候选
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 rounded-md px-2 text-[11px] text-muted-foreground hover:bg-slate-100 hover:text-foreground"
                      onClick={() => setIsConfigPanelCollapsed(true)}
                    >
                      收起
                    </Button>
                  </div>
                </div>

                <div className="mt-3 rounded-2xl border border-slate-200/80 bg-card/90 p-2.5 shadow-sm">
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <span className="text-[11px] font-medium text-muted-foreground">
                      数据集
                    </span>
                    <span
                      className={cn(
                        'rounded-full border px-1.5 py-0.5 text-[9px] font-medium',
                        selectedDatasetId
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : 'border-amber-200 bg-amber-50 text-amber-700'
                      )}
                    >
                      {selectedDatasetId ? '已绑定' : '未绑定'}
                    </span>
                  </div>
                  <Select
                    value={selectedDatasetId}
                    onValueChange={setSelectedDatasetId}
                    disabled={isLoadingDatasets || !datasets.length}
                  >
                    <SelectTrigger className="h-9 rounded-xl border-slate-200/80 bg-card/95 text-[13px]">
                      <SelectValue
                        placeholder={
                          isLoadingDatasets ? '加载中...' : '选择数据集'
                        }
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {(datasets || []).map((dataset) => (
                        <SelectItem key={dataset.id} value={dataset.id}>
                          {dataset.name || dataset.id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {datasets.length ? null : (
                    <div className="mt-2 text-[11px] leading-4 text-muted-foreground">
                      未加载到数据集。可查看历史 runs，创建 Golden
                      样本前需先选择数据集。
                    </div>
                  )}
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <RegressionInlineStat
                    label="runs"
                    value={visibleRuns.length}
                  />
                  <RegressionInlineStat
                    label="metrics"
                    value={retrievalOnly ? '检索-only' : metricKeys.length}
                    tone={retrievalOnly ? 'info' : 'neutral'}
                  />
                  <RegressionInlineStat
                    label="judge"
                    value={useLlmJudge && !retrievalOnly ? 'ON' : 'OFF'}
                    tone={useLlmJudge && !retrievalOnly ? 'success' : 'neutral'}
                  />
                </div>
              </div>

              <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto overscroll-contain p-2.5 pb-6 custom-scrollbar">
                <EmbeddedSection
                  title="运行当前 RAG"
                  description="当前数据集的标准问答会作为固定标尺，问题重新走 RAG 后再和标准答案、标准证据比较。"
                  className="bg-[linear-gradient(180deg,rgba(247,255,250,0.96)_0%,rgba(255,255,255,0.94)_100%)]"
                >
                  <div className="space-y-2">
                    <EmbeddedToggleCard
                      title="仅检索评测"
                      description="开启后 `metrics=[]`，只看标准证据命中：recall、hit@k、MRR、NDCG 与 abstain_rate。"
                      checked={retrievalOnly}
                      onCheckedChange={(checked) => {
                        setRetrievalOnly(checked)
                        if (checked) {
                          setUseLlmJudge(false)
                          setMetricKeys([])
                        } else if (!metricKeys.length) {
                          setMetricKeys(['faithfulness', 'response_relevancy'])
                        }
                      }}
                    />
                    <EmbeddedToggleCard
                      title="LLM-as-Judge"
                      description="为每个样本额外生成 score、reason 和 evidence quotes；检索-only 模式不可用。"
                      checked={useLlmJudge}
                      disabled={retrievalOnly}
                      onCheckedChange={(checked) =>
                        setUseLlmJudge(Boolean(checked))
                      }
                    />
                  </div>
                </EmbeddedSection>

                <EmbeddedCollapsibleSection
                  summary="评分维度"
                  description="默认收起，展开后选择 RAGAS 与程序化指标。"
                  badge={
                    retrievalOnly ? '检索-only' : `${metricKeys.length} 已选`
                  }
                  className="bg-[linear-gradient(180deg,rgba(250,252,255,0.96)_0%,rgba(255,255,255,0.94)_100%)]"
                >
                  <RegressionMetricPicker
                    metricKeys={metricKeys}
                    onMetricKeysChange={setMetricKeys}
                    disabled={retrievalOnly}
                  />
                </EmbeddedCollapsibleSection>
              </div>
            </aside>
          )
        ) : null}

        {/* 左侧：测试用例管理 */}
        <div
          className={cn(
            'flex flex-col bg-card rounded-2xl border border-border',
            embedded
              ? 'min-w-0 rounded-[28px] border-slate-200/80 bg-card shadow-[0_16px_40px_rgba(15,23,42,0.04)]'
              : 'w-1/3'
          )}
        >
          <TestCaseManager
            datasetId={selectedDatasetId || null}
            dense={embedded}
            onRunTests={handleRunTests}
            onCaseSelected={(caseId) => {
              // 可以在这里处理用例选中事件
            }}
          />
        </div>

        {/* 右侧：运行结果 */}
        <div
          className={cn(
            'flex-1 flex flex-col gap-2.5',
            embedded &&
              'min-w-0 overflow-y-auto overscroll-contain pr-1 custom-scrollbar'
          )}
        >
          {/* 运行历史列表 */}
          <div
            className={cn(
              'bg-card border border-border rounded-2xl overflow-hidden',
              embedded && 'rounded-[28px] border-slate-200/80 bg-card'
            )}
          >
            <div
              className={cn(
                'p-3 border-b border-border flex items-center justify-between',
                embedded && 'border-slate-200/80 bg-[#fffef9]'
              )}
            >
              <div>
                <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                  Run Timeline
                </div>
                <div className="mt-1 text-sm font-semibold text-foreground">
                  运行历史
                </div>
              </div>
              <div className="text-[11px] text-muted-foreground">
                {visibleRuns.length} 次
                {selectedDatasetId ? '（按数据集过滤）' : ''}
              </div>
            </div>
            <div
              className={cn(
                'overflow-y-auto overscroll-contain custom-scrollbar',
                embedded ? 'max-h-[190px]' : 'max-h-40'
              )}
            >
              {(() => {
                if (isLoadingRuns) {
                  return (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="w-6 h-6 animate-spin motion-reduce:animate-none text-muted-foreground" />
                    </div>
                  )
                } else if (visibleRuns.length === 0) {
                  return (
                    <div className="flex min-h-[128px] flex-col items-center justify-center px-3 py-5 text-center">
                      <Button
                        variant="outline"
                        size="sm"
                        className="mb-3 h-7 rounded-full border-slate-200 bg-card px-3 text-[11px] text-slate-600"
                        disabled
                      >
                        <Clock3 className="mr-1.5 h-3.5 w-3.5" />
                        查看全部历史
                      </Button>
                      <div className="text-sm font-medium text-foreground">
                        暂无运行记录
                      </div>
                      <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
                        运行后这里会保留 Golden 历史 run。
                      </div>
                    </div>
                  )
                } else {
                  return visibleRuns.map((run) => (
                    <button
                      key={run.id}
                      onClick={() => setSelectedRunId(run.id)}
                      className={cn(
                        'w-full text-left border-b transition-colors motion-reduce:transition-none',
                        embedded
                          ? 'border-slate-200/70 px-2.5 py-2 hover:bg-slate-50/80'
                          : 'border-border p-4 hover:bg-muted/50',
                        selectedRunId === run.id &&
                          (embedded ? 'bg-sky-50/70' : 'bg-primary/10')
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-medium text-foreground truncate">
                          运行 {run.id.slice(0, 8)}
                        </div>
                        <span
                          className={cn(
                            'text-[11px] px-2 py-0.5 rounded-full border',
                            (() => {
                              if (run.status === 'completed') {
                                return 'bg-success/10 text-success border-success/20'
                              } else if (run.status === 'failed') {
                                return 'bg-destructive/10 text-destructive border-destructive/20'
                              } else {
                                return 'bg-info/10 text-info border-info/20'
                              }
                            })()
                          )}
                        >
                          {run.status}
                        </span>
                      </div>
                      <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                        {embedded ? <Clock3 className="h-3.5 w-3.5" /> : null}
                        <span>{new Date(run.created_at).toLocaleString()}</span>
                      </div>
                    </button>
                  ))
                }
              })()}
            </div>
          </div>

          {/* 运行详情 */}
          <div
            className={cn(
              'flex-1 bg-card border border-border rounded-2xl p-2.5 overflow-y-auto overscroll-contain custom-scrollbar',
              embedded &&
                'min-h-[180px] rounded-[28px] border-slate-200/80 bg-card'
            )}
          >
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                  Golden Run Detail
                </div>
                <div className="mt-1 text-sm font-semibold text-foreground">
                  差距分析
                </div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  实际回答、召回上下文与 Golden 标尺的评分结果。
                </div>
              </div>
              {statusBadge}
            </div>

            {runDetail?.run?.error_message && (
              <div className="mt-3 text-sm text-destructive p-3 bg-destructive/10 border border-destructive/20 rounded-lg">
                {runDetail.run.error_message}
              </div>
            )}

            {displayMetrics.length > 0 || multimodalSliceRows.length > 0 ? (
              <div className="mt-4">
                {displayMetrics.length > 0 ? (
                  <StatsGrid className="lg:grid-cols-3">
                    {displayMetrics.map((m) => (
                      <StatCard
                        key={m.key}
                        icon={BarChart3}
                        label={ragasMetricLabel(m.key)}
                        value={m.value.toFixed(3)}
                        color="sky"
                        className="shadow-sm"
                      />
                    ))}
                  </StatsGrid>
                ) : null}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <RegressionInlineStat label="样本" value={summaryItems} />
                  <RegressionInlineStat
                    label="标准答案对比"
                    value={answerComparisonStatus}
                    tone="info"
                  />
                  <RegressionInlineStat
                    label="标准证据命中"
                    value={evidenceRecall}
                    tone="success"
                  />
                  <RegressionInlineStat label="Token" value={summaryTokens} />
                  <RegressionInlineStat label="费用" value={summaryCost} />
                </div>
                {multimodalSliceRows.length ? (
                  <div className="mt-3 rounded-2xl border border-slate-200/80 bg-[linear-gradient(180deg,rgba(248,251,255,0.96)_0%,rgba(255,255,255,0.96)_100%)] p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-foreground">
                          多模态切片
                        </div>
                        <div className="mt-0.5 text-[11px] text-muted-foreground">
                          按 Golden case 类型统计 chart / formula / table-math
                          的可评测覆盖。
                        </div>
                      </div>
                      <span className="rounded-full border border-slate-200 bg-card px-2 py-1 text-[10px] font-medium text-slate-600">
                        {safeNumber(multimodalSlices.items)} items
                      </span>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
                      {multimodalSliceRows.map((slice) => (
                        <div
                          key={slice.key}
                          className="rounded-xl border border-slate-200/80 bg-card/90 px-2.5 py-2 shadow-sm"
                        >
                          <div className="text-[11px] font-semibold text-foreground">
                            {slice.label}
                          </div>
                          <div className="mt-1 text-lg font-semibold leading-none text-slate-950 tabular-nums">
                            {slice.evaluatable}/{slice.count}
                          </div>
                          <div className="mt-1 text-[10px] text-muted-foreground">
                            覆盖率 {(slice.coverage * 100).toFixed(0)}%
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {(() => {
                  const slices = safeRecord(summary?.retrieval_slices)
                  const parseQuality = safeRecord(slices.parse_quality)
                  const chunkQuality = safeRecord(slices.chunk_quality)
                  const pq = Array.isArray(parseQuality.buckets) ? parseQuality.buckets : []
                  const cq = Array.isArray(chunkQuality.buckets) ? chunkQuality.buckets : []
                  const hasPq = pq.length
                  const hasCq = cq.length
                  if (!hasPq && !hasCq) return null

                  const renderTable = (title: string, rows: unknown[]) => {
                    const top = (rows || []).slice(0, 8)
                    return (
                      <div className="rounded-xl border border-border bg-muted/20 p-3">
                        <div className="text-xs font-semibold text-foreground mb-2">
                          {title}
                        </div>
                        <div className="overflow-auto">
                          <table
                            aria-label={`${title} 分桶统计`}
                            className="w-full text-xs"
                          >
                            <thead>
                              <tr className="text-muted-foreground border-b border-border/60">
                                <th className="text-left py-1 pr-2">bucket</th>
                                <th className="text-right py-1 pr-2">items</th>
                                <th className="text-right py-1 pr-2">recall</th>
                                <th className="text-right py-1 pr-2">mrr</th>
                                <th className="text-right py-1 pr-2">
                                  ndcg@10
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {top.map((r, index) => {
                                const row = safeRecord(r)
                                const bucketKey = primitiveText(row.key)
                                return (
                                  <tr
                                    key={bucketKey || `bucket-${index}`}
                                    className="border-b border-border/40"
                                  >
                                    <td className="py-1 pr-2 font-mono text-muted-foreground">
                                      {bucketKey}
                                    </td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {primitiveText(row.items, '—')}
                                    </td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {typeof row.retrieval_recall === 'number'
                                        ? row.retrieval_recall.toFixed(3)
                                        : '—'}
                                    </td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {typeof row.retrieval_mrr === 'number'
                                        ? row.retrieval_mrr.toFixed(3)
                                        : '—'}
                                    </td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {typeof row.retrieval_ndcg_at_10 === 'number'
                                        ? row.retrieval_ndcg_at_10.toFixed(3)
                                        : '—'}
                                    </td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )
                  }

                  return (
                    <div className="mt-4">
                      <div className="text-sm font-semibold text-foreground mb-3">
                        质量归因（Slices）
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {hasPq
                          ? renderTable(
                              'parse_quality → retrieval',
                              pq
                            )
                          : null}
                        {hasCq
                          ? renderTable(
                              'chunk_quality → retrieval',
                              cq
                            )
                          : null}
                      </div>
                    </div>
                  )
                })()}
              </div>
            ) : (
              <div className="mt-3 rounded-2xl border border-dashed border-slate-200 bg-[#fcfcfa] px-3 py-5 text-center">
                <div className="text-sm font-medium text-foreground">
                  {selectedRunId ? '当前还没有可展示分数' : '先选一个运行记录'}
                </div>
                <div className="mt-1.5 text-[11px] leading-5 text-muted-foreground">
                  {selectedRunId
                    ? '这条 run 可能仍在处理中，或后端尚未返回 summary 指标。'
                    : '右上方的运行历史里选中一条 run 后，这里会显示标准答案对比、标准证据命中与质量切片。'}
                </div>
              </div>
            )}

            {/* 明细列表 */}
            {runDetail?.items && runDetail.items.length > 0 && (
              <div className="mt-6">
                <div className="text-sm font-semibold text-foreground mb-3">
                  样本明细 ({runDetail.items.length})
                </div>
                <div className="space-y-2">
                  {runDetail.items.map((item, index: number) => (
                    <div
                      key={item.id}
                      className={cn(
                        'p-3 rounded-lg border',
                        embedded
                          ? 'border-slate-200/80 bg-[#fffef9]'
                          : 'border-border bg-muted/40'
                      )}
                    >
                      <div className="text-sm font-medium text-foreground mb-1">
                        {index + 1}. {item.question}
                      </div>
                      <div className="text-xs text-muted-foreground mt-2">
                        <span className="font-medium">实际回答:</span>{' '}
                        {item.response?.slice(0, 100)}...
                      </div>
                      {item.scores && Object.keys(item.scores).length > 0 && (
                        <div className="flex gap-2 mt-2">
                          {Object.entries(item.scores).map(
                            ([k, v]: [string, any]) => (
                              <span
                                key={k}
                                className="text-[11px] px-2 py-0.5 rounded-full bg-info/10 text-info border border-info/20"
                              >
                                {k}: {typeof v === 'number' ? v.toFixed(2) : v}
                              </span>
                            )
                          )}
                        </div>
                      )}
                      {(() => {
                        const exps = item.meta?.explanations
                        if (!exps || typeof exps !== 'object') return null
                        const entries = Object.entries(
                          exps as Record<string, any>
                        ).filter(([, v]) => typeof v === 'string' && v)
                        if (!entries.length) return null
                        return (
                          <details className="mt-2">
                            <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">
                              解释
                            </summary>
                            <div className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                              {entries.map(([k, v]) => (
                                <div key={k} className="flex gap-2">
                                  <span className="font-medium text-foreground/80">
                                    {k}:
                                  </span>
                                  <span className="break-words">
                                    {String(v)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </details>
                        )
                      })()}
                      {(() => {
                        const judge = safeRecord(item.meta?.llm_judge)
                        if (!judge.enabled) return null
                        const overall = judge.overall_score
                        const modelUsed = judge.model_used
                        const parts: Array<{ key: string; obj: Record<string, unknown> }> = [
                          { key: 'retrieval', obj: safeRecord(judge.retrieval) },
                          {
                            key: 'generation',
                            obj: safeRecord(judge.generation),
                          },
                        ]
                        return (
                          <details className="mt-2">
                            <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">
                              LLM Judge
                              {typeof overall === 'number'
                                ? ` (overall=${overall.toFixed(3)})`
                                : ''}
                            </summary>
                            <div className="mt-2 space-y-2 text-[11px] text-muted-foreground">
                              {modelUsed ? (
                                <div className="font-mono text-[11px] text-muted-foreground">
                                  model: {primitiveText(modelUsed)}
                                </div>
                              ) : null}
                              {parts.map(({ key, obj }) => {
                                if (!Object.keys(obj).length) return null
                                const score = obj.score
                                const reason = obj.reason
                                const quotes = Array.isArray(obj.evidence_quotes)
                                  ? obj.evidence_quotes.filter((x): x is string => typeof x === 'string' && Boolean(x))
                                  : []
                                return (
                                  <div
                                    key={key}
                                    className="rounded-md border border-border/60 bg-muted/30 p-2"
                                  >
                                    <div className="flex items-center justify-between gap-2">
                                      <span className="font-medium text-foreground/80">
                                        {key}
                                      </span>
                                      <span className="tabular-nums">
                                        {typeof score === 'number'
                                          ? score.toFixed(3)
                                          : '—'}
                                      </span>
                                    </div>
                                    {typeof reason === 'string' && reason ? (
                                      <div className="mt-1 text-muted-foreground">
                                        {reason}
                                      </div>
                                    ) : null}
                                    {quotes.length ? (
                                      <div className="mt-2 space-y-1">
                                        {quotes.slice(0, 3).map((q) => (
                                          <div
                                            key={q}
                                            className="font-mono text-[11px] text-muted-foreground"
                                          >
                                            “{q}”
                                          </div>
                                        ))}
                                      </div>
                                    ) : null}
                                  </div>
                                )
                              })}
                            </div>
                          </details>
                        )
                      })()}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          {embedded ? <RegressionMetricGuideCard /> : null}
        </div>
      </div>

      {/* AI 生成对话框 */}
      <TestGenerationDialog
        open={showGenerationDialog}
        onClose={() => setShowGenerationDialog(false)}
        onGenerated={handleGenerated}
      />
    </div>
  )
}
