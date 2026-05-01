'use client'

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  BarChart3,
  ChevronDown,
  ChevronRight,
  Database,
  GitCompare,
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
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi } from '@/lib/api/datasets'
import { evaluationApi } from '@/lib/api/evaluation'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { sanitizeFilename } from '@/lib/sanitize'
import type { Dataset, RegressionAblationGridValue, RegressionRun, RegressionRunCreate, RagasRegressionRunDiffResponse } from '@/types'
import { cn, detachPromise } from '@/lib/utils'

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


function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
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

const RAGAS_METRIC_OPTIONS = [
  { key: 'faithfulness', label: 'Faithfulness', hint: '答案是否忠于检索上下文' },
  { key: 'response_relevancy', label: 'Response Relevancy', hint: '回答是否真正回应问题' },
  { key: 'context_precision', label: 'Context Precision', hint: '上下文是否足够精准干净' },
]

const RETRIEVAL_MODE_OPTIONS = [
  { key: 'hybrid', label: 'hybrid' },
  { key: 'vector', label: 'vector' },
  { key: 'keyword', label: 'keyword' },
  { key: 'mmr', label: 'mmr' },
]

const LEADERBOARD_METRIC_OPTIONS = [
  { key: 'retrieval_mrr', label: 'retrieval_mrr' },
  { key: 'retrieval_recall', label: 'retrieval_recall' },
  { key: 'retrieval_ndcg_at_10', label: 'retrieval_ndcg@10' },
  { key: 'retrieval_ndcg_at_20', label: 'retrieval_ndcg@20' },
  { key: 'faithfulness_det', label: 'faithfulness_det' },
  { key: 'refusal_correctness', label: 'refusal_correctness' },
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
  return LEADERBOARD_METRIC_OPTIONS.find((item) => item.key === key)?.label || key
}

function runStatusMeta(statusValue: string | null | undefined): {
  status: 'completed' | 'failed' | 'processing'
  label: string
} {
  if (statusValue === 'completed') return { status: 'completed', label: '已完成' }
  if (statusValue === 'failed') return { status: 'failed', label: '失败' }
  return { status: 'processing', label: '运行中' }
}

function toRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function compactValue(value: unknown, maxLen = 72): string {
  if (value === null || value === undefined) return '-'
  const raw = (() => {
    if (typeof value === 'string') return value
    if (typeof value === 'number' || typeof value === 'boolean') return String(value)
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  })()
  if (!raw) return '-'
  return raw.length > maxLen ? `${raw.slice(0, maxLen - 1)}…` : raw
}

function AblationInlineStat({
  label,
  value,
  tone = 'neutral',
}: Readonly<{
  label: string
  value: ReactNode
  tone?: 'neutral' | 'sky' | 'amber' | 'violet' | 'emerald'
}>) {
  const toneClasses =
    tone === 'sky'
      ? {
          surface: 'border-sky-200/80 bg-sky-50/85',
          label: 'text-sky-700',
          value: 'text-sky-900',
        }
      : tone === 'amber'
        ? {
            surface: 'border-amber-200/80 bg-amber-50/85',
            label: 'text-amber-700',
            value: 'text-amber-900',
          }
        : tone === 'violet'
          ? {
              surface: 'border-violet-200/80 bg-violet-50/85',
              label: 'text-violet-700',
              value: 'text-violet-900',
            }
          : tone === 'emerald'
            ? {
                surface: 'border-emerald-200/80 bg-emerald-50/85',
                label: 'text-emerald-700',
                value: 'text-emerald-900',
              }
            : {
                surface: 'border-border/70 bg-card',
                label: 'text-muted-foreground',
                value: 'text-foreground',
              }

  return (
    <div className={cn('inline-flex items-center gap-1.5 rounded-md border px-2 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]', toneClasses.surface)}>
      <span className={cn('text-[11px] tracking-[0.08em]', toneClasses.label)}>{label}</span>
      <span className={cn('font-mono text-[11px] tabular-nums', toneClasses.value)}>{value}</span>
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
    <section className={cn('border-b border-border/70 bg-[linear-gradient(180deg,rgba(248,250,252,0.62)_0%,rgba(255,255,255,0.98)_100%)] px-5 py-4 last:border-b-0', className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{title}</div>
          {!collapsed && description ? <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{description}</p> : null}
        </div>
        {collapsible ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6 shrink-0 rounded-md border border-border/70 bg-card/90 text-muted-foreground hover:bg-slate-100 hover:text-foreground"
            onClick={() => setCollapsed((prev) => !prev)}
            aria-label={collapsed ? `展开${title}` : `收起${title}`}
          >
            <ChevronDown className={cn('h-3 w-3 transition-transform', collapsed ? '-rotate-90' : 'rotate-0')} />
          </Button>
        ) : null}
      </div>
      {!collapsed ? <div className="mt-3">{children}</div> : null}
    </section>
  )
}

type JsonTokenKind = 'plain' | 'key' | 'string' | 'number' | 'boolean' | 'null' | 'punctuation'

function splitCodeLines(value: string): string[] {
  const normalized = String(value ?? '').replace(/\r/g, '')
  const lines = normalized.split('\n')
  if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop()
  return lines.length ? lines : ['']
}

function tokenizeJsonLine(line: string): Array<{ text: string; kind: JsonTokenKind }> {
  const tokens: Array<{ text: string; kind: JsonTokenKind }> = []
  const pattern =
    /("(?:\\.|[^"\\])*")(\s*:)?|\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b|\btrue\b|\bfalse\b|\bnull\b|[{}\[\],:]/g

  let lastIndex = 0
  let match = pattern.exec(line)
  while (match) {
    if (match.index > lastIndex) {
      tokens.push({ text: line.slice(lastIndex, match.index), kind: 'plain' })
    }

    const raw = match[0] ?? ''
    if (match[1]) {
      const suffix = match[2] ?? ''
      tokens.push({ text: match[1], kind: suffix ? 'key' : 'string' })
      if (suffix) tokens.push({ text: suffix, kind: 'punctuation' })
    } else if (raw === 'true' || raw === 'false') {
      tokens.push({ text: raw, kind: 'boolean' })
    } else if (raw === 'null') {
      tokens.push({ text: raw, kind: 'null' })
    } else if (/^-?\d/.test(raw)) {
      tokens.push({ text: raw, kind: 'number' })
    } else {
      tokens.push({ text: raw, kind: 'punctuation' })
    }

    lastIndex = pattern.lastIndex
    match = pattern.exec(line)
  }

  if (lastIndex < line.length) {
    tokens.push({ text: line.slice(lastIndex), kind: 'plain' })
  }

  return tokens.length ? tokens : [{ text: line, kind: 'plain' }]
}

function jsonTokenClassName(kind: JsonTokenKind): string {
  if (kind === 'key') return 'text-sky-700'
  if (kind === 'string') return 'text-emerald-700'
  if (kind === 'number') return 'text-amber-700'
  if (kind === 'boolean') return 'text-violet-700'
  if (kind === 'null') return 'text-rose-600'
  if (kind === 'punctuation') return 'text-slate-500'
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
    <div className="h-full min-h-0 overflow-auto bg-[linear-gradient(180deg,rgba(248,250,252,0.96)_0%,rgba(255,255,255,1)_40%)]">
      <div className="min-w-max">
        {lines.map((line, index) => (
          <JsonCodeLine key={`json-line:${index + 1}`} lineNumber={index + 1} text={line} />
        ))}
      </div>
    </div>
  )
}

export function RetrievalAblationsPage() {
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetId, setDatasetId] = useState('')

  const [runsLoading, setRunsLoading] = useState(false)
  const [runs, setRuns] = useState<RegressionRun[]>([])
  const [selectedBaseRunId, setSelectedBaseRunId] = useState('')
  const [selectedTargetRunId, setSelectedTargetRunId] = useState('')
  const [leaderboardAssignRole, setLeaderboardAssignRole] = useState<'base' | 'target'>('target')
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false)
  const [leaderboardCollapsed, setLeaderboardCollapsed] = useState(false)

  const [leaderboardMetricKey, setLeaderboardMetricKey] = useState<string>('retrieval_mrr')
  const [leaderboardLoading, setLeaderboardLoading] = useState(false)
  const [leaderboard, setLeaderboard] = useState<RegressionRunLeaderboard | null>(null)

  const [diffLoading, setDiffLoading] = useState(false)
  const [diff, setDiff] = useState<RagasRegressionRunDiffResponse | null>(null)

  // Run config (ablation knobs)
  const [retrievalOnly, setRetrievalOnly] = useState(true)
  const [metricKeys, setMetricKeys] = useState<string[]>(['faithfulness', 'response_relevancy'])
  const [maxCases, setMaxCases] = useState(50)
  const [skipEmptyContexts, setSkipEmptyContexts] = useState(true)

  const [topK, setTopK] = useState(20)
  const [scoreThreshold, setScoreThreshold] = useState(0.0)
  const [retrievalMode, setRetrievalMode] = useState('hybrid')
  const [alpha, setAlpha] = useState(0.6)
  const [enableWeightRerank, setEnableWeightRerank] = useState(true)
  const [vectorWeight, setVectorWeight] = useState(0.6)
  const [keywordWeight, setKeywordWeight] = useState(0.4)
  const [mmrLambda, setMmrLambda] = useState(0.7)
  const [enableReranker, setEnableReranker] = useState(false)
  const [rerankerProvider, setRerankerProvider] = useState('llm')
  const [rerankerTopN, setRerankerTopN] = useState(20)

  const diffJson = useMemo(() => prettyJson(diff ?? { hint: '选择 base/target runs 并生成 diff' }), [diff])
  const diffScore = diff?.diff_score ?? null

  const diffScoreFmt = useMemo(() => {
    const b = toNumber(diffScore?.base_score)
    const a = toNumber(diffScore?.target_score)
    const d = toNumber(diffScore?.delta)
    return {
      base: b == null ? '-' : b.toFixed(4),
      target: a == null ? '-' : a.toFixed(4),
      delta: d == null ? '-' : d.toFixed(4),
      usedKeys: Array.isArray(diffScore?.used_metric_keys) ? diffScore.used_metric_keys.map(String) : [],
    }
  }, [diffScore])

  const runsByDataset = useMemo(() => {
    const ds = datasetId.trim()
    if (!ds) return runs
    return (runs || []).filter((r) => String(r?.dataset_id || '') === ds)
  }, [runs, datasetId])

  // Keep selection stable when dataset filter changes.
  useEffect(() => {
    if (!datasetId.trim()) return
    const items = runsByDataset || []
    const hasBase = items.some((r) => _stableId(r.id) === _stableId(selectedBaseRunId))
    const hasTarget = items.some((r) => _stableId(r.id) === _stableId(selectedTargetRunId))
    if (!hasBase) setSelectedBaseRunId(items?.[0]?.id || '')
    if (!hasTarget) setSelectedTargetRunId(items?.[0]?.id || '')
  }, [datasetId, runsByDataset, selectedBaseRunId, selectedTargetRunId])

  const loadDatasets = useCallback(async (): Promise<void> => {
    setDatasetsLoading(true)
    try {
      const res = await datasetApi.list({ limit: 200 })
      const items = Array.isArray(res.items) ? res.items : []
      setDatasets(items)
      setDatasetId((prev) => prev || items?.[0]?.id || '')
    } catch (err) {
      toast.error(formatApiError(err, '加载数据集失败'))
    } finally {
      setDatasetsLoading(false)
    }
  }, [])

  const refreshRuns = useCallback(async (): Promise<void> => {
    setRunsLoading(true)
    try {
      const res = await evaluationApi.listRegressionRuns({ limit: 80 })
      const items = Array.isArray(res.items) ? (res.items) : []
      setRuns(items)
      setSelectedBaseRunId((prev) => prev || items?.[0]?.id || '')
      setSelectedTargetRunId((prev) => prev || items?.[0]?.id || '')
    } catch (err) {
      toast.error(formatApiError(err, '拉取 runs 失败'))
    } finally {
      setRunsLoading(false)
    }
  }, [])

  async function refreshLeaderboard(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error('请选择 dataset')
      return
    }
    setLeaderboardLoading(true)
    try {
      const res = await evaluationApi.getRegressionRunLeaderboard({
        dataset_id: ds,
        metric_key: leaderboardMetricKey,
        limit: 50,
        include_incomplete: false,
      })
      setLeaderboard(res)
    } catch (err) {
      toast.error(formatApiError(err, '拉取 leaderboard 失败'))
    } finally {
      setLeaderboardLoading(false)
    }
  }

  function buildRegressionRunPayload(variant: Partial<RegressionRunCreate> = {}): RegressionRunCreate | null {
    const ds = datasetId.trim()
    if (!ds) {
      return null
    }
    const basePayload: RegressionRunCreate = {
      dataset_id: ds,
      metrics: retrievalOnly ? [] : metricKeys,
      skip_empty_contexts: Boolean(skipEmptyContexts),
      max_cases: Math.max(1, Math.min(maxCases, 500)),
      top_k: Math.max(1, Math.min(topK, 50)),
      score_threshold: Math.max(0, Math.min(scoreThreshold, 1)),
      retrieval_mode: retrievalMode,
      alpha: Math.max(0, Math.min(alpha, 1)),
      enable_weight_rerank: Boolean(enableWeightRerank),
      vector_weight: Math.max(0, Math.min(vectorWeight, 1)),
      keyword_weight: Math.max(0, Math.min(keywordWeight, 1)),
      mmr_lambda: Math.max(0, Math.min(mmrLambda, 1)),
      enable_reranker: Boolean(enableReranker),
      reranker_provider: String(rerankerProvider || 'llm'),
      reranker_top_n: Math.max(1, Math.min(rerankerTopN, 200)),
    }
    return {
      ...basePayload,
      ...variant,
      dataset_id: ds,
    }
  }

  async function runAblation(): Promise<void> {
    const payload = buildRegressionRunPayload()
    if (!payload) {
      toast.error('请选择 dataset')
      return
    }

    try {
      const run = await evaluationApi.createRegressionRun(payload)
      toast.success('已创建 regression run')
      await refreshRuns()
      setSelectedTargetRunId(run.id)
    } catch (err) {
      toast.error(formatApiError(err, '创建 regression run 失败'))
    }
  }

  async function runGridBatch(grid: Record<string, RegressionAblationGridValue[]>, maxCombinations: number): Promise<void> {
    const payload = buildRegressionRunPayload()
    if (!payload) {
      toast.error('请选择 dataset')
      return
    }
    try {
      const batch = await evaluationApi.createRegressionAblationBatch({
        ...payload,
        grid,
        max_combinations: maxCombinations,
      })
      if (batch.run_ids[0]) {
        setSelectedTargetRunId(batch.run_ids[0])
      }
      toast.success(`已提交 ${batch.total} 个 ablation runs`)
    } catch (err) {
      const message = formatApiError(err, '批量创建 ablation runs 失败')
      toast.error(message)
      throw new Error(message)
    }
  }

  async function computeDiff(): Promise<void> {
    const baseId = String(selectedBaseRunId || '').trim()
    const targetId = String(selectedTargetRunId || '').trim()
    if (!baseId || !targetId) {
      toast.error('请选择 base 与 target')
      return
    }
    if (baseId === targetId) {
      toast.error('base 与 target 不能相同')
      return
    }
    setDiffLoading(true)
    try {
      const res = await evaluationApi.diffRegressionRuns(targetId, {
        base_run_id: baseId,
        include_significance: true,
        include_per_case: true,
        max_case_diffs: 500,
      })
      setDiff(res)
      toast.success('已生成 diff')
    } catch (err) {
      toast.error(formatApiError(err, '生成 diff 失败'))
    } finally {
      setDiffLoading(false)
    }
  }

  async function exportDiffHtml(): Promise<void> {
    const baseId = String(selectedBaseRunId || '').trim()
    const targetId = String(selectedTargetRunId || '').trim()
    if (!baseId || !targetId) {
      toast.error('请选择 base 与 target')
      return
    }
    if (baseId === targetId) {
      toast.error('base 与 target 不能相同')
      return
    }

    try {
      const blob = await evaluationApi.exportRegressionRunDiffHtml(targetId, { base_run_id: baseId, redact: true })
      const name = sanitizeFilename(`regression-diff_${baseId.slice(0, 8)}_vs_${targetId.slice(0, 8)}.html`)
      downloadBlob(blob, name)
    } catch (err) {
      toast.error(formatApiError(err, '导出 HTML 失败'))
    }
  }

  async function exportRunBundle(runId: string, label: string): Promise<void> {
    const id = String(runId || '').trim()
    if (!id) {
      toast.error('请选择 run')
      return
    }

    try {
      const blob = await evaluationApi.exportRegressionRunBundle(id, {
        include_text: false,
        include_contexts: false,
        download: true,
      })
      const name = sanitizeFilename(`regression-run_${label}_${id.slice(0, 8)}.json`)
      downloadBlob(blob, name)
    } catch (err) {
      toast.error(formatApiError(err, '导出 run bundle 失败'))
    }
  }

  useEffect(() => {
    detachPromise(loadDatasets())
    detachPromise(refreshRuns())
  }, [loadDatasets, refreshRuns])

  const leaderboardItems = leaderboard?.items
  const leaderboardRows: RegressionLeaderboardRow[] = Array.isArray(leaderboardItems) ? leaderboardItems : []
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === datasetId) || null,
    [datasetId, datasets]
  )
  const selectedBaseRun = useMemo(
    () => runsByDataset.find((run) => _stableId(run.id) === _stableId(selectedBaseRunId)) || null,
    [runsByDataset, selectedBaseRunId]
  )
  const selectedTargetRun = useMemo(
    () => runsByDataset.find((run) => _stableId(run.id) === _stableId(selectedTargetRunId)) || null,
    [runsByDataset, selectedTargetRunId]
  )
  const deepDiveMetricKeys = useMemo(
    () => LEADERBOARD_METRIC_OPTIONS.map((item) => item.key),
    []
  )
  const completedRunsCount = useMemo(
    () => runsByDataset.filter((run) => String(run.status || '') === 'completed').length,
    [runsByDataset]
  )
  const diffDelta = toNumber(diffScore?.delta)
  const metricDiffRows = useMemo(
    () => (Array.isArray(diff?.metric_diffs) ? diff.metric_diffs : []),
    [diff]
  )
  const paramDiffRows = useMemo(() => {
    const base = toRecord(diff?.base_params)
    const target = toRecord(diff?.target_params)
    const keys = Array.from(new Set([...Object.keys(base), ...Object.keys(target)])).sort((a, b) => a.localeCompare(b))
    return keys.map((key) => {
      const before = compactValue(base[key])
      const after = compactValue(target[key])
      return { key, before, after, changed: before !== after }
    })
  }, [diff])
  return (
    <AppFrame showBackground={false} className="bg-slate-50">
      <div className="flex h-full min-h-0 flex-col bg-[linear-gradient(180deg,#f8fafc_0%,#ffffff_26%)]">
        <header className="shrink-0 border-b border-slate-200/80 bg-muted/30">
          <div className="px-6 py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl border border-sky-200/80 bg-card text-sky-700 shadow-sm">
                    <BarChart3 className="h-[18px] w-[18px] text-sky-600" />
                  </div>
                  <div className="min-w-0">
                    <h1 className="text-lg font-semibold tracking-[-0.01em] text-foreground">检索消融实验</h1>
                    <p className="mt-0.5 text-[13px] leading-6 text-muted-foreground">
                      围绕同一数据集调召回参数、查看排行榜，并对 baseline 与 candidate 做结构化 diff。
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2 rounded-xl border-sky-200/80 bg-card text-sky-700 hover:bg-sky-50"
                  disabled={datasetsLoading || runsLoading}
                  onClick={() => {
                    detachPromise(loadDatasets())
                    detachPromise(refreshRuns())
                  }}
                >
                  <RefreshCcw className="w-4 h-4" />
                  刷新
                </Button>
              </div>
            </div>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 overflow-hidden border-t border-slate-200/70">
          <aside className={cn(
            'shrink-0 border-r border-slate-200/80 bg-[linear-gradient(180deg,rgba(248,251,255,0.9)_0%,rgba(255,255,255,0.98)_100%)] transition-[width,opacity] duration-200',
            leftSidebarCollapsed ? 'w-0 overflow-hidden opacity-0 border-r-0' : 'w-[304px] opacity-100',
            'min-h-0 flex flex-col'
          )}>
            <div className="shrink-0 border-b border-sky-100/90 bg-primary/[0.08] px-5 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">参数配置</div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 rounded-md border border-slate-200/80 bg-card px-2.5 text-[11px] text-muted-foreground hover:bg-slate-50 hover:text-foreground"
                  onClick={() => setLeftSidebarCollapsed(true)}
                >
                  收起侧栏
                </Button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain no-scrollbar">
              <AblationSection
                title="实验基线"
                description="固定数据集与主指标，确认本轮 ablation 的起点。"
                className="bg-card"
              >
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="ablation-dataset" className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                      当前数据集
                    </Label>
                    <Select value={datasetId} onValueChange={setDatasetId} disabled={datasetsLoading || !datasets.length}>
                      <SelectTrigger id="ablation-dataset" className="h-10 rounded-lg border-border/70 bg-card">
                        <SelectValue placeholder={datasetsLoading ? '加载中...' : '选择数据集'} />
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

                  <div className="flex flex-wrap items-center gap-1.5">
                    <AblationInlineStat label="数据集" value={selectedDataset ? '1' : '0'} tone="sky" />
                    <AblationInlineStat label="作用域 Runs" value={runsByDataset.length} tone="neutral" />
                    <AblationInlineStat label="主指标" value={leaderboardMetricLabel(leaderboardMetricKey)} tone="neutral" />
                  </div>
                </div>
              </AblationSection>

              <AblationSection
                title="评测模式"
                description="决定这轮只看检索，还是同时带上 RAGAS 指标。"
                className="bg-card"
              >
                <div className="space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-foreground">仅检索评测</div>
                      <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
                        关闭 RAGAS 指标，只保留检索相关 recall / mrr / ndcg 等指标。
                      </div>
                    </div>
                    <Switch checked={retrievalOnly} onCheckedChange={setRetrievalOnly} />
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
                            <span className="block text-sm font-medium text-foreground">{option.label}</span>
                            <span className="block text-[11px] leading-5 text-muted-foreground">{option.hint}</span>
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
                    <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">样本上限</Label>
                    <Input type="number" value={maxCases} min={1} max={500} onChange={(e) => setMaxCases(Number(e.target.value || 0))} className="h-9 rounded-lg border-border/70 bg-card" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">召回 Top K</Label>
                    <Input type="number" value={topK} min={1} max={50} onChange={(e) => setTopK(Number(e.target.value || 0))} className="h-9 rounded-lg border-border/70 bg-card" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">检索模式</Label>
                    <Select value={retrievalMode} onValueChange={setRetrievalMode}>
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
                    <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">分数阈值</Label>
                    <Input type="number" value={scoreThreshold} min={0} max={1} step={0.01} onChange={(e) => setScoreThreshold(Number(e.target.value || 0))} className="h-9 rounded-lg border-border/70 bg-card" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">混合权重 Alpha</Label>
                    <Input type="number" value={alpha} min={0} max={1} step={0.05} onChange={(e) => setAlpha(Number(e.target.value || 0))} className="h-9 rounded-lg border-border/70 bg-card" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">MMR Lambda</Label>
                    <Input type="number" value={mmrLambda} min={0} max={1} step={0.05} onChange={(e) => setMmrLambda(Number(e.target.value || 0))} className="h-9 rounded-lg border-border/70 bg-card" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">向量权重</Label>
                    <Input type="number" value={vectorWeight} min={0} max={1} step={0.05} onChange={(e) => setVectorWeight(Number(e.target.value || 0))} className="h-9 rounded-lg border-border/70 bg-card" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">关键词权重</Label>
                    <Input type="number" value={keywordWeight} min={0} max={1} step={0.05} onChange={(e) => setKeywordWeight(Number(e.target.value || 0))} className="h-9 rounded-lg border-border/70 bg-card" />
                  </div>
                </div>
              </AblationSection>

              <AblationSection
                title="重排与过滤"
                description="布尔开关与 reranker 参数。"
                className="bg-card"
              >
                <div className="space-y-3">
                  <label className="flex items-start gap-3 py-1.5">
                    <Checkbox checked={skipEmptyContexts} onCheckedChange={(value) => setSkipEmptyContexts(value === true)} />
                    <span className="space-y-1">
                      <span className="block text-sm font-medium text-foreground">跳过空上下文样本</span>
                      <span className="block text-[11px] leading-5 text-muted-foreground">过滤掉没有引用上下文的样本，减少空样本对分数的扰动。</span>
                    </span>
                  </label>

                  <label className="flex items-start gap-3 py-1.5">
                    <Checkbox checked={enableWeightRerank} onCheckedChange={(value) => setEnableWeightRerank(value === true)} />
                    <span className="space-y-1">
                      <span className="block text-sm font-medium text-foreground">启用权重重排</span>
                      <span className="block text-[11px] leading-5 text-muted-foreground">对 hybrid 结果做二次权重整合，观察 vector / keyword 配比的影响。</span>
                    </span>
                  </label>

                  <div className="border-t border-border/70 pt-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-foreground">重排器</div>
                        <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
                          需要时再开启重排器，把服务商与重排深度作为单独实验旋钮。
                        </div>
                      </div>
                      <Switch checked={enableReranker} onCheckedChange={setEnableReranker} />
                    </div>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">服务提供方</Label>
                        <Input value={rerankerProvider} onChange={(e) => setRerankerProvider(e.target.value)} className="h-9 rounded-lg border-border/70 bg-card" />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">重排 Top N</Label>
                        <Input type="number" value={rerankerTopN} min={1} max={200} onChange={(e) => setRerankerTopN(Number(e.target.value || 0))} className="h-9 rounded-lg border-border/70 bg-card" />
                      </div>
                    </div>
                  </div>
                </div>
              </AblationSection>
            </div>

            <div className="shrink-0 border-t border-sky-100/90 bg-primary/[0.06] px-5 py-3.5 shadow-none">
              <div className="text-[11px] tracking-[0.08em] text-muted-foreground">运行入口</div>
              <Button className="mt-2 h-10 w-full gap-2 rounded-lg bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--info)))] text-primary-foreground shadow-[0_8px_24px_hsl(var(--primary)/0.24)] hover:opacity-90" onClick={() => detachPromise(runAblation())}>
                <PlayCircle className="h-4 w-4" />
                运行消融实验
              </Button>
            </div>
          </aside>

          <div className="relative min-w-0 flex min-h-0 flex-1 overflow-hidden">
            {leftSidebarCollapsed ? (
              <button
                type="button"
                className="focus-ring absolute left-0 top-3 z-20 -translate-x-1/2 rounded-full border border-border/70 bg-card p-1 text-muted-foreground shadow-sm transition-colors hover:bg-slate-50 hover:text-foreground"
                onClick={() => setLeftSidebarCollapsed(false)}
                aria-label="展开参数配置栏"
                title="展开参数配置栏"
              >
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            ) : null}
            <section
              className={cn(
                'shrink-0 border-r border-border/70 bg-card transition-[width,opacity] duration-200',
                leaderboardCollapsed ? 'w-0 overflow-hidden opacity-0 border-r-0 pointer-events-none' : 'w-[340px] opacity-100 xl:w-[360px]'
              )}
            >
              <div className="flex h-full min-h-0 flex-col">
                <div className="flex min-h-[56px] items-start justify-between gap-3 border-b border-border/70 bg-card px-5 py-2.5">
                  <div className="min-w-0">
                    <div className="text-[11px] font-medium tracking-[0.08em] text-foreground/80">Leaderboard</div>
                    <div className="truncate text-sm font-semibold text-foreground">实验排行榜</div>
                    <div className="mt-0.5 inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-slate-50/80 px-2 py-0.5 text-[11px] text-muted-foreground">
                      <span>可对比运行</span>
                      <span className="font-mono tabular-nums text-[11px] font-medium text-foreground">{runsByDataset.length}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Trophy className="h-4 w-4 text-primary" />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 rounded-md px-2.5 text-[11px] text-muted-foreground hover:bg-slate-100 hover:text-foreground"
                      onClick={() => setLeaderboardCollapsed(true)}
                    >
                      收起
                    </Button>
                  </div>
                </div>

                <div className="border-b border-border/70 bg-card px-5 py-3">
                  <div className="space-y-2">
                    <div className="flex items-end gap-2">
                      <div className="min-w-0 flex-1 space-y-1">
                        <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">排行榜主指标</Label>
                        <Select value={leaderboardMetricKey} onValueChange={setLeaderboardMetricKey}>
                          <SelectTrigger className="h-8 rounded-lg border-border/70 bg-card text-xs">
                            <SelectValue placeholder="选择指标" />
                          </SelectTrigger>
                          <SelectContent>
                            {LEADERBOARD_METRIC_OPTIONS.map((metric) => (
                              <SelectItem key={metric.key} value={metric.key}>
                                {metric.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      <Button
                        variant="outline"
                        className="h-8 gap-1.5 rounded-lg border-border/70 bg-card text-foreground hover:bg-slate-50 px-3 text-xs"
                        disabled={leaderboardLoading}
                        onClick={() => detachPromise(refreshLeaderboard())}
                      >
                        <RefreshCcw className="h-3.5 w-3.5" />
                        刷新
                      </Button>
                    </div>

                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] tracking-[0.08em] text-muted-foreground">点击行写入</span>
                      <div className="inline-flex rounded-lg border border-border/70 bg-card p-0.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)]">
                        <button
                          type="button"
                          className={cn(
                            'h-7 rounded-md px-2.5 text-[11px] font-medium',
                            leaderboardAssignRole === 'base' ? 'bg-foreground text-background shadow-sm' : 'text-muted-foreground hover:bg-slate-100'
                          )}
                          onClick={() => setLeaderboardAssignRole('base')}
                        >
                          BASE
                        </button>
                        <button
                          type="button"
                          className={cn(
                            'h-7 rounded-md px-2.5 text-[11px] font-medium',
                            leaderboardAssignRole === 'target' ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:bg-slate-100'
                          )}
                          onClick={() => setLeaderboardAssignRole('target')}
                        >
                          TARGET
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
                      const isBase = _stableId(runId) === _stableId(selectedBaseRunId)
                      const isTarget = _stableId(runId) === _stableId(selectedTargetRunId)
                      return (
                        <button
                          key={runId}
                          type="button"
                          className={cn(
                            'w-full border-b border-border/60 bg-card px-5 py-2.5 text-left transition-colors hover:bg-slate-50/70',
                            isBase || isTarget ? 'border-l-2 border-l-sky-500 bg-sky-50/75' : ''
                          )}
                          onClick={() => {
                            if (leaderboardAssignRole === 'base') setSelectedBaseRunId(runId)
                            else setSelectedTargetRunId(runId)
                          }}
                        >
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-mono text-[12px] text-foreground">{shortId(runId)}</span>
                              <StatusBadge status={badge.status} label={badge.label} dense />
                              {isBase ? <span className="rounded-full bg-foreground px-1.5 py-0.5 text-[9px] font-medium text-background">BASE</span> : null}
                              {isTarget ? <span className="rounded-full bg-primary/12 px-1.5 py-0.5 text-[9px] font-medium text-primary">TARGET</span> : null}
                            </div>
                            <div className="mt-1.5 text-[13px] font-semibold tabular-nums text-foreground">
                              {formatMetric(metricValue)}
                            </div>
                            <div className="mt-1 font-mono text-[11px] leading-4 text-muted-foreground">
                              {String(row.retrieval_config_hash || 'no-config-hash')}
                            </div>
                          </div>
                        </button>
                      )
                    })
                  ) : (
                    <div className="px-5 py-10 text-center">
                      <div className="text-sm font-medium text-foreground">还没有排行榜数据</div>
                      <div className="mt-2 text-[12px] leading-6 text-muted-foreground">
                        固定 dataset 后刷新一次 leaderboard，这里会显示每条 run 的主指标与配置哈希。
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </section>

            <section className="relative min-w-0 flex-1 bg-card">
              {leaderboardCollapsed ? (
                <button
                  type="button"
                  className={cn(
                    'focus-ring absolute left-0 z-20 -translate-x-1/2 rounded-full border border-border/70 bg-card p-1 text-muted-foreground shadow-sm transition-colors hover:bg-slate-50 hover:text-foreground',
                    leftSidebarCollapsed ? 'top-12' : 'top-3'
                  )}
                  onClick={() => setLeaderboardCollapsed(false)}
                  aria-label="展开排行榜"
                  title="展开排行榜"
                >
                  <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              ) : null}
              <div className="flex h-full min-h-0 flex-col">
                <div className="flex h-12 items-center justify-between gap-3 border-b border-border/70 bg-card px-5">
                  <div className="min-w-0">
                    <div className="text-[11px] tracking-[0.12em] text-muted-foreground">Diff Workspace</div>
                    <div className="truncate text-sm font-semibold text-foreground">基线 vs 候选</div>
                  </div>
                  <div className="flex items-center gap-1.5 text-[11px]">
                    <span className="text-muted-foreground">Diff Delta</span>
                    <span className={cn(
                      'font-mono font-semibold',
                      diffDelta !== null && diffDelta > 0 ? 'text-emerald-600' : diffDelta !== null && diffDelta < 0 ? 'text-rose-600' : 'text-foreground'
                    )}>
                      {diffDelta === null ? '-' : diffDelta.toFixed(4)}
                    </span>
                  </div>
                </div>

                <div className="border-b border-border/70 bg-card px-5 py-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">基线 Run</Label>
                      <Select value={selectedBaseRunId} onValueChange={setSelectedBaseRunId} disabled={runsLoading}>
                        <SelectTrigger className="h-9 rounded-lg border-border/70 bg-card">
                          <SelectValue placeholder={runsLoading ? '加载中...' : '选择 baseline'} />
                        </SelectTrigger>
                        <SelectContent>
                          {runsByDataset.map((run) => (
                            <SelectItem key={run.id} value={run.id}>
                              {shortId(String(run.id))} · {String(run.status || 'unknown')}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px] tracking-[0.08em] text-muted-foreground">候选 Run</Label>
                      <Select value={selectedTargetRunId} onValueChange={setSelectedTargetRunId} disabled={runsLoading}>
                        <SelectTrigger className="h-9 rounded-lg border-border/70 bg-card">
                          <SelectValue placeholder={runsLoading ? '加载中...' : '选择 candidate'} />
                        </SelectTrigger>
                        <SelectContent>
                          {runsByDataset.map((run) => (
                            <SelectItem key={run.id} value={run.id}>
                              {shortId(String(run.id))} · {String(run.status || 'unknown')}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="mt-2.5 flex items-center justify-between">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <AblationInlineStat label="Base" value={shortId(selectedBaseRun?.id ? String(selectedBaseRun.id) : '')} tone="sky" />
                      <AblationInlineStat label="Target" value={shortId(selectedTargetRun?.id ? String(selectedTargetRun.id) : '')} tone="neutral" />
                      <AblationInlineStat label="Delta" value={diffDelta === null ? '-' : diffDelta.toFixed(4)} tone={diffDelta !== null && diffDelta > 0 ? 'emerald' : diffDelta !== null && diffDelta < 0 ? 'amber' : 'neutral'} />
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Button className="h-9 gap-1.5 rounded-lg bg-primary px-3 text-xs text-primary-foreground shadow-[0_8px_20px_hsl(var(--primary)/0.22)] hover:bg-primary/90" disabled={diffLoading} onClick={() => detachPromise(computeDiff())}>
                        <GitCompare className="h-3.5 w-3.5" />
                        生成 Diff
                      </Button>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="outline" className="h-9 gap-1.5 rounded-lg border-border/70 bg-card text-foreground hover:bg-slate-50 px-2.5 text-xs">
                            导出
                            <MoreHorizontal className="h-3.5 w-3.5" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-40">
                          <DropdownMenuItem disabled={!selectedBaseRunId} onSelect={() => detachPromise(exportRunBundle(selectedBaseRunId, 'base'))}>
                            导出 base
                          </DropdownMenuItem>
                          <DropdownMenuItem disabled={!selectedTargetRunId} onSelect={() => detachPromise(exportRunBundle(selectedTargetRunId, 'target'))}>
                            导出 target
                          </DropdownMenuItem>
                          <DropdownMenuItem disabled={!diff} onSelect={() => downloadJson(diff, sanitizeFilename('regression-run-diff.json'))}>
                            导出 JSON
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => detachPromise(exportDiffHtml())}>
                            导出 HTML
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>
                </div>

                <Tabs defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
                  <div className="border-b border-border/70 px-5">
                    <TabsList className="h-10 justify-start gap-5 rounded-none border-none bg-transparent p-0">
                      <TabsTrigger value="overview" className="h-10 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-primary data-[state=active]:bg-transparent">
                        概览
                      </TabsTrigger>
                      <TabsTrigger value="config" className="h-10 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-primary data-[state=active]:bg-transparent">
                        配置差异
                      </TabsTrigger>
                      <TabsTrigger value="deep-dive" className="h-10 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-primary data-[state=active]:bg-transparent">
                        深度分析
                      </TabsTrigger>
                      <TabsTrigger value="raw" className="h-10 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-primary data-[state=active]:bg-transparent">
                        原始 JSON
                      </TabsTrigger>
                    </TabsList>
                  </div>

                  <TabsContent value="overview" className="mt-0 min-h-0 flex-1 overflow-auto">
                    {!diff ? (
                      <div className="px-5 py-10 text-center">
                        <div className="text-sm font-medium text-foreground">等待生成 diff</div>
                        <div className="mt-2 text-[12px] text-muted-foreground">
                          先从中间排行榜选中 base/target，或在上方下拉中手动指定，然后点击“生成 Diff”。
                        </div>
                      </div>
                    ) : (
                      <div className="px-5 py-3">
                        <div className="overflow-hidden border border-border/70">
                          <div className="grid border-b border-border/70 sm:grid-cols-3">
                            <div className="bg-card px-3 py-2.5 sm:border-r sm:border-border/70">
                              <div className="text-[11px] tracking-[0.08em] text-muted-foreground">Base Score</div>
                              <div className="mt-1 font-mono text-[13px] font-semibold text-foreground">{diffScoreFmt.base}</div>
                            </div>
                            <div className="bg-card px-3 py-2.5 sm:border-r sm:border-border/70">
                              <div className="text-[11px] tracking-[0.08em] text-muted-foreground">Target Score</div>
                              <div className="mt-1 font-mono text-[13px] font-semibold text-foreground">{diffScoreFmt.target}</div>
                            </div>
                            <div className="bg-card px-3 py-2.5">
                              <div className="text-[11px] tracking-[0.08em] text-muted-foreground">Delta</div>
                              <div className={cn(
                                'mt-1 font-mono text-[13px] font-semibold',
                                diffDelta !== null && diffDelta > 0 ? 'text-emerald-600' : diffDelta !== null && diffDelta < 0 ? 'text-rose-600' : 'text-foreground'
                              )}>
                                {diffScoreFmt.delta}
                              </div>
                            </div>
                          </div>

                          <div className="grid grid-cols-[minmax(120px,1fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)] border-b border-border/70 bg-card px-3 py-2 text-[11px] tracking-[0.08em] text-muted-foreground">
                            <div>Metric</div>
                            <div className="text-right">Before</div>
                            <div className="text-right">After</div>
                            <div className="text-right">Delta</div>
                          </div>
                          {metricDiffRows.length ? (
                            metricDiffRows.map((row) => {
                              const delta = toNumber(row.delta)
                              return (
                                <div key={row.key} className="grid grid-cols-[minmax(120px,1fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)_minmax(88px,0.8fr)] border-b border-border/60 px-3 py-2 text-xs last:border-b-0">
                                  <div className="truncate font-mono text-[11px] text-foreground">{row.key}</div>
                                  <div className="text-right font-mono text-[11px] text-muted-foreground">{compactValue(row.before, 24)}</div>
                                  <div className="text-right font-mono text-[11px] text-muted-foreground">{compactValue(row.after, 24)}</div>
                                  <div className={cn(
                                    'text-right font-mono text-[11px]',
                                    delta !== null && delta > 0 ? 'text-emerald-600' : delta !== null && delta < 0 ? 'text-rose-600' : 'text-foreground'
                                  )}>
                                    {delta === null ? compactValue(row.delta, 24) : delta.toFixed(4)}
                                  </div>
                                </div>
                              )
                            })
                          ) : (
                            <div className="px-3 py-4 text-xs text-muted-foreground">没有可展示的 metric_diffs。</div>
                          )}
                        </div>
                      </div>
                    )}
                  </TabsContent>

                  <TabsContent value="config" className="mt-0 min-h-0 flex-1 overflow-auto">
                    {!diff ? (
                      <div className="px-5 py-10 text-center text-[12px] text-muted-foreground">生成 diff 后可查看参数差异。</div>
                    ) : (
                      <div className="mx-5 my-3 overflow-hidden border border-border/70">
                        <div className="grid grid-cols-[minmax(140px,180px)_minmax(0,1fr)_minmax(0,1fr)] border-b border-border/70 bg-card px-3 py-2 text-[11px] tracking-[0.08em] text-muted-foreground">
                          <div>参数</div>
                          <div>Base</div>
                          <div>Target</div>
                        </div>
                        {paramDiffRows.length ? (
                          paramDiffRows.map((row) => (
                            <div
                              key={row.key}
                              className="grid grid-cols-[minmax(140px,180px)_minmax(0,1fr)_minmax(0,1fr)] border-b border-border/60 bg-card px-3 py-2 text-xs last:border-b-0"
                            >
                              <div className={cn('truncate font-mono text-[11px]', row.changed ? 'font-semibold text-foreground' : 'text-foreground')}>{row.key}</div>
                              <div className="truncate font-mono text-[11px] text-muted-foreground">{row.before}</div>
                              <div className={cn('truncate font-mono text-[11px]', row.changed ? 'text-foreground' : 'text-muted-foreground')}>{row.after}</div>
                            </div>
                          ))
                        ) : (
                          <div className="px-3 py-4 text-xs text-muted-foreground">没有可展示的参数差异。</div>
                        )}
                      </div>
                    )}
                  </TabsContent>

                  <TabsContent value="deep-dive" className="mt-0 min-h-0 flex-1 overflow-auto bg-slate-50/70">
                    <div className="space-y-4 px-5 py-4">
                      <AblationGridPanel
                        disabled={!datasetId.trim()}
                        onRunGrid={runGridBatch}
                        onBatchComplete={async () => {
                          await refreshRuns()
                          await refreshLeaderboard()
                        }}
                      />
                      <AblationStatisticsPanel diff={diff} />
                      <AblationComparisonMatrix
                        runs={runsByDataset}
                        baseRunId={selectedBaseRunId}
                        metricKeys={deepDiveMetricKeys}
                      />
                      <div className="grid gap-4 xl:grid-cols-2">
                        <AblationParetoPanel runs={runsByDataset} metricKey={leaderboardMetricKey} />
                        <AblationParameterImpactPanel runs={runsByDataset} metricKey={leaderboardMetricKey} />
                      </div>
                      <AblationSliceDiffPanel diff={diff} />
                      <AblationCaseDrilldown
                        baseRunId={selectedBaseRunId}
                        targetRunId={selectedTargetRunId}
                        metricKeys={deepDiveMetricKeys}
                        caseDiffs={diff?.case_diffs ?? []}
                      />
                    </div>
                  </TabsContent>

                  <TabsContent value="raw" className="mt-0 min-h-0 flex-1 overflow-hidden">
                    <div className="flex h-full min-h-0 flex-col">
                      <div className="flex items-center justify-between border-b border-border/70 px-5 py-2.5">
                        <div className="text-[11px] tracking-[0.12em] text-muted-foreground">Diff Payload</div>
                        <Database className="h-4 w-4 text-primary" />
                      </div>
                      <JsonCodeViewer code={diffJson} />
                    </div>
                  </TabsContent>
                </Tabs>
              </div>
            </section>
          </div>
        </div>
      </div>
    </AppFrame>
  )
}
