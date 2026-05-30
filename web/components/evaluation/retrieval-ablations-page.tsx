'use client'

import { useQuery } from '@tanstack/react-query'
import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  BarChart3,
  Bell,
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
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { queryKeys } from '@/lib/query-keys'
import {
  normalizeRerankerProvider,
  RERANKER_PROVIDER_OPTIONS,
} from '@/lib/reranker-provider-options'
import { sanitizeFilename } from '@/lib/sanitize'
import type {
  Dataset,
  RegressionAblationGridValue,
  RegressionRun,
  RegressionRunCreate,
} from '@/types'
import { cn, detachPromise } from '@/lib/utils'

const RETRIEVAL_ABLATION_DATASET_PARAMS = { limit: 200 } as const
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
  const text = String(value || '').trim()
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
            className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-sky-50 hover:text-sky-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
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
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]',
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
        'border-b border-slate-200/70 bg-card px-4 py-3 last:border-b-0',
        className
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-slate-950">
            {title}
          </div>
          {!collapsed && description ? (
            <p className="mt-1 text-[12px] leading-5 text-slate-500">
              {description}
            </p>
          ) : null}
        </div>
        {collapsible ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0 rounded-lg border border-slate-200 bg-card text-slate-500 hover:bg-slate-50 hover:text-slate-900"
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
      {!collapsed ? <div className="mt-3">{children}</div> : null}
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
    <div className="rounded-xl border border-slate-200 bg-card p-3 shadow-[0_8px_24px_rgba(15,23,42,0.05)]">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 ring-1 ring-blue-100">
          <Database className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div className="truncate text-[13px] font-semibold text-slate-950">
              {dataset?.name || '未选择数据集'}
            </div>
            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
              {dataset ? '固定' : '待选择'}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
            <span>ID: {shortId(dataset?.id)}</span>
            <span>版本: {version}</span>
          </div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
          {datasetPermissionLabel(dataset?.permission)}
        </span>
        <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700">
          主指标 {leaderboardMetricLabel(metricKey)}
        </span>
      </div>
    </div>
  )
}

function AblationLeaderboardEmptyState() {
  return (
    <div className="flex min-h-[530px] flex-col items-center justify-center px-8 text-center">
      <div className="ablation-empty-illustration relative h-40 w-56">
        <div className="absolute left-4 top-10 h-24 w-36 -rotate-6 rounded-2xl border border-blue-100 bg-card shadow-[0_16px_42px_rgba(37,99,235,0.12)]" />
        <div className="absolute left-11 top-16 h-2 w-20 rounded-full bg-slate-200" />
        <div className="absolute left-11 top-[108px] h-2 w-14 rounded-full bg-slate-100" />
        <div className="absolute left-24 top-24 h-8 w-3 rounded bg-blue-300" />
        <div className="absolute left-32 top-[72px] h-14 w-3 rounded bg-blue-500" />
        <div className="absolute left-40 top-12 h-20 w-3 rounded bg-blue-600" />
        <div className="absolute bottom-8 left-12 h-8 w-12 rounded bg-slate-200 shadow-sm" />
        <div className="absolute bottom-8 left-24 h-14 w-12 rounded bg-blue-500 shadow-[0_14px_30px_rgba(37,99,235,0.22)]" />
        <div className="absolute bottom-8 left-36 h-10 w-12 rounded bg-slate-200 shadow-sm" />
        <div className="absolute right-9 top-11 flex h-20 w-20 items-center justify-center rounded-full bg-amber-400 text-info-foreground shadow-[0_18px_44px_rgba(245,158,11,0.32)]">
          <Trophy className="h-10 w-10 fill-white/70" aria-hidden="true" />
        </div>
      </div>
      <div className="mt-2 text-[16px] font-semibold text-slate-950">
        暂无排行数据
      </div>
      <p className="mt-2 max-w-[260px] text-[13px] leading-6 text-slate-500">
        固定数据集后运行一次排行统计，这里会显示每条运行记录的主指标与配置得分。
      </p>
      <div className="mt-7 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-[12px] text-blue-700">
        排行榜数据将在固定数据集运行后自动生成
      </div>
    </div>
  )
}

function AblationDiffEmptyState() {
  const steps = [
    { label: '选择基线运行', hint: '选择作为基准的实验运行结果。' },
    { label: '选择候选运行', hint: '选择需要对比的实验运行结果。' },
    { label: '生成差异对比', hint: '点击“生成差异对比”查看配置差异与指标变化。' },
  ]

  return (
    <div className="flex min-h-[530px] flex-col items-center justify-center px-6 py-8 text-center">
      <div className="ablation-empty-illustration relative h-36 w-[360px]">
        <div className="absolute left-10 top-8 h-20 w-32 rounded-xl border border-blue-100 bg-card shadow-[0_16px_42px_rgba(37,99,235,0.10)]">
          <div className="border-b border-blue-50 px-3 py-2 text-left text-[10px] font-semibold text-blue-700">
            基线
          </div>
          <div className="space-y-2 px-3 py-3">
            <div className="h-2 rounded bg-slate-100" />
            <div className="h-2 w-20 rounded bg-slate-100" />
          </div>
        </div>
        <div className="absolute right-10 top-8 h-20 w-32 rounded-xl border border-emerald-100 bg-emerald-50/35 shadow-[0_16px_42px_rgba(16,185,129,0.10)]">
          <div className="border-b border-emerald-100 px-3 py-2 text-left text-[10px] font-semibold text-emerald-700">
            候选
          </div>
          <div className="space-y-2 px-3 py-3">
            <div className="h-2 rounded bg-slate-100" />
            <div className="h-2 w-20 rounded bg-slate-100" />
          </div>
        </div>
        <div className="absolute left-1/2 top-12 flex h-16 w-16 -translate-x-1/2 items-center justify-center rounded-full bg-card text-blue-600 shadow-[0_16px_42px_rgba(37,99,235,0.16)] ring-1 ring-blue-100">
          <GitCompare className="h-7 w-7" aria-hidden="true" />
        </div>
        <div className="absolute left-[88px] top-3 h-8 w-[184px] rounded-t-2xl border-x border-t border-dashed border-emerald-300" />
      </div>
      <div className="mt-3 text-[16px] font-semibold text-slate-950">
        等待生成差异对比
      </div>
      <p className="mt-2 max-w-[430px] text-[13px] leading-6 text-slate-500">
        请先选择基线运行与候选运行，然后点击“生成差异对比”。系统将对两次运行进行结构化对比，展示差异与影响分析。
      </p>
      <div className="mt-7 w-full max-w-[390px] rounded-2xl border border-dashed border-blue-200 bg-card/85 p-4 text-left">
        {steps.map((step, index) => (
          <div
            key={step.label}
            className="flex gap-3 py-2 first:pt-0 last:pb-0"
          >
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[11px] font-semibold text-info-foreground">
              {index + 1}
            </span>
            <span>
              <span className="block text-[13px] font-semibold text-slate-950">
                {step.label}
              </span>
              <span className="mt-0.5 block text-[12px] text-slate-500">
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

function splitCodeLines(value: string): string[] {
  const normalized = String(value ?? '').replaceAll('\r', '')
  const lines = normalized.split('\n')
  if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop()
  return lines.length ? lines : ['']
}

function tokenizeJsonLine(
  line: string
): Array<{ text: string; kind: JsonTokenKind }> {
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
    <div className="h-full min-h-0 overflow-auto bg-[linear-gradient(180deg,rgba(248,250,252,0.96)_0%,rgba(255,255,255,1)_40%)]">
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

export function RetrievalAblationsPage() {
  const [datasetId, setDatasetId] = useState('')

  const [selectedBaseRunId, setSelectedBaseRunId] = useState('')
  const [selectedTargetRunId, setSelectedTargetRunId] = useState('')
  const [leaderboardAssignRole, setLeaderboardAssignRole] = useState<
    'base' | 'target'
  >('target')
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false)
  const [leaderboardCollapsed, setLeaderboardCollapsed] = useState(false)

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

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.list(RETRIEVAL_ABLATION_DATASET_PARAMS),
    queryFn: () => datasetApi.list(RETRIEVAL_ABLATION_DATASET_PARAMS),
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
    () => (Array.isArray(datasetsQuery.data?.items) ? datasetsQuery.data?.items : EMPTY_DATASETS),
    [datasetsQuery.data?.items]
  )
  const runs = useMemo(
    () => (Array.isArray(runsQuery.data?.items) ? runsQuery.data?.items : EMPTY_RUNS),
    [runsQuery.data?.items]
  )
  const datasetsLoading = datasetsQuery.isLoading || datasetsQuery.isFetching
  const runsLoading = runsQuery.isLoading || runsQuery.isFetching
  const leaderboardLoading =
    leaderboardQuery.isLoading || leaderboardQuery.isFetching
  const diffLoading = diffQuery.isLoading || diffQuery.isFetching

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
    setDatasetId((prev) => prev || datasets?.[0]?.id || '')
  }, [datasets])

  function buildRegressionRunPayload(
    variant: Partial<RegressionRunCreate> = {}
  ): RegressionRunCreate | null {
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
      toast.error('请选择数据集')
      return
    }

    try {
      const run = await evaluationApi.createRegressionRun(payload)
      toast.success('已创建实验运行')
      await runsQuery.refetch()
      setSelectedTargetRunId(run.id)
    } catch (err) {
      toast.error(formatApiError(err, '创建实验运行失败'))
    }
  }

  async function runGridBatch(
    grid: Record<string, RegressionAblationGridValue[]>,
    maxCombinations: number
  ): Promise<void> {
    const payload = buildRegressionRunPayload()
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
        setSelectedTargetRunId(batch.run_ids[0])
      }
      await runsQuery.refetch()
      toast.success(`已提交 ${batch.total} 个消融实验运行`)
    } catch (err) {
      const message = formatApiError(err, '批量创建消融实验运行失败')
      toast.error(message)
      throw new Error(message)
    }
  }

  async function computeDiff(): Promise<void> {
    const baseId = String(selectedBaseRunId || '').trim()
    const targetId = String(selectedTargetRunId || '').trim()
    if (!baseId || !targetId) {
      toast.error('请选择基线与候选')
      return
    }
    if (baseId === targetId) {
      toast.error('基线与候选不能相同')
      return
    }
    try {
      const res = await diffQuery.refetch()
      if (res.error) return
      toast.success('已生成差异对比')
    } catch {}
  }

  async function exportDiffHtml(): Promise<void> {
    const baseId = String(selectedBaseRunId || '').trim()
    const targetId = String(selectedTargetRunId || '').trim()
    if (!baseId || !targetId) {
      toast.error('请选择基线与候选')
      return
    }
    if (baseId === targetId) {
      toast.error('基线与候选不能相同')
      return
    }

    try {
      const blob = await evaluationApi.exportRegressionRunDiffHtml(targetId, {
        base_run_id: baseId,
        redact: true,
      })
      const name = sanitizeFilename(
        `regression-diff_${baseId.slice(0, 8)}_vs_${targetId.slice(0, 8)}.html`
      )
      downloadBlob(blob, name)
    } catch (err) {
      toast.error(formatApiError(err, '导出对比页面失败'))
    }
  }

  async function exportRunBundle(runId: string, label: string): Promise<void> {
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
  const workspaceGridClassName = cn(
    'relative grid h-full min-h-[760px] gap-4',
    !leftSidebarCollapsed &&
      !leaderboardCollapsed &&
      'grid-cols-[390px_minmax(0,1fr)_360px]',
    leftSidebarCollapsed &&
      !leaderboardCollapsed &&
      'grid-cols-[minmax(0,1fr)_360px]',
    !leftSidebarCollapsed &&
      leaderboardCollapsed &&
      'grid-cols-[390px_minmax(0,1fr)]',
    leftSidebarCollapsed && leaderboardCollapsed && 'grid-cols-[minmax(0,1fr)]'
  )

  return (
    <AppFrame showBackground={false} className="bg-slate-50">
      <div className="flex h-[111.111%] w-[111.111%] origin-top-left scale-[0.9] flex-col bg-slate-50">
        <header className="shrink-0 border-b border-slate-200/80 bg-card/95 px-6 py-3.5">
          <PageHeader
            title="检索消融实验"
            description="围绕同一数据集调召回参数、查看实验排行，并对基线与候选做结构化差异对比。"
            iconImage="retrieval-ablation"
            icon={BarChart3}
            iconColor="text-info"
            badge="消融实验"
            compact
            className="p-0"
          >
              <div className="mr-14 flex shrink-0 items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="刷新消融实验数据"
                  className="h-9 w-9 rounded-xl border-slate-200 bg-card text-blue-700 hover:bg-blue-50"
                  disabled={datasetsLoading || runsLoading}
                  onClick={() => {
                    datasetsQuery.refetch()
                    runsQuery.refetch()
                  }}
                >
                  <RefreshCcw className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  aria-label="查看消融实验通知"
                  className="h-9 w-9 rounded-xl border-slate-200 bg-card text-slate-700 hover:bg-slate-50"
                >
                  <Bell className="h-4 w-4" />
                </Button>
              </div>
          </PageHeader>
        </header>

        <div className="min-h-0 flex-1 overflow-auto p-4">
          <div className={workspaceGridClassName}>
            {!leftSidebarCollapsed ? (
              <aside className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-card shadow-[0_8px_24px_rgba(15,23,42,0.05)]">
                <div className="shrink-0 border-b border-slate-200 bg-card px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[15px] font-semibold text-slate-950">
                      参数配置
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 rounded-lg border border-slate-200 bg-card px-2.5 text-[12px] text-slate-500 hover:bg-slate-50 hover:text-slate-900"
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
                          className="text-[12px] text-slate-500"
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
                            className="h-10 rounded-xl border-slate-200 bg-card text-[13px] shadow-[0_1px_2px_rgba(15,23,42,0.04)]"
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

                <div className="shrink-0 border-t border-sky-100/90 bg-sky-50/55 px-5 py-3.5 shadow-none">
                  <div className="text-[11px] tracking-[0.08em] text-muted-foreground">
                    运行入口
                  </div>
                  <Button
                    className="mt-2 h-10 w-full gap-2 rounded-lg border border-sky-200 bg-sky-50 text-sky-700 shadow-[0_8px_18px_rgba(14,116,144,0.10)] transition-colors hover:border-sky-300 hover:bg-sky-100 hover:text-sky-800"
                    onClick={() => detachPromise(runAblation())}
                  >
                    <PlayCircle className="h-4 w-4" />
                    运行消融实验
                  </Button>
                </div>
              </aside>
            ) : null}

            <div className="contents">
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
              {!leaderboardCollapsed ? (
                <section className="order-3 flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-card shadow-[0_8px_24px_rgba(15,23,42,0.05)]">
                  <div className="flex h-full min-h-0 flex-col">
                    <div className="flex min-h-[58px] items-center justify-between gap-3 border-b border-slate-200 bg-card px-4 py-3">
                      <div className="min-w-0">
                        <div className="truncate text-[15px] font-semibold text-slate-950">
                          实验排行
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Trophy className="h-4 w-4 text-primary" />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-8 rounded-lg px-2.5 text-[12px] text-slate-500 hover:bg-slate-50 hover:text-slate-900"
                          onClick={() => setLeaderboardCollapsed(true)}
                        >
                          收起
                        </Button>
                      </div>
                    </div>

                    <div className="border-b border-slate-200 bg-card px-4 py-3">
                      <div className="space-y-2">
                        <div className="flex items-end gap-2">
                          <div className="min-w-0 flex-1 space-y-1">
                            <Label className="text-[12px] text-slate-500">
                              排行榜主指标
                            </Label>
                            <Select
                              value={leaderboardMetricKey}
                              onValueChange={setLeaderboardMetricKey}
                            >
                              <SelectTrigger className="h-9 rounded-xl border-slate-200 bg-card text-[13px]">
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
                            className="h-9 gap-1.5 rounded-xl border-slate-200 bg-card px-3 text-[13px] text-slate-900 hover:bg-slate-50"
                            disabled={leaderboardLoading}
                            onClick={() => leaderboardQuery.refetch()}
                          >
                            <RefreshCcw className="h-3.5 w-3.5" />
                            刷新
                          </Button>
                        </div>

                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[12px] text-slate-500">
                            筛选运行
                          </span>
                          <div className="inline-flex rounded-lg border border-border/70 bg-card p-0.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.85)]">
                            <button
                              type="button"
                              className={cn(
                                'h-7 rounded-md px-2.5 text-[11px] font-medium',
                                leaderboardAssignRole === 'base'
                                  ? 'bg-info text-primary-foreground shadow-sm'
                                  : 'text-muted-foreground hover:bg-slate-100'
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
                                  : 'text-muted-foreground hover:bg-slate-100'
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
                                'w-full border-b border-border/60 bg-card px-5 py-2.5 text-left transition-colors hover:bg-slate-50/70',
                                isBase || isTarget
                                  ? 'border-l-2 border-l-sky-500 bg-sky-50/75'
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

              <section className="relative order-2 min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-card shadow-[0_8px_24px_rgba(15,23,42,0.05)]">
                {leaderboardCollapsed ? (
                  <button
                    type="button"
                    className={cn(
                      'focus-ring absolute right-0 z-20 translate-x-1/2 rounded-full border border-border/70 bg-card p-1 text-muted-foreground shadow-sm transition-colors hover:bg-slate-50 hover:text-foreground',
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
                  <div className="flex min-h-[58px] items-center justify-between gap-3 border-b border-slate-200 bg-card px-4 py-3">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <div className="truncate text-[15px] font-semibold text-slate-950">
                        差异对比工作区
                      </div>
                      <AblationInfoTooltip
                        label="查看运行记录选择说明"
                        side="bottom"
                      >
                        {runsSelectionHint}
                      </AblationInfoTooltip>
                    </div>
                    <div className="flex items-center gap-1.5 text-[11px]">
                      <span className="text-muted-foreground">指标变化</span>
                      <span
                        className={cn(
                          'font-mono font-semibold',
                          diffDelta !== null && diffDelta > 0
                            ? 'text-emerald-600'
                            : diffDelta !== null && diffDelta < 0
                              ? 'text-rose-600'
                              : 'text-foreground'
                        )}
                      >
                        {diffDelta === null ? '-' : diffDelta.toFixed(4)}
                      </span>
                    </div>
                  </div>

                  <div className="border-b border-slate-200 bg-card px-4 py-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <Label className="text-[12px] text-slate-500">
                          选择基线运行
                        </Label>
                        <Select
                          value={selectedBaseRunId}
                          onValueChange={setSelectedBaseRunId}
                          disabled={runsSelectDisabled}
                        >
                          <SelectTrigger className="h-10 rounded-xl border-slate-200 bg-card text-[13px]">
                            <SelectValue
                              placeholder={
                                runsLoading ? '加载中...' : '选择基线运行'
                              }
                            />
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
                        <Label className="text-[12px] text-slate-500">
                          选择候选运行
                        </Label>
                        <Select
                          value={selectedTargetRunId}
                          onValueChange={setSelectedTargetRunId}
                          disabled={runsSelectDisabled}
                        >
                          <SelectTrigger className="h-10 rounded-xl border-slate-200 bg-card text-[13px]">
                            <SelectValue
                              placeholder={
                                runsLoading ? '加载中...' : '选择候选运行'
                              }
                            />
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
                          value={shortId(
                            selectedBaseRun?.id
                              ? String(selectedBaseRun.id)
                              : ''
                          )}
                          tone="sky"
                        />
                        <AblationInlineStat
                          label="候选"
                          value={shortId(
                            selectedTargetRun?.id
                              ? String(selectedTargetRun.id)
                              : ''
                          )}
                          tone="neutral"
                        />
                        <AblationInlineStat
                          label="变化"
                          value={
                            diffDelta === null ? '-' : diffDelta.toFixed(4)
                          }
                          tone={
                            diffDelta !== null && diffDelta > 0
                              ? 'emerald'
                              : diffDelta !== null && diffDelta < 0
                                ? 'amber'
                                : 'neutral'
                          }
                        />
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Button
                          className="h-9 gap-1.5 rounded-xl bg-info px-4 text-[13px] text-primary-foreground shadow-[0_10px_24px_rgba(14,165,233,0.22)] hover:bg-info/90"
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
                              className="h-9 gap-1.5 rounded-xl border-slate-200 bg-card px-3 text-[13px] text-slate-900 hover:bg-slate-50"
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
                                  exportRunBundle(selectedBaseRunId, 'base')
                                )
                              }
                            >
                              导出基线
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              disabled={!selectedTargetRunId}
                              onSelect={() =>
                                detachPromise(
                                  exportRunBundle(selectedTargetRunId, 'target')
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

                  <Tabs
                    defaultValue="overview"
                    className="flex min-h-0 flex-1 flex-col"
                  >
                    <div className="border-b border-slate-200 px-4">
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
                      {!diff ? (
                        <AblationDiffEmptyState />
                      ) : (
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
                                    diffDelta !== null && diffDelta > 0
                                      ? 'text-emerald-600'
                                      : diffDelta !== null && diffDelta < 0
                                        ? 'text-rose-600'
                                        : 'text-foreground'
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
                              metricDiffRows.map((row) => {
                                const delta = toNumber(row.delta)
                                return (
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
                                    <div
                                      className={cn(
                                        'text-right font-mono text-[11px]',
                                        delta !== null && delta > 0
                                          ? 'text-emerald-600'
                                          : delta !== null && delta < 0
                                            ? 'text-rose-600'
                                            : 'text-foreground'
                                      )}
                                    >
                                      {delta === null
                                        ? compactValue(row.delta, 24)
                                        : delta.toFixed(4)}
                                    </div>
                                  </div>
                                )
                              })
                            ) : (
                              <div className="px-3 py-4 text-xs text-muted-foreground">
                                没有可展示的指标差异。
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </TabsContent>

                    <TabsContent
                      value="config"
                      className="mt-0 min-h-0 flex-1 overflow-auto"
                    >
                      {!diff ? (
                        <div className="px-5 py-10 text-center text-[12px] text-muted-foreground">
                          生成差异对比后可查看参数差异。
                        </div>
                      ) : (
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
                                    row.changed
                                      ? 'font-semibold text-foreground'
                                      : 'text-foreground'
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
                                    row.changed
                                      ? 'text-foreground'
                                      : 'text-muted-foreground'
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
                      )}
                    </TabsContent>

                    <TabsContent
                      value="deep-dive"
                      className="mt-0 min-h-0 flex-1 overflow-auto bg-slate-50/70"
                    >
                      <div className="space-y-4 px-5 py-4">
                        <AblationGridPanel
                          disabled={!datasetId.trim()}
                          onRunGrid={runGridBatch}
                          onBatchComplete={async () => {
                            await runsQuery.refetch()
                            await leaderboardQuery.refetch()
                          }}
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
                    </TabsContent>

                    <TabsContent
                      value="raw"
                      className="mt-0 min-h-0 flex-1 overflow-hidden"
                    >
                      <div className="flex h-full min-h-0 flex-col">
                        <div className="flex items-center justify-between border-b border-border/70 px-5 py-2.5">
                         <div className="text-[11px] tracking-[0.12em] text-muted-foreground">
                            对比数据
                          </div>
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
      </div>
    </AppFrame>
  )
}
