'use client'
import { useQuery } from '@tanstack/react-query';
import { useEffect, useLayoutEffect, useRef, useMemo, useState, type ReactNode } from 'react';
import { ChevronDown, Database, GitCompare, Info, MoreHorizontal } from '@/components/icons';
import { toast } from 'sonner';
import { AppFrame } from '@/components/app-frame';
import { AblationCaseDrilldown } from '@/components/evaluation/ablation-case-drilldown';
import { AblationComparisonMatrix } from '@/components/evaluation/ablation-comparison-matrix';
import { AblationGridPanel } from '@/components/evaluation/ablation-grid-panel';
import { AblationParameterImpactPanel } from '@/components/evaluation/ablation-parameter-impact-panel';
import { AblationParetoPanel } from '@/components/evaluation/ablation-pareto-panel';
import { AblationSliceDiffPanel } from '@/components/evaluation/ablation-slice-diff-panel';
import { AblationStatisticsPanel } from '@/components/evaluation/ablation-statistics-panel';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { OperationalWorkspace, WorkspaceNotice, WorkspaceTableScroll, workspaceStyles as ws } from '@/components/ui/operational-workspace';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { StatusBadge } from '@/components/ui/status-badge';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { formatApiError } from '@/lib/api-errors';
import { datasetApi } from '@/lib/api/datasets';
import { evaluationApi } from '@/lib/api/evaluation';
import { settingsApi } from '@/lib/api/settings';
import { Link } from '@/i18n/navigation';
import { toTrimmedPrimitiveString } from '@/lib/primitive-text';
import { queryKeys } from '@/lib/query-keys';
import { normalizeRerankerProvider, RERANKER_PROVIDER_OPTIONS } from '@/lib/reranker-provider-options';
import { sanitizeFilename } from '@/lib/sanitize';
import type { Dataset, RagasRegressionRunDiffResponse, RegressionAblationGridValue, RegressionRunMetricDiff, RegressionRun, RegressionRunCreate } from '@/types';
import { cn, detachPromise } from '@/lib/utils';
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
        'border-b border-border bg-background py-5 last:border-b-0',
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
            className="h-7 w-7 shrink-0 rounded-lg border border-border bg-background text-muted-foreground hover:bg-muted/50 hover:text-foreground"
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
  const hint = !datasetId ? '选择数据集后查看实验记录。' : caseCount === 0 ? '先在评测中心准备 Golden 样本，再运行实验。' : runCount < 2 ? '至少需要两条运行记录才能对比，可新建实验或自动补齐对照。' : '可查看指标、参数与样本差异。'

  return <div className={ws.empty}><h2>尚未生成运行对比</h2><p>{hint}</p>{autoRunLabel && onAutoRun ? <Button disabled={autoRunPending} onClick={onAutoRun}>{autoRunPending ? '正在提交…' : autoRunLabel}</Button> : null}{autoRunHelper ? <p>{autoRunHelper}</p> : null}</div>
}

type JsonTokenKind = 'plain' | 'key' | 'string' | 'number' | 'boolean' | 'null' | 'punctuation'
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
          <div className="bg-background px-3 py-2.5 sm:border-r sm:border-border/70">
            <div className="text-[11px] tracking-[0.08em] text-muted-foreground">
              基线得分
            </div>
            <div className="mt-1 font-mono text-[13px] font-semibold text-foreground">
              {diffScoreFmt.base}
            </div>
          </div>
          <div className="bg-background px-3 py-2.5 sm:border-r sm:border-border/70">
            <div className="text-[11px] tracking-[0.08em] text-muted-foreground">
              候选得分
            </div>
            <div className="mt-1 font-mono text-[13px] font-semibold text-foreground">
              {diffScoreFmt.target}
            </div>
          </div>
          <div className="bg-background px-3 py-2.5">
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

        <div className="grid grid-cols-[minmax(120px,1fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)] border-b border-border/70 bg-background px-3 py-2 text-[11px] tracking-[0.08em] text-muted-foreground">
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
      <div className="grid grid-cols-[minmax(140px,180px)_minmax(0,1fr)_minmax(0,1fr)] border-b border-border/70 bg-background px-3 py-2 text-[11px] tracking-[0.08em] text-muted-foreground">
        <div>参数</div>
        <div>基线</div>
        <div>候选</div>
      </div>
      {paramDiffRows.length ? (
        paramDiffRows.map((row) => (
          <div
            key={row.key}
            className="grid grid-cols-[minmax(140px,180px)_minmax(0,1fr)_minmax(0,1fr)] border-b border-border/60 bg-background px-3 py-2 text-xs last:border-b-0"
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
    <div className="flex min-h-0 flex-col">
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
  runsSelectionHint,
  diffDeltaClass,
  runsLoading,
  selectedBaseRunId,
  selectedTargetRunId,
  setSelectedBaseRunId,
  setSelectedTargetRunId,
  runsSelectDisabled,
  runsByDataset,
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
  runsSelectionHint: string
  diffDeltaClass: string
  runsLoading: boolean
  selectedBaseRunId: string
  selectedTargetRunId: string
  setSelectedBaseRunId: (value: string) => void
  setSelectedTargetRunId: (value: string) => void
  runsSelectDisabled: boolean
  runsByDataset: RegressionRun[]
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

  return (
<section className="min-w-0 border-t border-border">
      <div className="flex min-h-0 flex-col">
        <div className="flex min-h-[58px] items-center justify-between gap-3 border-b border-border bg-background px-4 py-3">
          <div className="flex min-w-0 items-center gap-1.5">
            <div className="truncate text-[15px] font-semibold text-foreground">
              差异对比工作区
            </div>
            <AblationInfoTooltip label="查看运行记录选择说明" side="bottom">
              {runsSelectionHint}
            </AblationInfoTooltip>
          </div>

        </div>

        <div className="border-b border-border bg-background px-4 py-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-[12px] text-muted-foreground">选择基线运行</Label>
              <Select
                value={selectedBaseRunId}
                onValueChange={setSelectedBaseRunId}
                disabled={runsSelectDisabled}
              >
                <SelectTrigger aria-label="选择基线运行" className="h-10 rounded-xl border-border bg-background text-[13px]">
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
                <SelectTrigger aria-label="选择候选运行" className="h-10 rounded-xl border-border bg-background text-[13px]">
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

          <div className="mt-4 flex items-center justify-end">
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
                  <Button
                    variant="outline"
                    className="h-9 gap-1.5 rounded-xl border-border bg-background px-3 text-[13px] text-foreground hover:bg-muted/50"
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
            className="mt-0 min-h-0 flex-1 overflow-auto bg-background"
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
  const [configOpen, setConfigOpen] = useState(false)
  const [runListView, setRunListView] = useState('experiments')
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const scopeRef = useRef({ datasetId })
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
  const [selectedBaseRunId, setSelectedBaseRunId] = useState('')
  const [selectedTargetRunId, setSelectedTargetRunId] = useState('')
  const [extraRuns, setExtraRuns] = useState<RegressionRun[]>([])
  const [pendingSelection, setPendingSelection] = useState<{ base: string | null; target: string | null }>({ base: null, target: null })
  const [selectionErrors, setSelectionErrors] = useState<{ base: { id: string; message: string } | null; target: { id: string; message: string } | null }>({ base: null, target: null })
  const selectionRequests = useRef({ base: 0, target: 0 })
  useLayoutEffect(() => {
    scopeRef.current = { datasetId }
    setActionError(null); setSubmitting(false); setAutoBootstrapPending(false)
    setExtraRuns([]); setSelectedBaseRunId(''); setSelectedTargetRunId('')
    setPendingSelection({ base: null, target: null }); setSelectionErrors({ base: null, target: null })
  }, [datasetId])

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

  const leaderboardItems = leaderboardQuery.data?.items
  const leaderboardRows: RegressionLeaderboardRow[] = Array.isArray(
    leaderboardItems
  )
    ? leaderboardItems
    : []
  const runsByDataset = useMemo(() => {
    const ds = datasetId.trim()
    if (!ds) return runs
    return (runs || []).filter((r) => String(r?.dataset_id || '') === ds)
  }, [runs, datasetId])

  const availableRuns = useMemo(() => {
    const records = new Map(runsByDataset.map(run => [run.id, run]))
    for (const run of extraRuns) if (run.dataset_id === datasetId && !records.has(run.id)) records.set(run.id, run)
    return Array.from(records.values())
  }, [runsByDataset, extraRuns, datasetId])

  async function selectRun(id: string, role: 'base' | 'target') {
    const context = scopeRef.current, request = ++selectionRequests.current[role]
    setSelectionErrors(current => ({ ...current, [role]: null }))
    const select = role === 'base' ? setSelectedBaseRunId : setSelectedTargetRunId
    if (availableRuns.some(run => run.id === id)) {
      setPendingSelection(current => ({ ...current, [role]: null })); select(id); return
    }
    setPendingSelection(current => ({ ...current, [role]: id }))
    try {
      const detail = await evaluationApi.getRegressionRun(id, { include_items: false })
      if (scopeRef.current !== context || selectionRequests.current[role] !== request) return
      if (detail.run.dataset_id !== datasetId) throw new Error('运行记录不属于当前数据集')
      setExtraRuns(current => [...current.filter(run => run.id !== id), detail.run])
      select(id)
    } catch (error) {
      if (scopeRef.current === context && selectionRequests.current[role] === request) setSelectionErrors(current => ({ ...current, [role]: { id, message: `${role === 'base' ? '基线' : '候选'} ${shortId(id)}：${formatApiError(error, '读取运行详情失败')}` } }))
    } finally {
      if (scopeRef.current === context && selectionRequests.current[role] === request) setPendingSelection(current => ({ ...current, [role]: null }))
    }
  }

  useEffect(() => {
    const pair = pickRunPair(
      availableRuns,
      selectedBaseRunId,
      selectedTargetRunId
    )
    if (pair.baseRunId !== _stableId(selectedBaseRunId))
      setSelectedBaseRunId(pair.baseRunId)
    if (pair.targetRunId !== _stableId(selectedTargetRunId))
      setSelectedTargetRunId(pair.targetRunId)
  }, [availableRuns, selectedBaseRunId, selectedTargetRunId])

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
    const payload = buildCurrentRegressionRunPayload()
    if (!payload || runDisabledReason) { setActionError(runDisabledReason || '请选择数据集'); return }
    const context = scopeRef.current
    setSubmitting(true); setActionError(null)
    try {
      const run = await evaluationApi.createRegressionRun(payload)
      if (scopeRef.current !== context) return
      await refetchAblationPanels()
      if (scopeRef.current !== context) return
      setSelectedTargetRunId(run.id); setConfigOpen(false)
      toast.success('已创建实验运行')
    } catch (error) { if (scopeRef.current === context) setActionError(formatApiError(error, '创建实验运行失败')) }
    finally { if (scopeRef.current === context) setSubmitting(false) }
  }

  async function runAutoBootstrap(): Promise<void> {
    if (runDisabledReason) {
      toast.error(runDisabledReason)
      return
    }

    const context = scopeRef.current
    setActionError(null)
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
          if (scopeRef.current !== context) return
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
          if (scopeRef.current !== context) return
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
          if (scopeRef.current !== context) return
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
          if (scopeRef.current !== context) return
      if (baselineRun?.id) setSelectedBaseRunId(String(baselineRun.id))
      setSelectedTargetRunId(run.id)
      toast.success(
        `已自动生成第 3 轮对比：${nextRetrievalMode === 'hybrid' ? 'hybrid' : 'vector'}`
      )
    } catch (err) {
      if (scopeRef.current === context) setActionError(formatApiError(err, '自动补齐基线/候选失败'))
    } finally {
      if (scopeRef.current === context) setAutoBootstrapPending(false)
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
    const context = scopeRef.current
    await submitAblationBatch(
      buildCurrentRegressionRunPayload(),
      grid,
      maxCombinations,
      () => runsQuery.refetch(),
      id => { if (scopeRef.current === context) setSelectedTargetRunId(id) }
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

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId) || null,
    [datasetId, datasets]
  )
  const runsSelectDisabled = runsLoading || availableRuns.length === 0
  const canGenerateDiff = Boolean(
    availableRuns.some(run => run.id === selectedBaseRunId) &&
    availableRuns.some(run => run.id === selectedTargetRunId) &&
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

  // Ranking candidates are independent of the capped recent-run endpoint.
  const tableRows = runListView === 'ranking' ? leaderboardRows.map(rank => {
    const run = availableRuns.find(item => item.id === rank.run_id)
    return { id: rank.run_id, status: rank.status, createdAt: rank.created_at ?? run?.created_at, topK: run ? runParamNumber(run, 'top_k') : null, metric: toNumber(rank.metric_value), hash: rank.retrieval_config_hash }
  }) : runsByDataset.map(run => {
    const rank = leaderboardRows.find(item => item.run_id === run.id)
    return { id: run.id, status: run.status, createdAt: run.created_at, topK: runParamNumber(run, 'top_k'), metric: toNumber(rank?.metric_value), hash: rank?.retrieval_config_hash }
  })

  return <AppFrame showBackground={false}><OperationalWorkspace title="检索调参对比" icon="retrieval-ablation" context={selectedDataset?.name || '选择数据集'} actions={<><Button asChild variant="ghost"><Link href="/evaluations">评测中心</Link></Button><Button onClick={() => { setActionError(null); setConfigOpen(true) }}>新建实验</Button></>} toolbar={<>
    <label className="flex max-w-full items-center gap-2 text-[13px]">数据集<select aria-label="实验数据集" className="h-10 max-w-[220px] rounded-md border border-input bg-background px-3" value={datasetId} disabled={datasetsLoading} onChange={event => setDatasetId(event.target.value)}><option value="" disabled>选择数据集</option>{datasets.map(dataset => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select></label>
    <label className="flex items-center gap-2 text-[13px]">主指标<select aria-label="排行榜主指标" className="h-10 rounded-md border border-input bg-background px-3" value={leaderboardMetricKey} onChange={event => setLeaderboardMetricKey(event.target.value)}>{LEADERBOARD_METRIC_OPTIONS.map(metric => <option key={metric.key} value={metric.key}>{metric.label}</option>)}</select></label>
    <Button variant="ghost" disabled={runsLoading || leaderboardLoading} onClick={() => { void refetchAblationPanels() }}>重新读取</Button>
  </>}>
    {datasetsQuery.isError ? <WorkspaceNotice retry={() => { void datasetsQuery.refetch() }}>{formatApiError(datasetsQuery.error, '数据集读取失败')}</WorkspaceNotice> : null}
    {runsQuery.isError ? <WorkspaceNotice retry={() => { void runsQuery.refetch() }}>{formatApiError(runsQuery.error, '实验记录读取失败')}</WorkspaceNotice> : null}
    {leaderboardQuery.isError ? <WorkspaceNotice retry={() => { void leaderboardQuery.refetch() }}>{formatApiError(leaderboardQuery.error, '实验排行读取失败')}</WorkspaceNotice> : null}
    {selectedDatasetCasesQuery.isError ? <WorkspaceNotice retry={() => { void selectedDatasetCasesQuery.refetch() }}>{formatApiError(selectedDatasetCasesQuery.error, '评测样本读取失败')}</WorkspaceNotice> : null}
    <section className={ws.section}>
      <div className={ws.sectionHeading}><h2 className={ws.sectionTitle}>实验记录与排行</h2><div role="group" aria-label="实验列表视图" className="flex gap-2"><Button variant={runListView === 'experiments' ? 'secondary' : 'ghost'} onClick={() => setRunListView('experiments')}>全部运行</Button><Button variant={runListView === 'ranking' ? 'secondary' : 'ghost'} onClick={() => setRunListView('ranking')}>按指标排行</Button></div></div>
      {runsLoading ? <p role="status" className="py-8 text-sm text-muted-foreground">正在读取实验记录…</p> : tableRows.length ? <WorkspaceTableScroll label="实验运行表格" stickyActions><table aria-label="实验运行" className={cn(ws.table, 'min-w-[740px]')}><thead><tr><th>运行</th><th className="hidden sm:table-cell">状态</th><th>TOP-K</th><th>{leaderboardMetricLabel(leaderboardMetricKey)}</th><th>配置</th><th>操作</th></tr></thead><tbody>{tableRows.map(row => {
        const badge = runStatusMeta(row.status)
        return <tr key={row.id} data-selected={row.id === selectedBaseRunId || row.id === selectedTargetRunId}>
          <td><strong className="font-mono text-[13px] font-medium">{shortId(row.id)}</strong><div className="mt-1 sm:hidden"><StatusBadge status={badge.status} label={badge.label} dense /></div><p>{row.createdAt ? row.createdAt.replace('T', ' ').slice(0, 19) : '—'}</p></td>
          <td className="hidden sm:table-cell"><StatusBadge status={badge.status} label={badge.label} dense /></td><td>{row.topK ?? '—'}</td><td className="tabular-nums">{formatMetric(row.metric)}</td><td><span className="font-mono text-xs">{row.hash?.slice(0, 12) || '—'}</span></td>
          <td><div className="flex gap-1">{(['base', 'target'] as const).map(role => <Button key={role} variant={row.id === (role === 'base' ? selectedBaseRunId : selectedTargetRunId) ? 'secondary' : 'ghost'} disabled={pendingSelection[role] === row.id} aria-label={`设为${role === 'base' ? '基线' : '候选'} ${row.id}`} onClick={() => { void selectRun(row.id, role) }}>{pendingSelection[role] === row.id ? '读取中…' : role === 'base' ? '基线' : '候选'}</Button>)}</div>{(['base', 'target'] as const).map(role => selectionErrors[role]?.id === row.id ? <p role="alert" key={role} className="max-w-64 text-[13px] text-destructive">{selectionErrors[role]!.message}</p> : null)}</td>
        </tr>
      })}</tbody></table>{runListView === 'ranking' && !leaderboardRows.length ? <p className="py-8 text-sm text-muted-foreground">当前主指标暂无可排行的已完成运行</p> : null}</WorkspaceTableScroll> : !runsQuery.isError ? <div className={ws.empty}><h2>当前数据集暂无实验运行</h2><p>{selectedDatasetCasesStatusText}</p><Button disabled={Boolean(runDisabledReason)} onClick={() => setConfigOpen(true)}>配置实验</Button></div> : null}
    </section>
    {diffQuery.isError ? <WorkspaceNotice retry={() => { void computeDiff() }}>{formatApiError(diffQuery.error, '运行对比读取失败')}</WorkspaceNotice> : null}
    <AblationComparisonWorkspace
                runsSelectionHint={runsSelectionHint}
                diffDeltaClass={diffDeltaClass}
                runsLoading={runsLoading}
                selectedBaseRunId={selectedBaseRunId}
                selectedTargetRunId={selectedTargetRunId}
                setSelectedBaseRunId={id => { void selectRun(id, 'base') }}
                setSelectedTargetRunId={id => { void selectRun(id, 'target') }}
                runsSelectDisabled={runsSelectDisabled}
                runsByDataset={availableRuns}
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
    <Dialog open={configOpen} onOpenChange={setConfigOpen}><DialogContent className={cn(ws.dialog, ws.wideDialog)}><DialogHeader className={ws.dialogHeader}><DialogTitle>实验参数</DialogTitle><DialogDescription>数据集：{selectedDataset?.name || datasetId || '未选择'}。本次参数仅用于新建实验。</DialogDescription></DialogHeader><div className={ws.dialogBody}>
      <p className="mb-3 text-[13px] text-muted-foreground">{selectedDatasetCasesStatusText}</p>
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
                        <Switch aria-label="仅检索模式"
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
                        <Input aria-label="评测样本上限"
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
                        <Input aria-label="召回数量 TOP-K"
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
                        <Input aria-label="分数阈值"
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
                        <Input aria-label="混合权重"
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
                        <Input aria-label="MMR 多样性系数"
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
                        <Input aria-label="向量权重"
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
                        <Input aria-label="关键词权重"
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
                          <Switch aria-label="启用重排器"
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
                            <Input aria-label="重排数量"
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

      {actionError ? <WorkspaceNotice>{actionError}</WorkspaceNotice> : null}
    </div><DialogFooter className={ws.dialogFooter}><Button variant="outline" onClick={() => setConfigOpen(false)}>取消</Button><Button disabled={Boolean(runDisabledReason) || submitting || autoBootstrapPending} onClick={() => { void runAblation() }}>{submitting ? '正在提交…' : '运行消融实验'}</Button>{autoRunLabel ? <Button variant="outline" disabled={Boolean(runDisabledReason) || submitting || autoBootstrapPending} onClick={() => { void runAutoBootstrap() }}>{autoBootstrapPending ? '正在提交…' : autoRunLabel}</Button> : null}</DialogFooter></DialogContent></Dialog>
  </OperationalWorkspace></AppFrame>
}
