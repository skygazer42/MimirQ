'use client'

import { useQuery } from '@tanstack/react-query'
import { useCallback, useMemo, useState, type ReactNode } from 'react'
import {
  Activity,
  BarChart3,
  CheckCircle2,
  Clock,
  Copy,
  Cpu,
  Database,
  FileJson,
  Gauge,
  Hash,
  RefreshCcw,
  ShieldCheck,
  Timer,
  Zap,
  ChevronDown,
  Terminal,
  Eraser,
  Search,
  Settings2,
  LayoutGrid,
  ShieldAlert,
  Info,
  type LucideIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useBackendHealth } from '@/hooks/use-backend-health'
import { useBackendMetaDetails } from '@/hooks/use-backend-meta'
import { formatApiError } from '@/lib/api-errors'
import {
  datasetApi,
  documentApi,
  observabilityApi,
  ragApi,
  retrievalApi,
} from '@/lib/api'
import {
  buildRetrievalConfigHashRequest,
  hasDatasetRagContract,
} from '@/lib/dataset-rag-contract'
import { API_V1_BASE_URL } from '@/lib/env'
import { queryKeys } from '@/lib/query-keys'
import { buildRagPreviewDiagnosticsSummary } from '@/lib/rag-preview-diagnostics'
import { cn } from '@/lib/utils'
import type {
  Dataset,
  DepsDiagnosticsResponse,
  Document as KnowledgeDocument,
  DocumentList,
  JsonObject,
  OnlineQualitySummaryResponse,
  PromptPreviewResponse,
} from '@/types'

// --- Constants & Styles ---

const CARD_BASE =
  'bg-card rounded-2xl border border-border/60 shadow-[0_1px_3px_rgba(15,23,42,0.03)] p-4'
const SECTION_TITLE =
  'text-[14px] font-semibold text-foreground flex items-center gap-2 mb-4'
const FIELD_LABEL = 'text-[12px] font-medium text-muted-foreground mb-1.5 block'
const ALL_DOCUMENTS_VALUE = '__all_documents__'
const EMPTY_DATASETS: Dataset[] = []
const EMPTY_DOCUMENTS: KnowledgeDocument[] = []
const PENDING_RUN_LABEL = '待执行'
const MISSING_RESULT_LABEL = '未返回'

const DIAGNOSTIC_DIMENSIONS = [
  {
    id: 'retrieval_accuracy',
    icon: Search,
    title: '知识检索准确性',
    subtitle: '检索是否准确',
  },
  {
    id: 'retrieval_recall',
    icon: CheckCircle2,
    title: '检索召回率',
    subtitle: '内容是否充分',
  },
  {
    id: 'context_relevance',
    icon: LayoutGrid,
    title: '上下文相关性',
    subtitle: '上下文关联度',
  },
  {
    id: 'generation_quality',
    icon: Activity,
    title: '生成质量',
    subtitle: '回答质量评估',
  },
  {
    id: 'fact_consistency',
    icon: ShieldCheck,
    title: '事实一致性',
    subtitle: '事实是否一致',
  },
  {
    id: 'safety_compliance',
    icon: ShieldCheck,
    title: '安全合规性',
    subtitle: '内容安全合规',
  },
  {
    id: 'cost_analysis',
    icon: Cpu,
    title: '成本分析',
    subtitle: '成本与资源使用',
  },
  {
    id: 'execution_perf',
    icon: Gauge,
    title: '执行性能',
    subtitle: '延迟与吞吐量',
  },
] as const

type DiagnosticDimensionId = (typeof DIAGNOSTIC_DIMENSIONS)[number]['id']
type MetricTone = 'slate' | 'green' | 'amber' | 'red' | 'blue' | 'purple'
type BinaryStatusTone = Exclude<MetricTone, 'purple'>

// --- Helper Functions ---

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function isDiagnosticRecord(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function diagnosticField(source: unknown, key: string): unknown {
  return isDiagnosticRecord(source) ? source[key] : undefined
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

function pickMetricNumber(source: unknown, keys: string[]): number | null {
  if (!isDiagnosticRecord(source)) return null
  for (const k of keys) {
    const v = source[k]
    if (typeof v === 'number' && Number.isFinite(v)) return v
    if (typeof v === 'string' && Number.isFinite(Number(v))) return Number(v)
  }
  return null
}

function pickMetricNumberByPath(source: unknown, paths: string[]): number | null {
  if (!isDiagnosticRecord(source)) return null
  for (const path of paths) {
    let value: unknown = source
    for (const key of path.split('.')) {
      value = diagnosticField(value, key)
      if (value === undefined) break
    }
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && Number.isFinite(Number(value))) {
      return Number(value)
    }
  }
  return null
}

function fmtScore(v: number | null, d = 2) {
  return v === null ? PENDING_RUN_LABEL : v.toFixed(d)
}

function fmtMetric(v: number | null, d = 2, suffix = '') {
  if (v === null) return PENDING_RUN_LABEL
  return `${v.toFixed(d)}${suffix}`
}

function fmtExecutedMetric(v: number | null, d = 2, suffix = '') {
  if (v === null) return MISSING_RESULT_LABEL
  return `${v.toFixed(d)}${suffix}`
}

function fmtMetricOrMissing(
  hasResult: boolean,
  value: number | null,
  d = 2,
  suffix = ''
) {
  if (value !== null) return `${value.toFixed(d)}${suffix}`
  return hasResult ? MISSING_RESULT_LABEL : PENDING_RUN_LABEL
}

function fmtCountOrMissing(
  hasResult: boolean,
  value: number | null,
  suffix = ''
) {
  if (value !== null) return `${value.toLocaleString()}${suffix}`
  return hasResult ? MISSING_RESULT_LABEL : PENDING_RUN_LABEL
}

function isPendingMetricLabel(value: string) {
  return value === PENDING_RUN_LABEL || value === MISSING_RESULT_LABEL
}

function fmtDateTime(value?: string | null) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
    .format(date)
    .replaceAll('/', '-')
}

function metricTone(v: number | null): MetricTone {
  if (v === null) return 'slate'
  if (v >= 0.8) return 'green'
  if (v >= 0.6) return 'amber'
  return 'red'
}

function shortId(value?: string | null, size = 8) {
  if (!value) return '--'
  return value.length > size ? `${value.slice(0, size)}...` : value
}

function datasetLabel(dataset: Dataset) {
  return dataset.name || shortId(dataset.id)
}

function documentLabel(document: KnowledgeDocument) {
  return document.filename || shortId(document.id)
}

function getListItems<T>(
  source: { items?: T[] } | T[] | null | undefined,
  fallback: T[]
): T[] {
  if (Array.isArray(source)) return source
  if (source && typeof source === 'object' && Array.isArray(source.items)) {
    return source.items
  }
  return fallback
}

function metricSource(hasResult: boolean, source: string) {
  return hasResult ? source : '手动诊断'
}

function diagnosticString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  ) {
    return String(value)
  }
  return ''
}

function diagnosticRecordString(
  value: Record<string, unknown>,
  keys: string[]
): string {
  for (const key of keys) {
    const label = diagnosticString(value[key])
    if (label) return label
  }
  return ''
}

function firstDiagnosticString(...values: unknown[]): string {
  for (const value of values) {
    const label = diagnosticString(value)
    if (label) return label
  }
  return ''
}

function dependencyStatus(value: unknown): string {
  if (!value || typeof value !== 'object') return 'unknown'
  const record = value as Record<string, unknown>
  const status = diagnosticRecordString(record, [
    'status',
    'state',
    'value',
    'label',
  ]).toLowerCase()
  if (status) return status
  if (record.ok === true) return 'connected'
  if (record.ok === false) return 'disconnected'
  return 'unknown'
}

function driftResultLabel(
  snapshot: JsonObject | null,
  metric: number | null
) {
  if (!snapshot) return PENDING_RUN_LABEL
  if (metric === null) return MISSING_RESULT_LABEL
  return `${metric.toFixed(3)} 漂移率`
}

function perfGateResultStatus(result: JsonObject | null) {
  if (!result) return PENDING_RUN_LABEL
  return (
    diagnosticRecordString(result, ['status', 'gate_status', 'result']) ||
    '已运行'
  )
}

function perfGateResultTone(
  result: JsonObject | null,
  status: string
): MetricTone {
  if (/pass|passed|ok|success|通过|已运行/i.test(status)) return 'green'
  if (result) return 'amber'
  return 'slate'
}

function okTone(
  ok: boolean,
  successTone: BinaryStatusTone = 'green',
  failureTone: BinaryStatusTone = 'red'
): BinaryStatusTone {
  return ok ? successTone : failureTone
}

function serviceDependencyStatus(ok: boolean) {
  return ok ? 'connected' : 'disconnected'
}

function systemStatusSummary(
  healthOk: boolean,
  readyOk: boolean
): { label: string; tone: BinaryStatusTone } {
  if (healthOk && readyOk) {
    return { label: '正常', tone: 'green' }
  }
  return { label: '需要排查', tone: 'red' }
}

function selectedDocumentScopeLabel(
  selectedCount: number,
  loading: boolean,
  hasDataset: boolean
) {
  if (selectedCount > 0) return `已选 ${selectedCount} 个文档`
  if (loading) return '正在加载文档...'
  if (hasDataset) return '当前数据集全部文档'
  return '请先选择数据集'
}

function citationTone(count: number | null): MetricTone {
  if (count === null) return 'slate'
  if (count > 0) return 'green'
  return 'amber'
}

function citationStatusLabel(hasResult: boolean, count: number | null) {
  if (!hasResult) return PENDING_RUN_LABEL
  if (count === null) return MISSING_RESULT_LABEL
  return `${count.toLocaleString()} 条引用`
}

function executionPerfValue(
  latencyMs: number | null,
  perfStatus: string,
  hasPerfResult: boolean,
  hasProbeResult: boolean
) {
  if (latencyMs === null) {
    if (hasPerfResult) return perfStatus
    if (hasProbeResult) return MISSING_RESULT_LABEL
    return PENDING_RUN_LABEL
  }
  return fmtMetric(latencyMs, 0, 'ms')
}

function executionPerfSource(latencyMs: number | null, hasPerfResult: boolean) {
  if (latencyMs === null) {
    return hasPerfResult ? 'perf-suite' : PENDING_RUN_LABEL
  }
  return 'metrics'
}

function executionPerfTone(
  latencyMs: number | null,
  fallbackTone: MetricTone
): MetricTone {
  if (latencyMs === null) return fallbackTone
  if (latencyMs <= 1000) return 'green'
  if (latencyMs <= 3000) return 'amber'
  return 'red'
}

function diagnosticsRunState(hasResult: boolean) {
  return hasResult
    ? { status: 'completed', message: '诊断已执行完毕' }
    : { status: 'not_run', message: '诊断尚未执行，请配置后运行' }
}

function manualDiagnosticsStatus(
  running: boolean,
  hasDiagnostics: boolean
) {
  if (running) return '执行中'
  if (hasDiagnostics) return '已生成'
  return PENDING_RUN_LABEL
}

function runningStatusLabel(running: boolean, value: string, runningLabel = '执行中') {
  return running ? runningLabel : value
}

function healthStatusLabel(isPending: boolean, healthy: boolean) {
  if (isPending) return '检查中'
  return healthy ? '正常' : '异常'
}

function healthSummaryStatusLabel(isPending: boolean, value: string) {
  return isPending ? '检查中' : value
}

function readyStatusLabel(
  loading: boolean,
  snapshot: JsonObject | null | undefined,
  ready: boolean,
  readyLabel: string,
  errorLabel: string
) {
  if (loading && snapshot === null) return '检查中'
  return ready ? readyLabel : errorLabel
}

function onlineQualityStatusLabel(loading: boolean, enabled?: boolean) {
  if (loading) return '检查中'
  return enabled ? '已启用' : '未启用'
}

function datasetSelectLabel(
  loading: boolean,
  selectedDataset: Dataset | null
) {
  if (loading) return '正在加载数据集...'
  if (!selectedDataset) return '暂无可用数据集'
  return `${datasetLabel(selectedDataset)} [${shortId(selectedDataset.id)}]`
}

function vectorBackendLabel(
  readySnapshot: JsonObject | null,
  healthPayload: Record<string, unknown> | null | undefined
) {
  const vector = diagnosticField(readySnapshot, 'vector')
  const vectorBackend = diagnosticField(vector, 'backend')
  return (
    firstDiagnosticString(
      vectorBackend,
      healthPayload?.vector_backend
    ) || 'milvus'
  )
}

function driftMetricCardValue(
  running: boolean,
  snapshot: JsonObject | null,
  metric: number | null
) {
  if (running) return '检查中'
  if (snapshot) return fmtExecutedMetric(metric, 3)
  return PENDING_RUN_LABEL
}

function diagnosticSummaryDetail(hasDiagnostics: boolean) {
  return hasDiagnostics
    ? '已有 RAG / Drift / Perf 结果'
    : '需手动运行左侧诊断'
}

function stableTextKey(text: string) {
  let hash = 0
  for (const char of text) {
    hash = Math.imul(hash, 31) + (char.codePointAt(0) ?? 0)
  }
  return `text-${Math.abs(hash).toString(36)}`
}

function recommendationItems(recommendations: string[]) {
  const seen = new Map<string, number>()
  return recommendations.map((text) => {
    const baseKey = stableTextKey(text)
    const duplicateIndex = seen.get(baseKey) ?? 0
    seen.set(baseKey, duplicateIndex + 1)
    return {
      key: duplicateIndex === 0 ? baseKey : `${baseKey}-${duplicateIndex}`,
      text,
    }
  })
}

function resourceStatusClass(status: string) {
  const normalized = status.toLowerCase()
  if (['connected', 'ok', 'ready'].includes(normalized)) {
    return 'border-success/20 bg-success/10 text-success'
  }
  if (['checking', 'pending'].includes(normalized)) {
    return 'border-primary/20/70 bg-primary/10 text-primary'
  }
  if (['disabled', 'off'].includes(normalized)) {
    return 'border-border/50 bg-muted/50 text-muted-foreground'
  }
  return 'border-destructive/20 bg-destructive/10 text-destructive'
}

function resourceStatusLabel(status: string) {
  const normalized = String(status || 'unknown').toLowerCase()
  if (['connected', 'ok', 'ready'].includes(normalized)) return '已连接'
  if (['checking', 'pending'].includes(normalized)) return '检查中'
  if (['disabled', 'off'].includes(normalized)) return '已停用'
  if (['disconnected', 'error', 'failed'].includes(normalized)) return '异常'
  return '未知'
}

async function copyToClipboard(text = ''): Promise<void> {
  try {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
      throw new Error('Clipboard API unavailable')
    }
    await navigator.clipboard.writeText(text)
    toast.success('已复制')
  } catch (err) {
    toast.error(err instanceof Error && err.message ? `复制失败：${err.message}` : '复制失败')
  }
}

// --- Reusable UI Parts ---

const TOP_HUD_TONE_CLASSES = {
  slate: 'bg-muted/50 text-muted-foreground/80 border-border/50',
  green: 'bg-success/10 text-success border-success/20',
  amber: 'bg-warning/10 text-warning border-warning/20',
  red: 'bg-destructive/10 text-destructive border-destructive/20',
  blue: 'bg-primary/10 text-primary border-primary/20',
  purple: 'bg-accent/10 text-accent border-accent/20',
} as const

const STATUS_PILL_TONE_CLASSES = {
  slate:
    'border-border bg-card/80 text-muted-foreground shadow-[0_1px_2px_rgba(15,23,42,0.04)]',
  green:
    'border-success/20 bg-card/85 text-success shadow-[0_1px_2px_rgba(5,150,105,0.08)]',
  amber:
    'border-warning/20 bg-card/85 text-warning shadow-[0_1px_2px_rgba(217,119,6,0.08)]',
  red:
    'border-destructive/20 bg-card/85 text-destructive shadow-[0_1px_2px_rgba(220,38,38,0.08)]',
  blue:
    'border-primary/20 bg-card/85 text-primary shadow-[0_1px_2px_hsl(var(--primary)/0.08)]',
  purple:
    'border-accent/20 bg-card/85 text-accent shadow-[0_1px_2px_rgba(126,34,206,0.08)]',
} as const

function statusPillTone(value: string, fallback: MetricTone = 'slate'): MetricTone {
  const normalized = String(value || '').toLowerCase()
  if (/正常|就绪|已启用|已生成|已运行|通过|connected|ready|ok|success/.test(normalized)) {
    return 'green'
  }
  if (/执行中|检查中|加载|running|checking|pending/.test(normalized)) {
    return 'blue'
  }
  if (/异常|失败|断开|需排查|error|failed|disconnected/.test(normalized)) {
    return 'red'
  }
  if (/未启用|禁用|disabled|待执行|未返回|not_run/.test(normalized)) {
    return 'slate'
  }
  return fallback
}

function DiagnosticStatusPill({
  value,
  tone,
  className,
}: Readonly<{
  value: string
  tone?: MetricTone
  className?: string
}>) {
  const resolvedTone = tone ?? statusPillTone(value)

  return (
    <span
      className={cn(
        'inline-flex h-6 max-w-full items-center justify-center truncate rounded-full border px-2 text-center text-[11px] font-semibold tracking-[-0.01em] tabular-nums',
        STATUS_PILL_TONE_CLASSES[resolvedTone],
        className
      )}
      title={value}
    >
      {value}
    </span>
  )
}

function TopHUDTile({
  icon: Icon,
  label,
  value,
  detail,
  tone = 'slate',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  detail: string
  tone?: keyof typeof TOP_HUD_TONE_CLASSES
}>) {
  const toneClasses = TOP_HUD_TONE_CLASSES[tone] || TOP_HUD_TONE_CLASSES.slate
  const valueTone = statusPillTone(value, tone)

  return (
    <div className="flex min-h-[78px] items-center gap-3 rounded-xl border border-border/60 bg-card px-3 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.02)]">
      <div
        className={cn(
          'flex size-10 shrink-0 items-center justify-center rounded-full border shadow-inner',
          toneClasses
        )}
      >
        <Icon className="size-5" />
      </div>
      <div className="min-w-0">
        <span className="block truncate text-[11px] font-medium text-muted-foreground">
          {label}
        </span>
        <DiagnosticStatusPill
          value={value}
          tone={valueTone}
          className="mt-1 h-6 max-w-full"
        />
        <p className="mt-1 truncate text-[10px] font-medium text-muted-foreground/80">
          {detail}
        </p>
      </div>
    </div>
  )
}

function DimensionMatrixItem({
  icon: Icon,
  title,
  subtitle,
  selected,
  value,
  source,
  tone = 'blue',
  onToggle,
}: Readonly<{
  icon: LucideIcon
  title: string
  subtitle: string
  selected: boolean
  value: string
  source: string
  tone?: MetricTone
  onToggle: () => void
}>) {
  const colorMap: Record<MetricTone, string> = {
    blue: 'bg-primary/10 text-primary border-primary/20',
    green: 'bg-success/10 text-success border-success/20',
    amber: 'bg-warning/10 text-warning border-warning/20',
    red: 'bg-destructive/10 text-destructive border-destructive/20',
    slate: 'bg-muted/50 text-muted-foreground/80 border-border/50',
    purple: 'bg-accent/10 text-accent border-accent/20',
  }

  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onToggle}
      className={cn(
        'group flex min-h-[68px] w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-all',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25',
        selected
          ? 'border-primary/30 bg-primary/[0.06] shadow-[0_1px_6px_hsl(var(--primary)/0.08)]'
          : 'border-border/60 bg-card hover:border-border hover:bg-muted/50'
      )}
    >
      <div
        className={cn(
          'size-8 shrink-0 rounded-xl flex items-center justify-center border transition-all',
          colorMap[tone]
        )}
      >
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-[12px] font-semibold leading-tight text-foreground group-hover:text-foreground">
              {title}
            </p>
            <p className="mt-0.5 truncate text-[10px] font-medium text-muted-foreground/80 group-hover:text-muted-foreground">
              {subtitle}
            </p>
          </div>
          <span
            className={cn(
              'shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold',
              selected
                ? 'border-primary/20 bg-card text-primary'
                : 'border-border/50 bg-muted/50 text-muted-foreground/80'
            )}
          >
            {selected ? '已选' : '未选'}
          </span>
        </div>
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <DiagnosticStatusPill
            value={value}
            tone={isPendingMetricLabel(value) ? 'slate' : tone}
            className="h-5 max-w-[96px] px-1.5 text-[10px]"
          />
          <span className="truncate rounded-full bg-card/70 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-muted-foreground/60">
            {source}
          </span>
        </div>
      </div>
    </button>
  )
}

function MainMetricCard({
  icon: Icon,
  label,
  value,
  help,
  loading = false,
  tone = 'slate',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  help?: ReactNode
  loading?: boolean
  tone?: string
}>) {
  const isWait = isPendingMetricLabel(value)
  const toneClass =
    {
      slate: 'bg-muted/50 text-muted-foreground/80 border-border/50',
      green: 'bg-success/10 text-success border-success/20',
      amber: 'bg-warning/10 text-warning border-warning/20',
      red: 'bg-destructive/10 text-destructive border-destructive/20',
    }[tone] || 'bg-muted/50 text-muted-foreground/80 border-border/50'

  return (
    <div className="group flex min-h-[48px] items-center gap-2 rounded-xl border border-border/60 bg-card px-2 py-1.5 shadow-[0_1px_2px_rgba(15,23,42,0.02)] transition-all hover:border-border hover:bg-muted/40">
      <div
        className={cn(
          'flex size-7 shrink-0 items-center justify-center rounded-lg border transition-colors',
          toneClass
        )}
      >
        <Icon className="size-3.5" />
      </div>
      <div className="flex min-w-0 flex-1 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <p className="truncate text-[10.5px] font-medium leading-none text-muted-foreground">
            {label}
          </p>
          {help ? (
            <MetricInfoTooltip label={`${label}说明`}>{help}</MetricInfoTooltip>
          ) : null}
        </div>
        <div className="shrink-0">
          {loading ? (
            <div className="h-5 w-16 animate-pulse rounded-full bg-muted" />
          ) : (
            <DiagnosticStatusPill
              value={value}
              tone={isWait ? 'slate' : (tone as MetricTone)}
              className="h-5 max-w-[76px] px-1.5 text-[10px]"
            />
          )}
        </div>
      </div>
    </div>
  )
}

function MetricInfoTooltip({
  label,
  children,
  side = 'top',
}: Readonly<{
  label: string
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
}>) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="inline-flex size-4 items-center justify-center rounded-full border border-border bg-card text-muted-foreground/80 transition-colors hover:border-primary/30 hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25"
        >
          <Info className="size-3" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent
        side={side}
        align="center"
        className="max-w-[280px] rounded-lg bg-foreground px-3 py-2 text-[11px] leading-5 text-background shadow-lg"
      >
        {children}
      </TooltipContent>
    </Tooltip>
  )
}

function DiagnosticUseGuide() {
  return (
    <div className="rounded-2xl border border-primary/15 bg-[linear-gradient(135deg,hsl(var(--primary)/0.10),hsl(var(--card))_48%,hsl(var(--accent)/0.08))] p-3 shadow-[0_10px_24px_hsl(var(--primary)/0.05)]">
      <div className="grid gap-2 lg:grid-cols-[1.1fr_1fr_1fr]">
        <DiagnosticUseStep
          icon={Search}
          title="RAG 预览看召回"
          action="点击：运行 RAG 预览"
          text="用当前问题真实调用检索预览，生成检索相关性、召回引用和 token 成本。"
        />
        <DiagnosticUseStep
          icon={Timer}
          title="漂移检查看重嵌入风险"
          action="点击：漂移检查"
          text="抽样比较当前 embedding 配置和已存向量，判断是否需要重建向量。"
        />
        <DiagnosticUseStep
          icon={ShieldCheck}
          title="性能门禁看稳定性"
          action="点击：性能门禁"
          text="运行后端性能探针，确认接口耗时和稳定性是否达到上线门槛。"
        />
      </div>
    </div>
  )
}

function DiagnosticUseStep({
  icon: Icon,
  title,
  action,
  text,
}: Readonly<{
  icon: LucideIcon
  title: string
  action: string
  text: string
}>) {
  return (
    <div className="flex gap-3 rounded-xl border border-border/80 bg-card/75 px-3 py-2.5">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/10 text-primary">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <p className="text-[12px] font-semibold text-foreground">{title}</p>
        <p className="mt-0.5 text-[10px] font-semibold text-primary">
          {action}
        </p>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{text}</p>
      </div>
    </div>
  )
}

// --- Page Component ---

export default function DiagnosticsPage() {
  const health = useBackendHealth()
  const meta = useBackendMetaDetails()

  // Config States
  const [probeDatasetId, setProbeDatasetId] = useState('')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [probeQuery, setProbeQuery] = useState('')
  const [probeResult, setProbeResult] = useState<PromptPreviewResponse | null>(
    null
  )
  const [probeExplainResult, setProbeExplainResult] = useState<JsonObject | null>(
    null
  )
  const [probeConfigHashResult, setProbeConfigHashResult] =
    useState<JsonObject | null>(null)
  const [probeRunning, setProbeRunning] = useState(false)
  const [selectedDimensions, setSelectedDimensions] = useState<
    DiagnosticDimensionId[]
  >(DIAGNOSTIC_DIMENSIONS.map((dimension) => dimension.id))

  // Param States
  const [driftSampleN, setDriftSampleN] = useState(200)
  const [driftThreshold, setDriftThreshold] = useState(0.05)
  const [driftSnapshot, setDriftSnapshot] = useState<JsonObject | null>(null)
  const [driftRunning, setDriftRunning] = useState(false)

  const [perfSuiteIterations, setPerfSuiteIterations] = useState(10)
  const [perfSuiteTimeoutSec, setPerfSuiteTimeoutSec] = useState(2)
  const [perfSuiteResult, setPerfSuiteResult] = useState<JsonObject | null>(
    null
  )
  const [perfSuiteRunning, setPerfSuiteRunning] = useState(false)

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive({ purpose: 'diagnostics' }),
    queryFn: () => datasetApi.listAll(),
    staleTime: 30_000,
  })
  const datasets = datasetsQuery.data ?? EMPTY_DATASETS
  const datasetsLoading = datasetsQuery.isPending
  const activeDatasetId = probeDatasetId || datasets[0]?.id || ''
  const activeDatasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(activeDatasetId),
    enabled: Boolean(activeDatasetId),
    queryFn: () => datasetApi.get(activeDatasetId),
    staleTime: 30_000,
  })
  const activeDataset = activeDatasetQuery.data ?? null
  const explainContractReason = !activeDatasetId
    ? '请选择数据集'
    : hasDatasetRagContract(activeDataset?.rag_defaults)
      ? null
      : '当前数据集未配置 rag_defaults，explain/hash 已禁用'
  const canExplainProbe = Boolean(activeDatasetId) && !explainContractReason

  const documentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      dataset_id: activeDatasetId,
      limit: 200,
      order_by: 'created_at',
      order_dir: 'desc',
    }),
    enabled: Boolean(activeDatasetId),
    queryFn: (): Promise<DocumentList> =>
      documentApi.list({
        skip: 0,
        limit: 200,
        dataset_id: activeDatasetId,
        order_by: 'created_at',
        order_dir: 'desc',
      }),
    staleTime: 15_000,
  })
  const documents =
    getListItems<KnowledgeDocument>(documentsQuery.data, EMPTY_DOCUMENTS)
  const documentsLoading =
    Boolean(activeDatasetId) &&
    (documentsQuery.isPending || documentsQuery.isFetching)
  const validSelectedDocumentIds = useMemo(() => {
    if (selectedDocumentIds.length === 0) return []
    const idSet = new Set(documents.map((document) => document.id))
    return selectedDocumentIds.filter((id) => idSet.has(id))
  }, [documents, selectedDocumentIds])

  const onlineQualityQuery = useQuery({
    queryKey: queryKeys.diagnostics.onlineQuality({
      window_minutes: 240,
      bucket_minutes: 5,
    }),
    queryFn: async (): Promise<OnlineQualitySummaryResponse | null> => {
      try {
        return await observabilityApi.getOnlineQualitySummary({
          window_minutes: 240,
          bucket_minutes: 5,
        })
      } catch {
        return null
      }
    },
    staleTime: 30_000,
  })
  const onlineQuality = onlineQualityQuery.data ?? null
  const onlineQualityLoading =
    onlineQualityQuery.isPending || onlineQualityQuery.isFetching

  const readySnapshotQuery = useQuery({
    queryKey: queryKeys.diagnostics.ready,
    queryFn: async (): Promise<JsonObject | null> => {
      try {
        const response = await fetch(`${API_V1_BASE_URL}/health/ready`, {
          cache: 'no-store',
        })
        const payload = await response.json().catch(() => null)
        return isDiagnosticRecord(payload) ? payload : null
      } catch {
        return null
      }
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  })
  const readySnapshot = readySnapshotQuery.data ?? null
  const readyLoading =
    readySnapshotQuery.isPending || readySnapshotQuery.isFetching

  const depsSnapshotQuery = useQuery({
    queryKey: queryKeys.diagnostics.deps,
    queryFn: async (): Promise<DepsDiagnosticsResponse | null> => {
      try {
        return await observabilityApi.getDepsDiagnosticsSnapshot()
      } catch {
        return null
      }
    },
    staleTime: 15_000,
  })
  const depsSnapshot = depsSnapshotQuery.data ?? null
  const depsLoading = depsSnapshotQuery.isPending || depsSnapshotQuery.isFetching

  async function runPromptPreviewProbe() {
    if (!probeQuery.trim()) {
      toast.error('请先输入查询提示或问题')
      return
    }
    setProbeRunning(true)
    setProbeResult(null)
    setProbeExplainResult(null)
    setProbeConfigHashResult(null)
    try {
      const promptPreviewRequest = {
        query: probeQuery.trim(),
        dataset_id: activeDatasetId || undefined,
        document_ids: validSelectedDocumentIds,
        structured_output: false,
      }
      const configHashRequest = buildRetrievalConfigHashRequest(
        activeDataset?.rag_defaults
      )

      const [previewResponse, explainResponse, hashResponse] =
        await Promise.all([
          ragApi.promptPreview(promptPreviewRequest),
          canExplainProbe && configHashRequest
            ? retrievalApi.explain({
                query: probeQuery.trim(),
                dataset_id: activeDatasetId || undefined,
                document_ids: validSelectedDocumentIds,
                rag_config: configHashRequest.rag_config,
                retrieval_only: true,
                top_citations_limit: 8,
              })
            : Promise.resolve(null),
          canExplainProbe && configHashRequest
            ? retrievalApi.configHash(configHashRequest)
            : Promise.resolve(null),
        ])

      setProbeResult(previewResponse)
      setProbeExplainResult(
        explainResponse && isDiagnosticRecord(explainResponse)
          ? explainResponse
          : null
      )
      setProbeConfigHashResult(
        hashResponse && isDiagnosticRecord(hashResponse)
          ? hashResponse
          : null
      )
      toast.success('RAG 预览完成')
    } catch (err) {
      toast.error(formatApiError(err, 'RAG 预览失败'))
    } finally {
      setProbeRunning(false)
    }
  }

  async function runEmbeddingDriftProbe() {
    setDriftRunning(true)
    setDriftSnapshot(null)
    try {
      const res = await observabilityApi.getEmbeddingDriftSnapshot({
        dataset_id: activeDatasetId || undefined,
        sample_n: driftSampleN,
        drift_threshold: driftThreshold,
      })
      setDriftSnapshot(res)
      toast.success('漂移检查完成')
    } catch (err) {
      toast.error(formatApiError(err, '漂移检查失败'))
    } finally {
      setDriftRunning(false)
    }
  }

  async function runPerfSuiteProbe() {
    setPerfSuiteRunning(true)
    setPerfSuiteResult(null)
    try {
      const res = await observabilityApi.runPerfSuite({
        iterations: perfSuiteIterations,
        timeout_sec: perfSuiteTimeoutSec,
      })
      setPerfSuiteResult(res)
      toast.success('性能门禁完成')
    } catch (err) {
      toast.error(formatApiError(err, '性能门禁失败'))
    } finally {
      setPerfSuiteRunning(false)
    }
  }

  const healthOk = Boolean(health.data?.payload?.ok)
  const readyOk = Boolean(readySnapshot?.ok)
  const systemStatus = systemStatusSummary(healthOk, readyOk)
  const serviceTime = fmtDateTime(meta.data?.time || health.data?.payload?.time)
  const currentVectorBackend = vectorBackendLabel(
    readySnapshot,
    health.data?.payload
  )
  const driftMetric = pickMetricNumberByPath(driftSnapshot, [
    'above_threshold.ratio',
    'above_threshold_ratio',
    'exceed_threshold_ratio',
    'exceed_ratio',
    'drift_rate',
    'driftRate',
    'drifted_ratio',
    'exceed_rate',
    'drift.avg',
    'drift.mean',
    'avg_drift',
    'mean_drift',
  ])
  const driftStatusLabel = driftResultLabel(driftSnapshot, driftMetric)
  const perfGateStatus = perfGateResultStatus(perfSuiteResult)
  const perfGateTone = perfGateResultTone(perfSuiteResult, perfGateStatus)
  const dependencyItems = [
    {
      label: '检索库',
      status: dependencyStatus(
        depsSnapshot?.postgres || readySnapshot?.database
      ),
    },
    {
      label: '向量后端',
      status: dependencyStatus(readySnapshot?.vector || depsSnapshot?.milvus),
    },
    {
      label: 'MinIO',
      status: dependencyStatus(depsSnapshot?.minio || readySnapshot?.minio),
    },
    {
      label: 'Redis',
      status: dependencyStatus(depsSnapshot?.redis || readySnapshot?.redis),
    },
    { label: '服务 API', status: serviceDependencyStatus(healthOk) },
  ]
  const selectedDataset =
    activeDataset || datasets.find((dataset) => dataset.id === activeDatasetId) || null
  const selectedDocuments = documents.filter((document) =>
    validSelectedDocumentIds.includes(document.id)
  )
  const selectedDocumentLabel = selectedDocumentScopeLabel(
    validSelectedDocumentIds.length,
    documentsLoading,
    Boolean(activeDatasetId)
  )

  const toggleDocument = useCallback((documentId: string) => {
    if (documentId === ALL_DOCUMENTS_VALUE) {
      setSelectedDocumentIds([])
      return
    }
    setSelectedDocumentIds((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId]
    )
  }, [])

  const toggleDimension = useCallback((dimensionId: DiagnosticDimensionId) => {
    setSelectedDimensions((current) =>
      current.includes(dimensionId)
        ? current.filter((id) => id !== dimensionId)
        : [...current, dimensionId]
    )
  }, [])

  const selectedDimensionSet = useMemo(
    () => new Set(selectedDimensions),
    [selectedDimensions]
  )

  const promptMetrics = probeResult?.metrics ?? null
  const retrievalScore = pickMetricNumber(promptMetrics, [
    'retrieval_score',
    'retrieval_relevance',
    'retrieval_relevance_score',
    'relevance',
    'similarity_score',
    'similarity',
  ])
  const contextScore = pickMetricNumber(promptMetrics, [
    'context_relevance',
    'context_relevancy',
    'context_score',
    'context_precision',
    'context_precision_score',
  ])
  const generationScore = pickMetricNumber(promptMetrics, [
    'generation_quality',
    'answer_quality',
    'response_relevancy',
    'response_relevance',
    'faithfulness',
  ])
  const factScore = pickMetricNumber(promptMetrics, [
    'faithfulness',
    'faithfulness_score',
    'factual_consistency',
    'fact_consistency',
  ])
  const safetyScore = pickMetricNumber(promptMetrics, [
    'safety_score',
    'safety',
    'policy_compliance',
    'compliance_score',
  ])
  const promptTokenCount = pickMetricNumber(promptMetrics, [
    'prompt_tokens',
    'total_prompt_tokens',
    'input_tokens',
    'tokens_prompt',
  ])
  const latencyMs = pickMetricNumber(promptMetrics, [
    'latency_ms',
    'duration_ms',
    'elapsed_ms',
    'total_ms',
    'retrieval_ms',
  ])
  const citationCount = Array.isArray(probeResult?.citations)
    ? probeResult.citations.length
    : null
  const hasProbeResult = Boolean(probeResult)
  const ragPreviewStatusLabel = citationStatusLabel(hasProbeResult, citationCount)
  const hasPerfSuiteResult = Boolean(perfSuiteResult)
  const dimensionStatuses: Record<
    DiagnosticDimensionId,
    { value: string; source: string; tone: MetricTone }
  > = {
    retrieval_accuracy: {
      value: fmtMetricOrMissing(hasProbeResult, retrievalScore),
      source: metricSource(hasProbeResult, 'metrics'),
      tone: metricTone(retrievalScore),
    },
    retrieval_recall: {
      value: fmtCountOrMissing(hasProbeResult, citationCount, ' 条'),
      source: metricSource(hasProbeResult, 'citations'),
      tone: citationTone(citationCount),
    },
    context_relevance: {
      value: fmtMetricOrMissing(hasProbeResult, contextScore),
      source: metricSource(hasProbeResult, 'metrics'),
      tone: metricTone(contextScore),
    },
    generation_quality: {
      value: fmtMetricOrMissing(hasProbeResult, generationScore),
      source: metricSource(hasProbeResult, 'metrics'),
      tone: metricTone(generationScore),
    },
    fact_consistency: {
      value: fmtMetricOrMissing(hasProbeResult, factScore),
      source: metricSource(hasProbeResult, 'metrics'),
      tone: metricTone(factScore),
    },
    safety_compliance: {
      value: fmtMetricOrMissing(hasProbeResult, safetyScore),
      source: metricSource(hasProbeResult, 'metrics'),
      tone: metricTone(safetyScore),
    },
    cost_analysis: {
      value: fmtCountOrMissing(hasProbeResult, promptTokenCount, ' tokens'),
      source: metricSource(hasProbeResult, 'metrics'),
      tone: promptTokenCount === null ? 'slate' : 'amber',
    },
    execution_perf: {
      value: executionPerfValue(
        latencyMs,
        perfGateStatus,
        hasPerfSuiteResult,
        hasProbeResult
      ),
      source: executionPerfSource(latencyMs, hasPerfSuiteResult),
      tone: executionPerfTone(latencyMs, perfGateTone),
    },
  }

  const backendSummaryJson = useMemo(
    () => {
      const runState = diagnosticsRunState(
        Boolean(
          probeResult ||
            probeExplainResult ||
            probeConfigHashResult ||
            driftSnapshot ||
            perfSuiteResult
        )
      )
      return prettyJson({
        status: runState.status,
        code: 0,
        message: runState.message,
        data: {
          dataset_id: activeDatasetId || null,
          document_ids: validSelectedDocumentIds,
          selected_dimensions: selectedDimensions,
          rag_preview: probeResult ?? null,
          retrieval_explain: probeExplainResult ?? null,
          retrieval_config_hash: probeConfigHashResult ?? null,
          embedding_drift: driftSnapshot ?? null,
          perf_suite: perfSuiteResult ?? null,
          deps: depsSnapshot ?? null,
        },
        metrics: {
          ...probeResult?.metrics,
          drift_rate: driftMetric,
          perf_gate: perfGateStatus,
        },
        timestamp: health.data?.payload?.time ?? null,
      })
    },
    [
      activeDatasetId,
      validSelectedDocumentIds,
      selectedDimensions,
      probeResult,
      probeExplainResult,
      probeConfigHashResult,
      driftSnapshot,
      perfSuiteResult,
      depsSnapshot,
      driftMetric,
      perfGateStatus,
      health.data,
    ]
  )
  const hasManualDiagnostics = Boolean(
    probeResult ||
      probeExplainResult ||
      probeConfigHashResult ||
      driftSnapshot ||
      perfSuiteResult
  )
  const manualDiagnosticsStatusLabel = manualDiagnosticsStatus(
    probeRunning || driftRunning || perfSuiteRunning,
    hasManualDiagnostics
  )

  const backendRecommendations = stringList(
    diagnosticField(onlineQuality, 'recommendations')
  )
  const backendRecommendationItems = recommendationItems(backendRecommendations)
  const ragPreviewSummary = useMemo(
    () =>
      buildRagPreviewDiagnosticsSummary({
        promptPreview: probeResult,
        explain: probeExplainResult,
        configHash: probeConfigHashResult,
        explainEnabled: canExplainProbe,
        contractReason: explainContractReason,
      }),
    [
      probeResult,
      probeExplainResult,
      probeConfigHashResult,
      canExplainProbe,
      explainContractReason,
    ]
  )

  return (
    <AppFrame>
      <PageScaffold
        title="诊断中心"
        description="全面诊断系统健康状态、服务依赖与 RAG 质量，保障稳定可靠运行"
        iconImage="diagnostics"
        icon={Activity}
        iconColor="text-primary"
        size="full"
        bodyGutter="dense"
        bodyClassName="bg-muted/40 pt-4 pb-6"
        actions={
          <div className="flex shrink-0 items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1.5 rounded-full border-destructive/20 bg-destructive/10 px-3 text-[12px] font-semibold text-destructive shadow-none hover:bg-destructive/15 hover:text-destructive"
              onClick={() => {
                depsSnapshotQuery.refetch()
                readySnapshotQuery.refetch()
                document
                  .getElementById('diagnostics-dependency-card')
                  ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
              }}
            >
              <ShieldAlert className="size-3.5" />
              服务健康排查
            </Button>
            <Button
              variant="outline"
              size="icon"
              aria-label="刷新诊断状态"
              className="h-8 w-8 rounded-lg border-border bg-card"
              onClick={() => {
                health.refetch()
                meta.refetch()
                readySnapshotQuery.refetch()
                onlineQualityQuery.refetch()
                depsSnapshotQuery.refetch()
              }}
            >
              <RefreshCcw className="size-4" />
            </Button>
          </div>
        }
      >
          <TooltipProvider delayDuration={120}>
            <div className="flex flex-col gap-3">
          {/* Top HUD Cards Row */}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <TopHUDTile
              icon={ShieldCheck}
              label="系统健康"
              value={healthStatusLabel(health.isPending, healthOk)}
              detail="健康探针"
              tone={okTone(healthOk)}
            />
            <TopHUDTile
              icon={Clock}
              label="服务时间 / API 版本"
              value={serviceTime}
              detail={meta.data?.api_version || 'v1'}
              tone="green"
            />
            <TopHUDTile
              icon={Database}
              label="依赖就绪"
              value={readyStatusLabel(
                readyLoading,
                readySnapshot,
                readyOk,
                '全部就绪',
                '异常'
              )}
              detail="就绪检查"
              tone={okTone(readyOk, 'blue')}
            />
            <TopHUDTile
              icon={Activity}
              label="在线评估"
              value={onlineQualityStatusLabel(
                onlineQualityLoading,
                onlineQuality?.enabled
              )}
              detail="在线指标"
              tone="purple"
            />
            <TopHUDTile
              icon={Gauge}
              label="性能门禁"
              value={perfGateStatus}
              detail="门禁探针"
              tone={perfGateTone}
            />
            <TopHUDTile
              icon={Timer}
              label="向量后端"
              value={currentVectorBackend}
              detail="向量服务"
              tone="green"
            />
            </div>

            <DiagnosticUseGuide />

            {/* Main Config Section */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
            {/* 1. 诊断配置 */}
            <div className={cn(CARD_BASE, 'lg:col-span-4')}>
              <h3 className={SECTION_TITLE}>
                <FileJson className="size-4 text-primary" /> 诊断配置
              </h3>
              <div className="space-y-3">
                <div>
                  <Label className={FIELD_LABEL}>数据集</Label>
                  <Select
                    value={activeDatasetId}
                    onValueChange={(value) => {
                      setProbeDatasetId(value)
                      setSelectedDocumentIds([])
                    }}
                    disabled={datasetsLoading || datasets.length === 0}
                  >
                    <SelectTrigger
                      id="diagnostics-dataset"
                      className="h-9 rounded-lg border-border bg-muted/40 text-[13px]"
                    >
                      <span className="truncate">
                        {datasetSelectLabel(datasetsLoading, selectedDataset)}
                      </span>
                    </SelectTrigger>
                    <SelectContent>
                      {datasets.map((dataset) => (
                        <SelectItem key={dataset.id} value={dataset.id}>
                          <span className="flex min-w-0 flex-col">
                            <span className="truncate text-[13px] font-medium">
                              {datasetLabel(dataset)}
                            </span>
                            <span className="truncate text-[10px] text-muted-foreground/80">
                              {shortId(dataset.id, 12)}
                            </span>
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className={FIELD_LABEL}>文档范围</Label>
                  <Select
                    value={validSelectedDocumentIds[0] || ALL_DOCUMENTS_VALUE}
                    onValueChange={toggleDocument}
                    disabled={
                      !activeDatasetId ||
                      documentsLoading ||
                      documents.length === 0
                    }
                  >
                    <SelectTrigger
                      id="diagnostics-documents"
                      className="h-9 rounded-lg border-border bg-muted/40 text-[13px]"
                    >
                      <span className="truncate">{selectedDocumentLabel}</span>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL_DOCUMENTS_VALUE}>
                        当前数据集全部文档
                      </SelectItem>
                      {documents.map((document) => {
                        const selected = validSelectedDocumentIds.includes(
                          document.id
                        )
                        return (
                          <SelectItem key={document.id} value={document.id}>
                            <span className="flex min-w-0 items-center gap-2">
                              <span
                                className={cn(
                                  'flex size-4 shrink-0 items-center justify-center rounded border text-[10px]',
                                  selected
                                    ? 'border-primary/30 bg-primary/10 text-primary'
                                    : 'border-border bg-card text-transparent'
                                )}
                              >
                                {selected ? '✓' : ''}
                              </span>
                              <span className="flex min-w-0 flex-col">
                                <span className="truncate text-[13px] font-medium">
                                  {documentLabel(document)}
                                </span>
                                <span className="truncate text-[10px] text-muted-foreground/80">
                                  {shortId(document.id, 12)}
                                </span>
                              </span>
                            </span>
                          </SelectItem>
                        )
                      })}
                    </SelectContent>
                  </Select>
                  {selectedDocuments.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {selectedDocuments.slice(0, 3).map((document) => (
                        <span
                          key={document.id}
                          className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
                        >
                          {documentLabel(document)}
                        </span>
                      ))}
                      {selectedDocuments.length > 3 ? (
                        <span className="rounded-full border border-border/50 bg-muted/50 px-2 py-0.5 text-[10px] font-medium text-muted-foreground/80">
                          +{selectedDocuments.length - 3}
                        </span>
                      ) : null}
                    </div>
                  ) : (
                    <p className="mt-1 text-[10px] font-medium text-muted-foreground/80">
                      不选择文档时，诊断当前数据集的全部可检索内容。
                    </p>
                  )}
                </div>
                <div>
                  <Label className={FIELD_LABEL}>查询提示 / 问题</Label>
                  <Textarea
                    value={probeQuery}
                    onChange={(e) => setProbeQuery(e.target.value)}
                    placeholder="请输入要检索的问题或说明诊断目标..."
                    className="min-h-[72px] bg-muted/40 border-border resize-none text-[13px]"
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    data-rag-preview-action="true"
                    className="h-9 flex-1 bg-primary text-primary-foreground hover:bg-primary/90 text-[13px] font-semibold shadow-[0_10px_24px_hsl(var(--primary)/0.18)] disabled:bg-muted disabled:text-muted-foreground"
                    onClick={runPromptPreviewProbe}
                    disabled={probeRunning || !activeDatasetId}
                  >
                    运行 RAG 预览
                  </Button>
                  <Button
                    variant="outline"
                    className="h-9 flex-none gap-2 border-border text-[13px] font-semibold"
                    onClick={() => {
                      setProbeDatasetId(datasets[0]?.id || '')
                      setSelectedDocumentIds([])
                      setProbeQuery('')
                    }}
                  >
                    <Eraser className="size-4" /> 清空配置
                  </Button>
                </div>
              </div>
            </div>

            {/* 2. 诊断维度矩阵 */}
            <div className={cn(CARD_BASE, 'lg:col-span-5')}>
              <div className="mb-4 flex items-center justify-between gap-3">
                <h3 className="m-0 flex items-center gap-2 text-[14px] font-semibold text-foreground">
                  <LayoutGrid className="size-4 text-primary" /> 诊断维度
                </h3>
                <span className="rounded-full border border-border/50 bg-muted/50 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                  已选 {selectedDimensions.length}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2.5">
                {DIAGNOSTIC_DIMENSIONS.map((dimension) => {
                  const status = dimensionStatuses[dimension.id]
                  return (
                    <DimensionMatrixItem
                      key={dimension.id}
                      icon={dimension.icon}
                      title={dimension.title}
                      subtitle={dimension.subtitle}
                      selected={selectedDimensionSet.has(dimension.id)}
                      value={status.value}
                      source={status.source}
                      tone={status.tone}
                      onToggle={() => toggleDimension(dimension.id)}
                    />
                  )
                })}
              </div>
            </div>

            {/* 3. 参数配置 */}
            <div className={cn(CARD_BASE, 'lg:col-span-3')}>
              <h3 className={SECTION_TITLE}>
                <Settings2 className="size-4 text-primary" /> 参数配置
              </h3>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className={FIELD_LABEL}>相似度阈值</Label>
                    <Input
                      type="number"
                      step="0.01"
                      value={driftThreshold}
                      onChange={(e) =>
                        setDriftThreshold(Number(e.target.value))
                      }
                      className="h-9 bg-muted/40 border-border text-[13px]"
                    />
                  </div>
                  <div>
                    <Label className={FIELD_LABEL}>采样数量</Label>
                    <Input
                      type="number"
                      value={driftSampleN}
                      onChange={(e) => setDriftSampleN(Number(e.target.value))}
                      className="h-9 bg-muted/40 border-border text-[13px]"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className={FIELD_LABEL}>迭代次数</Label>
                    <Input
                      type="number"
                      value={perfSuiteIterations}
                      onChange={(e) =>
                        setPerfSuiteIterations(Number(e.target.value))
                      }
                      className="h-9 bg-muted/40 border-border text-[13px]"
                    />
                  </div>
                  <div>
                    <Label className={FIELD_LABEL}>超时 (秒)</Label>
                    <Input
                      type="number"
                      step="0.1"
                      value={perfSuiteTimeoutSec}
                      onChange={(e) =>
                        setPerfSuiteTimeoutSec(Number(e.target.value))
                      }
                      className="h-9 bg-muted/40 border-border text-[13px]"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <Button
                    variant="outline"
                    className="h-9 w-full gap-2 border-border text-[13px] font-semibold"
                    onClick={runEmbeddingDriftProbe}
                    disabled={driftRunning}
                  >
                    <BarChart3
                      className={cn('size-4', driftRunning && 'animate-pulse')}
                    />{' '}
                    漂移检查
                  </Button>
                  <Button
                    variant="outline"
                    className="h-9 w-full gap-2 border-border text-[13px] font-semibold"
                    onClick={runPerfSuiteProbe}
                    disabled={perfSuiteRunning}
                  >
                    <ShieldCheck
                      className={cn(
                        'size-4',
                        perfSuiteRunning && 'animate-pulse'
                      )}
                    />{' '}
                    性能门禁
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* 4. 核心指标横条 */}
          <div>
            <div className="mb-2 flex items-center justify-between gap-3 px-2">
              <h3 className="m-0 flex items-center gap-2 text-[14px] font-semibold text-foreground">
                <BarChart3 className="size-4 text-primary" /> 核心指标
                <MetricInfoTooltip label="核心指标说明" side="right">
                  这里不是自动生成的总报告。RAG
                  预览、漂移检查、性能门禁是三个独立探针，分别点击后只更新自己负责的指标。
                </MetricInfoTooltip>
              </h3>
              <p className="text-[11px] font-medium text-muted-foreground/80">
                先跑左侧按钮，再看对应指标
              </p>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-[repeat(5,minmax(190px,1fr))]">
              <MainMetricCard
                icon={Search}
                label="检索相关性"
                value={fmtMetricOrMissing(hasProbeResult, retrievalScore)}
                help="点击“运行 RAG 预览”后生成。用于判断当前问题召回的片段和问题是否相关，低分通常要检查切块、embedding、Top K 或 reranker。"
                loading={probeRunning}
                tone={metricTone(retrievalScore)}
              />
              <MainMetricCard
                icon={CheckCircle2}
                label="召回引用"
                value={fmtCountOrMissing(hasProbeResult, citationCount)}
                help="点击“运行 RAG 预览”后生成。表示这次回答拿到了多少条可引用证据；为 0 时通常说明检索没找到可用上下文。"
                loading={probeRunning}
                tone={citationTone(citationCount)}
              />
              <MainMetricCard
                icon={Hash}
                label="提示词 token"
                value={fmtCountOrMissing(hasProbeResult, promptTokenCount)}
                help="点击“运行 RAG 预览”后生成。用于估算本次检索上下文和问题进入模型的 token 成本，过高会影响费用和响应速度。"
                loading={probeRunning}
                tone={promptTokenCount === null ? 'slate' : 'amber'}
              />
              <MainMetricCard
                icon={Timer}
                label="漂移率"
                value={driftMetricCardValue(
                  driftRunning,
                  driftSnapshot,
                  driftMetric
                )}
                help="点击“漂移检查”后生成。后端抽样比较当前 embedding 配置与已存向量；0 表示样本未发现漂移，比例升高说明可能需要重新嵌入。"
                loading={driftRunning}
                tone={metricTone(driftMetric)}
              />
              <MainMetricCard
                icon={ShieldCheck}
                label="性能门禁"
                value={runningStatusLabel(perfSuiteRunning, perfGateStatus)}
                help="点击“性能门禁”后生成。用于快速判断后端诊断接口在当前迭代次数和超时设置下是否稳定通过。"
                loading={perfSuiteRunning}
                tone={perfGateTone}
              />
            </div>
          </div>

          <div className={CARD_BASE}>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h3 className="m-0 flex items-center gap-2 text-[14px] font-semibold text-foreground">
                  <Search className="size-4 text-primary" /> 主预览
                </h3>
                <p className="mt-1 text-[11px] text-muted-foreground/80">
                  这里基于真实后端返回值显示 prompt-preview、retrieval explain 与 config hash。
                </p>
              </div>
              <DiagnosticStatusPill
                value={
                  canExplainProbe
                    ? probeRunning
                      ? 'explain 运行中'
                      : 'explain 已接入'
                    : 'explain 已禁用'
                }
                tone={canExplainProbe ? 'green' : 'amber'}
              />
            </div>

            {!probeResult && !probeRunning ? (
              <div className="rounded-xl border border-dashed border-border/60 bg-card/50 px-4 py-5 text-[12px] text-muted-foreground">
                运行一次 RAG 预览后，这里会展示 profile、config hash、通道候选、过滤/融合/reranker/耗时，以及 degraded/fallback 信号。
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                  <PreviewInfoCard
                    label="query_for_retrieval"
                    mono={false}
                    value={
                      ragPreviewSummary.queryForRetrieval || MISSING_RESULT_LABEL
                    }
                  />
                  <PreviewInfoCard
                    label="retrieval_profile"
                    value={ragPreviewSummary.profile || MISSING_RESULT_LABEL}
                  />
                  <PreviewInfoCard
                    label="config_hash"
                    value={ragPreviewSummary.configHash || MISSING_RESULT_LABEL}
                  />
                  <PreviewInfoCard
                    label="contract"
                    mono={false}
                    value={
                      ragPreviewSummary.explainEnabled
                        ? 'dataset rag_defaults'
                        : ragPreviewSummary.contractReason || 'disabled'
                    }
                  />
                </div>

                {!ragPreviewSummary.explainEnabled &&
                ragPreviewSummary.contractReason ? (
                  <div className="rounded-xl border border-warning/20 bg-warning/10 px-3 py-2 text-[12px] text-warning">
                    {ragPreviewSummary.contractReason}
                  </div>
                ) : null}

                <div className="grid gap-3 xl:grid-cols-4">
                  <PreviewListCard
                    title="通道候选"
                    emptyLabel="后端未返回 channel 数据"
                    items={ragPreviewSummary.channelCandidates}
                  />
                  <PreviewListCard
                    title="过滤"
                    emptyLabel="后端未返回 filtering/contract 字段"
                    items={ragPreviewSummary.filtering}
                  />
                  <PreviewListCard
                    title="融合"
                    emptyLabel="后端未返回 fusion 字段"
                    items={ragPreviewSummary.fusion}
                  />
                  <PreviewListCard
                    title="Reranker / 耗时"
                    emptyLabel="后端未返回 reranker/timing 字段"
                    items={[
                      ...ragPreviewSummary.reranker,
                      ...ragPreviewSummary.timings,
                    ]}
                  />
                </div>

                {ragPreviewSummary.degraded.length > 0 ? (
                  <PreviewMessageCard
                    title="Degraded"
                    tone="amber"
                    items={ragPreviewSummary.degraded}
                  />
                ) : null}
                {ragPreviewSummary.fallback.length > 0 ? (
                  <PreviewMessageCard
                    title="Fallback"
                    tone="red"
                    items={ragPreviewSummary.fallback}
                  />
                ) : null}
              </div>
            )}
          </div>

          {/* 5. 底层分析网格 */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
            {/* 执行结果 */}
            <div className={cn(CARD_BASE, 'lg:col-span-3')}>
              <h3 className={SECTION_TITLE}>
                <LayoutGrid className="size-4 text-primary" /> 执行结果
                <MetricInfoTooltip label="执行结果说明" side="right">
                  每一行对应一个按钮。只点“漂移检查”时，RAG
                  预览和性能门禁保持待执行是正常的。
                </MetricInfoTooltip>
              </h3>
              <div className="space-y-2 pt-1">
                <ConclusionItem
                  label="RAG 预览"
                  status={runningStatusLabel(probeRunning, ragPreviewStatusLabel)}
                />
                <ConclusionItem
                  label="漂移检查"
                  status={runningStatusLabel(driftRunning, driftStatusLabel)}
                />
                <ConclusionItem label="性能门禁" status={perfGateStatus} />
                <ConclusionItem
                  label="报告时间"
                  status={fmtDateTime(health.data?.payload?.time)}
                />
                </div>
              </div>

            {/* 依赖资源 */}
            <div
              id="diagnostics-dependency-card"
              className={cn(CARD_BASE, 'lg:col-span-3 scroll-mt-24')}
            >
              <h3 className={SECTION_TITLE}>
                <Database className="size-4 text-primary" /> 依赖资源
              </h3>
              <div className="grid grid-cols-2 gap-2 pt-1">
                {dependencyItems.map((item) => (
                  <ResourceItem
                    key={item.label}
                    label={item.label}
                    status={
                      item.status === 'unknown' && (depsLoading || readyLoading)
                        ? 'checking'
                        : item.status
                    }
                  />
                ))}
              </div>
            </div>

            {/* 排障摘要 */}
            <div className={cn(CARD_BASE, 'lg:col-span-3 flex flex-col')}>
              <div className="mb-3 flex items-start justify-between gap-3">
                <h3 className="m-0 flex items-center gap-2 text-[14px] font-semibold text-foreground">
                  <Terminal className="size-4 text-primary" /> 排障摘要
                </h3>
                <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                  原始响应已收起
                </span>
              </div>
              <div className="space-y-2">
                <DiagnosticsSummaryItem
                  label="系统健康"
                  value={healthSummaryStatusLabel(
                    health.isPending,
                    systemStatus.label
                  )}
                  detail={serviceTime}
                  tone={systemStatus.tone}
                />
                <DiagnosticsSummaryItem
                  label="依赖就绪"
                  value={readyStatusLabel(
                    readyLoading,
                    readySnapshot,
                    readyOk,
                    '已就绪',
                    '需排查'
                  )}
                  detail={readySnapshot ? '/health/ready 已返回' : '等待就绪响应'}
                  tone={okTone(readyOk, 'blue')}
                />
                <DiagnosticsSummaryItem
                  label="诊断任务"
                  value={manualDiagnosticsStatusLabel}
                  detail={diagnosticSummaryDetail(hasManualDiagnostics)}
                  tone={hasManualDiagnostics ? 'green' : 'slate'}
                />
              </div>
              <RawDiagnosticsDetails
                json={backendSummaryJson}
                onCopy={() => copyToClipboard(backendSummaryJson)}
              />
            </div>

            {/* 后端建议 */}
            <div className={cn(CARD_BASE, 'lg:col-span-3')}>
              <h3 className={SECTION_TITLE}>
                <Zap className="size-4 text-primary" /> 后端建议
              </h3>
              {backendRecommendationItems.length > 0 ? (
                <div className="space-y-2">
                  {backendRecommendationItems.map((recommendation) => (
                    <p
                      key={recommendation.key}
                      className="rounded-lg border border-border/50 bg-muted/40 px-3 py-2 text-[12px] leading-relaxed text-muted-foreground"
                    >
                      {recommendation.text}
                    </p>
                  ))}
                </div>
              ) : (
                <div className="flex min-h-[170px] flex-col items-center justify-center">
                  <div className="mb-4 flex size-14 items-center justify-center rounded-full border border-dashed border-border bg-muted/50">
                    <Activity className="size-6 text-muted-foreground/40" />
                  </div>
                  <DiagnosticStatusPill
                    value="待生成建议"
                    tone="slate"
                    className="h-6 px-2.5"
                  />
                  <p className="mt-2 text-[11px] text-muted-foreground/80">
                    运行 RAG 预览、漂移检查或性能门禁后生成建议
                  </p>
                </div>
              )}
            </div>
            </div>
          </div>
        </TooltipProvider>
        </PageScaffold>
    </AppFrame>
  )
}

function ConclusionItem({ label, status }: Readonly<{ label: string; status: string }>) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border/50 bg-card px-2.5 py-2">
      <div className="flex items-center gap-3">
        <div className="size-5 rounded bg-muted/50 border border-border/50 flex items-center justify-center">
          <LayoutGrid className="size-3 text-muted-foreground/80" />
        </div>
        <span className="text-[12px] font-medium text-muted-foreground">{label}</span>
      </div>
      <DiagnosticStatusPill
        value={status}
        tone={statusPillTone(status)}
        className="h-5 max-w-[108px] px-1.5 text-[10px]"
      />
    </div>
  )
}

function ResourceItem({ label, status }: Readonly<{ label: string; status: string }>) {
  const normalized = String(status || 'unknown').toLowerCase()
  const displayLabel = resourceStatusLabel(normalized)

  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-border/50 bg-card px-2.5 py-2">
      <span className="text-[12px] font-medium text-muted-foreground">{label}</span>
      <span
        className={cn(
          'rounded border px-2 py-0.5 text-[9px] font-bold uppercase',
          resourceStatusClass(normalized)
        )}
      >
        {displayLabel}
      </span>
    </div>
  )
}

function DiagnosticsSummaryItem({
  label,
  detail,
  value,
  tone = 'slate',
}: Readonly<{
  label: string
  detail: string
  value: string
  tone?: 'slate' | 'green' | 'blue' | 'red' | 'amber'
}>) {
  const toneClass =
    {
      slate: 'border-border/50 bg-muted/50 text-muted-foreground',
      green: 'border-success/20 bg-success/10 text-success',
      blue: 'border-primary/20 bg-primary/10 text-primary',
      red: 'border-destructive/20 bg-destructive/10 text-destructive',
      amber: 'border-warning/20 bg-warning/10 text-warning',
    }[tone] || 'border-border/50 bg-muted/50 text-muted-foreground'

  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-border/50 bg-muted/40 px-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-[11px] font-medium text-muted-foreground">
          {label}
        </p>
        <p className="mt-0.5 truncate text-[10px] text-muted-foreground/80">{detail}</p>
      </div>
      <span
        className={cn(
          'shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold',
          toneClass
        )}
      >
        {value}
      </span>
    </div>
  )
}

function RawDiagnosticsDetails({
  json,
  onCopy,
}: Readonly<{
  json: string
  onCopy: () => void
}>) {
  return (
    <details className="group mt-3 rounded-xl border border-border/60 bg-card">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5 text-[12px] font-semibold text-foreground transition-colors hover:bg-primary/[0.06] [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-2">
          <FileJson className="size-3.5 text-primary" />
          查看原始响应
        </span>
        <ChevronDown className="size-3.5 text-muted-foreground/80 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-border/50 p-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <p className="text-[11px] font-medium text-muted-foreground/80">
            仅用于排障复制，不默认占用诊断主视图。
          </p>
          <Button
            variant="outline"
            size="sm"
            aria-label="复制原始响应 JSON"
            className="h-7 gap-1.5 rounded-lg border-border bg-card text-[11px] font-semibold text-muted-foreground hover:bg-primary/10 hover:text-primary"
            onClick={onCopy}
          >
            <Copy className="size-3" /> 复制
          </Button>
        </div>
        <pre className="max-h-[180px] overflow-auto rounded-lg bg-foreground p-3 font-mono text-[11px] leading-5 text-background/85 custom-scrollbar">
          {json}
        </pre>
      </div>
    </details>
  )
}

function PreviewInfoCard({
  label,
  mono = true,
  value,
}: Readonly<{
  label: string
  mono?: boolean
  value: string
}>) {
  return (
    <div className="rounded-xl border border-border/60 bg-card/70 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground/80">
        {label}
      </div>
      <div
        className={cn(
          'mt-1 truncate text-[12px] font-semibold text-foreground',
          mono && 'font-mono'
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  )
}

function PreviewListCard({
  emptyLabel,
  items,
  title,
}: Readonly<{
  emptyLabel: string
  items: Array<{ label: string; value: string }>
  title: string
}>) {
  return (
    <div className="rounded-xl border border-border/60 bg-card/60 p-3">
      <div className="text-[12px] font-semibold text-foreground">{title}</div>
      {items.length > 0 ? (
        <div className="mt-2 space-y-2">
          {items.map((item) => (
            <div
              key={`${title}-${item.label}-${item.value}`}
              className="rounded-lg border border-border/50 bg-background/70 px-2.5 py-2"
            >
              <div className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground/75">
                {item.label}
              </div>
              <div className="mt-1 break-words font-mono text-[11px] text-foreground/90">
                {item.value}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-2 text-[11px] text-muted-foreground/75">
          {emptyLabel}
        </div>
      )}
    </div>
  )
}

function PreviewMessageCard({
  items,
  title,
  tone,
}: Readonly<{
  items: string[]
  title: string
  tone: 'amber' | 'red'
}>) {
  return (
    <div
      className={cn(
        'rounded-xl border px-3 py-3',
        tone === 'amber'
          ? 'border-warning/20 bg-warning/10'
          : 'border-destructive/20 bg-destructive/10'
      )}
    >
      <div
        className={cn(
          'text-[12px] font-semibold',
          tone === 'amber' ? 'text-warning' : 'text-destructive'
        )}
      >
        {title}
      </div>
      <div className="mt-2 space-y-1.5">
        {items.map((item) => (
          <div
            key={`${title}-${item}`}
            className="rounded-lg bg-background/75 px-2.5 py-2 font-mono text-[11px] text-foreground/90"
          >
            {item}
          </div>
        ))}
      </div>
    </div>
  )
}
