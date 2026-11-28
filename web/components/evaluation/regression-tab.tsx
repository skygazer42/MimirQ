/**
 * 回归测试 Tab
 *
 * 功能：
 * - 测试用例管理
 * - AI 生成问题
 * - 批量运行回归测试
 */

'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import { datasetApi, evaluationApi } from '@/lib/api'
import type { RegressionRun, RegressionRunCreate } from '@/types'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { WorkspaceNotice, WorkspaceNoticeStack } from '@/components/ui/operational-workspace'
import { TestCaseManager } from '@/components/test-case-manager'
import { TestGenerationDialog } from '@/components/test-generation-dialog'
import { Sparkles, Clock3, ChevronDown, Grid3X3 } from '@/components/icons'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { formatApiError, toApiErrorInfo } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { reportClientError } from '@/lib/client-logging'
import { RegressionItemMetadata } from '@/components/evaluation/regression-item-metadata'
import {
  buildRegressionSummaryModel,
  formatRegressionCount,
  formatRegressionMetric,
  formatRegressionRunAnswerMode,
  formatRegressionValue,
  regressionAnswerModeLabels,
} from '@/lib/regression-result-model'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Checkbox } from '@/components/ui/checkbox'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { getRagasMetricOptions, ragasMetricLabel, type RagasMetricOption } from './ragas-metrics'
import { queryKeys } from '@/lib/query-keys'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import evaluationStyles from './evaluation-panels.module.css'

function RegressionInlineStat({
  label,
  value,
  tone = 'neutral',
}: Readonly<{
  label: string
  value: ReactNode
  tone?: 'neutral' | 'success' | 'warning' | 'info'
}>) {
  return (
    <div className={evaluationStyles.inlineStat} data-tone={tone}>
      <span className="text-[13px] font-medium leading-none text-muted-foreground">{label}</span>
      <span className="text-[14px] font-semibold leading-6 tabular-nums">{value}</span>
    </div>
  )
}

function RegressionMetricCompactGrid({
  metrics,
}: Readonly<{
  metrics: Array<{ key: string; value: number }>
}>) {
  return (
    <section className="rounded-2xl border border-border/60 bg-muted/40 p-2">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[12px] font-semibold text-foreground">数值统计</div>
          <div className="mt-0.5 text-[12px] leading-4 text-muted-foreground">
            当前运行的分数、计数和其他数值；缺失项不按零计算。
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-border bg-card px-2 py-0.5 text-[12px] font-medium text-muted-foreground">
          {metrics.length} 项
        </span>
      </div>
      <div className="grid grid-cols-2 gap-1">
        {metrics.map((metric) => (
          <div
            key={metric.key}
            className={evaluationStyles.metricCard}
            data-metric={metric.key}
            title={`${ragasMetricLabel(metric.key)}: ${metric.value}`}
          >
            <span className={evaluationStyles.metricIcon} aria-hidden="true">
              <Grid3X3 />
            </span>
            <div className="truncate text-[12px] font-medium leading-4 text-muted-foreground">
              {ragasMetricLabel(metric.key)}
            </div>
            <div className="mt-0.5 font-mono text-[14px] font-semibold leading-6 tabular-nums text-foreground">
              {metric.value}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function RegressionConfigToggle({
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
    <div className={cn('border-b border-border bg-transparent py-3', disabled && 'opacity-60')}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground">{title}</div>
          <div className="mt-1 text-[13px] leading-4 text-muted-foreground">{description}</div>
        </div>
        <Switch aria-label={title} checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} />
      </div>
    </div>
  )
}

const REGRESSION_CORE_METRIC_KEYS = new Set(['faithfulness', 'response_relevancy', 'context_precision'])

type RegressionRunSubmission = Readonly<{
  status: 'accepted' | 'rejected' | 'unconfirmed'
  message: string
}>

function RegressionMetricPicker({
  disabled = false,
  metricKeys,
  onMetricKeysChange,
}: Readonly<{
  disabled?: boolean
  metricKeys: string[]
  onMetricKeysChange: (nextKeys: string[]) => void
}>) {
  const regressionMetrics = getRagasMetricOptions('regression')
  const coreMetrics = regressionMetrics.filter((metric) => REGRESSION_CORE_METRIC_KEYS.has(metric.key))
  const advancedMetrics = regressionMetrics.filter((metric) => !REGRESSION_CORE_METRIC_KEYS.has(metric.key))
  const selectedAdvancedMetrics = advancedMetrics.filter((metric) => metricKeys.includes(metric.key))

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
              checked={metricKeys.includes(metric.key)}
              disabled={disabled}
              metric={metric}
              onCheckedChange={(checked) => setMetricChecked(metric.key, checked)}
            />
          ))}
        </div>

        <details className="group overflow-hidden rounded-xl border border-border/60 bg-muted/40">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-2.5 py-2 [&::-webkit-details-marker]:hidden">
            <div className="min-w-0">
              <div className="text-[12px] font-semibold text-foreground">高级程序化指标</div>
              <div className="mt-0.5 line-clamp-1 text-[13px] text-muted-foreground">
                默认收起，按需要补充引用归因、上下文利用与鲁棒性指标。
              </div>
              {selectedAdvancedMetrics.length ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {selectedAdvancedMetrics.slice(0, 3).map((metric) => (
                    <span
                      key={metric.key}
                      className="rounded-full border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[12px] font-medium text-primary"
                    >
                      {metric.label}
                    </span>
                  ))}
                  {selectedAdvancedMetrics.length > 3 ? (
                    <span className="rounded-full border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[12px] font-medium text-primary">
                      +{selectedAdvancedMetrics.length - 3}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-card px-2 py-1 text-[12px] font-medium text-muted-foreground">
              {selectedAdvancedMetrics.length
                ? `${selectedAdvancedMetrics.length} 已选`
                : `${advancedMetrics.length} 项`}
              <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
            </span>
          </summary>
          <div className="grid gap-1.5 border-t border-border/60 bg-card p-2 md:grid-cols-2">
            {advancedMetrics.map((metric) => (
              <RegressionMetricOption
                key={metric.key}
                checked={metricKeys.includes(metric.key)}
                disabled={disabled}
                metric={metric}
                onCheckedChange={(checked) => setMetricChecked(metric.key, checked)}
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
  disabled,
  metric,
  onCheckedChange,
}: Readonly<{
  checked: boolean
  disabled: boolean
  metric: RagasMetricOption
  onCheckedChange: (checked: boolean) => void
}>) {
  const detailLabel = `${metric.label}，${metric.kind}，${metric.category}，${metric.cost}。${metric.hint}`

  return (
    <label
      className={cn(
        'flex items-start gap-2 rounded-xl border border-border/60 bg-card/95 px-2 py-1.5 shadow-sm',
        disabled && 'cursor-not-allowed',
      )}
    >
      <Checkbox checked={checked} disabled={disabled} onCheckedChange={(value) => onCheckedChange(value === true)} />
      <span className="min-w-0 flex-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              aria-label={detailLabel}
              className="block cursor-help outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
              tabIndex={disabled ? -1 : 0}
            >
              <span className="flex flex-wrap items-center gap-1.5 text-[13px] font-medium text-foreground">
                <span className="truncate">{metric.label}</span>
                <span className="rounded-full border border-border bg-muted/50 px-1.5 py-0.5 text-[12px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                  {metric.kind}
                </span>
              </span>
              <span className="mt-0.5 block line-clamp-1 text-[12px] leading-3 text-muted-foreground">
                {metric.hint}
              </span>
            </span>
          </TooltipTrigger>
          <TooltipContent
            align="start"
            className="max-w-[320px] rounded-xl border border-border bg-card px-3 py-2 text-left text-foreground/85 shadow-strong"
            side="right"
            sideOffset={8}
          >
            <div className="text-[12px] font-semibold leading-5 text-foreground">{metric.label}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {[metric.kind, metric.category, metric.cost].map((item) => (
                <span
                  key={item}
                  className="rounded-full border border-border bg-muted/50 px-1.5 py-0.5 text-[12px] font-medium text-muted-foreground"
                >
                  {item}
                </span>
              ))}
            </div>
            <div className="mt-2 text-[13px] leading-5 text-muted-foreground">{metric.hint}</div>
          </TooltipContent>
        </Tooltip>
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
    'bg-primary/10 text-primary border-primary/20',
    'bg-accent/10 text-accent border-accent/20',
    'bg-success/10 text-success border-success/20',
    'bg-success/10 text-success border-success/20',
    'bg-destructive/10 text-destructive border-destructive/20',
  ]

  return (
    <div className="shrink-0 rounded-lg border border-border/60 bg-card p-2">
      <div className="text-[13px] uppercase tracking-[0.12em] text-muted-foreground">Metric Guide</div>
      <div className="mt-1 text-sm font-semibold text-foreground">评测维度速览</div>
      <div className="mt-2 space-y-1.5">
        {REGRESSION_METRIC_GUIDE.map(([label, description], index) => (
          <div key={label} className="flex items-start gap-2">
            <span
              className={cn(
                'mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[12px] font-semibold',
                tones[index],
              )}
            >
              {index + 1}
            </span>
            <span className="min-w-0">
              <span className="block text-[12px] font-semibold text-foreground">{label}</span>
              <span className="mt-0.5 block text-[12px] leading-3 text-muted-foreground">{description}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function RegressionTestTab() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <RegressionWorkspace key={sessionKey} sessionKey={sessionKey} />
}

function RegressionWorkspace({ sessionKey }: Readonly<{ sessionKey: string }>) {
  const queryClient = useQueryClient()
  const searchParams = useSearchParams()
  const deepLinkDatasetId = searchParams.get('dataset_id') ?? ''
  const deepLinkRunId = searchParams.get('run_id') ?? ''
  const [showGenerationDialog, setShowGenerationDialog] = useState(false)

  // Dataset scope (required by backend for cases and runs)
  const [selectedDatasetId, setSelectedDatasetId] = useState(deepLinkDatasetId)
  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    staleTime: 30_000,
  })
  const datasets = datasetsQuery.data
  const isLoadingDatasets = datasetsQuery.isLoading || datasetsQuery.isFetching
  const selectedDataset = datasets?.find((dataset) => dataset.id === selectedDatasetId)
  const selectedDatasetLabel =
    selectedDatasetId === ''
      ? '选择数据集'
      : selectedDataset === undefined
        ? selectedDatasetId
        : `${selectedDataset.name}（${selectedDataset.id}）`
  const latestRegressionCaseQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionCases({ limit: 1 }),
    queryFn: ({ signal }) => evaluationApi.listRegressionCases({ limit: 1 }, { signal }),
    staleTime: 30_000,
  })
  const latestRegressionCaseDatasetId = latestRegressionCaseQuery.data?.items[0]?.dataset_id
  const isLoadingLatestRegressionCase = latestRegressionCaseQuery.isLoading || latestRegressionCaseQuery.isFetching

  // 运行配置
  const [answerMode, setAnswerMode] = useState<NonNullable<RegressionRunCreate['answer_mode']>>('rag')
  const [metricKeys, setMetricKeys] = useState<string[]>(['faithfulness', 'response_relevancy'])
  const [retrievalOnly, setRetrievalOnly] = useState(false)
  const [useLlmJudge, setUseLlmJudge] = useState(false)
  const missingScoringMetrics = !retrievalOnly && metricKeys.length === 0
  const runMetricKeys = retrievalOnly ? [] : metricKeys
  const runUsesLlmJudge = !retrievalOnly && useLlmJudge

  // 运行历史
  const [runSelection, setRunSelection] = useState<Readonly<{ datasetId: string; runId: string }> | null>(() =>
    deepLinkRunId === '' ? null : { datasetId: deepLinkDatasetId, runId: deepLinkRunId },
  )
  const selectedRunId =
    runSelection !== null && runSelection.datasetId === selectedDatasetId ? runSelection.runId : null
  const ownerRef = useRef({ active: true })
  const runScopeRef = useRef<{ datasetId: string; active: boolean } | null>(null)
  const currentRunSelectionRef = useRef(runSelection)
  const runRequestsRef = useRef(new Map<string, Promise<RegressionRun>>())
  const [pendingDatasetIds, setPendingDatasetIds] = useState<ReadonlySet<string>>(() => new Set())
  const [runSubmissions, setRunSubmissions] = useState<ReadonlyMap<string, RegressionRunSubmission>>(() => new Map())

  useLayoutEffect(() => {
    const owner = { active: true }
    ownerRef.current = owner
    return () => {
      owner.active = false
    }
  }, [])
  useLayoutEffect(() => {
    const scope = { datasetId: selectedDatasetId, active: true }
    runScopeRef.current = scope
    return () => {
      scope.active = false
    }
  }, [selectedDatasetId])
  useLayoutEffect(() => {
    currentRunSelectionRef.current = runSelection
  }, [runSelection])

  const runListDatasetId = selectedDatasetId === '' ? undefined : selectedDatasetId
  const runListParams = { limit: 50, dataset_id: runListDatasetId }
  const runsQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionRuns(runListParams),
    queryFn: ({ signal }) => evaluationApi.listRegressionRuns(runListParams, { signal }),
  })
  const runDetailQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionRunDetail(selectedRunId, {
      include_items: true,
      include_contexts: false,
    }),
    queryFn:
      selectedRunId === null
        ? skipToken
        : ({ signal }) =>
            evaluationApi.getRegressionRun(selectedRunId, { include_items: true, include_contexts: false }, { signal }),
    refetchInterval: (query) => {
      const detail = query.state.data
      if (detail === undefined || (selectedDatasetId !== '' && detail.run.dataset_id !== selectedDatasetId))
        return false
      const status = detail.run.status
      return status === 'pending' || status === 'running' ? 2000 : false
    },
  })
  const visibleRuns = runsQuery.data?.items
  const receivedRunDetail = runDetailQuery.data
  const runScopeMismatch =
    receivedRunDetail !== undefined &&
    selectedDatasetId !== '' &&
    receivedRunDetail.run.dataset_id !== selectedDatasetId
  const runDetail = runScopeMismatch ? undefined : receivedRunDetail
  const loadedRunId = runDetail?.run.id
  const loadedRunStatus = runDetail?.run.status
  useEffect(() => {
    if (loadedRunId === undefined || (loadedRunStatus !== 'completed' && loadedRunStatus !== 'failed')) return
    void queryClient.invalidateQueries({
      queryKey: queryKeys.evaluations.regressionRuns({ limit: 50, dataset_id: runListDatasetId }),
      exact: true,
    })
  }, [queryClient, runListDatasetId, loadedRunId, loadedRunStatus])
  const isLoadingRuns = runsQuery.isPending
  const creatingRun = pendingDatasetIds.has(selectedDatasetId)
  const runSubmission = runSubmissions.get(selectedDatasetId)

  useLayoutEffect(() => {
    setSelectedDatasetId(deepLinkDatasetId)
    setRunSelection(deepLinkRunId === '' ? null : { datasetId: deepLinkDatasetId, runId: deepLinkRunId })
  }, [deepLinkDatasetId, deepLinkRunId])

  useEffect(() => {
    if (creatingRun || selectedDatasetId === '') return
    if (runSelection !== null && runSelection.datasetId === selectedDatasetId) return
    const firstRun = visibleRuns?.[0]
    if (firstRun !== undefined) setRunSelection({ datasetId: selectedDatasetId, runId: firstRun.id })
  }, [creatingRun, runSelection, selectedDatasetId, visibleRuns])

  useEffect(() => {
    if (selectedDatasetId !== '') return
    if (selectedRunId !== null) {
      if (runDetail === undefined || runDetailQuery.error !== null || runDetail.run.dataset_id === null) return
      setSelectedDatasetId(runDetail.run.dataset_id)
      setRunSelection({ datasetId: runDetail.run.dataset_id, runId: runDetail.run.id })
      return
    }
    if (datasets === undefined || datasetsQuery.error !== null || datasets.length === 0) return
    if (deepLinkDatasetId === '' && (isLoadingLatestRegressionCase || latestRegressionCaseQuery.error !== null)) return
    setSelectedDatasetId((prev) => {
      if (prev !== '') return prev
      if (deepLinkDatasetId !== '') {
        return deepLinkDatasetId
      }
      const latestCaseDataset = datasets.find((dataset) => dataset.id === latestRegressionCaseDatasetId)
      return (latestCaseDataset ?? datasets[0]).id
    })
  }, [
    datasets,
    datasetsQuery.error,
    deepLinkDatasetId,
    deepLinkRunId,
    isLoadingLatestRegressionCase,
    latestRegressionCaseDatasetId,
    latestRegressionCaseQuery.error,
    runDetail,
    runDetailQuery.error,
    selectedDatasetId,
    selectedRunId,
  ])

  useEffect(() => {
    if (runsQuery.error === null) return
    reportClientError('Failed to load regression run history', runsQuery.error)
  }, [runsQuery.error])

  // 运行选中的测试
  const handleRunTests = async (caseIds: string[]) => {
    const scope = runScopeRef.current
    const owner = ownerRef.current
    if (!owner.active || getAuthSessionKey() !== sessionKey || scope === null || !scope.active) return
    if (selectedDatasetId === '' || scope.datasetId !== selectedDatasetId) {
      toast.error('请先选择数据集')
      return
    }
    if (missingScoringMetrics) {
      toast.error('请在运行配置中选择至少一个评分指标，或开启仅检索评测')
      return
    }
    const ids = [...new Set(caseIds)]
    if (ids.length === 0) {
      toast.error('请至少选择一个评测样本')
      return
    }
    if (ids.length > 500) {
      toast.error('一次最多运行 500 个评测样本，请减少选择后提交')
      return
    }
    const datasetId = scope.datasetId
    if (runRequestsRef.current.has(datasetId)) return
    const selectedAtStart = currentRunSelectionRef.current
    const params: RegressionRunCreate = {
      case_ids: ids,
      dataset_id: datasetId,
      answer_mode: answerMode,
      metrics: runMetricKeys,
      use_llm_judge: runUsesLlmJudge,
      skip_empty_contexts: false,
      max_cases: ids.length,
    }
    const request = evaluationApi.createRegressionRun(params)
    runRequestsRef.current.set(datasetId, request)
    setPendingDatasetIds(new Set(runRequestsRef.current.keys()))
    setRunSubmissions((current) => {
      const next = new Map(current)
      next.delete(datasetId)
      return next
    })

    try {
      const run = await request
      if (!owner.active || getAuthSessionKey() !== sessionKey) return
      const message = `数据集 ${datasetId} 已提交评测运行 ${run.id}`
      setRunSubmissions((current) => new Map(current).set(datasetId, { status: 'accepted', message }))
      if (scope.active) {
        toast.success(message)
        if (currentRunSelectionRef.current === selectedAtStart) setRunSelection({ datasetId, runId: run.id })
      }
    } catch (error) {
      if (!owner.active || getAuthSessionKey() !== sessionKey) return
      reportClientError('Failed to run Golden regression evaluation', error)
      const { status } = toApiErrorInfo(error, '评测运行提交失败')
      const rejected = status !== undefined && status >= 400 && status < 500 && status !== 408
      const message = formatApiError(
        error,
        rejected ? '评测提交被拒绝' : '评测提交结果未确认，请先重新读取运行记录核对',
      )
      setRunSubmissions((current) =>
        new Map(current).set(datasetId, { status: rejected ? 'rejected' : 'unconfirmed', message }),
      )
      if (scope.active) toast.error(message)
    } finally {
      if (runRequestsRef.current.get(datasetId) === request) runRequestsRef.current.delete(datasetId)
      if (owner.active && getAuthSessionKey() === sessionKey)
        setPendingDatasetIds(new Set(runRequestsRef.current.keys()))
    }
    if (owner.active && getAuthSessionKey() === sessionKey) {
      await queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.regressionRunLists })
    }
  }

  const summaryResult = useMemo(
    () => (runDetail === undefined ? undefined : buildRegressionSummaryModel(runDetail.run.summary)),
    [runDetail],
  )
  const summaryModel = summaryResult?.status === 'ready' ? summaryResult : undefined

  const showLatestCaseError =
    deepLinkDatasetId === '' &&
    selectedDatasetId === '' &&
    selectedRunId === null &&
    latestRegressionCaseQuery.error !== null
  const hasFloatingRunsRefreshError = runsQuery.error !== null && visibleRuns !== undefined
  const hasFloatingRunDetailRefreshError = runDetailQuery.error !== null && runDetail !== undefined
  const hasFloatingRegressionNotice =
    datasetsQuery.error !== null ||
    showLatestCaseError ||
    hasFloatingRunsRefreshError ||
    hasFloatingRunDetailRefreshError

  return (
    <div className={cn('flex-1 flex flex-col min-h-0 overflow-hidden', evaluationStyles.golden)}>
      {hasFloatingRegressionNotice ? (
        <WorkspaceNoticeStack ariaLabel="回归评测状态提示">
          {datasetsQuery.error !== null ? (
            <WorkspaceNotice
              tone="warning"
              title={datasets === undefined ? '数据集目录读取失败' : '更新失败，保留上次目录和当前选择'}
              error={datasetsQuery.error}
              fallbackMessage="数据集目录读取失败"
              retry={() => void datasetsQuery.refetch()}
              retryLabel="重新读取数据集目录"
              pending={datasetsQuery.isFetching}
            />
          ) : null}
          {showLatestCaseError ? (
            <WorkspaceNotice
              tone="warning"
              title="最近评测范围读取失败，请手动选择数据集"
              error={latestRegressionCaseQuery.error}
              fallbackMessage="最近评测范围读取失败，请手动选择数据集"
              retry={() => void latestRegressionCaseQuery.refetch()}
              retryLabel="重新读取最近评测范围"
              pending={latestRegressionCaseQuery.isFetching}
            />
          ) : null}
          {hasFloatingRunsRefreshError ? (
            <WorkspaceNotice
              tone="warning"
              title="更新失败，保留上次历史"
              error={runsQuery.error}
              fallbackMessage="运行历史读取失败"
              retry={() => void runsQuery.refetch()}
              retryLabel="重新读取运行历史"
              pending={runsQuery.isFetching}
            />
          ) : null}
          {hasFloatingRunDetailRefreshError ? (
            <WorkspaceNotice
              tone="warning"
              title="更新失败，保留上次详情"
              error={runDetailQuery.error}
              fallbackMessage="运行详情读取失败"
              retry={() => void runDetailQuery.refetch()}
              retryLabel="重新读取运行详情"
              pending={runDetailQuery.isFetching}
            />
          ) : null}
        </WorkspaceNoticeStack>
      ) : null}
      {datasetsQuery.isFetching && datasets !== undefined ? (
        <p role="status" className="text-sm text-muted-foreground">
          正在更新数据集目录，保留当前选择。
        </p>
      ) : null}
      <Dialog>
        <div className={evaluationStyles.goldenToolbar}>
          <div>
            <h2>{selectedDatasetLabel}</h2>
            <span className={evaluationStyles.goldenToolbarCaption}>标准问答与证据</span>
          </div>
          <div>
            <Button variant="outline" onClick={() => setShowGenerationDialog(true)}>
              <Sparkles className="size-4" />
              生成候选
            </Button>
            <DialogTrigger asChild>
              <Button variant="outline">Golden 评测配置</Button>
            </DialogTrigger>
          </div>
        </div>
        <DialogContent className={evaluationStyles.goldenConfigDialog}>
          <DialogTitle className="sr-only">Golden 评测参数</DialogTitle>
          <DialogDescription className="sr-only">配置数据集、运行方式和评分指标。</DialogDescription>
          <div className={evaluationStyles.goldenConfigBody}>
            <div className="shrink-0 border-b border-border bg-info/[0.025] px-3 py-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[13px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                    运行参数
                  </div>
                  <div className="mt-1 text-sm font-semibold text-foreground">Golden 评测配置</div>
                  <p className="mt-1 text-[13px] leading-4 text-muted-foreground">
                    按数据集维护 Golden 样本并配置评测方式。
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <DialogClose asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="px-2 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      完成
                    </Button>
                  </DialogClose>
                </div>
              </div>

              <div className="mt-3 rounded-2xl border border-border bg-background/70 p-2.5 shadow-none">
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span className="text-[13px] font-medium text-muted-foreground">数据集</span>
                  <span
                    className={cn(
                      'rounded-full border px-1.5 py-0.5 text-[12px] font-medium',
                      selectedDatasetId
                        ? 'border-success/30 bg-success/10 text-success'
                        : 'border-warning/30 bg-warning/10 text-warning',
                    )}
                  >
                    {selectedDatasetId ? '已绑定' : '未绑定'}
                  </span>
                </div>
                <Select
                  value={selectedDatasetId}
                  onValueChange={setSelectedDatasetId}
                  disabled={isLoadingDatasets || datasets === undefined || datasets.length === 0}
                >
                  <SelectTrigger aria-label="评测配置数据集" className="text-[13px]">
                    <SelectValue placeholder={isLoadingDatasets ? '加载中...' : '选择数据集'} />
                  </SelectTrigger>
                  <SelectContent>
                    {selectedDatasetId !== '' && selectedDataset === undefined ? (
                      <SelectItem value={selectedDatasetId} disabled>
                        已选数据集：{selectedDatasetId}
                      </SelectItem>
                    ) : null}
                    {datasets?.map((dataset) => (
                      <SelectItem key={dataset.id} value={dataset.id}>
                        {dataset.name} <span className="font-mono text-xs text-muted-foreground">({dataset.id})</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {datasets !== undefined && datasets.length === 0 ? (
                  <div className="mt-2 text-[13px] leading-4 text-muted-foreground">
                    当前目录没有可选数据集，已有运行历史仍可查看。
                  </div>
                ) : null}
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <RegressionInlineStat label="runs" value={visibleRuns === undefined ? '未取得' : visibleRuns.length} />
                <RegressionInlineStat
                  label="metrics"
                  value={retrievalOnly ? '检索-only' : metricKeys.length}
                  tone={retrievalOnly ? 'info' : 'neutral'}
                />
                <RegressionInlineStat
                  label="judge"
                  value={runUsesLlmJudge ? 'ON' : 'OFF'}
                  tone={runUsesLlmJudge ? 'success' : 'neutral'}
                />
              </div>
            </div>

            <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto overscroll-contain p-2.5 pb-6 custom-scrollbar">
              <section className="border-t border-border bg-success/[0.04] py-4">
                <h3 className="text-[13px] font-medium uppercase tracking-[0.12em] text-muted-foreground">运行方式</h3>
                <div className="mt-3 max-w-xs space-y-1.5">
                  <Label htmlFor="golden-answer-mode" className="text-[13px]">
                    问答模式
                  </Label>
                  <Select value={answerMode} onValueChange={(mode) => setAnswerMode(mode as typeof answerMode)}>
                    <SelectTrigger
                      id="golden-answer-mode"
                      aria-describedby="golden-answer-mode-description"
                      className="text-[13px]"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="rag">{regressionAnswerModeLabels.rag}</SelectItem>
                      <SelectItem value="ontology">{regressionAnswerModeLabels.ontology}</SelectItem>
                    </SelectContent>
                  </Select>
                  <p id="golden-answer-mode-description" className="text-[13px] leading-4 text-muted-foreground">
                    本体问答使用已发布本体的图谱证据。
                  </p>
                </div>
                <div className="mt-3 space-y-2">
                  <RegressionConfigToggle
                    title="仅检索评测"
                    description="只比较检索结果与标准证据。"
                    checked={retrievalOnly}
                    onCheckedChange={setRetrievalOnly}
                  />
                  <RegressionConfigToggle
                    title="LLM-as-Judge"
                    description="为每个样本生成得分、理由和原文证据。"
                    checked={runUsesLlmJudge}
                    disabled={retrievalOnly}
                    onCheckedChange={setUseLlmJudge}
                  />
                </div>
              </section>

              <details className="group overflow-hidden border-t border-border bg-info/[0.025]">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-2.5 py-2.5 [&::-webkit-details-marker]:hidden">
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                      评分维度
                    </div>
                    <p className="mt-1 line-clamp-2 text-[13px] leading-4 text-muted-foreground">
                      {missingScoringMetrics ? '评分评测至少需要一个指标。' : '展开后选择 RAGAS 与程序化指标。'}
                    </p>
                  </div>
                  <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-card px-2 py-1 text-[12px] font-medium text-muted-foreground">
                    {retrievalOnly ? '检索-only' : `${metricKeys.length} 已选`}
                    <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180 motion-reduce:transition-none" />
                  </span>
                </summary>
                <div className="border-t border-border/60 bg-card/80 p-2.5">
                  <RegressionMetricPicker
                    metricKeys={runMetricKeys}
                    onMetricKeysChange={setMetricKeys}
                    disabled={retrievalOnly}
                  />
                </div>
              </details>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <div className={evaluationStyles.goldenGrid}>
        {/* 左侧：测试用例管理 */}
        <div className={cn('flex flex-col bg-background rounded-2xl border border-border', evaluationStyles.casePane)}>
          {creatingRun ? (
            <p role="status" className="text-sm text-muted-foreground">
              正在提交当前数据集的评测运行…
            </p>
          ) : null}
          <TestCaseManager
            key={selectedDatasetId}
            datasetId={selectedDatasetId === '' ? null : selectedDatasetId}
            dense
            isRunning={creatingRun}
            onRunTests={handleRunTests}
          />
        </div>

        {/* 右侧：运行结果 */}
        <div className={cn('flex-1 flex flex-col gap-2.5', evaluationStyles.goldenResults)}>
          {/* 运行历史列表 */}
          <div
            className={cn(
              'shrink-0 bg-background border border-border rounded-2xl overflow-hidden',
              evaluationStyles.goldenSection,
            )}
          >
            <div className="p-3 border-b border-border flex items-center justify-between bg-info/[0.025]">
              <div>
                <div className="mt-1 text-sm font-semibold text-foreground">运行历史</div>
              </div>
              <div className="text-[13px] text-muted-foreground">
                最近已读取 {visibleRuns === undefined ? '未取得' : visibleRuns.length} 条
                {selectedDatasetId === '' ? null : '（当前数据集）'}
              </div>
            </div>
            <div className="overflow-y-auto overscroll-contain custom-scrollbar max-h-[190px]">
              {runsQuery.error !== null && visibleRuns === undefined ? (
                <WorkspaceNotice
                  retry={() => void runsQuery.refetch()}
                  retryLabel="重新读取运行历史"
                  pending={runsQuery.isFetching}
                >
                  {formatApiError(runsQuery.error, '运行历史读取失败')}
                </WorkspaceNotice>
              ) : null}
              {runsQuery.isFetching && visibleRuns !== undefined ? (
                <p role="status" className="text-sm text-muted-foreground">
                  正在更新运行历史，保留当前选择。
                </p>
              ) : null}
              {selectedRunId !== null &&
              visibleRuns !== undefined &&
              !visibleRuns.some((run) => run.id === selectedRunId) ? (
                <p role="status" className="text-sm text-muted-foreground">
                  已选运行 {selectedRunId} 不在本次最近记录中。
                </p>
              ) : null}
              {(() => {
                if (visibleRuns === undefined) {
                  return (
                    <div role="status" className="flex items-center justify-center py-8">
                      {isLoadingRuns ? '正在读取运行历史…' : '运行历史暂不可用。'}
                    </div>
                  )
                } else if (visibleRuns.length === 0) {
                  return (
                    <div className="flex min-h-[128px] flex-col items-center justify-center px-3 py-5 text-center">
                      <div className="text-sm font-medium text-foreground">暂无运行记录</div>
                      <div className="mt-1 text-[13px] leading-4 text-muted-foreground">运行后可在此切换记录。</div>
                    </div>
                  )
                } else {
                  return visibleRuns.map((run) => (
                    <button
                      key={run.id}
                      type="button"
                      aria-pressed={selectedRunId === run.id}
                      onClick={() => {
                        const datasetId =
                          selectedDatasetId === '' && run.dataset_id !== null ? run.dataset_id : selectedDatasetId
                        const selection = { datasetId, runId: run.id }
                        currentRunSelectionRef.current = selection
                        if (selectedDatasetId === '') setSelectedDatasetId(datasetId)
                        setRunSelection(selection)
                      }}
                      className={cn(
                        'w-full text-left border-b border-border/60 px-2.5 py-2 hover:bg-muted/40 transition-colors motion-reduce:transition-none',
                        selectedRunId === run.id && 'bg-info/5',
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-medium text-foreground truncate">运行 {run.id.slice(0, 8)}</div>
                        <span className={evaluationStyles.runStatus} data-status={run.status}>
                          {run.status}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                        <span>{formatRegressionRunAnswerMode(run)}</span>
                        <span className="inline-flex items-center gap-1">
                          <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                          {new Date(run.created_at).toLocaleString()}
                        </span>
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
              'flex-1 bg-background border border-border rounded-2xl p-2.5 overflow-y-auto overscroll-contain custom-scrollbar',
              evaluationStyles.goldenSection,
            )}
          >
            <div className="mb-3">
              <div>
                <div className="mt-1 text-sm font-semibold text-foreground">结果与标准对照</div>
                <div className="mt-0.5 text-[13px] text-muted-foreground">
                  {runDetail === undefined
                    ? '对照标准答案、引用证据和预期元数据。'
                    : formatRegressionRunAnswerMode(runDetail.run)}
                </div>
              </div>
            </div>

            {runSubmission !== undefined ? (
              runSubmission.status === 'accepted' ? (
                <p role="status" className="text-sm text-muted-foreground">
                  {runSubmission.message}
                </p>
              ) : (
                <WorkspaceNotice
                  retry={() => void runsQuery.refetch()}
                  retryLabel="重新读取运行记录"
                  pending={runsQuery.isFetching}
                >
                  {runSubmission.message}
                  {runSubmission.status === 'unconfirmed' ? ' 重新提交会新建运行，请先核对记录。' : null}
                </WorkspaceNotice>
              )
            ) : null}
            {runDetailQuery.error !== null && runDetail === undefined ? (
              <WorkspaceNotice
                retry={() => void runDetailQuery.refetch()}
                retryLabel="重新读取运行详情"
                pending={runDetailQuery.isFetching}
              >
                {formatApiError(runDetailQuery.error, '运行详情读取失败')}
              </WorkspaceNotice>
            ) : null}
            {runScopeMismatch ? (
              <WorkspaceNotice>所选运行不属于当前数据集，请更改数据集范围或重新选择运行。</WorkspaceNotice>
            ) : null}
            {runDetail?.run?.error_message && (
              <div className="mt-3 text-sm text-destructive p-3 bg-destructive/10 border border-destructive/20 rounded-lg">
                {runDetail.run.error_message}
              </div>
            )}

            {summaryResult?.status === 'invalid' ? (
              <WorkspaceNotice
                retry={() => void runDetailQuery.refetch()}
                retryLabel="重新读取运行统计"
                pending={runDetailQuery.isFetching}
              >
                {summaryResult.message}
              </WorkspaceNotice>
            ) : null}
            {summaryModel !== undefined && summaryModel.hasSummary ? (
              <div className="mt-4">
                {summaryModel.metrics.length > 0 ? (
                  <RegressionMetricCompactGrid metrics={summaryModel.metrics} />
                ) : null}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <RegressionInlineStat label="样本" value={formatRegressionCount(summaryModel.summary.items)} />
                  <RegressionInlineStat
                    label="标准答案对比"
                    value={
                      summaryModel.metrics.some((metric) =>
                        ['answer_correctness', 'factual_correctness'].includes(metric.key),
                      )
                        ? '已返回分数'
                        : '未提供分数'
                    }
                    tone="info"
                  />
                  <RegressionInlineStat
                    label="标准证据命中"
                    value={formatRegressionMetric(summaryModel.summary.retrieval_recall)}
                    tone="success"
                  />
                  <RegressionInlineStat
                    label="业务元数据命中"
                    value={formatRegressionMetric(summaryModel.summary.expected_metadata_hit_rate)}
                    tone="success"
                  />
                  <RegressionInlineStat
                    label="Token"
                    value={formatRegressionCount(summaryModel.summary.total_tokens)}
                  />
                  <RegressionInlineStat label="费用" value={formatRegressionValue(summaryModel.summary.total_cost)} />
                  {summaryModel.slices.length > 0 ? (
                    <RegressionInlineStat
                      label="切片覆盖"
                      value={summaryModel.sliceSummary}
                      tone={summaryModel.textOnlyFullCoverage ? 'neutral' : 'warning'}
                    />
                  ) : null}
                </div>
                {summaryModel.hasExpectedMetadata ? (
                  <div className="mt-3 rounded-2xl border border-success/25 bg-success/[0.04] p-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-foreground">业务元数据召回</div>
                        <div className="mt-0.5 max-w-2xl text-[13px] leading-5 text-muted-foreground">
                          对照样本声明的 expected_metadata，展示实际返回的字段命中和召回统计。
                        </div>
                      </div>
                      <span className="rounded-full border border-success/30 bg-success/10 px-2 py-1 text-[12px] font-medium text-success">
                        {formatRegressionCount(summaryModel.summary.expected_metadata_cases_total)} cases
                      </span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <RegressionInlineStat
                        label="expected_metadata_hit_rate"
                        value={formatRegressionMetric(summaryModel.summary.expected_metadata_hit_rate)}
                        tone="success"
                      />
                      <RegressionInlineStat
                        label="expected_metadata_recall"
                        value={formatRegressionMetric(summaryModel.summary.expected_metadata_recall)}
                        tone="info"
                      />
                      <RegressionInlineStat
                        label="expected_metadata_fields_matched"
                        value={`${formatRegressionCount(summaryModel.summary.expected_metadata_fields_matched)}/${formatRegressionCount(summaryModel.summary.expected_metadata_fields_total)}`}
                      />
                    </div>
                  </div>
                ) : null}
                {summaryModel.slices.length > 0 && !summaryModel.textOnlyFullCoverage ? (
                  <div className="mt-3 rounded-2xl border border-border bg-info/[0.025] p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-foreground">切片覆盖统计</div>
                        <div className="mt-0.5 text-[13px] text-muted-foreground">
                          仅展示实际返回的非零记录；纯文本完整覆盖保留在上方摘要。
                        </div>
                      </div>
                      <span className="rounded-full border border-border bg-card px-2 py-1 text-[12px] font-medium text-muted-foreground">
                        {formatRegressionCount(summaryModel.summary.multimodal_slices?.items)} items
                      </span>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
                      {summaryModel.slices.map((slice) => (
                        <div
                          key={slice.key}
                          className="rounded-xl border border-border/60 bg-card/90 px-2.5 py-2 shadow-sm"
                        >
                          <div className="text-[13px] font-semibold text-foreground">{slice.label}</div>
                          <div className="mt-1 text-lg font-semibold leading-none text-foreground tabular-nums">
                            {slice.evaluatable}/{slice.count}
                          </div>
                          <div className="mt-1 text-[12px] text-muted-foreground">
                            覆盖率 {(slice.coverage * 100).toFixed(2)}%
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {summaryModel.qualityGroups.length > 0 ? (
                  <div className="mt-4">
                    <div className="text-sm font-semibold text-foreground mb-3">质量归因</div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {summaryModel.qualityGroups.map((group) => (
                        <div key={group.title} className="rounded-xl border border-border bg-muted/20 p-3">
                          <div className="text-xs font-semibold text-foreground mb-2">{group.title}</div>
                          {group.truncated ? (
                            <p className="text-xs text-muted-foreground">本次结果仅包含部分分桶。</p>
                          ) : null}
                          {group.buckets.length === 0 ? (
                            <p role="status" className="text-xs text-muted-foreground">
                              本次没有分桶记录。
                            </p>
                          ) : null}
                          <div className="overflow-auto">
                            <table aria-label={`${group.title} 分桶统计`} className="w-full text-xs">
                              <thead>
                                <tr className="text-muted-foreground border-b border-border/60">
                                  <th className="text-left py-1 pr-2">bucket</th>
                                  <th className="text-right py-1 pr-2">items</th>
                                  <th className="text-right py-1 pr-2">recall</th>
                                  <th className="text-right py-1 pr-2">mrr</th>
                                  <th className="text-right py-1 pr-2">ndcg@10</th>
                                </tr>
                              </thead>
                              <tbody>
                                {group.buckets.map((bucket) => (
                                  <tr key={bucket.key} className="border-b border-border/40">
                                    <td className="py-1 pr-2 font-mono text-muted-foreground">{bucket.key}</td>
                                    <td className="py-1 pr-2 text-right tabular-nums">{bucket.items}</td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {formatRegressionMetric(bucket.retrieval_recall)}
                                    </td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {formatRegressionMetric(bucket.retrieval_mrr)}
                                    </td>
                                    <td className="py-1 pr-2 text-right tabular-nums">
                                      {formatRegressionMetric(bucket.retrieval_ndcg_at_10)}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <div
                className="mt-3 rounded-2xl border border-dashed border-border bg-muted/20 px-3 py-5 text-center"
                role="status"
              >
                {selectedRunId === null
                  ? '先选择一个运行记录。'
                  : runDetailQuery.isFetching && runDetail === undefined
                    ? '正在读取运行统计…'
                    : '当前运行没有可展示的统计。'}
              </div>
            )}
            {runDetail !== undefined ? (
              <details className="mt-3 rounded-xl border border-border p-3">
                <summary className="cursor-pointer text-sm">原始运行统计</summary>
                <pre className="mt-2 overflow-auto whitespace-pre-wrap break-words text-xs">
                  {JSON.stringify(runDetail.run.summary, null, 2)}
                </pre>
              </details>
            ) : null}

            {/* 明细列表 */}
            {runDetail !== undefined && runDetail.items.length > 0 && (
              <div className="mt-6">
                <div className="text-sm font-semibold text-foreground mb-3">样本明细 ({runDetail.items.length})</div>
                <div className="space-y-2">
                  {runDetail.items.map((item, index: number) => (
                    <div key={item.id} className="p-3 rounded-lg border border-border/60 bg-muted/20">
                      <div className="text-sm font-medium text-foreground mb-1">
                        {index + 1}. {item.question}
                      </div>
                      <div className="text-xs text-muted-foreground mt-2 whitespace-pre-wrap break-words line-clamp-2">
                        <span className="font-medium">实际回答:</span> {item.response}
                      </div>
                      {Object.keys(item.scores).length > 0 && (
                        <div className="flex gap-2 mt-2">
                          {Object.entries(item.scores).map(([k, v]) => (
                            <span
                              key={k}
                              className="text-[13px] px-2 py-0.5 rounded-full bg-info/10 text-info border border-info/20"
                            >
                              {k}: {formatRegressionValue(v)}
                            </span>
                          ))}
                        </div>
                      )}
                      <RegressionItemMetadata metadata={item.meta} />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <details className={cn('group', evaluationStyles.guide)}>
            <summary className="flex list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
              <ChevronDown
                className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                aria-hidden="true"
              />
              指标说明
            </summary>
            <RegressionMetricGuideCard />
          </details>
        </div>
      </div>

      {/* AI 生成对话框 */}
      <TestGenerationDialog
        open={showGenerationDialog}
        onClose={() => setShowGenerationDialog(false)}
        initialDatasetId={selectedDatasetId}
      />
    </div>
  )
}
