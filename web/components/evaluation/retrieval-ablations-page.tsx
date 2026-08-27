'use client'

import { useQuery } from '@tanstack/react-query'
import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  AlertTriangle,
  BarChart3,
  ChevronLeft,
  ChevronDown,
  ChevronRight,
  Database,
  GitCompare,
  Info,
  MoreHorizontal,
  PlayCircle,
  RefreshCcw,
  Trophy,
} from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { AblationCaseDrilldown } from '@/components/evaluation/ablation-case-drilldown'
import { AblationComparisonMatrix } from '@/components/evaluation/ablation-comparison-matrix'
import { AblationGridPanel } from '@/components/evaluation/ablation-grid-panel'
import { AblationParameterImpactPanel } from '@/components/evaluation/ablation-parameter-impact-panel'
import { AblationParetoPanel } from '@/components/evaluation/ablation-pareto-panel'
import { AblationSliceDiffPanel } from '@/components/evaluation/ablation-slice-diff-panel'
import { AblationStatisticsPanel } from '@/components/evaluation/ablation-statistics-panel'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi } from '@/lib/api/datasets'
import { evaluationApi } from '@/lib/api/evaluation'
import { settingsApi } from '@/lib/api/settings'
import { Link } from '@/i18n/navigation'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { queryKeys } from '@/lib/query-keys'
import {
  normalizeRerankerProvider,
  RERANKER_PROVIDER_OPTIONS,
} from '@/lib/reranker-provider-options'
import { sanitizeFilename } from '@/lib/sanitize'
import type {
  Dataset,
  RagasRegressionRunDiffResponse,
  RegressionAblationGridValue,
  RegressionRunMetricDiff,
  RegressionRun,
  RegressionRunCreate,
} from '@/types'
import { cn, detachPromise } from '@/lib/utils'
const EMPTY_DATASETS: Dataset[] = []
const EMPTY_RUNS: RegressionRun[] = []

type RegressionLeaderboardRow = {
  run_id: string
  status: string
  created_at?: string | null
  finished_at?: string | null
  metric_key: string
  metric_value?: number | null
  retrieval_config_hash?: string | null
}

type RegressionRunLeaderboard = {
  items?: RegressionLeaderboardRow[]
}

type AblationInlineTone = 'neutral' | 'sky' | 'amber' | 'violet' | 'emerald'
type LeaderboardAssignRole = 'base' | 'target'

type AblationRunPayloadConfig = {
  datasetId: string
  retrievalOnly: boolean
  metricKeys: string[]
  skipEmptyContexts: boolean
  maxCases: number
  topK: number
  scoreThreshold: number
  retrievalMode: string
  alpha: number
  enableWeightRerank: boolean
  vectorWeight: number
  keywordWeight: number
  mmrLambda: number
  enableReranker: boolean
  rerankerProvider: string
  rerankerTopN: number
}

type AutoBootstrapStage = 'top_k' | 'reranker' | 'retrieval_mode'

type AutoBootstrapPlan = {
  stage: AutoBootstrapStage
  label: string
  helper: string
}

const ABLATION_INLINE_TONE_CLASSES: Record<
  AblationInlineTone,
  { surface: string; label: string; value: string }
> = {
  neutral: {
    surface: 'border-border/70 bg-card',
    label: 'text-muted-foreground',
    value: 'text-foreground',
  },
  sky: {
    surface: 'border-info/30 bg-info/5',
    label: 'text-info',
    value: 'text-info',
  },
  amber: {
    surface: 'border-warning/30 bg-warning/5',
    label: 'text-warning',
    value: 'text-warning',
  },
  violet: {
    surface: 'border-accent/30 bg-accent/5',
    label: 'text-accent',
    value: 'text-accent',
  },
  emerald: {
    surface: 'border-success/30 bg-success/5',
    label: 'text-success',
    value: 'text-success',
  },
}

const JSON_TOKEN_PATTERN = new RegExp(
  [
    String.raw`("(?:\\.|[^"\\])*")(\s*:)?`,
    String.raw`\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b`,
    String.raw`\b(?:true|false|null)\b`,
    String.raw`[{}\[\],:]`,
  ].join('|'),
  'g'
)

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '无法序列化的 JSON'
  }
}

function downloadJson(value: unknown, filename: string): void {
  const content = JSON.stringify(value ?? {}, null, 2)
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, max))
}

function pickAutoCandidateTopK(currentTopK: number): number {
  const base = clampNumber(currentTopK, 1, 50)
  const plus = clampNumber(base + 10, 1, 50)
  if (plus !== base) return plus
  const minus = clampNumber(base - 10, 1, 50)
  if (minus !== base) return minus
  return base >= 50 ? 49 : base + 1
}

function runParamNumber(run: RegressionRun, key: string): number | null {
  const params = run.params && typeof run.params === 'object' ? run.params : null
  return toNumber(params ? (params as Record<string, unknown>)[key] : null)
}

function runParamBoolean(run: RegressionRun, key: string): boolean | null {
  const params = run.params && typeof run.params === 'object' ? run.params : null
  const raw = params ? (params as Record<string, unknown>)[key] : null
  if (typeof raw === 'boolean') return raw
  if (raw === 'true') return true
  if (raw === 'false') return false
  return null
}

function runParamString(run: RegressionRun, key: string): string {
  const params = run.params && typeof run.params === 'object' ? run.params : null
  return toTrimmedPrimitiveString(params ? (params as Record<string, unknown>)[key] : null)
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

function _stableId(val: unknown): string {
  return toTrimmedPrimitiveString(val)
}

function formatMetric(value: number | null): string {
  return value === null ? '-' : value.toFixed(4)
}

function shortId(value: string | null | undefined): string {
  const text = String(value || '').trim()
  if (!text) return '-'
  return `${text.slice(0, 8)}…`
}

function leaderboardMetricLabel(key: string): string {
  return (
    LEADERBOARD_METRIC_OPTIONS.find((item) => item.key === key)?.label || key
  )
}

function datasetPermissionLabel(value: unknown): string {
  const text = toTrimmedPrimitiveString(value)
  if (!text) return '权限未配置'
  if (text === 'all_team_members') return '全员可见'
  if (text === 'only_me') return '仅自己可见'
  return text
}

function runStatusMeta(statusValue: string | null | undefined): {
  status: 'completed' | 'failed' | 'processing'
  label: string
} {
  if (statusValue === 'completed')
    return { status: 'completed', label: '已完成' }
  if (statusValue === 'failed') return { status: 'failed', label: '失败' }
  return { status: 'processing', label: '运行中' }
}

function pickRunPair(
  items: RegressionRun[],
  currentBaseRunId: string,
  currentTargetRunId: string
): {
  baseRunId: string
  targetRunId: string
} {
  const ids = new Set(items.map((run) => _stableId(run.id)).filter(Boolean))
  const currentBase = _stableId(currentBaseRunId)
  const currentTarget = _stableId(currentTargetRunId)
  let targetRunId =
    currentTarget && ids.has(currentTarget)
      ? currentTarget
      : _stableId(items?.[0]?.id)
  let baseRunId = currentBase && ids.has(currentBase) ? currentBase : ''

  if (!baseRunId || baseRunId === targetRunId) {
    baseRunId = _stableId(
      items.find((run) => _stableId(run.id) !== targetRunId)?.id
    )
  }

  if (baseRunId === targetRunId) {
    baseRunId = ''
  }

  return { baseRunId, targetRunId }
}

function buildRegressionRunPayload(
  config: AblationRunPayloadConfig,
  variant: Partial<RegressionRunCreate> = {}
): RegressionRunCreate | null {
  const ds = config.datasetId.trim()
  if (!ds) return null

  return {
    dataset_id: ds,
    metrics: config.retrievalOnly ? [] : config.metricKeys,
    skip_empty_contexts: Boolean(config.skipEmptyContexts),
    max_cases: clampNumber(config.maxCases, 1, 500),
    top_k: clampNumber(config.topK, 1, 50),
    score_threshold: clampNumber(config.scoreThreshold, 0, 1),
    retrieval_mode: config.retrievalMode,
    alpha: clampNumber(config.alpha, 0, 1),
    enable_weight_rerank: Boolean(config.enableWeightRerank),
    vector_weight: clampNumber(config.vectorWeight, 0, 1),
    keyword_weight: clampNumber(config.keywordWeight, 0, 1),
    mmr_lambda: clampNumber(config.mmrLambda, 0, 1),
    enable_reranker: Boolean(config.enableReranker),
    reranker_provider: String(config.rerankerProvider || 'llm'),
    reranker_top_n: clampNumber(config.rerankerTopN, 1, 200),
    ...variant,
  }
}

async function submitAblationRun(
  payload: RegressionRunCreate | null,
  refetchRuns: () => Promise<unknown>,
  selectTargetRun: (id: string) => void
): Promise<void> {
  if (!payload) {
    toast.error('请选择数据集')
    return
  }

  try {
    const run = await evaluationApi.createRegressionRun(payload)
    toast.success('已创建实验运行')
    await refetchRuns()
    selectTargetRun(run.id)
  } catch (err) {
    toast.error(formatApiError(err, '创建实验运行失败'))
  }
}

async function submitAblationBatch(
  payload: RegressionRunCreate | null,
  grid: Record<string, RegressionAblationGridValue[]>,
  maxCombinations: number,
  refetchRuns: () => Promise<unknown>,
  selectTargetRun: (id: string) => void
): Promise<void> {
  if (!payload) {
    toast.error('请选择数据集')
    return
  }

  try {
    const batch = await evaluationApi.createRegressionAblationBatch({
      ...payload,
      grid,
      max_combinations: maxCombinations,
    })
    if (batch.run_ids[0]) {
      selectTargetRun(batch.run_ids[0])
    }
    await refetchRuns()
    toast.success(`已提交 ${batch.total} 个消融实验运行`)
  } catch (err) {
    const message = formatApiError(err, '批量创建消融实验运行失败')
    toast.error(message)
    throw new Error(message)
  }
}

function getComparableRunIds(
  selectedBaseRunId: string,
  selectedTargetRunId: string
): { baseId: string; targetId: string } | null {
  const baseId = String(selectedBaseRunId || '').trim()
  const targetId = String(selectedTargetRunId || '').trim()
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
  refetchDiff: () => Promise<{ error?: unknown }>
): Promise<void> {
  const pair = getComparableRunIds(selectedBaseRunId, selectedTargetRunId)
  if (!pair) return

  try {
    const res = await refetchDiff()
    if (res.error) return
    toast.success('已生成差异对比')
  } catch {}
}

async function exportRegressionDiffHtml(
  selectedBaseRunId: string,
  selectedTargetRunId: string
): Promise<void> {
  const pair = getComparableRunIds(selectedBaseRunId, selectedTargetRunId)
  if (!pair) return

  try {
    const blob = await evaluationApi.exportRegressionRunDiffHtml(pair.targetId, {
      base_run_id: pair.baseId,
      redact: true,
    })
    const name = sanitizeFilename(
      `regression-diff_${pair.baseId.slice(0, 8)}_vs_${pair.targetId.slice(0, 8)}.html`
    )
    downloadBlob(blob, name)
  } catch (err) {
    toast.error(formatApiError(err, '导出对比页面失败'))
  }
}

async function exportRegressionRunBundle(
  runId: string,
  label: string
): Promise<void> {
  const id = String(runId || '').trim()
  if (!id) {
    toast.error('请选择运行记录')
    return
  }

  try {
    const blob = await evaluationApi.exportRegressionRunBundle(id, {
      include_text: false,
      include_contexts: false,
      download: true,
    })
    const name = sanitizeFilename(
      `regression-run_${label}_${id.slice(0, 8)}.json`
    )
    downloadBlob(blob, name)
  } catch (err) {
    toast.error(formatApiError(err, '导出运行记录失败'))
  }
}

function runSelectText(run: RegressionRun): string {
  const statusMeta = runStatusMeta(String(run.status || ''))
  return `${shortId(String(run.id))} · ${statusMeta.label}`
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
        <TooltipContent
          side={side}
          align="center"
          className="max-w-[280px] text-[11px] leading-5"
        >
          {children}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

function toRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function compactValue(value: unknown, maxLen = 72): string {
  if (value === null || value === undefined) return '-'
  const raw = (() => {
    if (typeof value === 'string') return value
    if (typeof value === 'number' || typeof value === 'boolean')
      return String(value)
    try {
      return JSON.stringify(value)
    } catch {
      return '无法序列化'
    }
  })()
  if (!raw) return '-'
  return raw.length > maxLen ? `${raw.slice(0, maxLen - 1)}…` : raw
}

function ablationDeltaClass(value: number | null): string {
  if (value !== null && value > 0) return 'text-success'
  if (value !== null && value < 0) return 'text-destructive'
  return 'text-foreground'
}

function ablationDeltaTone(value: number | null): AblationInlineTone {
  if (value !== null && value > 0) return 'emerald'
  if (value !== null && value < 0) return 'amber'
  return 'neutral'
}

function formatAblationDelta(value: number | null): string {
  if (value === null) return '-'
  return value.toFixed(4)
}

function ablationWorkspaceGridClassName(
  leftExpanded: boolean,
  leaderboardExpanded: boolean
): string {
  if (leftExpanded && leaderboardExpanded) {
    return cn(
      'relative grid h-full min-h-[760px] gap-4',
      'grid-cols-[390px_minmax(0,1fr)_360px]'
    )
  }
  if (leftExpanded === false && leaderboardExpanded) {
    return cn(
      'relative grid h-full min-h-[760px] gap-4',
      'grid-cols-[minmax(0,1fr)_360px]'
    )
  }
  if (leftExpanded && leaderboardExpanded === false) {
    return cn(
      'relative grid h-full min-h-[760px] gap-4',
      'grid-cols-[390px_minmax(0,1fr)]'
    )
  }
  return cn(
    'relative grid h-full min-h-[760px] gap-4',
    'grid-cols-[minmax(0,1fr)]'
  )
}

function AblationInlineStat({
  label,
  value,
  tone = 'neutral',
}: Readonly<{
  label: string
  value: ReactNode
  tone?: AblationInlineTone
}>) {
  const toneClasses = ABLATION_INLINE_TONE_CLASSES[tone]

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 shadow-[inset_0_1px_0_hsl(var(--background)/0.9)]',
        toneClasses.surface
      )}
    >
      <span className={cn('text-[11px] tracking-[0.08em]', toneClasses.label)}>
        {label}
      </span>
      <span
        className={cn('font-mono text-[11px] tabular-nums', toneClasses.value)}
      >
        {value}
      </span>
    </div>
  )
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
    <section
      className={cn(
        'border-b border-border/60 bg-card px-4 py-3 last:border-b-0',
        className
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-foreground">
            {title}
          </div>
          {!collapsed && description ? (
            <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        {collapsible ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0 rounded-lg border border-border bg-card text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            onClick={() => setCollapsed((prev) => !prev)}
            aria-label={collapsed ? `展开${title}` : `收起${title}`}
          >
            <ChevronDown
              className={cn(
                'h-3 w-3 transition-transform',
                collapsed ? '-rotate-90' : 'rotate-0'
              )}
            />
          </Button>
        ) : null}
      </div>
      {collapsed ? null : <div className="mt-3">{children}</div>}
    </section>
  )
}

function AblationDatasetCard({
  dataset,
  metricKey,
}: Readonly<{
  dataset: Dataset | null
  metricKey: string
}>) {
  const pipeline = toRecord(dataset?.pipeline)
  const version = compactValue(pipeline.version ?? 'v1', 20)

  return (
    <div className="rounded-xl border border-border bg-card p-3 shadow-none">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/20">
          <Database className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div className="truncate text-[13px] font-semibold text-foreground">
              {dataset?.name || '未选择数据集'}
            </div>
            <span className="rounded-full border border-success/30 bg-success/10 px-2 py-0.5 text-[10px] font-medium text-success">
              {dataset ? '固定' : '待选择'}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            <span>ID: {shortId(dataset?.id)}</span>
            <span>版本: {version}</span>
          </div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
          {datasetPermissionLabel(dataset?.permission)}
        </span>
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
          主指标 {leaderboardMetricLabel(metricKey)}
        </span>
      </div>
    </div>
  )
}

function AblationLeaderboardEmptyState() {
  return (
    <div className="flex min-h-[530px] flex-col items-center justify-center px-8 text-center">
      <div className="relative h-40 w-56">
        <div className="absolute left-4 top-10 h-24 w-36 -rotate-6 rounded-2xl border border-primary/20 bg-card" />
        <div className="absolute left-11 top-16 h-2 w-20 rounded-full bg-border/70" />
        <div className="absolute left-11 top-[108px] h-2 w-14 rounded-full bg-muted" />
        <div className="absolute left-24 top-24 h-8 w-3 rounded bg-primary/30" />
        <div className="absolute left-32 top-[72px] h-14 w-3 rounded bg-primary" />
        <div className="absolute left-40 top-12 h-20 w-3 rounded bg-primary" />
        <div className="absolute bottom-8 left-12 h-8 w-12 rounded bg-border/70" />
        <div className="absolute bottom-8 left-24 h-14 w-12 rounded bg-primary" />
        <div className="absolute bottom-8 left-36 h-10 w-12 rounded bg-border/70" />
        <div className="absolute right-9 top-11 flex h-20 w-20 items-center justify-center rounded-2xl border border-warning/30 bg-warning/10 text-warning">
          <Trophy className="h-10 w-10 fill-current opacity-70" aria-hidden="true" />
        </div>
      </div>
      <div className="mt-2 text-[16px] font-semibold text-foreground">
        暂无排行数据
      </div>
      <p className="mt-2 max-w-[260px] text-[13px] leading-6 text-muted-foreground">
        固定数据集后运行一次排行统计，这里会显示每条运行记录的主指标与配置得分。
      </p>
      <div className="mt-7 rounded-xl border border-primary/20 bg-primary/10 px-4 py-3 text-[12px] text-primary">
        排行榜数据将在固定数据集运行后自动生成
      </div>
    </div>
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
  caseCount: number
  runCount: number
  autoRunLabel?: string | null
  autoRunHelper?: string | null
  autoRunPending?: boolean
  onAutoRun?: () => void
}>) {
  const hasDataset = Boolean(datasetId.trim())
  const hasCases = caseCount > 0
  const hasComparableRuns = runCount >= 2
  const title = !hasDataset
    ? '先选择数据集'
    : !hasCases
      ? '当前数据集还没有 Golden 样本'
      : !runCount
        ? '已有 Golden 样本，但还没有实验运行'
        : !hasComparableRuns
          ? '已有 Golden 样本，但还差 1 条实验运行'
          : '等待生成差异对比'
  const description = !hasDataset
    ? '先固定一个数据集，这里才能加载可对比的运行记录。'
    : !hasCases
      ? '这个页面不是用来创建 Golden 样本的。请先回“评测中心”准备标准问题、标准答案和标准证据。'
      : !runCount
        ? `当前数据集已经有 ${caseCount} 条 Golden/Regression 样本，但还没有实验运行。先点击左下角“运行消融实验”跑出第一条基线记录。`
        : !hasComparableRuns
          ? `当前数据集已经有 ${caseCount} 条 Golden/Regression 样本，也已经跑出 1 条实验记录。差异对比至少需要 2 条：先保留这条作为基线，再改一个参数跑第二条候选。`
          : '请先选择基线运行与候选运行，然后点击“生成差异对比”。系统将对两次运行进行结构化对比，展示差异与影响分析。'
  const steps = !hasDataset
    ? [
        { label: '选择数据集', hint: '固定本次要比较的知识库数据集。' },
        { label: '确认 Golden 样本', hint: '确保该数据集已有标准问题、标准答案和标准证据。' },
        { label: '进入对比', hint: '完成后这里才会出现可比较的实验记录。' },
      ]
    : !hasCases
      ? [
          { label: '返回评测中心', hint: '去 Golden 回归评测页维护样本。' },
          { label: '准备 Golden 样本', hint: '至少要有标准问题、标准答案和标准证据。' },
          { label: '再回到这里', hint: '有了样本后再运行检索调参对比。' },
        ]
      : !runCount
        ? [
            { label: '保留当前参数', hint: '先用你认为最稳定的一套检索参数跑第一条基线。' },
            { label: '运行消融实验', hint: '点击左下角“运行消融实验”生成第一条记录。' },
            { label: '再改一个参数', hint: '例如 top_k、检索模式或 reranker，准备第二次运行。' },
          ]
        : !hasComparableRuns
          ? [
              { label: '把现有记录当基线', hint: '当前这 1 条实验记录先作为稳定方案。' },
              { label: '只改一个参数', hint: '例如 top_k、reranker 开关或 score threshold。' },
              { label: '再运行一次', hint: '生成第 2 条候选记录后，这里才能比较差异。' },
            ]
          : [
              { label: '选择基线运行', hint: '选择作为基准的实验运行结果。' },
              { label: '选择候选运行', hint: '选择需要对比的实验运行结果。' },
              { label: '生成差异对比', hint: '点击“生成差异对比”查看配置差异与指标变化。' },
            ]

  return (
    <div className="flex min-h-[530px] flex-col items-center justify-center px-6 py-8 text-center">
      <div className="relative h-36 w-[360px]">
        <div className="absolute left-10 top-8 h-20 w-32 rounded-xl border border-primary/20 bg-card">
          <div className="border-b border-primary/15 px-3 py-2 text-left text-[10px] font-semibold text-primary">
            基线
          </div>
          <div className="space-y-2 px-3 py-3">
            <div className="h-2 rounded bg-muted" />
            <div className="h-2 w-20 rounded bg-muted" />
          </div>
        </div>
        <div className="absolute right-10 top-8 h-20 w-32 rounded-xl border border-success/20 bg-success/5">
          <div className="border-b border-success/20 px-3 py-2 text-left text-[10px] font-semibold text-success">
            候选
          </div>
          <div className="space-y-2 px-3 py-3">
            <div className="h-2 rounded bg-muted" />
            <div className="h-2 w-20 rounded bg-muted" />
          </div>
        </div>
        <div className="absolute left-1/2 top-12 flex h-16 w-16 -translate-x-1/2 items-center justify-center rounded-2xl border border-primary/20 bg-card text-primary ring-1 ring-primary/20">
          <GitCompare className="h-7 w-7" aria-hidden="true" />
        </div>
        <div className="absolute left-[88px] top-3 h-8 w-[184px] rounded-t-2xl border-x border-t border-dashed border-success/40" />
      </div>
      <div className="mt-3 text-[16px] font-semibold text-foreground">
        {title}
      </div>
      <p className="mt-2 max-w-[430px] text-[13px] leading-6 text-muted-foreground">
        {description}
      </p>
      <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1.5 text-[11px] font-medium text-primary">
        <span>Golden 样本 {caseCount}</span>
        <span className="h-3 w-px bg-primary/20" />
        <span>实验运行 {runCount}</span>
      </div>
      {autoRunLabel && onAutoRun ? (
        <div className="mt-4 flex max-w-[430px] flex-col items-center">
          <Button
            type="button"
            className="h-10 rounded-full bg-info px-5 text-[13px] font-semibold text-primary-foreground hover:bg-info/90"
            disabled={autoRunPending}
            onClick={onAutoRun}
          >
            <PlayCircle className="mr-2 h-4 w-4" />
            {autoRunPending ? '正在自动补齐...' : autoRunLabel}
          </Button>
          {autoRunHelper ? (
            <div className="mt-2 text-[11px] leading-5 text-info">
              {autoRunHelper}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="mt-7 w-full max-w-[390px] rounded-2xl border border-dashed border-primary/30 bg-card/85 p-4 text-left">
        {steps.map((step, index) => (
          <div
            key={step.label}
            className="flex gap-3 py-2 first:pt-0 last:pb-0"
          >
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">
              {index + 1}
            </span>
            <span>
              <span className="block text-[13px] font-semibold text-foreground">
                {step.label}
              </span>
              <span className="mt-0.5 block text-[12px] text-muted-foreground">
                {step.hint}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

type JsonTokenKind =
  | 'plain'
  | 'key'
  | 'string'
  | 'number'
  | 'boolean'
  | 'null'
  | 'punctuation'

type JsonToken = { text: string; kind: JsonTokenKind }

function splitCodeLines(value: string): string[] {
  const normalized = String(value ?? '').replaceAll('\r', '')
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

function JsonCodeLine({
  lineNumber,
  text,
}: Readonly<{ lineNumber: number; text: string }>) {
  const tokens = useMemo(() => tokenizeJsonLine(text), [text])

  return (
    <div className="grid grid-cols-[52px_minmax(0,1fr)] border-b border-border/60 text-[12px] leading-6">
      <div className="select-none border-r border-border/70 px-3 text-right font-mono tabular-nums text-muted-foreground">
        {lineNumber}
      </div>
      <div className="min-w-0 px-3 font-mono">
        <span className="inline-block min-w-full whitespace-pre">
          {tokens.map((token, idx) => (
            <span
              key={`${lineNumber}:${idx}:${token.kind}`}
              className={jsonTokenClassName(token.kind)}
            >
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
          <JsonCodeLine
            key={`json-line:${index + 1}`}
            lineNumber={index + 1}
            text={line}
          />
        ))}
      </div>
    </div>
  )
}

type AblationDiffScoreDisplay = {
  base: string
  target: string
  delta: string
  usedKeys: string[]
}

type AblationParamDiffRow = {
  key: string
  before: string
  after: string
  changed: boolean
}

function AblationMetricDeltaCell({
  value,
}: Readonly<{ value: unknown }>) {
  const delta = toNumber(value)
  const label = delta === null ? compactValue(value, 24) : delta.toFixed(4)

  return (
    <div
      className={cn(
        'text-right font-mono text-[11px]',
        ablationDeltaClass(delta)
      )}
    >
      {label}
    </div>
  )
}

function AblationOverviewTab({
  diff,
  diffScoreFmt,
  diffDeltaClass,
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
  diffScoreFmt: AblationDiffScoreDisplay
  diffDeltaClass: string
  metricDiffRows: RegressionRunMetricDiff[]
  datasetId: string
  caseCount: number
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
        <div className="grid border-b border-border/70 sm:grid-cols-3">
          <div className="bg-card px-3 py-2.5 sm:border-r sm:border-border/70">
            <div className="text-[11px] tracking-[0.08em] text-muted-foreground">
              基线得分
            </div>
            <div className="mt-1 font-mono text-[13px] font-semibold text-foreground">
              {diffScoreFmt.base}
            </div>
          </div>
          <div className="bg-card px-3 py-2.5 sm:border-r sm:border-border/70">
            <div className="text-[11px] tracking-[0.08em] text-muted-foreground">
              候选得分
            </div>
            <div className="mt-1 font-mono text-[13px] font-semibold text-foreground">
              {diffScoreFmt.target}
            </div>
          </div>
          <div className="bg-card px-3 py-2.5">
            <div className="text-[11px] tracking-[0.08em] text-muted-foreground">
              指标变化
            </div>
            <div
              className={cn(
                'mt-1 font-mono text-[13px] font-semibold',
                diffDeltaClass
              )}
            >
              {diffScoreFmt.delta}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-[minmax(120px,1fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)] border-b border-border/70 bg-card px-3 py-2 text-[11px] tracking-[0.08em] text-muted-foreground">
          <div>指标</div>
          <div className="text-right">基线</div>
          <div className="text-right">候选</div>
          <div className="text-right">变化</div>
        </div>
        {metricDiffRows.length ? (
          metricDiffRows.map((row) => (
            <div
              key={row.key}
              className="grid grid-cols-[minmax(120px,1fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)] border-b border-border/60 px-3 py-2 text-xs last:border-b-0"
            >
              <div className="truncate font-mono text-[11px] text-foreground">
                {row.key}
              </div>
              <div className="text-right font-mono text-[11px] text-muted-foreground">
                {compactValue(row.before, 24)}
              </div>
              <div className="text-right font-mono text-[11px] text-muted-foreground">
                {compactValue(row.after, 24)}
              </div>
              <AblationMetricDeltaCell value={row.delta} />
            </div>
          ))
        ) : (
          <div className="px-3 py-4 text-xs text-muted-foreground">
            没有可展示的指标差异。
          </div>
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
      <div className="px-5 py-10 text-center text-[12px] text-muted-foreground">
        生成差异对比后可查看参数差异。
      </div>
    )
  }

  return (
    <div className="mx-5 my-3 overflow-hidden border border-border/70">
      <div className="grid grid-cols-[minmax(140px,180px)_minmax(0,1fr)_minmax(0,1fr)] border-b border-border/70 bg-card px-3 py-2 text-[11px] tracking-[0.08em] text-muted-foreground">
        <div>参数</div>
        <div>基线</div>
        <div>候选</div>
      </div>
      {paramDiffRows.length ? (
        paramDiffRows.map((row) => (
          <div
            key={row.key}
            className="grid grid-cols-[minmax(140px,180px)_minmax(0,1fr)_minmax(0,1fr)] border-b border-border/60 bg-card px-3 py-2 text-xs last:border-b-0"
          >
            <div
              className={cn(
                'truncate font-mono text-[11px]',
                row.changed ? 'font-semibold text-foreground' : 'text-foreground'
              )}
            >
              {row.key}
            </div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">
              {row.before}
            </div>
            <div
              className={cn(
                'truncate font-mono text-[11px]',
                row.changed ? 'text-foreground' : 'text-muted-foreground'
              )}
            >
              {row.after}
            </div>
          </div>
        ))
      ) : (
        <div className="px-3 py-4 text-xs text-muted-foreground">
          没有可展示的参数差异。
        </div>
      )}
    </div>
  )
}

function AblationDeepDiveTab({
  datasetId,
  runDisabledReason,
  runGridBatch,
  refetchPanels,
  diff,
  runsByDataset,
  selectedBaseRunId,
  selectedTargetRunId,
  leaderboardMetricKey,
  deepDiveMetricKeys,
}: Readonly<{
  datasetId: string
  runDisabledReason: string
  runGridBatch: (
    grid: Record<string, RegressionAblationGridValue[]>,
    maxCombinations: number
  ) => Promise<void>
  refetchPanels: () => Promise<void>
  diff: RagasRegressionRunDiffResponse | null
  runsByDataset: RegressionRun[]
  selectedBaseRunId: string
  selectedTargetRunId: string
  leaderboardMetricKey: string
  deepDiveMetricKeys: string[]
}>) {
  return (
    <div className="space-y-4 px-5 py-4">
      <AblationGridPanel
        disabled={!datasetId.trim() || Boolean(runDisabledReason)}
        disabledReason={runDisabledReason}
        onRunGrid={runGridBatch}
        onBatchComplete={refetchPanels}
      />
      <AblationStatisticsPanel diff={diff} />
      <AblationComparisonMatrix
        runs={runsByDataset}
        baseRunId={selectedBaseRunId}
        metricKeys={deepDiveMetricKeys}
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <AblationParetoPanel
          runs={runsByDataset}
          metricKey={leaderboardMetricKey}
        />
        <AblationParameterImpactPanel
          runs={runsByDataset}
          metricKey={leaderboardMetricKey}
        />
      </div>
      <AblationSliceDiffPanel diff={diff} />
      <AblationCaseDrilldown
        baseRunId={selectedBaseRunId}
        targetRunId={selectedTargetRunId}
        metricKeys={deepDiveMetricKeys}
        caseDiffs={diff?.case_diffs ?? []}
      />
    </div>
  )
}

function AblationRawTab({ diffJson }: Readonly<{ diffJson: string }>) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-border/70 px-5 py-2.5">
        <div className="text-[11px] tracking-[0.12em] text-muted-foreground">
          对比数据
        </div>
        <Database className="h-4 w-4 text-primary" />
      </div>
      <JsonCodeViewer code={diffJson} />
    </div>
  )
}

function AblationComparisonWorkspace({
  leaderboardCollapsed,
  leftSidebarCollapsed,
  setLeaderboardCollapsed,
  runsSelectionHint,
  diffDeltaClass,
  diffDeltaValue,
  runsLoading,
  selectedBaseRunId,
  selectedTargetRunId,
  setSelectedBaseRunId,
  setSelectedTargetRunId,
  runsSelectDisabled,
  runsByDataset,
  selectedBaseRun,
  selectedTargetRun,
  diffDeltaTone,
  diffLoading,
  canGenerateDiff,
  computeDiff,
  diff,
  exportDiffHtml,
  diffScoreFmt,
  metricDiffRows,
  paramDiffRows,
  datasetId,
  runDisabledReason,
  runGridBatch,
  refetchPanels,
  leaderboardMetricKey,
  deepDiveMetricKeys,
  diffJson,
  caseCount,
  autoRunLabel,
  autoRunHelper,
  autoBootstrapPending,
  runAutoBootstrap,
}: Readonly<{
  leaderboardCollapsed: boolean
  leftSidebarCollapsed: boolean
  setLeaderboardCollapsed: (value: boolean) => void
  runsSelectionHint: string
  diffDeltaClass: string
  diffDeltaValue: string
  runsLoading: boolean
  selectedBaseRunId: string
  selectedTargetRunId: string
  setSelectedBaseRunId: (value: string) => void
  setSelectedTargetRunId: (value: string) => void
  runsSelectDisabled: boolean
  runsByDataset: RegressionRun[]
  selectedBaseRun: RegressionRun | null
  selectedTargetRun: RegressionRun | null
  diffDeltaTone: AblationInlineTone
  diffLoading: boolean
  canGenerateDiff: boolean
  computeDiff: () => Promise<void>
  diff: RagasRegressionRunDiffResponse | null
  exportDiffHtml: () => Promise<void>
  diffScoreFmt: AblationDiffScoreDisplay
  metricDiffRows: RegressionRunMetricDiff[]
  paramDiffRows: AblationParamDiffRow[]
  datasetId: string
  runDisabledReason: string
  runGridBatch: (
    grid: Record<string, RegressionAblationGridValue[]>,
    maxCombinations: number
  ) => Promise<void>
  refetchPanels: () => Promise<void>
  leaderboardMetricKey: string
  deepDiveMetricKeys: string[]
  diffJson: string
  caseCount: number
  autoRunLabel: string | null
  autoRunHelper: string | null
  autoBootstrapPending: boolean
  runAutoBootstrap: () => Promise<void>
}>) {
  const basePlaceholder = runsLoading ? '加载中...' : '选择基线运行'
  const targetPlaceholder = runsLoading ? '加载中...' : '选择候选运行'
  const baseRunLabel = selectedBaseRun?.id ? String(selectedBaseRun.id) : ''
  const targetRunLabel = selectedTargetRun?.id
    ? String(selectedTargetRun.id)
    : ''

  return (
    <section className="relative order-2 min-w-0 overflow-hidden rounded-2xl border border-border bg-card shadow-[0_8px_24px_hsl(var(--foreground)/0.05)]">
      {leaderboardCollapsed ? (
        <button
          type="button"
          className={cn(
            'focus-ring absolute right-0 z-20 translate-x-1/2 rounded-full border border-border/70 bg-card p-1 text-muted-foreground shadow-sm transition-colors hover:bg-muted/50 hover:text-foreground',
            leftSidebarCollapsed ? 'top-12' : 'top-3'
          )}
          onClick={() => setLeaderboardCollapsed(false)}
          aria-label="展开排行榜"
          title="展开排行榜"
        >
          <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      ) : null}
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex min-h-[58px] items-center justify-between gap-3 border-b border-border bg-card px-4 py-3">
          <div className="flex min-w-0 items-center gap-1.5">
            <div className="truncate text-[15px] font-semibold text-foreground">
              差异对比工作区
            </div>
            <AblationInfoTooltip label="查看运行记录选择说明" side="bottom">
              {runsSelectionHint}
            </AblationInfoTooltip>
          </div>
          <div className="flex items-center gap-1.5 text-[11px]">
            <span className="text-muted-foreground">指标变化</span>
            <span
              className={cn('font-mono font-semibold', diffDeltaClass)}
            >
              {diffDeltaValue}
            </span>
          </div>
        </div>

        <div className="border-b border-border bg-card px-4 py-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-[12px] text-muted-foreground">选择基线运行</Label>
              <Select
                value={selectedBaseRunId}
                onValueChange={setSelectedBaseRunId}
                disabled={runsSelectDisabled}
              >
                <SelectTrigger className="h-10 rounded-xl border-border bg-card text-[13px]">
                  <SelectValue placeholder={basePlaceholder} />
                </SelectTrigger>
                <SelectContent>
                  {runsByDataset.map((run) => (
                    <SelectItem key={run.id} value={run.id}>
                      {runSelectText(run)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-[12px] text-muted-foreground">选择候选运行</Label>
              <Select
                value={selectedTargetRunId}
                onValueChange={setSelectedTargetRunId}
                disabled={runsSelectDisabled}
              >
                <SelectTrigger className="h-10 rounded-xl border-border bg-card text-[13px]">
                  <SelectValue placeholder={targetPlaceholder} />
                </SelectTrigger>
                <SelectContent>
                  {runsByDataset.map((run) => (
                    <SelectItem key={run.id} value={run.id}>
                      {runSelectText(run)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="mt-2.5 flex items-center justify-between">
            <div className="flex flex-wrap items-center gap-1.5">
              <AblationInlineStat
                label="基线"
                value={shortId(baseRunLabel)}
                tone="sky"
              />
              <AblationInlineStat
                label="候选"
                value={shortId(targetRunLabel)}
                tone="neutral"
              />
              <AblationInlineStat
                label="变化"
                value={diffDeltaValue}
                tone={diffDeltaTone}
              />
            </div>
            <div className="flex items-center gap-1.5">
              <Button
                className="h-9 gap-1.5 rounded-xl bg-info px-4 text-[13px] text-primary-foreground shadow-none hover:bg-info/90"
                disabled={diffLoading || !canGenerateDiff}
                onClick={() => detachPromise(computeDiff())}
              >
                <GitCompare className="h-3.5 w-3.5" />
                生成对比
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    className="h-9 gap-1.5 rounded-xl border-border bg-card px-3 text-[13px] text-foreground hover:bg-muted/50"
                  >
                    导出
                    <MoreHorizontal className="h-3.5 w-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-40">
                  <DropdownMenuItem
                    disabled={!selectedBaseRunId}
                    onSelect={() =>
                      detachPromise(
                        exportRegressionRunBundle(selectedBaseRunId, 'base')
                      )
                    }
                  >
                    导出基线
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={!selectedTargetRunId}
                    onSelect={() =>
                      detachPromise(
                        exportRegressionRunBundle(
                          selectedTargetRunId,
                          'target'
                        )
                      )
                    }
                  >
                    导出候选
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={!diff}
                    onSelect={() =>
                      downloadJson(
                        diff,
                        sanitizeFilename('regression-run-diff.json')
                      )
                    }
                  >
                    导出数据
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={!canGenerateDiff}
                    onSelect={() => detachPromise(exportDiffHtml())}
                  >
                    导出页面
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>

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

          <TabsContent
            value="overview"
            className="mt-0 min-h-0 flex-1 overflow-auto"
          >
            <AblationOverviewTab
              diff={diff}
              diffScoreFmt={diffScoreFmt}
              diffDeltaClass={diffDeltaClass}
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

          <TabsContent
            value="config"
            className="mt-0 min-h-0 flex-1 overflow-auto"
          >
            <AblationConfigTab diff={diff} paramDiffRows={paramDiffRows} />
          </TabsContent>

          <TabsContent
            value="deep-dive"
            className="mt-0 min-h-0 flex-1 overflow-auto bg-muted/40"
          >
            <AblationDeepDiveTab
              datasetId={datasetId}
              runDisabledReason={runDisabledReason}
              runGridBatch={runGridBatch}
              refetchPanels={refetchPanels}
              diff={diff}
              runsByDataset={runsByDataset}
              selectedBaseRunId={selectedBaseRunId}
              selectedTargetRunId={selectedTargetRunId}
              leaderboardMetricKey={leaderboardMetricKey}
              deepDiveMetricKeys={deepDiveMetricKeys}
            />
          </TabsContent>

          <TabsContent
            value="raw"
            className="mt-0 min-h-0 flex-1 overflow-hidden"
          >
            <AblationRawTab diffJson={diffJson} />
          </TabsContent>
        </Tabs>
      </div>
    </section>
  )
}

export function RetrievalAblationsPage() {
  const [datasetId, setDatasetId] = useState('')

  const [selectedBaseRunId, setSelectedBaseRunId] = useState('')
  const [selectedTargetRunId, setSelectedTargetRunId] = useState('')
  const [leaderboardAssignRole, setLeaderboardAssignRole] =
    useState<LeaderboardAssignRole>('target')
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false)
  const [leaderboardCollapsed, setLeaderboardCollapsed] = useState(false)
  const leftSidebarExpanded = leftSidebarCollapsed === false
  const leaderboardExpanded = leaderboardCollapsed === false

  const [leaderboardMetricKey, setLeaderboardMetricKey] =
    useState<string>('retrieval_mrr')

  // Run config (ablation knobs)
  const [retrievalOnly, setRetrievalOnly] = useState(true)
  const [metricKeys, setMetricKeys] = useState<string[]>([
    'faithfulness',
    'response_relevancy',
  ])
  const [maxCases, setMaxCases] = useState(50)
  const [skipEmptyContexts, setSkipEmptyContexts] = useState(true)

  const [topK, setTopK] = useState(20)
  const [scoreThreshold, setScoreThreshold] = useState(0)
  const [retrievalMode, setRetrievalMode] = useState('hybrid')
  const [alpha, setAlpha] = useState(0.6)
  const [enableWeightRerank, setEnableWeightRerank] = useState(true)
  const [vectorWeight, setVectorWeight] = useState(0.6)
  const [keywordWeight, setKeywordWeight] = useState(0.4)
  const [mmrLambda, setMmrLambda] = useState(0.7)
  const [enableReranker, setEnableReranker] = useState(false)
  const [rerankerProvider, setRerankerProvider] = useState('llm')
  const [rerankerTopN, setRerankerTopN] = useState(20)
  const [settingsDefaultsApplied, setSettingsDefaultsApplied] = useState(false)
  const [defaultDatasetApplied, setDefaultDatasetApplied] = useState(false)
  const [autoBootstrapPending, setAutoBootstrapPending] = useState(false)

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive({ purpose: 'retrieval-ablations' }),
    queryFn: () => datasetApi.listAll(),
  })
  const settingsSnapshotQuery = useQuery({
    queryKey: queryKeys.settings.snapshot,
    queryFn: () => settingsApi.get(),
  })
  const runsQuery = useQuery({
    queryKey: queryKeys.evaluations.list({ limit: 80, dataset_id: datasetId.trim() || undefined }),
    queryFn: () =>
      evaluationApi.listRegressionRuns({
        limit: 80,
        dataset_id: datasetId.trim() || undefined,
      }),
  })
  const selectedDatasetCasesQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionCases({
      dataset_id: datasetId.trim() || undefined,
      limit: 1,
    }),
    enabled: Boolean(datasetId.trim()),
    queryFn: () =>
      evaluationApi.listRegressionCases({
        dataset_id: datasetId.trim(),
        limit: 1,
      }),
  })
  const leaderboardQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionLeaderboard({
      dataset_id: datasetId.trim() || undefined,
      metric_key: leaderboardMetricKey,
      limit: 50,
      include_incomplete: false,
    }),
    enabled: Boolean(datasetId.trim()),
    queryFn: () =>
      evaluationApi.getRegressionRunLeaderboard({
        dataset_id: datasetId.trim(),
        metric_key: leaderboardMetricKey,
        limit: 50,
        include_incomplete: false,
      }),
  })
  const diffQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionRunDiff(selectedTargetRunId, {
      base_run_id: selectedBaseRunId,
      include_significance: true,
      include_per_case: true,
      max_case_diffs: 500,
    }),
    enabled: false,
    queryFn: () =>
      evaluationApi.diffRegressionRuns(selectedTargetRunId, {
        base_run_id: selectedBaseRunId,
        include_significance: true,
        include_per_case: true,
        max_case_diffs: 500,
      }),
  })
  const settingsSnapshot = settingsSnapshotQuery.data
  useEffect(() => {
    if (settingsDefaultsApplied || !settingsSnapshot?.rag) return
    setEnableReranker(Boolean(settingsSnapshot.rag.enable_reranker))
    setRerankerProvider(settingsSnapshot.rag.reranker_provider
      ? normalizeRerankerProvider(settingsSnapshot.rag.reranker_provider)
      : 'llm')
    setRerankerTopN(settingsSnapshot.rag.reranker_top_n
      ? Math.max(1, Math.min(Number(settingsSnapshot.rag.reranker_top_n), 200))
      : 20)
    setSettingsDefaultsApplied(true)
  }, [settingsDefaultsApplied, settingsSnapshot])
  const diff = diffQuery.data ?? null
  const diffJson = useMemo(
    () => prettyJson(diff ?? { hint: '选择基线/候选运行并生成差异对比' }),
    [diff]
  )
  const diffScore = diff?.diff_score ?? null

  const diffScoreFmt = useMemo(() => {
    const b = toNumber(diffScore?.base_score)
    const a = toNumber(diffScore?.target_score)
    const d = toNumber(diffScore?.delta)
    return {
      base: b == null ? '-' : b.toFixed(4),
      target: a == null ? '-' : a.toFixed(4),
      delta: d == null ? '-' : d.toFixed(4),
      usedKeys: Array.isArray(diffScore?.used_metric_keys)
        ? diffScore.used_metric_keys.map(String)
        : [],
    }
  }, [diffScore])

  const datasets = useMemo(
    () => datasetsQuery.data ?? EMPTY_DATASETS,
    [datasetsQuery.data]
  )
  const runs = useMemo(
    () => (Array.isArray(runsQuery.data?.items) ? runsQuery.data?.items : EMPTY_RUNS),
    [runsQuery.data?.items]
  )
  const datasetsLoading = datasetsQuery.isLoading || datasetsQuery.isFetching
  const runsLoading = runsQuery.isLoading || runsQuery.isFetching
  const selectedDatasetCasesLoading =
    selectedDatasetCasesQuery.isLoading || selectedDatasetCasesQuery.isFetching
  const leaderboardLoading =
    leaderboardQuery.isLoading || leaderboardQuery.isFetching
  const diffLoading = diffQuery.isLoading || diffQuery.isFetching
  const selectedDatasetCaseCount = Number(selectedDatasetCasesQuery.data?.total ?? 0)
  const selectedDatasetHasNoCases =
    Boolean(datasetId.trim()) &&
    !selectedDatasetCasesLoading &&
    !selectedDatasetCasesQuery.error &&
    selectedDatasetCaseCount <= 0
  const selectedDatasetCasesUnavailable =
    !datasetId.trim() || selectedDatasetHasNoCases || Boolean(selectedDatasetCasesQuery.error)
  const runDisabledReason = !datasetId.trim()
    ? '请选择数据集'
    : selectedDatasetCasesLoading
      ? '正在确认 Golden/Regression 样本数'
      : selectedDatasetCasesQuery.error
        ? '无法确认 Golden/Regression 样本数，请刷新后重试'
        : selectedDatasetHasNoCases
          ? '当前数据集没有 Golden/Regression 样本，请先在评测页导入或生成样本'
          : ''
  const selectedDatasetCasesStatusText = !datasetId.trim()
    ? '请先选择数据集，再运行检索消融。'
    : selectedDatasetCasesLoading
      ? '正在确认当前数据集的 Golden/Regression 样本数...'
      : selectedDatasetCasesQuery.error
        ? '无法读取当前数据集的 Golden/Regression 样本数，请刷新后重试。'
        : selectedDatasetHasNoCases
          ? '当前数据集没有 Golden/Regression 样本，运行消融会直接失败；请先在评测页导入或生成样本。'
          : `Golden/Regression 样本 ${selectedDatasetCaseCount} 条，可运行检索消融。`

  const runsByDataset = useMemo(() => {
    const ds = datasetId.trim()
    if (!ds) return runs
    return (runs || []).filter((r) => String(r?.dataset_id || '') === ds)
  }, [runs, datasetId])

  useEffect(() => {
    const pair = pickRunPair(
      runsByDataset || [],
      selectedBaseRunId,
      selectedTargetRunId
    )
    if (pair.baseRunId !== _stableId(selectedBaseRunId))
      setSelectedBaseRunId(pair.baseRunId)
    if (pair.targetRunId !== _stableId(selectedTargetRunId))
      setSelectedTargetRunId(pair.targetRunId)
  }, [runsByDataset, selectedBaseRunId, selectedTargetRunId])

  useEffect(() => {
    if (!datasetsQuery.error) return
    toast.error(formatApiError(datasetsQuery.error, '加载数据集失败'))
  }, [datasetsQuery.error])

  useEffect(() => {
    if (!runsQuery.error) return
    toast.error(formatApiError(runsQuery.error, '拉取运行记录失败'))
  }, [runsQuery.error])

  useEffect(() => {
    if (!leaderboardQuery.error) return
    toast.error(formatApiError(leaderboardQuery.error, '拉取实验排行失败'))
  }, [leaderboardQuery.error])

  useEffect(() => {
    if (!diffQuery.error) return
    toast.error(formatApiError(diffQuery.error, '生成差异对比失败'))
  }, [diffQuery.error])

  useEffect(() => {
    if (defaultDatasetApplied || datasets.length === 0 || runsLoading) return
    const datasetIds = new Set(datasets.map((dataset) => String(dataset.id)))
    const completedRunDatasetId = _stableId(
      runs.find(
        (run) =>
          String(run.status || '') === 'completed' &&
          datasetIds.has(String(run.dataset_id || ''))
      )?.dataset_id
    )
    setDatasetId((prev) => prev || completedRunDatasetId || datasets[0]?.id || '')
    setDefaultDatasetApplied(true)
  }, [datasets, defaultDatasetApplied, runs, runsLoading])

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
    enableReranker,
    rerankerProvider,
    rerankerTopN,
  }

  function buildCurrentRegressionRunPayload(
    variant: Partial<RegressionRunCreate> = {}
  ): RegressionRunCreate | null {
    return buildRegressionRunPayload(runPayloadConfig, variant)
  }

  async function runAblation(): Promise<void> {
    if (runDisabledReason) {
      toast.error(runDisabledReason)
      return
    }
    await submitAblationRun(
      buildCurrentRegressionRunPayload(),
      () => runsQuery.refetch(),
      setSelectedTargetRunId
    )
  }

  async function runAutoBootstrap(): Promise<void> {
    if (runDisabledReason) {
      toast.error(runDisabledReason)
      return
    }

    const plan = autoBootstrapPlan
    if (!plan) {
      await runAblation()
      return
    }

    const baselineTopK = clampNumber(topK, 1, 50)
    const candidateTopK = pickAutoCandidateTopK(baselineTopK)
    setAutoBootstrapPending(true)

    try {
      const payload = buildCurrentRegressionRunPayload()
      if (!payload) {
        toast.error('请选择数据集')
        return
      }

      if (plan.stage === 'top_k') {
        if (runsByDataset.length === 0) {
          const batch = await evaluationApi.createRegressionAblationBatch({
            ...payload,
            grid: {
              top_k: [baselineTopK, candidateTopK],
            },
            max_combinations: 2,
            ablation_label_prefix: 'auto-bootstrap-top-k',
          })
          await runsQuery.refetch()
          if (batch.run_ids[0]) setSelectedBaseRunId(String(batch.run_ids[0]))
          if (batch.run_ids[1]) setSelectedTargetRunId(String(batch.run_ids[1]))
          toast.success(
            `已自动生成第 1 轮对比：top_k ${baselineTopK} vs ${candidateTopK}`
          )
          return
        }

        const baselineRun =
          runsByDataset.find((run) => runParamNumber(run, 'top_k') !== candidateTopK) ||
          runsByDataset[0] ||
          null
        const run = await evaluationApi.createRegressionRun({
          ...payload,
          top_k: candidateTopK,
        })
        await runsQuery.refetch()
        if (baselineRun?.id) setSelectedBaseRunId(String(baselineRun.id))
        setSelectedTargetRunId(run.id)
        toast.success(`已自动补齐第 1 轮对比：top_k ${candidateTopK}`)
        return
      }

      if (plan.stage === 'reranker') {
        const existingStates = new Set(
          runsByDataset
            .map((run) => runParamBoolean(run, 'enable_reranker'))
            .filter((value): value is boolean => typeof value === 'boolean')
        )
        const nextEnableReranker = existingStates.has(false)
          ? true
          : existingStates.has(true)
            ? false
            : !enableReranker
        const baselineRun =
          runsByDataset.find(
            (run) => runParamBoolean(run, 'enable_reranker') !== nextEnableReranker
          ) || runsByDataset[0] || null
        const run = await evaluationApi.createRegressionRun({
          ...payload,
          enable_reranker: nextEnableReranker,
        })
        await runsQuery.refetch()
        if (baselineRun?.id) setSelectedBaseRunId(String(baselineRun.id))
        setSelectedTargetRunId(run.id)
        toast.success(
          `已自动生成第 2 轮对比：reranker ${nextEnableReranker ? 'ON' : 'OFF'}`
        )
        return
      }

      const existingModes = new Set(
        runsByDataset
          .map((run) => runParamString(run, 'retrieval_mode'))
          .filter((value) => value === 'hybrid' || value === 'vector')
      )
      const nextRetrievalMode =
        existingModes.has('hybrid') && !existingModes.has('vector')
          ? 'vector'
          : existingModes.has('vector') && !existingModes.has('hybrid')
            ? 'hybrid'
            : retrievalMode === 'vector'
              ? 'hybrid'
              : 'vector'
      const baselineRun =
        runsByDataset.find(
          (run) => runParamString(run, 'retrieval_mode') !== nextRetrievalMode
        ) || runsByDataset[0] || null
      const run = await evaluationApi.createRegressionRun({
        ...payload,
        retrieval_mode: nextRetrievalMode,
      })
      await runsQuery.refetch()
      if (baselineRun?.id) setSelectedBaseRunId(String(baselineRun.id))
      setSelectedTargetRunId(run.id)
      toast.success(
        `已自动生成第 3 轮对比：${nextRetrievalMode === 'hybrid' ? 'hybrid' : 'vector'}`
      )
    } catch (err) {
      toast.error(formatApiError(err, '自动补齐基线/候选失败'))
    } finally {
      setAutoBootstrapPending(false)
    }
  }

  async function runGridBatch(
    grid: Record<string, RegressionAblationGridValue[]>,
    maxCombinations: number
  ): Promise<void> {
    if (runDisabledReason) {
      toast.error(runDisabledReason)
      return
    }
    await submitAblationBatch(
      buildCurrentRegressionRunPayload(),
      grid,
      maxCombinations,
      () => runsQuery.refetch(),
      setSelectedTargetRunId
    )
  }

  async function computeDiff(): Promise<void> {
    await computeRegressionDiff(selectedBaseRunId, selectedTargetRunId, () =>
      diffQuery.refetch()
    )
  }

  async function exportDiffHtml(): Promise<void> {
    await exportRegressionDiffHtml(selectedBaseRunId, selectedTargetRunId)
  }

  async function refetchAblationPanels(): Promise<void> {
    await runsQuery.refetch()
    await leaderboardQuery.refetch()
  }

  const leaderboardItems = leaderboardQuery.data?.items
  const leaderboardRows: RegressionLeaderboardRow[] = Array.isArray(
    leaderboardItems
  )
    ? leaderboardItems
    : []
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId) || null,
    [datasetId, datasets]
  )
  const selectedBaseRun = useMemo(
    () =>
      runsByDataset.find(
        (run) => _stableId(run.id) === _stableId(selectedBaseRunId)
      ) || null,
    [runsByDataset, selectedBaseRunId]
  )
  const selectedTargetRun = useMemo(
    () =>
      runsByDataset.find(
        (run) => _stableId(run.id) === _stableId(selectedTargetRunId)
      ) || null,
    [runsByDataset, selectedTargetRunId]
  )
  const runsSelectDisabled = runsLoading || runsByDataset.length === 0
  const canGenerateDiff = Boolean(
    _stableId(selectedBaseRunId) &&
    _stableId(selectedTargetRunId) &&
    _stableId(selectedBaseRunId) !== _stableId(selectedTargetRunId)
  )
  const autoBootstrapPlan = useMemo<AutoBootstrapPlan | null>(() => {
    if (runDisabledReason) return null

    const topKValues = new Set(
      runsByDataset
        .map((run) => runParamNumber(run, 'top_k'))
        .filter((value): value is number => typeof value === 'number')
    )
    if (topKValues.size < 2) {
      const candidateTopK = pickAutoCandidateTopK(topK)
      return {
        stage: 'top_k',
        label:
          runsByDataset.length === 0
            ? '自动生成第 1 轮对比'
            : '自动补齐第 1 轮对比',
        helper: `系统会先比较 top_k：${clampNumber(topK, 1, 50)} vs ${candidateTopK}。`,
      }
    }

    const rerankerStates = new Set(
      runsByDataset
        .map((run) => runParamBoolean(run, 'enable_reranker'))
        .filter((value): value is boolean => typeof value === 'boolean')
    )
    if (!(rerankerStates.has(true) && rerankerStates.has(false))) {
      return {
        stage: 'reranker',
        label: '自动生成第 2 轮对比',
        helper: '系统会在保持其他参数基本不变时，补一组 reranker ON/OFF 对比。',
      }
    }

    const retrievalModes = new Set(
      runsByDataset
        .map((run) => runParamString(run, 'retrieval_mode'))
        .filter((value) => value === 'hybrid' || value === 'vector')
    )
    if (!(retrievalModes.has('hybrid') && retrievalModes.has('vector'))) {
      return {
        stage: 'retrieval_mode',
        label: '自动生成第 3 轮对比',
        helper: '系统会补一组 hybrid vs vector 对比，帮你看检索模式切换的影响。',
      }
    }

    return null
  }, [runDisabledReason, runsByDataset, topK])
  const autoRunLabel = autoBootstrapPlan?.label || null
  const autoRunHelper = autoBootstrapPlan?.helper || null
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
  const deepDiveMetricKeys = useMemo(
    () => LEADERBOARD_METRIC_OPTIONS.map((item) => item.key),
    []
  )
  const diffDelta = toNumber(diffScore?.delta)
  const diffDeltaClass = ablationDeltaClass(diffDelta)
  const diffDeltaValue = formatAblationDelta(diffDelta)
  const diffDeltaTone = ablationDeltaTone(diffDelta)
  const metricDiffRows = useMemo(
    () => (Array.isArray(diff?.metric_diffs) ? diff.metric_diffs : []),
    [diff]
  )
  const paramDiffRows = useMemo(() => {
    const base = toRecord(diff?.base_params)
    const target = toRecord(diff?.target_params)
    const keys = Array.from(
      new Set([...Object.keys(base), ...Object.keys(target)])
    ).sort((a, b) => a.localeCompare(b))
    return keys.map((key) => {
      const before = compactValue(base[key])
      const after = compactValue(target[key])
      return { key, before, after, changed: before !== after }
    })
  }, [diff])
  const workspaceGridClassName = ablationWorkspaceGridClassName(
    leftSidebarExpanded,
    leaderboardExpanded
  )

  return (
    <AppFrame showBackground={false} className="bg-muted/50">
      <div className="flex h-[111.111%] w-[111.111%] origin-top-left scale-[0.9] flex-col bg-muted/50">
        <header className="shrink-0 border-b border-border/60 bg-card/95 px-6 py-3.5">
          <PageHeader
            title="检索调参对比"
            description="围绕同一数据集调召回参数、查看实验排行，并对基线与候选做结构化差异对比（也就是检索消融实验）。"
            iconImage="retrieval-ablation"
            icon={BarChart3}
            iconColor="text-info"
            badge="消融实验"
            compact
            className="p-0"
          >
              <div className="mr-14 flex shrink-0 items-center gap-2">
                <Button
                  asChild
                  variant="outline"
                  className="h-9 rounded-xl border-border bg-card px-3 text-[12px] text-foreground/85 hover:bg-muted/50 hover:text-foreground"
                >
                  <Link href="/evaluations">
                    <ChevronLeft className="mr-1.5 h-4 w-4" />
                    返回评测中心
                  </Link>
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="刷新消融实验数据"
                  className="h-9 w-9 rounded-xl border-border bg-card text-primary hover:bg-primary/10"
                  disabled={datasetsLoading || runsLoading}
                  onClick={() => {
                    datasetsQuery.refetch()
                    runsQuery.refetch()
                  }}
                >
                  <RefreshCcw className="h-4 w-4" />
                </Button>
              </div>
          </PageHeader>
        </header>

        <div className="min-h-0 flex-1 overflow-auto p-4">
          <div className={workspaceGridClassName}>
            {leftSidebarExpanded ? (
              <aside className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[0_8px_24px_hsl(var(--foreground)/0.05)]">
                <div className="shrink-0 border-b border-border bg-card px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[15px] font-semibold text-foreground">
                      参数配置
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                      onClick={() => setLeftSidebarCollapsed(true)}
                    >
                      收起
                    </Button>
                  </div>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain no-scrollbar">
                  <AblationSection
                    title="实验基线"
                    description="固定数据集与主指标，确认本轮消融实验的起点。"
                    className="bg-card"
                  >
                    <div className="space-y-3">
                      <div className="space-y-1.5">
                        <Label
                          htmlFor="ablation-dataset"
                          className="text-[12px] text-muted-foreground"
                        >
                          当前数据集
                        </Label>
                        <Select
                          value={datasetId}
                          onValueChange={setDatasetId}
                          disabled={datasetsLoading || !datasets.length}
                        >
                          <SelectTrigger
                            id="ablation-dataset"
                            className="h-10 rounded-xl border-border bg-card text-[13px] shadow-[0_1px_2px_hsl(var(--foreground)/0.04)]"
                          >
                            <SelectValue
                              placeholder={
                                datasetsLoading ? '加载中...' : '选择数据集'
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
                      </div>

                      <AblationDatasetCard
                        dataset={selectedDataset}
                        metricKey={leaderboardMetricKey}
                      />
                      <div
                        className={cn(
                          'flex items-start gap-2 rounded-xl border px-3 py-2 text-[12px] leading-5',
                          selectedDatasetCasesUnavailable
                            ? 'border-warning/30 bg-warning/10 text-warning'
                            : 'border-success/30 bg-success/10 text-success'
                        )}
                      >
                        {selectedDatasetCasesUnavailable ? (
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                        ) : (
                          <Trophy className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                        )}
                        <span>{selectedDatasetCasesStatusText}</span>
                      </div>
                    </div>
                  </AblationSection>

                  <AblationSection
                    title="评测模式"
                    description="决定这轮只看检索，还是同时带上生成质量指标。"
                    className="bg-card"
                  >
                    <div className="space-y-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-foreground">
                            仅检索评测
                          </div>
                          <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
                            关闭生成质量指标，只保留召回率、平均倒数排名与归一化增益等检索指标。
                          </div>
                        </div>
                        <Switch
                          checked={retrievalOnly}
                          onCheckedChange={setRetrievalOnly}
                        />
                      </div>

                      <div className="grid gap-2.5">
                        {RAGAS_METRIC_OPTIONS.map((option) => {
                          const checked = metricKeys.includes(option.key)
                          return (
                            <label
                              key={option.key}
                              className={cn(
                                'flex items-start gap-3 py-1.5',
                                retrievalOnly && 'opacity-60'
                              )}
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
                                <span className="block text-sm font-medium text-foreground">
                                  {option.label}
                                </span>
                                <span className="block text-[11px] leading-5 text-muted-foreground">
                                  {option.hint}
                                </span>
                              </span>
                            </label>
                          )
                        })}
                      </div>
                    </div>
                  </AblationSection>

                  <AblationSection
                    title="检索参数"
                    description="召回窗口、混合检索与权重参数。"
                    className="bg-card"
                  >
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                          样本上限
                        </Label>
                        <Input
                          type="number"
                          value={maxCases}
                          min={1}
                          max={500}
                          onChange={(e) =>
                            setMaxCases(Number(e.target.value || 0))
                          }
                          className="h-9 rounded-lg border-border/70 bg-card"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                          召回数量
                        </Label>
                        <Input
                          type="number"
                          value={topK}
                          min={1}
                          max={50}
                          onChange={(e) => setTopK(Number(e.target.value || 0))}
                          className="h-9 rounded-lg border-border/70 bg-card"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                          检索模式
                        </Label>
                        <Select
                          value={retrievalMode}
                          onValueChange={setRetrievalMode}
                        >
                          <SelectTrigger className="h-9 rounded-lg border-border/70 bg-card">
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
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                          分数阈值
                        </Label>
                        <Input
                          type="number"
                          value={scoreThreshold}
                          min={0}
                          max={1}
                          step={0.01}
                          onChange={(e) =>
                            setScoreThreshold(Number(e.target.value || 0))
                          }
                          className="h-9 rounded-lg border-border/70 bg-card"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                          混合权重
                        </Label>
                        <Input
                          type="number"
                          value={alpha}
                          min={0}
                          max={1}
                          step={0.05}
                          onChange={(e) =>
                            setAlpha(Number(e.target.value || 0))
                          }
                          className="h-9 rounded-lg border-border/70 bg-card"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                          多样性系数
                        </Label>
                        <Input
                          type="number"
                          value={mmrLambda}
                          min={0}
                          max={1}
                          step={0.05}
                          onChange={(e) =>
                            setMmrLambda(Number(e.target.value || 0))
                          }
                          className="h-9 rounded-lg border-border/70 bg-card"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                          向量权重
                        </Label>
                        <Input
                          type="number"
                          value={vectorWeight}
                          min={0}
                          max={1}
                          step={0.05}
                          onChange={(e) =>
                            setVectorWeight(Number(e.target.value || 0))
                          }
                          className="h-9 rounded-lg border-border/70 bg-card"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                          关键词权重
                        </Label>
                        <Input
                          type="number"
                          value={keywordWeight}
                          min={0}
                          max={1}
                          step={0.05}
                          onChange={(e) =>
                            setKeywordWeight(Number(e.target.value || 0))
                          }
                          className="h-9 rounded-lg border-border/70 bg-card"
                        />
                      </div>
                    </div>
                  </AblationSection>

                  <AblationSection
                    title="重排与过滤"
                    description="控制过滤策略与重排模型参数。"
                    className="bg-card"
                  >
                    <div className="space-y-3">
                      <label className="flex items-start gap-3 py-1.5">
                        <Checkbox
                          checked={skipEmptyContexts}
                          onCheckedChange={(value) =>
                            setSkipEmptyContexts(value === true)
                          }
                        />
                        <span className="space-y-1">
                          <span className="block text-sm font-medium text-foreground">
                            跳过空上下文样本
                          </span>
                          <span className="block text-[11px] leading-5 text-muted-foreground">
                            过滤掉没有引用上下文的样本，减少空样本对分数的扰动。
                          </span>
                        </span>
                      </label>

                      <label className="flex items-start gap-3 py-1.5">
                        <Checkbox
                          checked={enableWeightRerank}
                          onCheckedChange={(value) =>
                            setEnableWeightRerank(value === true)
                          }
                        />
                        <span className="space-y-1">
                          <span className="block text-sm font-medium text-foreground">
                            启用权重重排
                          </span>
                          <span className="block text-[11px] leading-5 text-muted-foreground">
                            对混合检索结果做二次权重整合，观察向量与关键词配比的影响。
                          </span>
                        </span>
                      </label>

                      <div className="border-t border-border/70 pt-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-foreground">
                              重排器
                            </div>
                            <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
                              默认跟随全局重排配置；本次实验可临时切换重排服务与候选数量。
                            </div>
                          </div>
                          <Switch
                            checked={enableReranker}
                            onCheckedChange={setEnableReranker}
                          />
                        </div>
                        <div className="mt-3 grid gap-3 sm:grid-cols-2">
                          <div className="space-y-1.5">
                            <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                              重排服务
                            </Label>
                            <Select
                              value={rerankerProvider}
                              onValueChange={setRerankerProvider}
                            >
                              <SelectTrigger className="h-9 rounded-lg border-border/70 bg-card">
                                <SelectValue placeholder="选择重排器" />
                              </SelectTrigger>
                              <SelectContent>
                                {RERANKER_PROVIDER_OPTIONS.map((option) => (
                                  <SelectItem key={option.key} value={option.key}>
                                    {option.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <div className="text-[11px] leading-5 text-muted-foreground">
                              读取系统设置默认值，运行实验时可单独覆盖。
                            </div>
                          </div>
                          <div className="space-y-1.5">
                            <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">
                              重排数量
                            </Label>
                            <Input
                              type="number"
                              value={rerankerTopN}
                              min={1}
                              max={200}
                              onChange={(e) =>
                                setRerankerTopN(Number(e.target.value || 0))
                              }
                              className="h-9 rounded-lg border-border/70 bg-card"
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  </AblationSection>
                </div>

                <div className="shrink-0 border-t border-info/20 bg-info/5 px-5 py-3.5 shadow-none">
                  <div className="text-[11px] tracking-[0.08em] text-muted-foreground">
                    运行入口
                  </div>
                  <Button
                    className="mt-2 h-10 w-full gap-2 rounded-lg border border-info/30 bg-info/10 text-info shadow-[0_8px_18px_hsl(var(--info)/0.10)] transition-colors hover:border-info/40 hover:bg-info/15 hover:text-info"
                    disabled={Boolean(runDisabledReason) || autoBootstrapPending}
                    onClick={() =>
                      detachPromise(
                        autoRunLabel ? runAutoBootstrap() : runAblation()
                      )
                    }
                  >
                    <PlayCircle className="h-4 w-4" />
                    {autoBootstrapPending
                      ? '正在自动补齐...'
                      : autoRunLabel || '运行消融实验'}
                  </Button>
                  {runDisabledReason ? (
                    <div className="mt-2 text-[11px] leading-5 text-warning">
                      {runDisabledReason}
                    </div>
                  ) : autoRunLabel ? (
                    <div className="mt-2 text-[11px] leading-5 text-info">
                      {autoRunHelper}
                    </div>
                  ) : null}
                </div>
              </aside>
            ) : null}

            <div className="contents">
              {leftSidebarCollapsed ? (
                <button
                  type="button"
                  className="focus-ring absolute left-0 top-3 z-20 -translate-x-1/2 rounded-full border border-border/70 bg-card p-1 text-muted-foreground shadow-sm transition-colors hover:bg-muted/50 hover:text-foreground"
                  onClick={() => setLeftSidebarCollapsed(false)}
                  aria-label="展开参数配置栏"
                  title="展开参数配置栏"
                >
                  <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              ) : null}
              {leaderboardExpanded ? (
                <section className="order-3 flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[0_8px_24px_hsl(var(--foreground)/0.05)]">
                  <div className="flex h-full min-h-0 flex-col">
                    <div className="flex min-h-[58px] items-center justify-between gap-3 border-b border-border bg-card px-4 py-3">
                      <div className="min-w-0">
                        <div className="truncate text-[15px] font-semibold text-foreground">
                          实验排行
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Trophy className="h-4 w-4 text-primary" />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-8 rounded-lg px-2.5 text-[12px] text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                          onClick={() => setLeaderboardCollapsed(true)}
                        >
                          收起
                        </Button>
                      </div>
                    </div>

                    <div className="border-b border-border bg-card px-4 py-3">
                      <div className="space-y-2">
                        <div className="flex items-end gap-2">
                          <div className="min-w-0 flex-1 space-y-1">
                            <Label className="text-[12px] text-muted-foreground">
                              排行榜主指标
                            </Label>
                            <Select
                              value={leaderboardMetricKey}
                              onValueChange={setLeaderboardMetricKey}
                            >
                              <SelectTrigger className="h-9 rounded-xl border-border bg-card text-[13px]">
                                <SelectValue placeholder="选择指标" />
                              </SelectTrigger>
                              <SelectContent>
                                {LEADERBOARD_METRIC_OPTIONS.map((metric) => (
                                  <SelectItem
                                    key={metric.key}
                                    value={metric.key}
                                  >
                                    {metric.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>

                          <Button
                            variant="outline"
                            className="h-9 gap-1.5 rounded-xl border-border bg-card px-3 text-[13px] text-foreground hover:bg-muted/50"
                            disabled={leaderboardLoading}
                            onClick={() => leaderboardQuery.refetch()}
                          >
                            <RefreshCcw className="h-3.5 w-3.5" />
                            刷新
                          </Button>
                        </div>

                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[12px] text-muted-foreground">
                            筛选运行
                          </span>
                          <div className="inline-flex rounded-lg border border-border/70 bg-card p-0.5 shadow-[inset_0_1px_0_hsl(var(--background)/0.85)]">
                            <button
                              type="button"
                              className={cn(
                                'h-7 rounded-md px-2.5 text-[11px] font-medium',
                                leaderboardAssignRole === 'base'
                                  ? 'bg-info text-primary-foreground shadow-sm'
                                  : 'text-muted-foreground hover:bg-muted'
                              )}
                              onClick={() => setLeaderboardAssignRole('base')}
                            >
                              基线
                            </button>
                            <button
                              type="button"
                              className={cn(
                                'h-7 rounded-md px-2.5 text-[11px] font-medium',
                                leaderboardAssignRole === 'target'
                                  ? 'bg-primary text-primary-foreground shadow-sm'
                                  : 'text-muted-foreground hover:bg-muted'
                              )}
                              onClick={() => setLeaderboardAssignRole('target')}
                            >
                              候选
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="min-h-0 flex-1 overflow-y-auto no-scrollbar">
                      {leaderboardRows.length ? (
                        leaderboardRows.map((row) => {
                          const runId = String(row.run_id || '')
                          const metricValue = toNumber(row.metric_value)
                          const badge = runStatusMeta(row.status)
                          const isBase =
                            _stableId(runId) === _stableId(selectedBaseRunId)
                          const isTarget =
                            _stableId(runId) === _stableId(selectedTargetRunId)
                          return (
                            <button
                              key={runId}
                              type="button"
                              className={cn(
                                'w-full border-b border-border/60 bg-card px-5 py-2.5 text-left transition-colors hover:bg-muted/40',
                                isBase || isTarget
                                  ? 'border-l-2 border-l-info bg-info/5'
                                  : ''
                              )}
                              onClick={() => {
                                if (leaderboardAssignRole === 'base')
                                  setSelectedBaseRunId(runId)
                                else setSelectedTargetRunId(runId)
                              }}
                            >
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-1.5">
                                  <span className="font-mono text-[12px] text-foreground">
                                    {shortId(runId)}
                                  </span>
                                  <StatusBadge
                                    status={badge.status}
                                    label={badge.label}
                                    dense
                                  />
                                  {isBase ? (
                                    <span className="rounded-full bg-info px-1.5 py-0.5 text-[9px] font-medium text-primary-foreground">
                                      基线
                                    </span>
                                  ) : null}
                                  {isTarget ? (
                                    <span className="rounded-full bg-primary/12 px-1.5 py-0.5 text-[9px] font-medium text-primary">
                                      候选
                                    </span>
                                  ) : null}
                                </div>
                                <div className="mt-1.5 text-[13px] font-semibold tabular-nums text-foreground">
                                  {formatMetric(metricValue)}
                                </div>
                                <div className="mt-1 font-mono text-[11px] leading-4 text-muted-foreground">
                                  {String(
                                    row.retrieval_config_hash ||
                                      '无配置哈希'
                                  )}
                                </div>
                              </div>
                            </button>
                          )
                        })
                      ) : (
                        <AblationLeaderboardEmptyState />
                      )}
                    </div>
                  </div>
                </section>
              ) : null}

              <AblationComparisonWorkspace
                leaderboardCollapsed={leaderboardCollapsed}
                leftSidebarCollapsed={leftSidebarCollapsed}
                setLeaderboardCollapsed={setLeaderboardCollapsed}
                runsSelectionHint={runsSelectionHint}
                diffDeltaClass={diffDeltaClass}
                diffDeltaValue={diffDeltaValue}
                runsLoading={runsLoading}
                selectedBaseRunId={selectedBaseRunId}
                selectedTargetRunId={selectedTargetRunId}
                setSelectedBaseRunId={setSelectedBaseRunId}
                setSelectedTargetRunId={setSelectedTargetRunId}
                runsSelectDisabled={runsSelectDisabled}
                runsByDataset={runsByDataset}
                selectedBaseRun={selectedBaseRun}
                selectedTargetRun={selectedTargetRun}
                diffDeltaTone={diffDeltaTone}
                diffLoading={diffLoading}
                canGenerateDiff={canGenerateDiff}
                computeDiff={computeDiff}
                diff={diff}
                exportDiffHtml={exportDiffHtml}
                diffScoreFmt={diffScoreFmt}
                metricDiffRows={metricDiffRows}
                paramDiffRows={paramDiffRows}
                datasetId={datasetId}
                runDisabledReason={runDisabledReason}
                runGridBatch={runGridBatch}
                refetchPanels={refetchAblationPanels}
                leaderboardMetricKey={leaderboardMetricKey}
                deepDiveMetricKeys={deepDiveMetricKeys}
                diffJson={diffJson}
                caseCount={selectedDatasetCaseCount}
                autoRunLabel={autoRunLabel}
                autoRunHelper={autoRunHelper}
                autoBootstrapPending={autoBootstrapPending}
                runAutoBootstrap={runAutoBootstrap}
              />
            </div>
          </div>
        </div>
      </div>
    </AppFrame>
  )
}
