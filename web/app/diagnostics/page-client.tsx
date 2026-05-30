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
import { PageHeader } from '@/components/ui/page-header'
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
import { useBackendMeta } from '@/hooks/use-backend-meta'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi, documentApi, observabilityApi, ragApi } from '@/lib/api'
import { API_V1_BASE_URL } from '@/lib/env'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'
import type {
  Dataset,
  DatasetListResponse,
  Document as KnowledgeDocument,
  DocumentList,
  OnlineQualitySummaryResponse,
  PromptPreviewResponse,
} from '@/types'
import type { DepsDiagnosticsResponse } from '@/types'

// --- Constants & Styles ---

const CARD_BASE =
  'bg-card rounded-2xl border border-slate-200/70 shadow-[0_1px_3px_rgba(15,23,42,0.03)] p-4'
const SECTION_TITLE =
  'text-[14px] font-semibold text-slate-950 flex items-center gap-2 mb-4'
const FIELD_LABEL = 'text-[12px] font-medium text-slate-500 mb-1.5 block'
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

// --- Helper Functions ---

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function pickMetricNumber(source: any, keys: string[]): number | null {
  if (!source || typeof source !== 'object') return null
  for (const k of keys) {
    const v = source[k]
    if (typeof v === 'number' && Number.isFinite(v)) return v
    if (typeof v === 'string' && Number.isFinite(Number(v))) return Number(v)
  }
  return null
}

function pickMetricNumberByPath(source: any, paths: string[]): number | null {
  if (!source || typeof source !== 'object') return null
  for (const path of paths) {
    const value = path
      .split('.')
      .reduce<any>(
        (current, key) =>
          current && typeof current === 'object' ? current[key] : undefined,
        source
      )
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

function dependencyStatus(value: unknown): string {
  if (!value || typeof value !== 'object') return 'unknown'
  const status = String(
    (value as Record<string, unknown>).status || ''
  ).toLowerCase()
  if (status) return status
  if ((value as Record<string, unknown>).ok === true) return 'connected'
  if ((value as Record<string, unknown>).ok === false) return 'disconnected'
  return 'unknown'
}

async function copyToClipboard(text = ''): Promise<void> {
  try {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
      throw new Error('Clipboard API unavailable')
    }
    await navigator.clipboard.writeText(text)
    toast.success('已复制')
  } catch (err) {
    toast.error('复制失败')
  }
}

// --- Reusable UI Parts ---

const TOP_HUD_TONE_CLASSES = {
  slate: 'bg-slate-50 text-slate-400 border-slate-100',
  green: 'bg-emerald-50 text-emerald-500 border-emerald-100',
  amber: 'bg-amber-50 text-amber-500 border-amber-100',
  red: 'bg-red-50 text-red-500 border-red-100',
  blue: 'bg-blue-50 text-blue-500 border-blue-100',
  purple: 'bg-purple-50 text-purple-500 border-purple-100',
} as const

function TopHUDTile({
  icon: Icon,
  label,
  value,
  detail,
  tone = 'slate',
}: {
  icon: LucideIcon
  label: string
  value: string
  detail: string
  tone?: keyof typeof TOP_HUD_TONE_CLASSES
}) {
  const toneClasses = TOP_HUD_TONE_CLASSES[tone] || TOP_HUD_TONE_CLASSES.slate

  return (
    <div className="min-h-[84px] rounded-xl border border-slate-200/70 bg-card px-4 py-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.02)] flex items-center gap-3.5">
      <div
        className={cn(
          'size-11 shrink-0 rounded-full flex items-center justify-center border shadow-inner',
          toneClasses
        )}
      >
        <Icon className="size-5" />
      </div>
      <div className="min-w-0">
        <span className="block truncate text-[11px] font-medium text-slate-500">
          {label}
        </span>
        <h4
          className={cn(
            'mt-1 whitespace-nowrap font-semibold leading-none tracking-[-0.02em] text-slate-950',
            value.length > 14 ? 'text-[13px]' : 'text-[15px]'
          )}
        >
          {value}
        </h4>
        <p className="mt-1.5 truncate text-[9px] font-bold uppercase tracking-[0.16em] text-slate-300">
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
}: {
  icon: LucideIcon
  title: string
  subtitle: string
  selected: boolean
  value: string
  source: string
  tone?: MetricTone
  onToggle: () => void
}) {
  const colorMap: Record<MetricTone, string> = {
    blue: 'bg-blue-50 text-blue-600 border-blue-100',
    green: 'bg-emerald-50 text-emerald-600 border-emerald-100',
    amber: 'bg-amber-50 text-amber-600 border-amber-100',
    red: 'bg-red-50 text-red-500 border-red-100',
    slate: 'bg-slate-50 text-slate-400 border-slate-100',
    purple: 'bg-purple-50 text-purple-600 border-purple-100',
  }

  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onToggle}
      className={cn(
        'group flex min-h-[68px] w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-all',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/25',
        selected
          ? 'border-blue-200 bg-blue-50/40 shadow-[0_1px_6px_rgba(37,99,235,0.08)]'
          : 'border-slate-200/70 bg-card hover:border-slate-300 hover:bg-slate-50'
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
            <p className="truncate text-[12px] font-semibold leading-tight text-slate-700 group-hover:text-slate-900">
              {title}
            </p>
            <p className="mt-0.5 truncate text-[10px] font-medium text-slate-400 group-hover:text-slate-500">
              {subtitle}
            </p>
          </div>
          <span
            className={cn(
              'shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold',
              selected
                ? 'border-blue-100 bg-card text-blue-600'
                : 'border-slate-100 bg-slate-50 text-slate-400'
            )}
          >
            {selected ? '已选' : '未选'}
          </span>
        </div>
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <span
            className={cn(
              'truncate text-[11px] font-semibold',
              isPendingMetricLabel(value) ? 'text-slate-400' : 'text-slate-700'
            )}
          >
            {value}
          </span>
          <span className="truncate text-[9px] font-medium uppercase tracking-[0.12em] text-slate-300">
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
}: {
  icon: LucideIcon
  label: string
  value: string
  help?: ReactNode
  loading?: boolean
  tone?: string
}) {
  const isWait = isPendingMetricLabel(value)
  const toneClass =
    {
      slate: 'bg-slate-50 text-slate-400 border-slate-100',
      green: 'bg-emerald-50 text-emerald-500 border-emerald-100',
      amber: 'bg-amber-50 text-amber-500 border-amber-100',
      red: 'bg-red-50 text-red-500 border-red-100',
    }[tone] || 'bg-slate-50 text-slate-400 border-slate-100'

  return (
    <div className="group flex min-h-[86px] items-center gap-4 rounded-2xl border border-slate-200/70 bg-card p-4 shadow-[0_1px_2px_rgba(15,23,42,0.02)] transition-all hover:shadow-md">
      <div
        className={cn(
          'size-10 rounded-full border flex items-center justify-center transition-colors',
          toneClass
        )}
      >
        <Icon className="size-5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex items-center gap-1.5">
          <p className="text-[11px] font-medium leading-none text-slate-500">
            {label}
          </p>
          {help ? (
            <MetricInfoTooltip label={`${label}说明`}>{help}</MetricInfoTooltip>
          ) : null}
        </div>
        {loading ? (
          <div className="h-5 w-20 bg-slate-50 animate-pulse rounded" />
        ) : (
          <p
            className={cn(
              'text-[15px] font-semibold',
              isWait ? 'text-slate-300' : 'text-slate-800'
            )}
          >
            {value}
          </p>
        )}
      </div>
    </div>
  )
}

function MetricInfoTooltip({
  label,
  children,
  side = 'top',
}: {
  label: string
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="inline-flex size-4 items-center justify-center rounded-full border border-slate-200 bg-card text-slate-400 transition-colors hover:border-blue-200 hover:bg-blue-50 hover:text-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-200"
        >
          <Info className="size-3" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent
        side={side}
        align="center"
        className="max-w-[280px] rounded-lg bg-slate-950 px-3 py-2 text-[11px] leading-5 text-slate-50 shadow-lg"
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
}: {
  icon: LucideIcon
  title: string
  action: string
  text: string
}) {
  return (
    <div className="flex gap-3 rounded-xl border border-border/80 bg-card/75 px-3 py-2.5">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/10 text-primary">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <p className="text-[12px] font-semibold text-slate-900">{title}</p>
        <p className="mt-0.5 text-[10px] font-semibold text-primary">
          {action}
        </p>
        <p className="mt-1 text-[11px] leading-5 text-slate-500">{text}</p>
      </div>
    </div>
  )
}

// --- Page Component ---

export default function DiagnosticsPage() {
  const health = useBackendHealth()
  const meta = useBackendMeta()

  // Config States
  const [probeDatasetId, setProbeDatasetId] = useState('')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [probeQuery, setProbeQuery] = useState(
    '请输入要检索的问题或说明诊断目标...'
  )
  const [probeResult, setProbeResult] = useState<PromptPreviewResponse | null>(
    null
  )
  const [probeRunning, setProbeRunning] = useState(false)
  const [selectedDimensions, setSelectedDimensions] = useState<
    DiagnosticDimensionId[]
  >(DIAGNOSTIC_DIMENSIONS.map((dimension) => dimension.id))

  // Param States
  const [driftSampleN, setDriftSampleN] = useState(200)
  const [driftThreshold, setDriftThreshold] = useState(0.05)
  const [driftSnapshot, setDriftSnapshot] = useState<Record<
    string,
    any
  > | null>(null)
  const [driftRunning, setDriftRunning] = useState(false)

  const [perfSuiteIterations, setPerfSuiteIterations] = useState(10)
  const [perfSuiteTimeoutSec, setPerfSuiteTimeoutSec] = useState(2)
  const [perfSuiteResult, setPerfSuiteResult] = useState<Record<
    string,
    any
  > | null>(null)
  const [perfSuiteRunning, setPerfSuiteRunning] = useState(false)

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.list({ limit: 200 }),
    queryFn: (): Promise<DatasetListResponse> => datasetApi.list({ limit: 200 }),
    staleTime: 30_000,
  })
  const datasets = getListItems<Dataset>(datasetsQuery.data, EMPTY_DATASETS)
  const datasetsLoading = datasetsQuery.isPending
  const activeDatasetId = probeDatasetId || datasets[0]?.id || ''

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
    queryFn: async (): Promise<Record<string, any> | null> => {
      try {
        const response = await fetch(`${API_V1_BASE_URL}/health/ready`, {
          cache: 'no-store',
        })
        const payload = await response.json().catch(() => null)
        return payload && typeof payload === 'object' ? payload : null
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
    try {
      const res = await ragApi.promptPreview({
        query: probeQuery.trim(),
        dataset_id: activeDatasetId || undefined,
        document_ids: validSelectedDocumentIds,
        structured_output: false,
      })
      setProbeResult(res)
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
      setDriftSnapshot(res as Record<string, any>)
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
      setPerfSuiteResult(res as Record<string, any>)
      toast.success('性能门禁完成')
    } catch (err) {
      toast.error(formatApiError(err, '性能门禁失败'))
    } finally {
      setPerfSuiteRunning(false)
    }
  }

  const healthOk = Boolean(health.data?.payload?.ok)
  const readyOk = Boolean(readySnapshot?.ok)
  const systemStatusLabel = healthOk && readyOk ? '正常' : '需要排查'
  const systemStatusTone = healthOk && readyOk ? 'green' : 'red'
  const serviceTime = fmtDateTime(meta.data?.time || health.data?.payload?.time)
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
  const driftStatusLabel = driftSnapshot
    ? driftMetric === null
      ? MISSING_RESULT_LABEL
      : `${driftMetric.toFixed(3)} 漂移率`
    : PENDING_RUN_LABEL
  const perfGateStatus = perfSuiteResult
    ? String(
        perfSuiteResult.status ||
          perfSuiteResult.gate_status ||
          perfSuiteResult.result ||
          '已运行'
      )
    : PENDING_RUN_LABEL
  const perfGateTone: MetricTone = /pass|passed|ok|success|通过|已运行/i.test(
    perfGateStatus
  )
    ? 'green'
    : perfSuiteResult
      ? 'amber'
      : 'slate'
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
      label: '向量库',
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
    { label: '服务 API', status: healthOk ? 'connected' : 'disconnected' },
  ]
  const selectedDataset =
    datasets.find((dataset) => dataset.id === activeDatasetId) || null
  const selectedDocuments = documents.filter((document) =>
    validSelectedDocumentIds.includes(document.id)
  )
  const selectedDocumentLabel =
    validSelectedDocumentIds.length > 0
      ? `已选 ${validSelectedDocumentIds.length} 个文档`
      : documentsLoading
        ? '正在加载文档...'
        : activeDatasetId
          ? '当前数据集全部文档'
          : '请先选择数据集'

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
  const ragPreviewStatusLabel = hasProbeResult
    ? citationCount === null
      ? MISSING_RESULT_LABEL
      : `${citationCount.toLocaleString()} 条引用`
    : PENDING_RUN_LABEL
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
      tone:
        citationCount === null
          ? 'slate'
          : citationCount > 0
            ? 'green'
            : 'amber',
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
      value:
        latencyMs !== null
          ? fmtMetric(latencyMs, 0, 'ms')
          : perfSuiteResult
            ? perfGateStatus
            : hasProbeResult
              ? MISSING_RESULT_LABEL
              : PENDING_RUN_LABEL,
      source:
        latencyMs !== null
          ? 'metrics'
          : perfSuiteResult
            ? 'perf-suite'
            : PENDING_RUN_LABEL,
      tone:
        latencyMs !== null
          ? latencyMs <= 1000
            ? 'green'
            : latencyMs <= 3000
              ? 'amber'
              : 'red'
          : perfGateTone,
    },
  }

  const backendSummaryJson = useMemo(
    () =>
      prettyJson({
        status:
          probeResult || driftSnapshot || perfSuiteResult
            ? 'completed'
            : 'not_run',
        code: 0,
        message:
          probeResult || driftSnapshot || perfSuiteResult
            ? '诊断已执行完毕'
            : '诊断尚未执行，请配置后运行',
        data: {
          dataset_id: activeDatasetId || null,
          document_ids: validSelectedDocumentIds,
          selected_dimensions: selectedDimensions,
          rag_preview: probeResult ?? null,
          embedding_drift: driftSnapshot ?? null,
          perf_suite: perfSuiteResult ?? null,
          deps: depsSnapshot ?? null,
        },
        metrics: {
          ...(probeResult?.metrics ?? {}),
          drift_rate: driftMetric,
          perf_gate: perfGateStatus,
        },
        timestamp: health.data?.payload?.time ?? null,
      }),
    [
      activeDatasetId,
      validSelectedDocumentIds,
      selectedDimensions,
      probeResult,
      driftSnapshot,
      perfSuiteResult,
      depsSnapshot,
      driftMetric,
      perfGateStatus,
      health.data,
    ]
  )
  const hasManualDiagnostics = Boolean(
    probeResult || driftSnapshot || perfSuiteResult
  )
  const manualDiagnosticsStatus =
    probeRunning || driftRunning || perfSuiteRunning
      ? '执行中'
      : hasManualDiagnostics
        ? '已生成'
        : PENDING_RUN_LABEL

  const backendRecommendations = ((onlineQuality as any)?.recommendations ??
    []) as string[]

  return (
    <AppFrame>
      <PageScaffold
        title="诊断中心"
        description="全面诊断系统健康状态、服务依赖与 RAG 质量，保障稳定可靠运行"
	        icon={Activity}
	        iconColor="text-blue-600"
	        size="full"
	        showHeader={false}
	        bodyGutter="dense"
	        bodyClassName="bg-slate-50/50 pt-3 pb-6"
	      >
	        <TooltipProvider delayDuration={120}>
	          <div className="flex flex-col gap-3">
          <PageHeader
            title="诊断中心"
            description="全面诊断系统健康状态、服务依赖与 RAG 质量，保障稳定可靠运行"
            iconImage="diagnostics"
            icon={Activity}
            iconColor="text-info"
            compact
            className="p-0"
          >
            <div className="flex shrink-0 items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 rounded-full border-red-100 bg-red-50 px-3 text-[12px] font-semibold text-red-500 shadow-none hover:bg-red-100 hover:text-red-600"
              >
                <ShieldAlert className="size-3.5" />
                服务健康排查
              </Button>
              <Button
                variant="outline"
                size="icon"
                aria-label="刷新诊断状态"
                className="h-8 w-8 rounded-lg border-slate-200 bg-card"
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
          </PageHeader>

          {/* Top HUD Cards Row */}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <TopHUDTile
              icon={ShieldCheck}
              label="系统健康"
              value={health.isPending ? '检查中' : healthOk ? '正常' : '异常'}
              detail="STATUS_OK"
              tone={healthOk ? 'green' : 'red'}
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
              value={
                readyLoading && !readySnapshot
                  ? '检查中'
                  : readyOk
                    ? '全部就绪'
                    : '异常'
              }
              detail="READY"
              tone={readyOk ? 'blue' : 'red'}
            />
            <TopHUDTile
              icon={Activity}
              label="在线评估"
              value={
                onlineQualityLoading
                  ? '检查中'
                  : onlineQuality?.enabled
                    ? '已启用'
                    : '未启用'
              }
              detail="ONLINE_METRICS"
              tone="purple"
            />
            <TopHUDTile
              icon={Gauge}
              label="性能门禁"
              value={perfGateStatus}
              detail="PERF_GATE"
              tone={perfGateTone}
            />
            <TopHUDTile
              icon={Timer}
              label="向量后端"
              value={
                readySnapshot?.vector?.backend ||
	                health.data?.payload?.vector_backend ||
	                'milvus'
	              }
	              detail="VECTOR_PROVIDER"
	              tone="green"
	            />
	          </div>

	          <DiagnosticUseGuide />

	          {/* Main Config Section */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
            {/* 1. 诊断配置 */}
            <div className={cn(CARD_BASE, 'lg:col-span-4')}>
              <h3 className={SECTION_TITLE}>
                <FileJson className="size-4 text-blue-500" /> 诊断配置
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
                      className="h-9 rounded-lg border-slate-200 bg-slate-50/50 text-[13px]"
                    >
                      <span className="truncate">
                        {datasetsLoading
                          ? '正在加载数据集...'
                          : selectedDataset
                            ? `${datasetLabel(selectedDataset)} [${shortId(selectedDataset.id)}]`
                            : '暂无可用数据集'}
                      </span>
                    </SelectTrigger>
                    <SelectContent>
                      {datasets.map((dataset) => (
                        <SelectItem key={dataset.id} value={dataset.id}>
                          <span className="flex min-w-0 flex-col">
                            <span className="truncate text-[13px] font-medium">
                              {datasetLabel(dataset)}
                            </span>
                            <span className="truncate text-[10px] text-slate-400">
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
                      className="h-9 rounded-lg border-slate-200 bg-slate-50/50 text-[13px]"
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
                                    ? 'border-blue-200 bg-blue-50 text-blue-600'
                                    : 'border-slate-200 bg-card text-transparent'
                                )}
                              >
                                {selected ? '✓' : ''}
                              </span>
                              <span className="flex min-w-0 flex-col">
                                <span className="truncate text-[13px] font-medium">
                                  {documentLabel(document)}
                                </span>
                                <span className="truncate text-[10px] text-slate-400">
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
                          className="rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-600"
                        >
                          {documentLabel(document)}
                        </span>
                      ))}
                      {selectedDocuments.length > 3 ? (
                        <span className="rounded-full border border-slate-100 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-400">
                          +{selectedDocuments.length - 3}
                        </span>
                      ) : null}
                    </div>
                  ) : (
                    <p className="mt-1 text-[10px] font-medium text-slate-400">
                      不选择文档时，诊断当前数据集的全部可检索内容。
                    </p>
                  )}
                </div>
                <div>
                  <Label className={FIELD_LABEL}>查询提示 / 问题</Label>
                  <Textarea
                    value={probeQuery}
                    onChange={(e) => setProbeQuery(e.target.value)}
                    className="min-h-[72px] bg-slate-50/50 border-slate-200 resize-none text-[13px]"
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
                    className="h-9 flex-none gap-2 border-slate-200 text-[13px] font-semibold"
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
                <h3 className="m-0 flex items-center gap-2 text-[14px] font-semibold text-slate-950">
                  <LayoutGrid className="size-4 text-blue-500" /> 诊断维度
                </h3>
                <span className="rounded-full border border-slate-100 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold text-slate-500">
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
                <Settings2 className="size-4 text-blue-500" /> 参数配置
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
                      className="h-9 bg-slate-50/50 border-slate-200 text-[13px]"
                    />
                  </div>
                  <div>
                    <Label className={FIELD_LABEL}>采样数量</Label>
                    <Input
                      type="number"
                      value={driftSampleN}
                      onChange={(e) => setDriftSampleN(Number(e.target.value))}
                      className="h-9 bg-slate-50/50 border-slate-200 text-[13px]"
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
                      className="h-9 bg-slate-50/50 border-slate-200 text-[13px]"
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
                      className="h-9 bg-slate-50/50 border-slate-200 text-[13px]"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <Button
                    variant="outline"
                    className="h-9 w-full gap-2 border-slate-200 text-[13px] font-semibold"
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
                    className="h-9 w-full gap-2 border-slate-200 text-[13px] font-semibold"
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
	            <div className="mb-3 flex items-center justify-between gap-3 px-2">
	              <h3 className="m-0 flex items-center gap-2 text-[14px] font-semibold text-slate-950">
	                <BarChart3 className="size-4 text-blue-500" /> 核心指标
	                <MetricInfoTooltip label="核心指标说明" side="right">
	                  这里不是自动生成的总报告。RAG
	                  预览、漂移检查、性能门禁是三个独立探针，分别点击后只更新自己负责的指标。
	                </MetricInfoTooltip>
	              </h3>
	              <p className="text-[11px] font-medium text-slate-400">
	                先跑左侧按钮，再看对应指标
	              </p>
	            </div>
	            <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
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
	                tone={
	                  citationCount === null
	                    ? 'slate'
	                    : citationCount > 0
                      ? 'green'
                      : 'amber'
	                }
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
	                value={
	                  driftRunning
	                    ? '检查中'
	                    : driftSnapshot
	                      ? fmtExecutedMetric(driftMetric, 3)
	                      : PENDING_RUN_LABEL
	                }
	                help="点击“漂移检查”后生成。后端抽样比较当前 embedding 配置与已存向量；0 表示样本未发现漂移，比例升高说明可能需要重新嵌入。"
	                loading={driftRunning}
	                tone={metricTone(driftMetric)}
	              />
	              <MainMetricCard
	                icon={ShieldCheck}
	                label="性能门禁"
	                value={perfSuiteRunning ? '执行中' : perfGateStatus}
	                help="点击“性能门禁”后生成。用于快速判断后端诊断接口在当前迭代次数和超时设置下是否稳定通过。"
	                loading={perfSuiteRunning}
	                tone={perfGateTone}
	              />
	            </div>
	          </div>

	          {/* 5. 底层分析网格 */}
	          <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
	            {/* 执行结果 */}
	            <div className={cn(CARD_BASE, 'lg:col-span-3')}>
	              <h3 className={SECTION_TITLE}>
	                <LayoutGrid className="size-4 text-blue-500" /> 执行结果
	                <MetricInfoTooltip label="执行结果说明" side="right">
	                  每一行对应一个按钮。只点“漂移检查”时，RAG
	                  预览和性能门禁保持待执行是正常的。
	                </MetricInfoTooltip>
	              </h3>
	              <div className="space-y-2 pt-1">
                <ConclusionItem
                  label="RAG 预览"
                  status={probeRunning ? '执行中' : ragPreviewStatusLabel}
                />
                <ConclusionItem
                  label="漂移检查"
                  status={driftRunning ? '执行中' : driftStatusLabel}
                />
                <ConclusionItem label="性能门禁" status={perfGateStatus} />
                <ConclusionItem
                  label="报告时间"
                  status={fmtDateTime(health.data?.payload?.time)}
                />
	              </div>
	            </div>

            {/* 依赖资源 */}
            <div className={cn(CARD_BASE, 'lg:col-span-3')}>
              <h3 className={SECTION_TITLE}>
                <Database className="size-4 text-blue-500" /> 依赖资源
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
                <h3 className="m-0 flex items-center gap-2 text-[14px] font-semibold text-slate-950">
                  <Terminal className="size-4 text-blue-500" /> 排障摘要
                </h3>
                <span className="rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-600">
                  原始响应已收起
                </span>
              </div>
              <div className="space-y-2">
                <DiagnosticsSummaryItem
                  label="系统健康"
                  value={health.isPending ? '检查中' : systemStatusLabel}
                  detail={serviceTime}
                  tone={systemStatusTone}
                />
                <DiagnosticsSummaryItem
                  label="依赖就绪"
                  value={
                    readyLoading && !readySnapshot
                      ? '检查中'
                      : readyOk
                        ? '已就绪'
                        : '需排查'
                  }
                  detail={readySnapshot ? '/health/ready 已返回' : '等待就绪响应'}
                  tone={readyOk ? 'blue' : 'red'}
                />
                <DiagnosticsSummaryItem
                  label="诊断任务"
                  value={manualDiagnosticsStatus}
                  detail={
                    hasManualDiagnostics
                      ? '已有 RAG / Drift / Perf 结果'
                      : '需手动运行左侧诊断'
                  }
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
                <Zap className="size-4 text-blue-500" /> 后端建议
              </h3>
              {backendRecommendations.length > 0 ? (
                <div className="space-y-2">
                  {backendRecommendations.map((r: string, i: number) => (
                    <p
                      key={i}
                      className="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2 text-[12px] leading-relaxed text-slate-600"
                    >
                      {r}
                    </p>
                  ))}
                </div>
              ) : (
                <div className="flex min-h-[170px] flex-col items-center justify-center">
                  <div className="mb-4 flex size-14 items-center justify-center rounded-full border border-dashed border-slate-200 bg-slate-50">
                    <Activity className="size-6 text-slate-200" />
                  </div>
                  <p className="text-[13px] font-semibold text-slate-400">
                    暂无后端建议
                  </p>
                  <p className="mt-1 text-[11px] text-slate-300">
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

function ConclusionItem({ label, status }: { label: string; status: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 bg-card px-2.5 py-2">
      <div className="flex items-center gap-3">
        <div className="size-5 rounded bg-slate-50 border border-slate-100 flex items-center justify-center">
          <LayoutGrid className="size-3 text-slate-400" />
        </div>
        <span className="text-[12px] font-medium text-slate-600">{label}</span>
      </div>
      <span className="truncate text-right text-[11px] font-semibold text-slate-400">
        {status}
      </span>
    </div>
  )
}

function ResourceItem({ label, status }: { label: string; status: string }) {
  const normalized = String(status || 'unknown').toLowerCase()
  const isOk = ['connected', 'ok', 'ready'].includes(normalized)
  const isChecking = ['checking', 'pending'].includes(normalized)

  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-100 bg-card px-2.5 py-2">
      <span className="text-[12px] font-medium text-slate-600">{label}</span>
      <span
        className={cn(
          'rounded border px-2 py-0.5 text-[9px] font-bold uppercase',
          isOk
            ? 'border-emerald-100/70 bg-emerald-50 text-emerald-600'
            : isChecking
              ? 'border-blue-100/70 bg-blue-50 text-blue-600'
              : 'border-red-100/70 bg-red-50 text-red-500'
        )}
      >
        {status}
      </span>
    </div>
  )
}

function DiagnosticsSummaryItem({
  label,
  detail,
  value,
  tone = 'slate',
}: {
  label: string
  detail: string
  value: string
  tone?: 'slate' | 'green' | 'blue' | 'red' | 'amber'
}) {
  const toneClass =
    {
      slate: 'border-slate-100 bg-slate-50 text-slate-600',
      green: 'border-emerald-100 bg-emerald-50 text-emerald-600',
      blue: 'border-blue-100 bg-blue-50 text-blue-600',
      red: 'border-red-100 bg-red-50 text-red-500',
      amber: 'border-amber-100 bg-amber-50 text-amber-600',
    }[tone] || 'border-slate-100 bg-slate-50 text-slate-600'

  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-100 bg-slate-50/60 px-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-[11px] font-medium text-slate-500">
          {label}
        </p>
        <p className="mt-0.5 truncate text-[10px] text-slate-400">{detail}</p>
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
}: {
  json: string
  onCopy: () => void
}) {
  return (
    <details className="group mt-3 rounded-xl border border-slate-200/70 bg-card">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5 text-[12px] font-semibold text-slate-700 transition-colors hover:bg-blue-50/50 [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-2">
          <FileJson className="size-3.5 text-blue-500" />
          查看原始响应
        </span>
        <ChevronDown className="size-3.5 text-slate-400 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-slate-100 p-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <p className="text-[11px] font-medium text-slate-400">
            仅用于排障复制，不默认占用诊断主视图。
          </p>
          <Button
            variant="outline"
            size="sm"
            aria-label="复制原始响应 JSON"
            className="h-7 gap-1.5 rounded-lg border-slate-200 bg-card text-[11px] font-semibold text-slate-600 hover:bg-blue-50 hover:text-blue-600"
            onClick={onCopy}
          >
            <Copy className="size-3" /> 复制
          </Button>
        </div>
        <pre className="max-h-[180px] overflow-auto rounded-lg bg-slate-950 p-3 font-mono text-[11px] leading-5 text-blue-100 custom-scrollbar">
          {json}
        </pre>
      </div>
    </details>
  )
}
