'use client'
import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useRef, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react'
import { ChevronDown, Database, GitCompare, Info, MoreHorizontal } from '@/components/icons'
import { toast } from 'sonner'
import { AppFrame } from '@/components/app-frame'
import { AblationCaseDrilldown } from '@/components/evaluation/ablation-case-drilldown'
import { AblationComparisonMatrix } from '@/components/evaluation/ablation-comparison-matrix'
import { AblationComparisonSummary } from '@/components/evaluation/ablation-comparison-summary'
import { AblationGridPanel } from '@/components/evaluation/ablation-grid-panel'
import { AblationParameterImpactPanel } from '@/components/evaluation/ablation-parameter-impact-panel'
import { AblationParetoPanel } from '@/components/evaluation/ablation-pareto-panel'
import { AblationSliceDiffPanel } from '@/components/evaluation/ablation-slice-diff-panel'
import { AblationStatisticsPanel } from '@/components/evaluation/ablation-statistics-panel'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  OperationalWorkspace,
  WorkspaceNotice,
  WorkspaceNoticeStack,
  WorkspaceTableScroll,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { downloadBlob } from '@/lib/download'
import { datasetApi } from '@/lib/api/datasets'
import { evaluationApi } from '@/lib/api/evaluation'
import { Link } from '@/i18n/navigation'
import { queryKeys } from '@/lib/query-keys'
import { RERANKER_PROVIDER_OPTIONS } from '@/lib/reranker-provider-options'
import { formatRegressionRunAnswerMode } from '@/lib/regression-result-model'
import { sanitizeFilename } from '@/lib/sanitize'
import {
  analyzeRegressionRuns,
  getRegressionRunMetric,
  getRegressionRunParameters,
  isParetoRun,
} from '@/lib/regression-run-statistics'
import {
  regressionRunAblationParamsSchema,
  regressionAblationFormSchema,
  type RegressionRunAblationParams,
} from '@/lib/regression-run-schema'
import type {
  Dataset,
  RagasRegressionRunDiffResponse,
  RegressionAblationGridValue,
  RegressionRunMetricDiff,
  RegressionRun,
  RegressionRunList,
  RegressionAblationBatchResponse,
} from '@/types'
import { cn, detachPromise } from '@/lib/utils'
const EMPTY_DATASETS: Dataset[] = []
const EMPTY_RUNS: RegressionRun[] = []

type RegressionRunQueryState = Pick<UseQueryResult<RegressionRunList>, 'data' | 'error' | 'isFetching' | 'refetch'>

type AblationScope = { datasetId: string; active: boolean }

type AblationRunPayloadConfig = {
  datasetId: string
  retrievalOnly: boolean
  metricKeys: string[]
  skipEmptyContexts: boolean
  maxCases: string
  topK: string
  scoreThreshold: string
  retrievalMode: string
  alpha: string
  enableWeightRerank: boolean
  vectorWeight: string
  keywordWeight: string
  mmrLambda: string
  rerankerMode: string
  rerankerProvider: string
  rerankerTopN: string
}

type AutoBootstrapStage = 'top_k' | 'reranker' | 'retrieval_mode'

type AutoBootstrapPlan = {
  stage: AutoBootstrapStage
  label: string
  helper: string
}

const JSON_TOKEN_PATTERN = new RegExp(
  [
    String.raw`("(?:\\.|[^"\\])*")(\s*:)?`,
    String.raw`\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b`,
    String.raw`\b(?:true|false|null)\b`,
    String.raw`[{}\[\],:]`,
  ].join('|'),
  'g',
)

function downloadJson(value: unknown, filename: string): void {
  try {
    const content = JSON.stringify(value, null, 2)
    if (content === undefined) throw new Error('导出内容不是可序列化JSON')
    downloadBlob(filename, new Blob([content], { type: 'application/json;charset=utf-8' }))
    toast.success('已开始下载对比数据')
  } catch (error) {
    toast.error(formatApiError(error, '导出对比数据失败'))
  }
}

function pickAutoCandidateTopK(currentTopK: number): number {
  return currentTopK === 50 ? 40 : Math.min(currentTopK + 10, 50)
}

const RAGAS_METRIC_OPTIONS = [
  {
    key: 'faithfulness',
    label: '事实一致性',
    hint: '答案是否忠于检索上下文',
  },
  {
    key: 'response_relevancy',
    label: '回答相关性',
    hint: '回答是否真正回应问题',
  },
  {
    key: 'context_precision',
    label: '上下文精度',
    hint: '上下文是否足够精准干净',
  },
]

const RETRIEVAL_MODE_OPTIONS = [
  { key: 'hybrid', label: '混合检索' },
  { key: 'vector', label: '向量检索' },
  { key: 'keyword', label: '关键词检索' },
  { key: 'mmr', label: '多样性召回' },
]

const LEADERBOARD_METRIC_OPTIONS = [
  { key: 'retrieval_mrr', label: '检索平均倒数排名' },
  { key: 'retrieval_recall', label: '检索召回率' },
  { key: 'retrieval_ndcg_at_10', label: '前 10 归一化增益' },
  { key: 'retrieval_ndcg_at_20', label: '前 20 归一化增益' },
  { key: 'faithfulness_det', label: '事实一致性' },
  { key: 'refusal_correctness', label: '拒答正确率' },
]

function formatMetric(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toFixed(4)
}

function leaderboardMetricLabel(key: string): string {
  return LEADERBOARD_METRIC_OPTIONS.find((item) => item.key === key)?.label ?? key
}

function runStatusMeta(statusValue: string): {
  status: 'pending' | 'completed' | 'failed' | 'processing'
  label: string
} {
  if (statusValue === 'completed') return { status: 'completed', label: '已完成' }
  if (statusValue === 'failed') return { status: 'failed', label: '失败' }
  if (statusValue === 'pending' || statusValue === 'queued') return { status: 'pending', label: '待运行' }
  if (statusValue === 'running') return { status: 'processing', label: '运行中' }
  return { status: 'pending', label: `未识别状态：${statusValue}` }
}

function buildRegressionRunPayload(draft: AblationRunPayloadConfig) {
  const config = regressionAblationFormSchema.parse(draft)
  const payload = {
    dataset_id: config.datasetId,
    metrics: config.retrievalOnly ? [] : config.metricKeys,
    skip_empty_contexts: config.skipEmptyContexts,
    max_cases: config.maxCases,
    top_k: config.topK,
    score_threshold: config.scoreThreshold,
    retrieval_mode: config.retrievalMode,
    alpha: config.alpha,
    enable_weight_rerank: config.enableWeightRerank,
    vector_weight: config.vectorWeight,
    keyword_weight: config.keywordWeight,
    mmr_lambda: config.mmrLambda,
  }
  if (config.rerankerMode === 'system') return payload
  if (config.rerankerMode === 'disabled') return { ...payload, enable_reranker: false }
  return {
    ...payload,
    enable_reranker: true,
    reranker_provider: config.rerankerProvider,
    reranker_top_n: config.rerankerTopN,
  }
}

function getComparableRunIds(
  selectedBaseRunId: string,
  selectedTargetRunId: string,
): { baseId: string; targetId: string } | null {
  const baseId = selectedBaseRunId
  const targetId = selectedTargetRunId
  if (!baseId || !targetId) {
    toast.error('请选择基线与候选')
    return null
  }
  if (baseId === targetId) {
    toast.error('基线与候选不能相同')
    return null
  }
  return { baseId, targetId }
}

async function computeRegressionDiff(
  selectedBaseRunId: string,
  selectedTargetRunId: string,
  refetchDiff: () => Promise<{ error: unknown | null }>,
  isCurrent: () => boolean,
): Promise<void> {
  if (!isCurrent()) return
  const pair = getComparableRunIds(selectedBaseRunId, selectedTargetRunId)
  if (pair === null) return
  try {
    const result = await refetchDiff()
    if (isCurrent() && result.error === null) toast.success('已读取差异对比')
  } catch (error) {
    if (isCurrent()) toast.error(formatApiError(error, '读取差异对比失败'))
  }
}

async function exportRegressionDiffHtml(
  selectedBaseRunId: string,
  selectedTargetRunId: string,
  isCurrent: () => boolean,
  signal: AbortSignal,
): Promise<void> {
  if (!isCurrent()) return
  const pair = getComparableRunIds(selectedBaseRunId, selectedTargetRunId)
  if (pair === null) return
  try {
    const blob = await evaluationApi.exportRegressionRunDiffHtml(
      pair.targetId,
      { base_run_id: pair.baseId, redact: true },
      { signal },
    )
    if (!isCurrent()) return
    const name = sanitizeFilename(`regression-diff_${pair.baseId.slice(0, 8)}_vs_${pair.targetId.slice(0, 8)}.html`)
    downloadBlob(name, blob)
    toast.success('已开始下载对比页面')
  } catch (error) {
    if (isCurrent() && !signal.aborted) toast.error(formatApiError(error, '导出对比页面失败'))
  }
}

async function exportRegressionRunBundle(
  runId: string,
  label: 'base' | 'target',
  isCurrent: () => boolean,
  signal: AbortSignal,
): Promise<void> {
  if (!isCurrent()) return
  if (runId === '') {
    toast.error('请选择运行记录')
    return
  }
  try {
    const blob = await evaluationApi.exportRegressionRunBundle(
      runId,
      { include_text: false, include_contexts: false, download: true },
      { signal },
    )
    if (!isCurrent()) return
    downloadBlob(sanitizeFilename(`regression-run_${label}_${runId.slice(0, 8)}.json`), blob)
    toast.success('已开始下载运行记录')
  } catch (error) {
    if (isCurrent() && !signal.aborted) toast.error(formatApiError(error, '导出运行记录失败'))
  }
}

function runSelectText(run: RegressionRun): string {
  const statusMeta = runStatusMeta(run.status)
  return `${formatRegressionRunAnswerMode(run)} · ${run.id} · ${statusMeta.label}`
}

function AblationInfoTooltip({
  label,
  children,
  side = 'right',
}: Readonly<{
  label: string
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
}>) {
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={label}
            className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:bg-info/10 hover:text-info focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/40"
          >
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent side={side} align="center" className="max-w-[280px] text-[11px] leading-5">
          {children}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

function serializeDiffValue(value: unknown): string {
  if (value === undefined) return '未提供'
  return JSON.stringify(value, (_key: string, field: unknown) => {
    if (field === null || typeof field !== 'object' || Array.isArray(field)) return field
    return Object.fromEntries(
      Object.entries(field).sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)),
    )
  })
}

function ablationDeltaClass(value: number | null): string {
  if (value !== null && value > 0) return 'text-success'
  if (value !== null && value < 0) return 'text-destructive'
  return 'text-foreground'
}

function AblationSection({
  title,
  description,
  children,
  className,
  collapsible = true,
  defaultCollapsed = false,
}: Readonly<{
  title: string
  description?: string
  children: ReactNode
  className?: string
  collapsible?: boolean
  defaultCollapsed?: boolean
}>) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  return (
    <section className={cn('border-b border-border bg-background py-5 last:border-b-0', className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-foreground">{title}</div>
          {!collapsed && description ? (
            <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {collapsible ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0 rounded-lg border border-border bg-background text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            onClick={() => setCollapsed((prev) => !prev)}
            aria-label={collapsed ? `展开${title}` : `收起${title}`}
          >
            <ChevronDown className={cn('h-3 w-3 transition-transform', collapsed ? '-rotate-90' : 'rotate-0')} />
          </Button>
        ) : null}
      </div>
      {collapsed ? null : <div className="mt-3">{children}</div>}
    </section>
  )
}

function AblationDiffEmptyState({
  datasetId,
  caseCount,
  runCount,
  autoRunLabel,
  autoRunHelper,
  autoRunPending,
  onAutoRun,
}: Readonly<{
  datasetId: string
  caseCount: number | undefined
  runCount: number
  autoRunLabel?: string | null
  autoRunHelper?: string | null
  autoRunPending?: boolean
  onAutoRun?: () => void
}>) {
  const hint = !datasetId
    ? '选择数据集后查看实验记录。'
    : caseCount === undefined
      ? '当前样本数尚未确认，请查看样本读取状态。'
      : caseCount === 0
        ? '先在评测中心准备 Golden 样本，再运行实验。'
        : runCount < 2
          ? '至少需要两条运行记录才能对比，可新建实验或自动补齐对照。'
          : '可查看指标、参数与样本差异。'

  return (
    <div className={ws.empty}>
      <h2>尚未生成运行对比</h2>
      <p>{hint}</p>
      {autoRunLabel && onAutoRun ? (
        <Button disabled={autoRunPending} onClick={onAutoRun}>
          {autoRunPending ? '正在提交…' : autoRunLabel}
        </Button>
      ) : null}
      {autoRunHelper ? <p>{autoRunHelper}</p> : null}
    </div>
  )
}

type JsonTokenKind = 'plain' | 'key' | 'string' | 'number' | 'boolean' | 'null' | 'punctuation'
type JsonToken = { text: string; kind: JsonTokenKind }

function splitCodeLines(value: string): string[] {
  const normalized = value.replaceAll('\r', '')
  const lines = normalized.split('\n')
  if (lines.length > 1 && lines.at(-1) === '') lines.pop()
  return lines.length ? lines : ['']
}

function jsonTokenKindFromRaw(raw: string): JsonTokenKind {
  if (raw === 'true' || raw === 'false') return 'boolean'
  if (raw === 'null') return 'null'
  if (/^-?\d/.test(raw)) return 'number'
  return 'punctuation'
}

function appendJsonToken(tokens: JsonToken[], match: RegExpExecArray): void {
  const raw = match[0] ?? ''
  const quotedText = match[1]
  if (!quotedText) {
    tokens.push({ text: raw, kind: jsonTokenKindFromRaw(raw) })
    return
  }

  const suffix = match[2] ?? ''
  tokens.push({ text: quotedText, kind: suffix ? 'key' : 'string' })
  if (suffix) tokens.push({ text: suffix, kind: 'punctuation' })
}

function tokenizeJsonLine(line: string): JsonToken[] {
  const tokens: JsonToken[] = []
  JSON_TOKEN_PATTERN.lastIndex = 0

  let lastIndex = 0
  let match = JSON_TOKEN_PATTERN.exec(line)
  while (match) {
    if (match.index > lastIndex) {
      tokens.push({ text: line.slice(lastIndex, match.index), kind: 'plain' })
    }

    appendJsonToken(tokens, match)
    lastIndex = JSON_TOKEN_PATTERN.lastIndex
    match = JSON_TOKEN_PATTERN.exec(line)
  }

  if (lastIndex < line.length) {
    tokens.push({ text: line.slice(lastIndex), kind: 'plain' })
  }

  return tokens.length ? tokens : [{ text: line, kind: 'plain' }]
}

function jsonTokenClassName(kind: JsonTokenKind): string {
  if (kind === 'key') return 'text-info'
  if (kind === 'string') return 'text-success'
  if (kind === 'number') return 'text-warning'
  if (kind === 'boolean') return 'text-accent'
  if (kind === 'null') return 'text-destructive'
  if (kind === 'punctuation') return 'text-muted-foreground'
  return 'text-foreground'
}

function JsonCodeLine({ lineNumber, text }: Readonly<{ lineNumber: number; text: string }>) {
  const tokens = useMemo(() => tokenizeJsonLine(text), [text])

  return (
    <div className="grid grid-cols-[52px_minmax(0,1fr)] border-b border-border/60 text-[12px] leading-6">
      <div className="select-none border-r border-border/70 px-3 text-right font-mono tabular-nums text-muted-foreground">
        {lineNumber}
      </div>
      <div className="min-w-0 px-3 font-mono">
        <span className="inline-block min-w-full whitespace-pre">
          {tokens.map((token, idx) => (
            <span key={`${lineNumber}:${idx}:${token.kind}`} className={jsonTokenClassName(token.kind)}>
              {token.text}
            </span>
          ))}
        </span>
      </div>
    </div>
  )
}

function JsonCodeViewer({ code }: Readonly<{ code: string }>) {
  const lines = useMemo(() => splitCodeLines(code), [code])

  return (
    <div className="h-full min-h-0 overflow-auto bg-background">
      <div className="min-w-max">
        {lines.map((line, index) => (
          <JsonCodeLine key={`json-line:${index + 1}`} lineNumber={index + 1} text={line} />
        ))}
      </div>
    </div>
  )
}

type AblationParamDiffRow = {
  key: string
  before: string
  after: string
  changed: boolean
}

function AblationOverviewTab({
  diff,
  metricDiffRows,
  datasetId,
  caseCount,
  runCount,
  autoRunLabel,
  autoRunHelper,
  autoRunPending,
  onAutoRun,
}: Readonly<{
  diff: RagasRegressionRunDiffResponse | null
  metricDiffRows: RegressionRunMetricDiff[]
  datasetId: string
  caseCount: number | undefined
  runCount: number
  autoRunLabel?: string | null
  autoRunHelper?: string | null
  autoRunPending?: boolean
  onAutoRun?: () => void
}>) {
  if (!diff) {
    return (
      <AblationDiffEmptyState
        datasetId={datasetId}
        caseCount={caseCount}
        runCount={runCount}
        autoRunLabel={autoRunLabel}
        autoRunHelper={autoRunHelper}
        autoRunPending={autoRunPending}
        onAutoRun={onAutoRun}
      />
    )
  }

  return (
    <div className="px-5 py-3">
      <div className="overflow-hidden border border-border/70">
        {metricDiffRows.length ? (
          <WorkspaceTableScroll label="运行指标差异">
            <table className="w-full min-w-[560px] text-xs">
              <caption className="sr-only">基线与候选运行的实际指标值及差值</caption>
              <thead className="bg-background text-[11px] tracking-[0.08em] text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    指标
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    基线
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    候选
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    变化
                  </th>
                </tr>
              </thead>
              <tbody>
                {metricDiffRows.map((row) => (
                  <tr key={row.key} className="border-t border-border/60">
                    <th scope="row" className="px-3 py-2 text-left font-mono text-[11px] font-normal text-foreground">
                      {row.key}
                    </th>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-muted-foreground">
                      {typeof row.before === 'number' ? formatMetric(row.before) : serializeDiffValue(row.before)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-muted-foreground">
                      {typeof row.after === 'number' ? formatMetric(row.after) : serializeDiffValue(row.after)}
                    </td>
                    <td
                      className={cn(
                        'px-3 py-2 text-right font-mono text-[11px] tabular-nums',
                        ablationDeltaClass(row.delta),
                      )}
                    >
                      {row.delta !== null && row.delta > 0 ? '+' : ''}
                      {formatMetric(row.delta)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </WorkspaceTableScroll>
        ) : (
          <div className="px-3 py-4 text-xs text-muted-foreground">没有可展示的指标差异。</div>
        )}
      </div>
    </div>
  )
}

function AblationConfigTab({
  diff,
  paramDiffRows,
}: Readonly<{
  diff: RagasRegressionRunDiffResponse | null
  paramDiffRows: AblationParamDiffRow[]
}>) {
  if (!diff) {
    return (
      <div className="px-5 py-10 text-center text-[12px] text-muted-foreground">生成差异对比后可查看参数差异。</div>
    )
  }

  return (
    <div className="mx-5 my-3 overflow-hidden border border-border/70">
      {paramDiffRows.length ? (
        <WorkspaceTableScroll label="运行参数差异">
          <table className="w-full min-w-[620px] text-xs">
            <caption className="sr-only">基线与候选的完整 JSON 参数，变化按完整类型和值比较</caption>
            <thead className="bg-background text-[11px] tracking-[0.08em] text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  参数
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  基线
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  候选
                </th>
              </tr>
            </thead>
            <tbody>
              {paramDiffRows.map((row) => (
                <tr key={row.key} className="border-t border-border/60 bg-background">
                  <th
                    scope="row"
                    className={cn(
                      'px-3 py-2 text-left align-top font-mono text-[11px] text-foreground',
                      row.changed ? 'font-semibold' : 'font-normal',
                    )}
                  >
                    {row.key}
                    {row.changed ? <span className="mt-1 block text-[10px]">已变化</span> : null}
                  </th>
                  <td className="px-3 py-2 align-top font-mono text-[11px] text-muted-foreground">
                    <pre className="max-w-[440px] whitespace-pre-wrap break-all">{row.before}</pre>
                  </td>
                  <td
                    className={cn(
                      'px-3 py-2 align-top font-mono text-[11px]',
                      row.changed ? 'text-foreground' : 'text-muted-foreground',
                    )}
                  >
                    <pre className="max-w-[440px] whitespace-pre-wrap break-all">{row.after}</pre>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </WorkspaceTableScroll>
      ) : (
        <div className="px-3 py-4 text-xs text-muted-foreground">没有可展示的参数差异。</div>
      )}
    </div>
  )
}

function AblationDeepDiveTab({
  datasetId,
  runDisabledReason,
  runGridBatch,
  runSubmissionPending,
  diff,
  runsByDataset,
  runsQuery,
  selectedBaseRunId,
  leaderboardMetricKey,
  deepDiveMetricKeys,
}: Readonly<{
  datasetId: string
  runDisabledReason: string
  runGridBatch: (
    grid: Record<string, RegressionAblationGridValue[]>,
    maxCombinations: number,
  ) => Promise<RegressionAblationBatchResponse>
  runSubmissionPending: boolean
  diff: RagasRegressionRunDiffResponse | null
  runsByDataset: RegressionRun[]
  runsQuery: RegressionRunQueryState
  selectedBaseRunId: string
  leaderboardMetricKey: string
  deepDiveMetricKeys: string[]
}>) {
  const hasRunData = runsQuery.data !== undefined || runsByDataset.length > 0
  const analysis = analyzeRegressionRuns(runsByDataset, [...new Set([...deepDiveMetricKeys, leaderboardMetricKey])])
  const paretoRunIds = new Set(
    analysis.runs
      .filter((entry) => isParetoRun(entry, analysis.runs, leaderboardMetricKey))
      .map((entry) => entry.run.id),
  )
  return (
    <div className="space-y-4 px-5 py-4">
      <AblationGridPanel
        key={datasetId}
        disabled={datasetId === '' || runDisabledReason !== '' || runSubmissionPending}
        disabledReason={runDisabledReason}
        onRunGrid={runGridBatch}
      />
      <AblationStatisticsPanel diff={diff} />
      {datasetId !== '' && runsQuery.error !== null ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-destructive">
          <p>
            {formatApiError(runsQuery.error, '运行统计所需记录读取失败')}
            {hasRunData ? '；保留已加载结果。' : ''}
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={runsQuery.isFetching}
            onClick={() => detachPromise(runsQuery.refetch())}
          >
            重新读取运行
          </Button>
        </div>
      ) : null}
      {datasetId === '' ? (
        <p role="status" className="text-sm text-muted-foreground">
          请先选择数据集，再查看运行统计。
        </p>
      ) : !hasRunData ? (
        runsQuery.error === null ? (
          <p role="status" className="text-sm text-muted-foreground">
            正在读取当前数据集的运行记录…
          </p>
        ) : null
      ) : (
        <>
          {runsQuery.isFetching ? (
            <p role="status" className="text-sm text-muted-foreground">
              正在刷新运行统计，保留已加载结果…
            </p>
          ) : null}
          {analysis.errors.length > 0 ? (
            <div role="alert" className="text-sm text-destructive">
              {analysis.errors.map((issue) => (
                <p key={issue.runId} className="break-words">
                  运行 {issue.runId} 未参与数值比较：{formatApiError(issue.error, '运行统计无效')}
                </p>
              ))}
            </div>
          ) : null}
          <AblationComparisonMatrix
            runs={analysis.runs}
            baseRunId={selectedBaseRunId}
            metricKeys={deepDiveMetricKeys}
            primaryMetricKey={leaderboardMetricKey}
            paretoRunIds={paretoRunIds}
          />
          <div className="grid gap-4 xl:grid-cols-2">
            <AblationParetoPanel runs={analysis.runs} metricKey={leaderboardMetricKey} paretoRunIds={paretoRunIds} />
            <AblationParameterImpactPanel runs={analysis.runs} metricKey={leaderboardMetricKey} />
          </div>
        </>
      )}
      <AblationSliceDiffPanel diff={diff} metricKey={leaderboardMetricKey} />
      <AblationCaseDrilldown
        key={JSON.stringify(diff === null ? null : [diff.base_run_id, diff.target_run_id])}
        diff={diff}
      />
    </div>
  )
}

function AblationRawTab({ diffJson }: Readonly<{ diffJson: string }>) {
  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-border/70 px-5 py-2.5">
        <div className="text-[11px] tracking-[0.12em] text-muted-foreground">对比数据</div>
        <Database className="h-4 w-4 text-primary" />
      </div>
      <JsonCodeViewer code={diffJson} />
    </div>
  )
}

function AblationComparisonWorkspace({
  runsSelectionHint,
  runsLoading,
  selectedBaseRunId,
  selectedTargetRunId,
  setSelectedBaseRunId,
  setSelectedTargetRunId,
  runsSelectDisabled,
  runsByDataset,
  runsQuery,
  diffLoading,
  canGenerateDiff,
  computeDiff,
  diff,
  exportDiffHtml,
  metricDiffRows,
  paramDiffRows,
  datasetId,
  runDisabledReason,
  runGridBatch,
  exportRunBundle,
  leaderboardMetricKey,
  deepDiveMetricKeys,
  diffJson,
  caseCount,
  autoRunLabel,
  autoRunHelper,
  autoBootstrapPending,
  runAutoBootstrap,
}: Readonly<{
  runsSelectionHint: string
  runsLoading: boolean
  selectedBaseRunId: string
  selectedTargetRunId: string
  setSelectedBaseRunId: (value: string) => void
  setSelectedTargetRunId: (value: string) => void
  runsSelectDisabled: boolean
  runsByDataset: RegressionRun[]
  runsQuery: RegressionRunQueryState
  diffLoading: boolean
  canGenerateDiff: boolean
  computeDiff: () => Promise<void>
  diff: RagasRegressionRunDiffResponse | null
  exportDiffHtml: () => Promise<void>
  metricDiffRows: RegressionRunMetricDiff[]
  paramDiffRows: AblationParamDiffRow[]
  datasetId: string
  runDisabledReason: string
  runGridBatch: (
    grid: Record<string, RegressionAblationGridValue[]>,
    maxCombinations: number,
  ) => Promise<RegressionAblationBatchResponse>
  exportRunBundle: (runId: string, label: 'base' | 'target') => Promise<void>
  leaderboardMetricKey: string
  deepDiveMetricKeys: string[]
  diffJson: string
  caseCount: number | undefined
  autoRunLabel: string | null
  autoRunHelper: string | null
  autoBootstrapPending: boolean
  runAutoBootstrap: () => Promise<void>
}>) {
  const basePlaceholder = runsLoading ? '加载中...' : '选择基线运行'
  const targetPlaceholder = runsLoading ? '加载中...' : '选择候选运行'

  return (
    <section className="min-w-0 border-t border-border">
      <div className="flex min-h-0 flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-border bg-background px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-1.5">
            <h2 className="truncate text-[15px] font-semibold text-foreground">差异对比工作区</h2>
            <AblationInfoTooltip label="查看运行记录选择说明" side="bottom">
              {runsSelectionHint}
            </AblationInfoTooltip>
          </div>
        </div>

        <details open={diff === null} className="group border-b border-border bg-background">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2 text-[13px] leading-6 text-muted-foreground [&::-webkit-details-marker]:hidden">
            <ChevronDown
              className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
              aria-hidden="true"
            />
            比较运行与导出
          </summary>
          <div className="px-4 pb-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="min-w-0 space-y-1">
                <Label className="text-[12px] text-muted-foreground">选择基线运行</Label>
                <Select value={selectedBaseRunId} onValueChange={setSelectedBaseRunId} disabled={runsSelectDisabled}>
                  <SelectTrigger
                    aria-label="选择基线运行"
                    className="h-auto min-h-11 text-left sm:h-auto sm:min-h-9 sm:text-[13px] [&>span]:line-clamp-none [&>span]:break-all"
                  >
                    <SelectValue placeholder={basePlaceholder} />
                  </SelectTrigger>
                  <SelectContent className="max-w-[calc(100vw-32px)]">
                    {selectedBaseRunId !== '' && !runsByDataset.some((run) => run.id === selectedBaseRunId) ? (
                      <SelectItem value={selectedBaseRunId} disabled>
                        {selectedBaseRunId}（记录未载入）
                      </SelectItem>
                    ) : null}
                    {runsByDataset.map((run) => (
                      <SelectItem key={run.id} value={run.id} className="break-all">
                        {runSelectText(run)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="min-w-0 space-y-1">
                <Label className="text-[12px] text-muted-foreground">选择候选运行</Label>
                <Select
                  value={selectedTargetRunId}
                  onValueChange={setSelectedTargetRunId}
                  disabled={runsSelectDisabled}
                >
                  <SelectTrigger
                    aria-label="选择候选运行"
                    className="h-auto min-h-11 text-left sm:h-auto sm:min-h-9 sm:text-[13px] [&>span]:line-clamp-none [&>span]:break-all"
                  >
                    <SelectValue placeholder={targetPlaceholder} />
                  </SelectTrigger>
                  <SelectContent className="max-w-[calc(100vw-32px)]">
                    {selectedTargetRunId !== '' && !runsByDataset.some((run) => run.id === selectedTargetRunId) ? (
                      <SelectItem value={selectedTargetRunId} disabled>
                        {selectedTargetRunId}（记录未载入）
                      </SelectItem>
                    ) : null}
                    {runsByDataset.map((run) => (
                      <SelectItem key={run.id} value={run.id} className="break-all">
                        {runSelectText(run)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="mt-3 flex items-center justify-end">
              <div className="flex items-center gap-1.5">
                <Button
                  className="gap-2"
                  disabled={diffLoading || !canGenerateDiff}
                  onClick={() => detachPromise(computeDiff())}
                >
                  <GitCompare className="h-3.5 w-3.5" />
                  生成对比
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" className="gap-1.5 px-3 text-[13px]">
                      导出
                      <MoreHorizontal className="h-3.5 w-3.5" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-40">
                    <DropdownMenuItem
                      disabled={!selectedBaseRunId}
                      onSelect={() => detachPromise(exportRunBundle(selectedBaseRunId, 'base'))}
                    >
                      导出基线
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={!selectedTargetRunId}
                      onSelect={() => detachPromise(exportRunBundle(selectedTargetRunId, 'target'))}
                    >
                      导出候选
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={!diff}
                      onSelect={() => downloadJson(diff, sanitizeFilename('regression-run-diff.json'))}
                    >
                      导出数据
                    </DropdownMenuItem>
                    <DropdownMenuItem disabled={!canGenerateDiff} onSelect={() => detachPromise(exportDiffHtml())}>
                      导出页面
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          </div>
        </details>

        {diff !== null ? <AblationComparisonSummary diff={diff} /> : null}

        <Tabs defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
          <div className="border-b border-border px-4">
            <TabsList className="h-10 justify-start gap-5 rounded-none border-none bg-transparent p-0">
              <TabsTrigger
                value="overview"
                className="h-10 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-primary data-[state=active]:bg-transparent"
              >
                概览
              </TabsTrigger>
              <TabsTrigger
                value="config"
                className="h-10 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-primary data-[state=active]:bg-transparent"
              >
                配置差异
              </TabsTrigger>
              <TabsTrigger
                value="deep-dive"
                className="h-10 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-primary data-[state=active]:bg-transparent"
              >
                深度分析
              </TabsTrigger>
              <TabsTrigger
                value="raw"
                className="h-10 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-primary data-[state=active]:bg-transparent"
              >
                原始数据
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="overview" className="mt-0 min-h-0 flex-1 overflow-auto">
            <AblationOverviewTab
              diff={diff}
              metricDiffRows={metricDiffRows}
              datasetId={datasetId}
              caseCount={caseCount}
              runCount={runsByDataset.length}
              autoRunLabel={autoRunLabel}
              autoRunHelper={autoRunHelper}
              autoRunPending={autoBootstrapPending}
              onAutoRun={autoRunLabel ? () => detachPromise(runAutoBootstrap()) : undefined}
            />
          </TabsContent>

          <TabsContent value="config" className="mt-0 min-h-0 flex-1 overflow-auto">
            <AblationConfigTab diff={diff} paramDiffRows={paramDiffRows} />
          </TabsContent>

          <TabsContent
            forceMount
            value="deep-dive"
            className="mt-0 min-h-0 flex-1 overflow-auto bg-background data-[state=inactive]:hidden"
          >
            <AblationDeepDiveTab
              datasetId={datasetId}
              runDisabledReason={runDisabledReason}
              runGridBatch={runGridBatch}
              runSubmissionPending={autoBootstrapPending}
              diff={diff}
              runsByDataset={runsByDataset}
              runsQuery={runsQuery}
              selectedBaseRunId={selectedBaseRunId}
              leaderboardMetricKey={leaderboardMetricKey}
              deepDiveMetricKeys={deepDiveMetricKeys}
            />
          </TabsContent>

          <TabsContent value="raw" className="mt-0 min-h-0 flex-1 overflow-hidden">
            <AblationRawTab diffJson={diffJson} />
          </TabsContent>
        </Tabs>
      </div>
    </section>
  )
}

export function RetrievalAblationsPage() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <RetrievalAblationWorkspace key={sessionKey} sessionKey={sessionKey} />
}

function RetrievalAblationWorkspace({ sessionKey }: Readonly<{ sessionKey: string }>) {
  const queryClient = useQueryClient()
  const runRequestsRef = useRef(new Map<string, Promise<unknown>>())
  const [pendingDatasets, setPendingDatasets] = useState<ReadonlySet<string>>(new Set())
  const exportRequestsRef = useRef(new Set<AbortController>())
  const [datasetId, setDatasetId] = useState('')
  const [configOpen, setConfigOpen] = useState(false)
  const [runListView, setRunListView] = useState('experiments')
  const submitting = pendingDatasets.has(datasetId)
  const [actionError, setActionError] = useState<string | null>(null)
  const scopeRef = useRef<AblationScope>({ datasetId, active: false })
  const [leaderboardMetricKey, setLeaderboardMetricKey] = useState<string>('retrieval_mrr')

  // Run config (ablation knobs)
  const [retrievalOnly, setRetrievalOnly] = useState(true)
  const [metricKeys, setMetricKeys] = useState<string[]>(['faithfulness', 'response_relevancy'])
  const [maxCases, setMaxCases] = useState('50')
  const [skipEmptyContexts, setSkipEmptyContexts] = useState(true)

  const [topK, setTopK] = useState('20')
  const [scoreThreshold, setScoreThreshold] = useState('0')
  const [retrievalMode, setRetrievalMode] = useState('hybrid')
  const [alpha, setAlpha] = useState('0.6')
  const [enableWeightRerank, setEnableWeightRerank] = useState(true)
  const [vectorWeight, setVectorWeight] = useState('0.6')
  const [keywordWeight, setKeywordWeight] = useState('0.4')
  const [mmrLambda, setMmrLambda] = useState('0.7')
  const [rerankerMode, setRerankerMode] = useState('system')
  const [rerankerProvider, setRerankerProvider] = useState('llm')
  const [rerankerTopN, setRerankerTopN] = useState('20')
  const runPayloadConfig: AblationRunPayloadConfig = {
    datasetId,
    retrievalOnly,
    metricKeys,
    skipEmptyContexts,
    maxCases,
    topK,
    scoreThreshold,
    retrievalMode,
    alpha,
    enableWeightRerank,
    vectorWeight,
    keywordWeight,
    mmrLambda,
    rerankerMode,
    rerankerProvider,
    rerankerTopN,
  }

  const configuration = regressionAblationFormSchema.safeParse(runPayloadConfig)
  const [defaultDatasetApplied, setDefaultDatasetApplied] = useState(false)
  const autoBootstrapPending = submitting
  const [selectedBaseRunId, setSelectedBaseRunId] = useState('')
  const [selectedTargetRunId, setSelectedTargetRunId] = useState('')
  const [extraRuns, setExtraRuns] = useState<RegressionRun[]>([])
  const [pendingSelection, setPendingSelection] = useState<{ base: string | null; target: string | null }>({
    base: null,
    target: null,
  })
  const [selectionErrors, setSelectionErrors] = useState<{
    base: { id: string; message: string } | null
    target: { id: string; message: string } | null
  }>({ base: null, target: null })
  const selectionRequests = useRef({ base: 0, target: 0 })
  const selectionInitializedRef = useRef(false)
  useLayoutEffect(() => {
    const context = { datasetId, active: true }
    const exportRequests = exportRequestsRef.current
    scopeRef.current = context
    setActionError(null)
    setExtraRuns([])
    setSelectedBaseRunId('')
    setSelectedTargetRunId('')
    setPendingSelection({ base: null, target: null })
    setSelectionErrors({ base: null, target: null })
    selectionRequests.current = { base: 0, target: 0 }
    selectionInitializedRef.current = false
    return () => {
      context.active = false
      for (const controller of exportRequests) controller.abort()
      exportRequests.clear()
    }
  }, [datasetId])

  function isCurrentScope(context: AblationScope): boolean {
    return context.active && scopeRef.current === context && getAuthSessionKey() === sessionKey
  }

  function invalidateRunRecords() {
    if (getAuthSessionKey() !== sessionKey) return
    detachPromise(queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.regressionRunLists }))
    detachPromise(
      queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.regressionLeaderboard().slice(0, 2) }),
    )
  }

  async function submitRunRequest<T>(requestDatasetId: string, request: () => Promise<T>): Promise<T> {
    if (
      !scopeRef.current.active ||
      scopeRef.current.datasetId !== requestDatasetId ||
      getAuthSessionKey() !== sessionKey
    ) {
      throw new Error('当前范围已变化，请重新操作')
    }
    if (runRequestsRef.current.has(requestDatasetId)) throw new Error('当前数据集仍有创建请求进行中')
    const pending = request()
    runRequestsRef.current.set(requestDatasetId, pending)
    setPendingDatasets(new Set(runRequestsRef.current.keys()))
    try {
      return await pending
    } finally {
      if (runRequestsRef.current.get(requestDatasetId) === pending) runRequestsRef.current.delete(requestDatasetId)
      invalidateRunRecords()
      if (scopeRef.current.active && getAuthSessionKey() === sessionKey) {
        setPendingDatasets(new Set(runRequestsRef.current.keys()))
      }
    }
  }

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
  })
  const regressionRunParams = { limit: 80, dataset_id: datasetId === '' ? undefined : datasetId }
  const runsQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionRuns(regressionRunParams),
    queryFn: ({ signal }) => evaluationApi.listRegressionRuns(regressionRunParams, { signal }),
  })
  const selectedDatasetCasesParams = { dataset_id: datasetId, limit: 1 }
  const selectedDatasetCasesQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionCases(selectedDatasetCasesParams),
    enabled: datasetId !== '',
    queryFn: ({ signal }) => evaluationApi.listRegressionCases(selectedDatasetCasesParams, { signal }),
  })
  const leaderboardParams = {
    dataset_id: datasetId,
    metric_key: leaderboardMetricKey,
    limit: 50,
    include_incomplete: false,
    max_candidates: 500,
  }
  const leaderboardQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionLeaderboard(leaderboardParams),
    enabled: datasetId !== '',
    queryFn: ({ signal }) => evaluationApi.getRegressionRunLeaderboard(leaderboardParams, { signal }),
  })
  const diffParams = {
    base_run_id: selectedBaseRunId,
    include_significance: true,
    include_per_case: true,
    max_case_diffs: 500,
  }
  const diffQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionRunDiff(selectedTargetRunId, diffParams),
    enabled: false,
    queryFn: ({ signal }) => evaluationApi.diffRegressionRuns(selectedTargetRunId, diffParams, { signal }),
  })
  const diff = diffQuery.data ?? null
  const diffJson = diff === null ? '尚未生成运行对比' : JSON.stringify(diff, null, 2)

  const datasets = datasetsQuery.data ?? EMPTY_DATASETS
  const runs = runsQuery.data === undefined ? EMPTY_RUNS : runsQuery.data.items
  const datasetsLoading = datasetsQuery.isLoading || datasetsQuery.isFetching
  const runsLoading = runsQuery.isLoading || runsQuery.isFetching
  const selectedDatasetCasesLoading = selectedDatasetCasesQuery.isPending || selectedDatasetCasesQuery.isFetching
  const leaderboardLoading = leaderboardQuery.isLoading || leaderboardQuery.isFetching
  const diffLoading = diffQuery.isLoading || diffQuery.isFetching
  const selectedDatasetCaseCount = selectedDatasetCasesQuery.data?.total
  const selectedDatasetHasNoCases = selectedDatasetCasesQuery.isSuccess && selectedDatasetCaseCount === 0
  const runDisabledReason =
    datasetId === ''
      ? '请选择数据集'
      : selectedDatasetCasesLoading
        ? '正在确认 Golden/Regression 样本数'
        : selectedDatasetCasesQuery.error
          ? '无法确认 Golden/Regression 样本数，请刷新后重试'
          : selectedDatasetHasNoCases
            ? '当前数据集没有 Golden/Regression 样本，请先在评测页导入或生成样本'
            : configuration.success
              ? ''
              : configuration.error.issues[0].message
  const selectedDatasetCasesStatusText =
    datasetId === ''
      ? '请先选择数据集，再运行检索消融。'
      : selectedDatasetCasesLoading
        ? '正在确认当前数据集的 Golden/Regression 样本数...'
        : selectedDatasetCasesQuery.error
          ? '无法读取当前数据集的 Golden/Regression 样本数，请刷新后重试。'
          : selectedDatasetHasNoCases
            ? '当前数据集没有 Golden/Regression 样本，运行消融会直接失败；请先在评测页导入或生成样本。'
            : `Golden/Regression 样本 ${selectedDatasetCaseCount} 条。`

  const leaderboardRows = leaderboardQuery.data === undefined ? [] : leaderboardQuery.data.items
  const runTableQuery = runListView === 'ranking' ? leaderboardQuery : runsQuery
  const runsByDataset = useMemo(() => {
    if (datasetId === '') return EMPTY_RUNS
    return runs.filter((run) => run.dataset_id === datasetId)
  }, [runs, datasetId])

  const availableRuns = useMemo(() => {
    const records = new Map(runsByDataset.map((run) => [run.id, run]))
    for (const run of extraRuns) if (run.dataset_id === datasetId && !records.has(run.id)) records.set(run.id, run)
    return Array.from(records.values())
  }, [runsByDataset, extraRuns, datasetId])

  const recordedConfigurations = useMemo(() => {
    const records = new Map<string, RegressionRunAblationParams>()
    const errors: { runId: string; error: unknown }[] = []
    for (const run of availableRuns) {
      try {
        const parameters = Object.fromEntries(
          getRegressionRunParameters(run).map((parameter) => [parameter.key, parameter.value]),
        )
        records.set(run.id, regressionRunAblationParamsSchema.parse(parameters))
      } catch (error) {
        errors.push({ runId: run.id, error })
      }
    }
    return { records, errors }
  }, [availableRuns])

  function runTopK(run: RegressionRun): number | null {
    const config = recordedConfigurations.records.get(run.id)
    return config === undefined || config.top_k === undefined ? null : config.top_k
  }

  function runRerankerEnabled(run: RegressionRun): boolean | null {
    const config = recordedConfigurations.records.get(run.id)
    return config === undefined || config.enable_reranker === undefined ? null : config.enable_reranker
  }

  function runRetrievalMode(run: RegressionRun): string | null {
    const config = recordedConfigurations.records.get(run.id)
    return config === undefined || config.retrieval_mode === undefined ? null : config.retrieval_mode
  }

  async function selectRun(id: string, role: 'base' | 'target') {
    selectionInitializedRef.current = true
    const context = scopeRef.current,
      request = ++selectionRequests.current[role]
    setSelectionErrors((current) => ({ ...current, [role]: null }))
    const select = role === 'base' ? setSelectedBaseRunId : setSelectedTargetRunId
    if (availableRuns.some((run) => run.id === id)) {
      setPendingSelection((current) => ({ ...current, [role]: null }))
      select(id)
      return
    }
    setPendingSelection((current) => ({ ...current, [role]: id }))
    try {
      const detail = await evaluationApi.getRegressionRun(id, { include_items: false })
      if (!isCurrentScope(context) || selectionRequests.current[role] !== request) return
      if (detail.run.dataset_id !== datasetId) throw new Error('运行记录不属于当前数据集')
      setExtraRuns((current) => [...current.filter((run) => run.id !== id), detail.run])
      select(id)
    } catch (error) {
      if (isCurrentScope(context) && selectionRequests.current[role] === request)
        setSelectionErrors((current) => ({
          ...current,
          [role]: {
            id,
            message: `${role === 'base' ? '基线' : '候选'} ${id}：${formatApiError(error, '读取运行详情失败')}`,
          },
        }))
    } finally {
      if (isCurrentScope(context) && selectionRequests.current[role] === request)
        setPendingSelection((current) => ({ ...current, [role]: null }))
    }
  }

  useEffect(() => {
    if (
      selectionInitializedRef.current ||
      submitting ||
      runsQuery.data === undefined ||
      runsQuery.error !== null ||
      availableRuns.length === 0
    )
      return
    selectionInitializedRef.current = true
    setSelectedTargetRunId(availableRuns[0].id)
    const baseline = availableRuns.find((run) => run.id !== availableRuns[0].id)
    if (baseline !== undefined) setSelectedBaseRunId(baseline.id)
  }, [availableRuns, submitting, runsQuery.data, runsQuery.error])

  useEffect(() => {
    if (
      defaultDatasetApplied ||
      datasetId !== '' ||
      datasets.length === 0 ||
      datasetsQuery.error !== null ||
      runsQuery.data === undefined ||
      runsQuery.error !== null ||
      runsLoading
    )
      return
    const datasetIds = new Set(datasets.map((dataset) => dataset.id))
    const recent = runs.find(
      (run) => run.status === 'completed' && run.dataset_id !== null && datasetIds.has(run.dataset_id),
    )
    const initial = recent === undefined || recent.dataset_id === null ? datasets[0].id : recent.dataset_id
    setDatasetId(initial)
    setDefaultDatasetApplied(true)
  }, [
    datasets,
    datasetId,
    defaultDatasetApplied,
    runs,
    runsLoading,
    runsQuery.data,
    runsQuery.error,
    datasetsQuery.error,
  ])

  async function runAblation(): Promise<void> {
    selectionInitializedRef.current = true
    if (runDisabledReason !== '') {
      setActionError(runDisabledReason)
      return
    }
    const context = scopeRef.current
    const selection = { ...selectionRequests.current }
    setActionError(null)
    try {
      const payload = buildRegressionRunPayload(runPayloadConfig)
      const run = await submitRunRequest(payload.dataset_id, () => evaluationApi.createRegressionRun(payload))
      if (!isCurrentScope(context)) return
      setExtraRuns((current) => [...current.filter((item) => item.id !== run.id), run])
      if (sameSelection(selection)) setSelectedTargetRunId(run.id)
      setConfigOpen(false)
      toast.success('已接受实验运行，结果请查看运行记录')
    } catch (error) {
      if (isCurrentScope(context))
        setActionError('未取得有效创建回执，请先重新读取运行记录确认。 ' + formatApiError(error, '提交实验运行失败'))
    }
  }

  async function runAutoBootstrap(): Promise<void> {
    if (runDisabledReason !== '') {
      setActionError(runDisabledReason)
      return
    }
    const plan = autoBootstrapPlan
    if (plan === null) {
      setActionError('自动配置尚不可用，请先读取当前运行记录')
      return
    }
    selectionInitializedRef.current = true
    const context = scopeRef.current
    const selection = { ...selectionRequests.current }
    setActionError(null)
    try {
      const payload = buildRegressionRunPayload(runPayloadConfig)
      let key: 'top_k' | 'enable_reranker' | 'retrieval_mode'
      let values: RegressionAblationGridValue[]
      if (plan.stage === 'top_k') {
        key = 'top_k'
        values = [payload.top_k, pickAutoCandidateTopK(payload.top_k)]
      } else if (plan.stage === 'reranker') {
        key = 'enable_reranker'
        values = [false, true]
      } else {
        key = 'retrieval_mode'
        values = ['hybrid', 'vector']
      }

      const batch = await submitRunRequest(payload.dataset_id, () =>
        evaluationApi.createRegressionAblationBatch({
          ...payload,
          grid: { [key]: values },
          max_combinations: values.length,
          ablation_label_prefix: `auto-bootstrap-${key}`,
        }),
      )
      if (!isCurrentScope(context)) return
      if (sameSelection(selection)) {
        setSelectedBaseRunId(batch.run_ids[0])
        setSelectedTargetRunId(batch.run_ids[batch.run_ids.length - 1])
      }
      toast.success(`已接受 ${batch.total} 个自动配置运行，结果请查看运行记录`)
    } catch (error) {
      if (isCurrentScope(context)) {
        setActionError('未取得有效创建回执，请先重新读取运行记录确认。 ' + formatApiError(error, '自动提交失败'))
      }
    }
  }

  async function runGridBatch(
    grid: Record<string, RegressionAblationGridValue[]>,
    maxCombinations: number,
  ): Promise<RegressionAblationBatchResponse> {
    selectionInitializedRef.current = true
    if (runDisabledReason !== '') throw new Error(runDisabledReason)
    const payload = buildRegressionRunPayload(runPayloadConfig)
    const context = scopeRef.current
    const selection = { ...selectionRequests.current }
    const batch = await submitRunRequest(payload.dataset_id, () =>
      evaluationApi.createRegressionAblationBatch({
        ...payload,
        grid,
        max_combinations: maxCombinations,
      }),
    )
    if (isCurrentScope(context)) {
      if (sameSelection(selection)) setSelectedTargetRunId(batch.run_ids[0])
      toast.success(`已接受 ${batch.total} 个消融运行，结果请查看运行记录`)
    }
    return batch
  }

  function sameSelection(selection: { base: number; target: number }): boolean {
    return selectionRequests.current.base === selection.base && selectionRequests.current.target === selection.target
  }

  async function computeDiff(): Promise<void> {
    const context = scopeRef.current
    const selection = { ...selectionRequests.current }
    await computeRegressionDiff(
      selectedBaseRunId,
      selectedTargetRunId,
      () => diffQuery.refetch(),
      () => isCurrentScope(context) && sameSelection(selection),
    )
  }

  async function exportDiffHtml(): Promise<void> {
    const context = scopeRef.current
    const controller = new AbortController()
    exportRequestsRef.current.add(controller)
    try {
      await exportRegressionDiffHtml(
        selectedBaseRunId,
        selectedTargetRunId,
        () => isCurrentScope(context),
        controller.signal,
      )
    } finally {
      exportRequestsRef.current.delete(controller)
    }
  }

  async function exportRunBundle(runId: string, label: 'base' | 'target'): Promise<void> {
    const context = scopeRef.current
    const controller = new AbortController()
    exportRequestsRef.current.add(controller)
    try {
      await exportRegressionRunBundle(runId, label, () => isCurrentScope(context), controller.signal)
    } finally {
      exportRequestsRef.current.delete(controller)
    }
  }

  async function refetchAblationPanels(): Promise<void> {
    await Promise.all([runsQuery.refetch(), datasetId === '' ? undefined : leaderboardQuery.refetch()])
  }

  const selectedDataset = datasets.find((dataset) => dataset.id === datasetId)
  const runsSelectDisabled = runsLoading || availableRuns.length === 0
  const canGenerateDiff =
    availableRuns.some((run) => run.id === selectedBaseRunId) &&
    availableRuns.some((run) => run.id === selectedTargetRunId) &&
    selectedBaseRunId !== selectedTargetRunId
  function getAutoBootstrapPlan(): AutoBootstrapPlan | null {
    if (
      runDisabledReason !== '' ||
      submitting ||
      !configuration.success ||
      runsLoading ||
      runsQuery.data === undefined ||
      runsQuery.error !== null
    )
      return null

    const topKValues = new Set(
      runsByDataset.map((run) => runTopK(run)).filter((value): value is number => typeof value === 'number'),
    )
    if (topKValues.size < 2) {
      const candidateTopK = pickAutoCandidateTopK(configuration.data.topK)
      return {
        stage: 'top_k',
        label: runsByDataset.length === 0 ? '自动生成第 1 轮对比' : '自动补齐第 1 轮对比',
        helper: `系统会先比较 top_k：${configuration.data.topK} vs ${candidateTopK}。`,
      }
    }

    const rerankerStates = new Set(
      runsByDataset
        .map((run) => runRerankerEnabled(run))
        .filter((value): value is boolean => typeof value === 'boolean'),
    )
    if (!(rerankerStates.has(true) && rerankerStates.has(false))) {
      return {
        stage: 'reranker',
        label: '自动生成第 2 轮对比',
        helper: '按当前配置新建关闭与启用重排的两次运行。',
      }
    }

    const retrievalModes = new Set(
      runsByDataset.map((run) => runRetrievalMode(run)).filter((value) => value === 'hybrid' || value === 'vector'),
    )
    if (!(retrievalModes.has('hybrid') && retrievalModes.has('vector'))) {
      return {
        stage: 'retrieval_mode',
        label: '自动生成第 3 轮对比',
        helper: '系统会补一组 hybrid vs vector 对比，帮你看检索模式切换的影响。',
      }
    }

    return null
  }
  const autoBootstrapPlan = getAutoBootstrapPlan()
  const autoRunLabel = autoBootstrapPlan === null ? null : autoBootstrapPlan.label
  const autoRunHelper = autoBootstrapPlan === null ? null : autoBootstrapPlan.helper
  const runsSelectionHint = useMemo(() => {
    if (!datasetId.trim()) return '先选择数据集，再加载可对比的运行记录。'
    if (runsLoading) return '正在加载当前数据集的运行记录...'
    if (runsByDataset.length === 0) {
      return '当前数据集暂无可对比的运行记录。先运行消融实验；至少累计 2 条运行记录后才能生成差异对比。'
    }
    if (runsByDataset.length === 1) {
      return '当前数据集只有 1 条运行记录。差异对比需要基线与候选两条不同运行。'
    }
    return '这里用于比较两次运行的配置、指标和逐样本差异；基线通常选择稳定版本，候选选择待验证版本。'
  }, [datasetId, runsByDataset.length, runsLoading])
  const deepDiveMetricKeys = useMemo(() => LEADERBOARD_METRIC_OPTIONS.map((item) => item.key), [])
  const metricDiffRows = diff === null ? [] : diff.metric_diffs
  const paramDiffRows = useMemo(() => {
    if (diff === null) return []
    const base = diff.base_params
    const target = diff.target_params
    const keys = Array.from(new Set([...Object.keys(base), ...Object.keys(target)])).sort((a, b) => a.localeCompare(b))
    return keys.map((key) => {
      const before = serializeDiffValue(base[key])
      const after = serializeDiffValue(target[key])
      return { key, before, after, changed: before !== after }
    })
  }, [diff])

  // Ranking candidates are independent of the capped recent-run endpoint.
  const tableRows =
    runListView === 'ranking'
      ? leaderboardRows.map((rank) => {
          const run = availableRuns.find((item) => item.id === rank.run_id)
          return {
            id: rank.run_id,
            status: rank.status,
            createdAt: rank.created_at,
            topK: run ? runTopK(run) : null,
            metric: rank.metric_value,
            metricError: null,
            hash: rank.retrieval_config_hash,
          }
        })
      : runsByDataset.map((run) => {
          const rank = leaderboardRows.find((item) => item.run_id === run.id)
          let metric: number | null = null
          let metricError: string | null = null
          try {
            metric = getRegressionRunMetric(run, leaderboardMetricKey)
          } catch (error) {
            metricError = formatApiError(error, '运行指标无效')
          }
          return {
            id: run.id,
            status: run.status,
            createdAt: run.created_at,
            topK: runTopK(run),
            metric,
            metricError,
            hash: rank?.retrieval_config_hash,
          }
        })

  return (
    <AppFrame showBackground={false}>
      <OperationalWorkspace
        title="检索调参对比"
        icon="retrieval-ablation"
        context={selectedDataset?.name ?? (datasetId === '' ? '选择数据集' : datasetId)}
        actions={
          <>
            <Button asChild variant="ghost">
              <Link href="/evaluations">评测中心</Link>
            </Button>
            <Button
              onClick={() => {
                setActionError(null)
                setConfigOpen(true)
              }}
            >
              新建实验
            </Button>
          </>
        }
        toolbar={
          <>
            <label className="flex max-w-full items-center gap-2 text-[13px]">
              数据集
              <select
                aria-label="实验数据集"
                className="h-11 max-w-[220px] rounded-md border border-input bg-background px-3 sm:h-9"
                value={datasetId}
                disabled={datasetsLoading}
                onChange={(event) => {
                  setDefaultDatasetApplied(true)
                  setDatasetId(event.target.value)
                }}
              >
                <option value="" disabled>
                  选择数据集
                </option>
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-[13px]">
              主指标
              <select
                aria-label="排行榜主指标"
                className="h-11 rounded-md border border-input bg-background px-3 sm:h-9"
                value={leaderboardMetricKey}
                onChange={(event) => setLeaderboardMetricKey(event.target.value)}
              >
                {LEADERBOARD_METRIC_OPTIONS.map((metric) => (
                  <option key={metric.key} value={metric.key}>
                    {metric.label}
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="ghost"
              disabled={runsLoading || leaderboardLoading}
              onClick={() => {
                void refetchAblationPanels()
              }}
            >
              重新读取
            </Button>
          </>
        }
      >
        {(!configOpen && actionError !== null) ||
        recordedConfigurations.errors.length > 0 ||
        datasetsQuery.isError ||
        runsQuery.isError ||
        leaderboardQuery.isError ||
        selectedDatasetCasesQuery.isError ||
        diffQuery.isError ? (
          <WorkspaceNoticeStack ariaLabel="检索消融状态提示">
            {!configOpen && actionError !== null ? (
              <WorkspaceNotice
                tone="warning"
                retry={() => detachPromise(refetchAblationPanels())}
                retryLabel="重新读取运行记录"
              >
                {actionError}
              </WorkspaceNotice>
            ) : null}
            {recordedConfigurations.errors.length > 0 ? (
              <WorkspaceNotice tone="warning">
                {recordedConfigurations.errors.map((issue) => (
                  <p key={issue.runId}>
                    运行 {issue.runId} 的记录参数不可用于自动配置：{formatApiError(issue.error, '参数结构无效')}
                  </p>
                ))}
              </WorkspaceNotice>
            ) : null}
            {datasetsQuery.isError ? (
              <WorkspaceNotice
                tone="warning"
                title="数据集读取失败"
                error={datasetsQuery.error}
                fallbackMessage="数据集读取失败"
                retry={() => {
                  void datasetsQuery.refetch()
                }}
              />
            ) : null}
            {runsQuery.isError ? (
              <WorkspaceNotice
                tone="warning"
                title="实验记录读取失败"
                error={runsQuery.error}
                fallbackMessage="实验记录读取失败"
                retry={() => {
                  void runsQuery.refetch()
                }}
              />
            ) : null}
            {leaderboardQuery.isError ? (
              <WorkspaceNotice
                tone="warning"
                title="实验排行读取失败"
                error={leaderboardQuery.error}
                fallbackMessage="实验排行读取失败"
                retry={() => {
                  void leaderboardQuery.refetch()
                }}
              />
            ) : null}
            {selectedDatasetCasesQuery.isError ? (
              <WorkspaceNotice
                tone="warning"
                title="评测样本读取失败"
                error={selectedDatasetCasesQuery.error}
                fallbackMessage="评测样本读取失败"
                retry={() => {
                  void selectedDatasetCasesQuery.refetch()
                }}
              />
            ) : null}
            {diffQuery.isError ? (
              <WorkspaceNotice
                tone="warning"
                title="运行对比读取失败"
                error={diffQuery.error}
                fallbackMessage="运行对比读取失败"
                retry={() => {
                  void computeDiff()
                }}
              />
            ) : null}
          </WorkspaceNoticeStack>
        ) : null}
        <AblationComparisonWorkspace
          runsSelectionHint={runsSelectionHint}
          runsLoading={runsLoading}
          selectedBaseRunId={selectedBaseRunId}
          selectedTargetRunId={selectedTargetRunId}
          setSelectedBaseRunId={(id) => {
            void selectRun(id, 'base')
          }}
          setSelectedTargetRunId={(id) => {
            void selectRun(id, 'target')
          }}
          runsSelectDisabled={runsSelectDisabled}
          runsByDataset={availableRuns}
          runsQuery={runsQuery}
          diffLoading={diffLoading}
          canGenerateDiff={canGenerateDiff}
          computeDiff={computeDiff}
          diff={diff}
          exportDiffHtml={exportDiffHtml}
          metricDiffRows={metricDiffRows}
          paramDiffRows={paramDiffRows}
          datasetId={datasetId}
          runDisabledReason={runDisabledReason}
          runGridBatch={runGridBatch}
          exportRunBundle={exportRunBundle}
          leaderboardMetricKey={leaderboardMetricKey}
          deepDiveMetricKeys={deepDiveMetricKeys}
          diffJson={diffJson}
          caseCount={selectedDatasetCaseCount}
          autoRunLabel={autoRunLabel}
          autoRunHelper={autoRunHelper}
          autoBootstrapPending={autoBootstrapPending}
          runAutoBootstrap={runAutoBootstrap}
        />
        <section className={ws.section}>
          <div className={ws.sectionHeading}>
            <h2 className={ws.sectionTitle}>实验记录与排行</h2>
            <div role="group" aria-label="实验列表视图" className="flex gap-2">
              <Button
                variant={runListView === 'experiments' ? 'secondary' : 'ghost'}
                onClick={() => setRunListView('experiments')}
              >
                最近运行
              </Button>
              <Button
                variant={runListView === 'ranking' ? 'secondary' : 'ghost'}
                onClick={() => setRunListView('ranking')}
              >
                按指标排行
              </Button>
            </div>
          </div>
          <p className="mb-3 text-[11px] text-muted-foreground">
            最近运行最多显示 80 条；排行从最近 500 条已完成运行中取前 50 条。
          </p>
          {runTableQuery.isFetching && !runTableQuery.isPending ? (
            <p role="status" className="mb-3 text-[13px] text-muted-foreground">
              正在刷新运行记录…
            </p>
          ) : null}
          {datasetId === '' ? (
            <p className="py-8 text-sm text-muted-foreground">请先选择数据集。</p>
          ) : runTableQuery.isPending ? (
            <p role="status" className="py-8 text-sm text-muted-foreground">
              正在读取实验记录…
            </p>
          ) : tableRows.length ? (
            <WorkspaceTableScroll label="实验运行表格" stickyActions>
              <table aria-label="实验运行" className={cn(ws.table, 'min-w-[740px]')}>
                <thead>
                  <tr>
                    <th>运行</th>
                    <th className="hidden sm:table-cell">状态</th>
                    <th>TOP-K</th>
                    <th>{leaderboardMetricLabel(leaderboardMetricKey)}</th>
                    <th>配置</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((row) => {
                    const badge = runStatusMeta(row.status)
                    return (
                      <tr key={row.id} data-selected={row.id === selectedBaseRunId || row.id === selectedTargetRunId}>
                        <td className="max-w-[360px] whitespace-normal">
                          <strong className="block break-all font-mono text-[13px] font-normal" title={row.id}>
                            {row.id}
                          </strong>
                          {row.id === selectedBaseRunId ? (
                            <span className="mr-2 text-xs text-muted-foreground">基线</span>
                          ) : null}
                          {row.id === selectedTargetRunId ? (
                            <span className="text-xs text-muted-foreground">候选</span>
                          ) : null}
                          <div className="mt-1 sm:hidden">
                            <StatusBadge status={badge.status} label={badge.label} dense />
                          </div>
                          <p>{row.createdAt ? row.createdAt.replace('T', ' ').slice(0, 19) : '—'}</p>
                        </td>
                        <td className="hidden sm:table-cell">
                          <StatusBadge status={badge.status} label={badge.label} dense />
                        </td>
                        <td>{row.topK ?? '—'}</td>
                        <td className="tabular-nums">
                          {row.metricError === null ? (
                            formatMetric(row.metric)
                          ) : (
                            <p role="alert" className="max-w-64 text-destructive">
                              {row.metricError}
                            </p>
                          )}
                        </td>
                        <td>
                          <span className="font-mono text-xs">
                            {row.hash === null || row.hash === undefined ? '—' : row.hash.slice(0, 12)}
                          </span>
                        </td>
                        <td>
                          <div className="flex gap-1">
                            {(['base', 'target'] as const).map((role) => (
                              <Button
                                key={role}
                                variant={
                                  row.id === (role === 'base' ? selectedBaseRunId : selectedTargetRunId)
                                    ? 'secondary'
                                    : 'ghost'
                                }
                                disabled={pendingSelection[role] === row.id}
                                aria-label={`设为${role === 'base' ? '基线' : '候选'} ${row.id}`}
                                onClick={() => {
                                  void selectRun(row.id, role)
                                }}
                              >
                                {pendingSelection[role] === row.id ? '读取中…' : role === 'base' ? '基线' : '候选'}
                              </Button>
                            ))}
                          </div>
                          {(['base', 'target'] as const).map((role) =>
                            selectionErrors[role]?.id === row.id ? (
                              <p role="alert" key={role} className="max-w-64 text-[13px] text-destructive">
                                {selectionErrors[role]!.message}
                              </p>
                            ) : null,
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </WorkspaceTableScroll>
          ) : !runTableQuery.isError ? (
            <div className={ws.empty}>
              <h2>{runListView === 'ranking' ? '当前指标暂无已完成运行' : '当前数据集暂无实验运行'}</h2>
              <p>{selectedDatasetCasesStatusText}</p>
              <Button disabled={submitting || datasetId === ''} onClick={() => setConfigOpen(true)}>
                配置实验
              </Button>
            </div>
          ) : null}
        </section>
        <Dialog
          open={configOpen}
          onOpenChange={(open) => {
            if (!submitting) setConfigOpen(open)
          }}
        >
          <DialogContent className={cn(ws.dialog, ws.wideDialog)}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle>实验参数</DialogTitle>
              <DialogDescription>
                数据集：{selectedDataset?.name ?? (datasetId === '' ? '未选择' : datasetId)}。本次参数仅用于新建实验。
              </DialogDescription>
            </DialogHeader>
            {actionError !== null ? (
              <p
                role="alert"
                className="shrink-0 border-b border-border px-[18px] py-3 text-sm text-destructive sm:px-6"
              >
                {actionError}
              </p>
            ) : null}
            <div className={cn(ws.dialogBody, 'min-w-0 flex-1')}>
              <fieldset disabled={submitting} className="min-w-0">
                <p className="mb-3 text-[13px] text-muted-foreground">{selectedDatasetCasesStatusText}</p>
                <AblationSection
                  title="评测模式"
                  description="决定这轮只看检索，还是同时带上生成质量指标。"
                  className="bg-card"
                  collapsible={false}
                >
                  <div className="space-y-3">
                    <div className="flex flex-col items-start justify-between gap-3 sm:flex-row">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-foreground">仅检索评测</div>
                        <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
                          关闭生成质量指标，只保留召回率、平均倒数排名与归一化增益等检索指标。
                        </div>
                      </div>
                      <div className="flex w-full shrink-0 items-center justify-between gap-3 sm:w-auto">
                        <span className="text-sm text-foreground">{retrievalOnly ? '仅检索' : '检索与生成'}</span>
                        <Switch aria-label="仅检索模式" checked={retrievalOnly} onCheckedChange={setRetrievalOnly} />
                      </div>
                    </div>

                    <div className="grid gap-2.5">
                      {RAGAS_METRIC_OPTIONS.map((option) => {
                        const checked = metricKeys.includes(option.key)
                        return (
                          <label
                            key={option.key}
                            className={cn('flex items-start gap-3 py-1.5', retrievalOnly && 'opacity-60')}
                          >
                            <Checkbox
                              checked={checked}
                              disabled={retrievalOnly}
                              onCheckedChange={(value) => {
                                const next = new Set(metricKeys)
                                if (value === true) next.add(option.key)
                                else next.delete(option.key)
                                setMetricKeys(Array.from(next))
                              }}
                            />
                            <span className="space-y-1">
                              <span className="block text-sm font-medium text-foreground">{option.label}</span>
                              <span className="block text-[11px] leading-5 text-muted-foreground">{option.hint}</span>
                            </span>
                          </label>
                        )
                      })}
                    </div>
                  </div>
                </AblationSection>

                <AblationSection title="检索参数" description="召回窗口、混合检索与权重参数。" className="bg-card">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label
                        htmlFor="ablation-max-cases"
                        className="text-[11px] tracking-[0.08em] text-muted-foreground"
                      >
                        样本上限
                      </Label>
                      <Input
                        id="ablation-max-cases"
                        aria-label="评测样本上限"
                        type="number"
                        value={maxCases}
                        min={1}
                        max={500}
                        required
                        onChange={(e) => setMaxCases(e.target.value)}
                        className="border-border/70 bg-card"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="ablation-top-k" className="text-[11px] tracking-[0.08em] text-muted-foreground">
                        召回数量
                      </Label>
                      <Input
                        id="ablation-top-k"
                        aria-label="召回数量 TOP-K"
                        type="number"
                        value={topK}
                        min={1}
                        max={50}
                        required
                        onChange={(e) => setTopK(e.target.value)}
                        className="border-border/70 bg-card"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label
                        htmlFor="ablation-retrieval-mode"
                        className="text-[11px] tracking-[0.08em] text-muted-foreground"
                      >
                        检索模式
                      </Label>
                      <Select value={retrievalMode} onValueChange={setRetrievalMode}>
                        <SelectTrigger id="ablation-retrieval-mode" className="border-border/70 bg-card">
                          <SelectValue placeholder="选择模式" />
                        </SelectTrigger>
                        <SelectContent>
                          {RETRIEVAL_MODE_OPTIONS.map((option) => (
                            <SelectItem key={option.key} value={option.key}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label
                        htmlFor="ablation-score-threshold"
                        className="text-[11px] tracking-[0.08em] text-muted-foreground"
                      >
                        分数阈值
                      </Label>
                      <Input
                        id="ablation-score-threshold"
                        aria-label="分数阈值"
                        type="number"
                        value={scoreThreshold}
                        min={0}
                        max={1}
                        step="any"
                        required
                        onChange={(e) => setScoreThreshold(e.target.value)}
                        className="border-border/70 bg-card"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="ablation-alpha" className="text-[11px] tracking-[0.08em] text-muted-foreground">
                        混合权重
                      </Label>
                      <Input
                        id="ablation-alpha"
                        aria-label="混合权重"
                        type="number"
                        value={alpha}
                        min={0}
                        max={1}
                        step="any"
                        required
                        onChange={(e) => setAlpha(e.target.value)}
                        className="border-border/70 bg-card"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label
                        htmlFor="ablation-mmr-lambda"
                        className="text-[11px] tracking-[0.08em] text-muted-foreground"
                      >
                        多样性系数
                      </Label>
                      <Input
                        id="ablation-mmr-lambda"
                        aria-label="MMR 多样性系数"
                        type="number"
                        value={mmrLambda}
                        min={0}
                        max={1}
                        step="any"
                        required
                        onChange={(e) => setMmrLambda(e.target.value)}
                        className="border-border/70 bg-card"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label
                        htmlFor="ablation-vector-weight"
                        className="text-[11px] tracking-[0.08em] text-muted-foreground"
                      >
                        向量权重
                      </Label>
                      <Input
                        id="ablation-vector-weight"
                        aria-label="向量权重"
                        type="number"
                        value={vectorWeight}
                        min={0}
                        max={1}
                        step="any"
                        required
                        onChange={(e) => setVectorWeight(e.target.value)}
                        className="border-border/70 bg-card"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label
                        htmlFor="ablation-keyword-weight"
                        className="text-[11px] tracking-[0.08em] text-muted-foreground"
                      >
                        关键词权重
                      </Label>
                      <Input
                        id="ablation-keyword-weight"
                        aria-label="关键词权重"
                        type="number"
                        value={keywordWeight}
                        min={0}
                        max={1}
                        step="any"
                        required
                        onChange={(e) => setKeywordWeight(e.target.value)}
                        className="border-border/70 bg-card"
                      />
                    </div>
                  </div>
                </AblationSection>

                <AblationSection title="重排与过滤" description="控制过滤策略与重排模型参数。" className="bg-card">
                  <div className="space-y-3">
                    <label className="flex items-start gap-3 py-1.5">
                      <Checkbox
                        checked={skipEmptyContexts}
                        onCheckedChange={(value) => setSkipEmptyContexts(value === true)}
                      />
                      <span className="space-y-1">
                        <span className="block text-sm font-medium text-foreground">跳过空上下文样本</span>
                        <span className="block text-[11px] leading-5 text-muted-foreground">
                          过滤掉没有引用上下文的样本，减少空样本对分数的扰动。
                        </span>
                      </span>
                    </label>

                    <label className="flex items-start gap-3 py-1.5">
                      <Checkbox
                        checked={enableWeightRerank}
                        onCheckedChange={(value) => setEnableWeightRerank(value === true)}
                      />
                      <span className="space-y-1">
                        <span className="block text-sm font-medium text-foreground">启用权重重排</span>
                        <span className="block text-[11px] leading-5 text-muted-foreground">
                          对混合检索结果做二次权重整合，观察向量与关键词配比的影响。
                        </span>
                      </span>
                    </label>

                    <div className="border-t border-border/70 pt-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="ablation-reranker-mode">重排配置</Label>
                        <Select value={rerankerMode} onValueChange={setRerankerMode}>
                          <SelectTrigger
                            id="ablation-reranker-mode"
                            aria-label="本轮重排配置"
                            className="border-border/70 bg-card"
                          >
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="system">跟随系统</SelectItem>
                            <SelectItem value="disabled">本轮关闭</SelectItem>
                            <SelectItem value="enabled">本轮启用并指定参数</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      {rerankerMode === 'system' ? (
                        <p className="mt-2 text-[11px] text-muted-foreground">
                          本轮不覆盖重排选项，服务端使用实际全局配置。
                        </p>
                      ) : rerankerMode === 'enabled' ? (
                        <div className="mt-3 grid gap-3 sm:grid-cols-2">
                          <div className="space-y-1.5">
                            <Label htmlFor="ablation-reranker-provider" className="text-[11px] text-muted-foreground">
                              重排服务
                            </Label>
                            <Select value={rerankerProvider} onValueChange={setRerankerProvider}>
                              <SelectTrigger
                                id="ablation-reranker-provider"
                                aria-label="本轮重排服务"
                                className="border-border/70 bg-card"
                              >
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {RERANKER_PROVIDER_OPTIONS.filter((option) => option.key !== 'none').map((option) => (
                                  <SelectItem key={option.key} value={option.key}>
                                    {option.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <label className="block space-y-1.5 text-[11px] text-muted-foreground">
                            重排数量
                            <Input
                              type="number"
                              value={rerankerTopN}
                              min={1}
                              max={200}
                              required
                              onChange={(event) => setRerankerTopN(event.target.value)}
                              className="border-border/70 bg-card"
                            />
                          </label>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </AblationSection>

                {!configuration.success ? (
                  <p role="alert" className="mt-3 text-sm text-destructive">
                    {configuration.error.issues[0].message}
                  </p>
                ) : null}
              </fieldset>
            </div>
            <DialogFooter className={ws.dialogFooter}>
              <Button variant="outline" disabled={submitting} onClick={() => setConfigOpen(false)}>
                取消
              </Button>
              <Button
                disabled={runDisabledReason !== '' || submitting}
                onClick={() => {
                  void runAblation()
                }}
              >
                {submitting ? '正在提交…' : '运行消融实验'}
              </Button>
              {autoRunLabel ? (
                <Button
                  variant="outline"
                  disabled={runDisabledReason !== '' || submitting}
                  onClick={() => {
                    void runAutoBootstrap()
                  }}
                >
                  {autoBootstrapPending ? '正在提交…' : autoRunLabel}
                </Button>
              ) : null}
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </OperationalWorkspace>
    </AppFrame>
  )
}
