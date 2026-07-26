'use client'

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  Check,
  CheckCircle2,
  CircleDashed,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  Download,
  FileDigit,
  FileCheck2,
  FileSearch,
  Gauge,
  Radar,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
  UploadCloud,
  Workflow,
} from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { EChartsOption } from 'echarts'
import { toast } from 'sonner'

import { datasetApi, documentApi, observabilityApi } from '@/lib/api'
import { globalEventBus } from '@/lib/event-bus'
import type {
  DatasetPrecheckFileOut,
  DatasetPrecheckNearDupResponse,
  DatasetPrecheckSamplesResponse,
  DatasetPrecheckSummary,
  Document,
  IngestionDashboardSummaryResponse,
  TaskQueueObservabilitySnapshotResponse,
} from '@/types'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { useDatasets } from '@/hooks/use-datasets'
import { usePathname, useRouter } from '@/i18n/navigation'
import { Button } from '@/components/ui/button'
import { EChart } from '@/components/ui/echart'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { DropZone, type DropZoneHandle } from '@/components/ingestion/drop-zone'
import { EmptyState } from '@/components/ingestion/empty-state'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import {
  buildEvidenceSlotReason,
  buildEvidenceSlotTags,
  buildFileTypeDistribution,
  buildDocumentThroughputAreaRows,
  buildPdfDispositionBreakdown,
  buildSalesAuditProfile,
  buildThroughputAreaRows,
  computeDocsPerMinute,
  computeDurationPercentiles,
  computeMegabytesPerSecond,
  getDocumentKind,
  getDocumentKindAccent,
  matchesReasonFilter,
} from '@/components/ingestion/monitor-utils'

import { buildDemoDocuments } from './demo-documents'
import { IngestionViewSwitch } from './view-switch'
import { LoadingWireframe } from './components/loading-wireframe'
import { SalesPanelHeader } from './components/sales-panel-header'
import {
  anonymizeEvidenceName,
  buildDemoNearDupResponse,
  buildDemoPrecheckSamples,
  buildDemoPrecheckSummary,
} from './demo-precheck'
import {
  collectSalesAuditSampleFiles,
  downloadTextFile,
  estimatePdfPageCountFromSignals,
  formatClockLabel,
  formatClockSecondsLabel,
  formatDurationClock,
  formatMonthDayLabel,
  getDocumentRuntimeStats,
  getPersistedSalesAuditDisposition,
  getPersistedSampleDisposition,
  isExecutionMonitorDocument,
  safeNumber,
} from './document-signals'
import {
  SALES_PANEL_CLASS,
  SALES_PANEL_INSET_CLASS,
  SALES_SUMMARY_STRIP_CLASS,
  buildDocumentProfileFile,
  buildPrecheckProfileFile,
  formatPdfPageAverageLabel,
  formatStructureAverageLabel,
  getAuditRailStatusTone,
  getDocumentStatusLabel,
  getDocumentStatusTone,
  getDriverDotTone,
  getHeaderAnimation,
  getHeaderBodyVisibilityClass,
  getPdfSplitColor,
  getProgressTone,
  getQueueOutcomeReason,
  getRecentLogDetail,
  getRecentLogTone,
  getRiskTagPresentation,
  getSalesCoreIcon,
  getSalesCoreIconTone,
  getSeverityFill,
  getTaskProgress,
  resolveFallbackComplexity,
  resolveThroughputRowsSource,
  type SalesEvidenceTableRow,
  type SalesProcessingLane,
} from './presentation'
import { buildSafeReportFilename, renderReportHtmlToJpeg } from './report-canvas'
import { buildReportHtml, escapeHtml } from './report-html'
import type { IngestionMode, SampleDisposition } from './types'

const DATASET_ALL = '__all__'
const EXECUTION_TASK_PAGE_SIZE = 5
const PRECHECK_SAMPLE_NUMERATOR = 3
const PRECHECK_SAMPLE_DENOMINATOR = 1000
const PRECHECK_SAMPLE_MAX = 2000
const INGESTION_BACKGROUND_CLASS =
  'bg-background bg-[radial-gradient(circle_at_top,hsl(var(--info)/0.10),transparent_34rem)] dark:bg-background'
const INGESTION_HERO_PANEL_CLASS =
  'relative overflow-hidden rounded-[28px] border border-info/30 bg-[linear-gradient(135deg,hsl(var(--card)/0.92),hsl(var(--info)/0.10)_45%,hsl(var(--background)/0.82))] shadow-[0_24px_70px_-48px_hsl(var(--info)/0.55)] backdrop-blur-2xl'

type AuditDispositionFilter = 'all' | 'pending' | 'manual' | 'approved'

const EMPTY_INGESTION_SUMMARY: IngestionDashboardSummaryResponse = {
  window_hours: 0,
  bucket_minutes: 20,
  window_start: '',
  window_end: '',
  dataset_id: null,
  created_count: 0,
  by_status: {},
  by_stage_processing: {},
  avg_completed_latency_sec: null,
  top_error_reasons: {},
  timeseries: {
    ts_ms: [],
    completed: [],
    failed: [],
    quarantined: [],
    cancelled: [],
  },
}

export default function KnowledgeIngestionPageClient() {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const reduceMotion = useReducedMotion()
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const dropZoneRef = useRef<DropZoneHandle>(null)
  const demoMode =
    /(^|\/)demo(\/|$)/.test(pathname) && searchParams.get('demo') === '1'
  const mode: IngestionMode =
    searchParams.get('mode') === 'execution-monitor'
      ? 'execution-monitor'
      : 'sales-audit'
  const showSalesPolicyBadge = mode === 'sales-audit'
  const [datasetScope, setDatasetScope] = useState(
    searchParams.get('datasetId') || DATASET_ALL
  )
  const [desktopScopeCollapsed, setDesktopScopeCollapsed] = useState(true)
  const [headerCollapsed, setHeaderCollapsed] = useState(false)
  const [selectedReason, setSelectedReason] = useState<string | null>(null)
  const [auditDispositionFilter, setAuditDispositionFilter] =
    useState<AuditDispositionFilter>('all')
  const [selectedAuditIds, setSelectedAuditIds] = useState<string[]>([])
  const [sampleDispositions, setSampleDispositions] = useState<
    Record<string, SampleDisposition>
  >({})
  const [activeDetailId, setActiveDetailId] = useState<string | null>(null)
  const [selectedEvidenceFile, setSelectedEvidenceFile] =
    useState<DatasetPrecheckFileOut | null>(null)
  const [successPulseVisible, setSuccessPulseVisible] = useState(false)
  const [executionTaskPage, setExecutionTaskPage] = useState(1)
  const [renderTimestamp] = useState(() => Date.now())

  const selectedDatasetId = datasetScope === DATASET_ALL ? null : datasetScope
  const { datasets } = useDatasets()

  const documentsQuery = useQuery({
    queryKey: ['knowledge-ingestion-documents', selectedDatasetId],
    queryFn: async ({ signal }) => {
      const response = await documentApi.list(
        {
          limit: 200,
          dataset_id: selectedDatasetId ?? undefined,
        },
        { signal }
      )
      return response.items ?? []
    },
    staleTime: 10_000,
    refetchInterval: demoMode ? false : 25_000,
  })

  const summaryQuery = useQuery<IngestionDashboardSummaryResponse | null>({
    queryKey: ['knowledge-ingestion-summary', selectedDatasetId],
    queryFn: async () => {
      try {
        return await observabilityApi.getIngestionDashboardSummary({
          window_hours: 12,
          bucket_minutes: 20,
          dataset_id: selectedDatasetId ?? undefined,
        })
      } catch {
        return null
      }
    },
    staleTime: 10_000,
    refetchInterval: demoMode ? false : 25_000,
  })

  const taskQueueQuery =
    useQuery<TaskQueueObservabilitySnapshotResponse | null>({
      queryKey: ['knowledge-ingestion-task-queue'],
      queryFn: async () => {
        try {
          return await observabilityApi.getTaskQueueSnapshot()
        } catch {
          return null
        }
      },
      enabled: mode === 'execution-monitor' && !demoMode,
      staleTime: 10_000,
      refetchInterval: demoMode ? false : 25_000,
    })

  const precheckRunsQuery = useQuery({
    queryKey: ['knowledge-ingestion-precheck-runs', selectedDatasetId],
    queryFn: async () => {
      if (!selectedDatasetId) return []
      const response = await datasetApi.listPrecheckScanRuns(
        selectedDatasetId,
        { skip: 0, limit: 20 }
      )
      return response.items ?? []
    },
    enabled: Boolean(selectedDatasetId) && !demoMode,
    staleTime: 10_000,
  })

  const latestPrecheckRun = useMemo(
    () =>
      (precheckRunsQuery.data ?? []).find(
        (run) => String(run.status || '').toLowerCase() === 'completed'
      ) ??
      (precheckRunsQuery.data ?? [])[0] ??
      null,
    [precheckRunsQuery.data]
  )

  const precheckSummaryQuery = useQuery<DatasetPrecheckSummary | null>({
    queryKey: [
      'knowledge-ingestion-precheck-summary',
      selectedDatasetId,
      latestPrecheckRun?.id,
    ],
    queryFn: async () => {
      if (!selectedDatasetId || !latestPrecheckRun?.id) return null
      return await datasetApi.getPrecheckSummary(
        selectedDatasetId,
        latestPrecheckRun.id
      )
    },
    enabled: Boolean(selectedDatasetId && latestPrecheckRun?.id) && !demoMode,
    staleTime: 10_000,
  })

  const precheckSamplesQuery = useQuery<DatasetPrecheckSamplesResponse | null>({
    queryKey: [
      'knowledge-ingestion-precheck-samples',
      selectedDatasetId,
      latestPrecheckRun?.id,
    ],
    queryFn: async () => {
      if (!selectedDatasetId || !latestPrecheckRun?.id) return null
      return await datasetApi.getPrecheckSamples(
        selectedDatasetId,
        latestPrecheckRun.id,
        { prefer_artifact: true, size: 12 }
      )
    },
    enabled: Boolean(selectedDatasetId && latestPrecheckRun?.id) && !demoMode,
    staleTime: 10_000,
  })

  const precheckNearDupQuery = useQuery<DatasetPrecheckNearDupResponse | null>({
    queryKey: [
      'knowledge-ingestion-precheck-near-dup',
      selectedDatasetId,
      latestPrecheckRun?.id,
    ],
    queryFn: async () => {
      if (!selectedDatasetId || !latestPrecheckRun?.id) return null
      return await datasetApi.getPrecheckNearDups(
        selectedDatasetId,
        latestPrecheckRun.id
      )
    },
    enabled: Boolean(selectedDatasetId && latestPrecheckRun?.id) && !demoMode,
    staleTime: 10_000,
  })

  const documents = useMemo(
    () =>
      demoMode
        ? buildDemoDocuments(documentsQuery.data ?? [])
        : (documentsQuery.data ?? []),
    [demoMode, documentsQuery.data]
  )
  const executionDocuments = useMemo(
    () => documents.filter(isExecutionMonitorDocument),
    [documents]
  )
  const summary = useMemo(
    () => summaryQuery.data ?? EMPTY_INGESTION_SUMMARY,
    [summaryQuery.data]
  )
  const taskQueueSnapshot = taskQueueQuery.data ?? null
  const taskQueueStatusLabel = useMemo(() => {
    if (demoMode) return 'Demo 运行态'
    if (taskQueueQuery.isFetching && !taskQueueSnapshot) return '读取队列'
    if (!taskQueueSnapshot) return '队列未知'
    if (!taskQueueSnapshot.enabled) return '队列未启用'
    if (!taskQueueSnapshot.broker_up) return 'Broker 异常'
    return 'Broker 正常'
  }, [demoMode, taskQueueQuery.isFetching, taskQueueSnapshot])
  const taskQueueStatusTone = useMemo(() => {
    if (demoMode || !taskQueueSnapshot)
      return 'border-border/18 bg-muted/[0.08] text-foreground'
    if (!taskQueueSnapshot.enabled)
      return 'border-warning/18 bg-warning/[0.08] text-warning'
    if (!taskQueueSnapshot.broker_up)
      return 'border-rose/18 bg-rose/[0.08] text-rose'
    return 'border-success/18 bg-success/[0.08] text-success'
  }, [demoMode, taskQueueSnapshot])
  const salesAuditSummary = useMemo(
    () =>
      demoMode
        ? buildDemoPrecheckSummary(documents)
        : (precheckSummaryQuery.data ?? null),
    [demoMode, documents, precheckSummaryQuery.data]
  )
  const salesAuditSamples = useMemo(
    () =>
      demoMode
        ? buildDemoPrecheckSamples(documents)
        : (precheckSamplesQuery.data ?? null),
    [demoMode, documents, precheckSamplesQuery.data]
  )
  const salesAuditNearDup = useMemo(
    () =>
      demoMode
        ? buildDemoNearDupResponse()
        : (precheckNearDupQuery.data ?? null),
    [demoMode, precheckNearDupQuery.data]
  )

  useEffect(() => {
    const node = scrollContainerRef.current
    if (!node) return

    const handleScroll = () => {
      if (mode !== 'sales-audit') {
        setHeaderCollapsed(false)
        return
      }

      setHeaderCollapsed((previous) => {
        const collapseThreshold = 96
        const expandThreshold = 40
        if (previous) return node.scrollTop > expandThreshold
        return node.scrollTop > collapseThreshold
      })
    }

    handleScroll()
    node.addEventListener('scroll', handleScroll, { passive: true })
    return () => node.removeEventListener('scroll', handleScroll)
  }, [mode])

  useEffect(() => {
    if (!successPulseVisible) return
    const timeoutId = globalThis.window.setTimeout(() => {
      setSuccessPulseVisible(false)
    }, 1400)
    return () => globalThis.window.clearTimeout(timeoutId)
  }, [successPulseVisible])

  const selectedDatasetLabel = useMemo(() => {
    if (!selectedDatasetId) return '全部项目'
    return (
      datasets.find((dataset) => dataset.id === selectedDatasetId)?.name ||
      selectedDatasetId
    )
  }, [datasets, selectedDatasetId])

  const statusCounts = useMemo(
    () => ({
      completed: safeNumber(summary.by_status.completed),
      processing: safeNumber(summary.by_status.processing),
      pending: safeNumber(summary.by_status.pending),
      failed: safeNumber(summary.by_status.failed),
      quarantined: safeNumber(summary.by_status.quarantined),
    }),
    [summary.by_status]
  )

  const summaryThroughputRows = useMemo(
    () => buildThroughputAreaRows(summary.timeseries),
    [summary.timeseries]
  )
  const documentThroughputRows = useMemo(
    () =>
      buildDocumentThroughputAreaRows(executionDocuments, {
        bucketMinutes: summary.bucket_minutes || 60,
        maxRows: 96,
      }),
    [executionDocuments, summary.bucket_minutes]
  )
  const throughputRowsSource = useMemo(
    () =>
      resolveThroughputRowsSource(
        summaryThroughputRows.some((row) => row.total > 0),
        documentThroughputRows.length
      ),
    [documentThroughputRows.length, summaryThroughputRows]
  )
  const throughputRows = useMemo(
    () =>
      throughputRowsSource === 'documents'
        ? documentThroughputRows
        : summaryThroughputRows,
    [documentThroughputRows, summaryThroughputRows, throughputRowsSource]
  )
  const docsPerMinute = useMemo(
    () =>
      computeDocsPerMinute(
        throughputRows.map((row) => ({
          t: row.ts,
          completed: row.completed,
          failed: row.failed,
          quarantined: row.quarantined,
        }))
    ),
    [throughputRows]
  )
  const megabytesPerSecond = useMemo(
    () => computeMegabytesPerSecond(executionDocuments),
    [executionDocuments]
  )
  const recentThroughputDetail = useMemo(() => {
    if (throughputRowsSource === 'documents') {
      return '按文档更新时间聚合'
    }

    const recentBuckets = throughputRows
      .filter((row) => row.ts > 0)
      .slice(-5)

    if (recentBuckets.length >= 2) {
      const first = recentBuckets[0]?.ts ?? 0
      const last = recentBuckets.at(-1)?.ts ?? 0
      const spanMinutes = Math.round((last - first) / 60_000)

      if (spanMinutes >= 60) {
        return `最近 ${Math.max(1, Math.round(spanMinutes / 60))} 小时桶均值`
      }
      if (spanMinutes > 0) {
        return `最近 ${spanMinutes} 分钟桶均值`
      }
    }

    return '后端时间桶均值'
  }, [throughputRows, throughputRowsSource])
  const throughputTrendWindowLabel = useMemo(() => {
    if (throughputRowsSource === 'documents') return '文档历史时序'
    const hours = Number(summary.window_hours || 0)
    return hours > 0 ? `近 ${hours} 小时` : '后端时间窗'
  }, [summary.window_hours, throughputRowsSource])
  const durationPercentiles = useMemo(
    () => computeDurationPercentiles(executionDocuments),
    [executionDocuments]
  )
  const pdfDisposition = useMemo(
    () => buildPdfDispositionBreakdown(executionDocuments),
    [executionDocuments]
  )
  const salesAuditPersistedDispositions = useMemo(() => {
    const persisted = Object.fromEntries(
      collectSalesAuditSampleFiles(salesAuditSamples)
        .map((file) => [
          String(file.name),
          getPersistedSalesAuditDisposition(file),
        ] as const)
        .filter((entry): entry is [string, SampleDisposition] => Boolean(entry[1]))
    )

    return persisted
  }, [salesAuditSamples])
  const resolvedSampleDispositions = useMemo(() => {
    const executionPersisted = Object.fromEntries(
      executionDocuments
        .map((document) => [
          document.id,
          getPersistedSampleDisposition(document),
        ] as const)
        .filter((entry): entry is [string, SampleDisposition] => Boolean(entry[1]))
    )

    return {
      ...executionPersisted,
      ...salesAuditPersistedDispositions,
      ...sampleDispositions,
    }
  }, [executionDocuments, salesAuditPersistedDispositions, sampleDispositions])

  const reviewQueue = statusCounts.failed + statusCounts.quarantined
  const approvedCount = Object.values(resolvedSampleDispositions).filter(
    (value) => value === 'approved'
  ).length
  const manualCount = Object.values(resolvedSampleDispositions).filter(
    (value) => value === 'manual'
  ).length
  const readyRate = documents.length
    ? Math.round(
        ((statusCounts.completed + approvedCount) / documents.length) * 100
      )
    : 0

  const auditSourceDocuments = mode === 'execution-monitor' ? executionDocuments : documents
  const auditCandidates = useMemo(() => {
    const prioritised = auditSourceDocuments.filter(
      (document) =>
        ['failed', 'quarantined', 'processing', 'pending'].includes(
          String(document.status)
        ) || Boolean(document.error_message)
    )
    return (prioritised.length ? prioritised : auditSourceDocuments).slice(0, 10)
  }, [auditSourceDocuments])

  const reasonFilteredAuditSamples = useMemo(
    () =>
      auditCandidates.filter((document) =>
        matchesReasonFilter(document, selectedReason)
      ),
    [auditCandidates, selectedReason]
  )

  const auditRailCounts = useMemo(() => {
    const counts = {
      all: reasonFilteredAuditSamples.length,
      pending: 0,
      manual: 0,
      approved: 0,
    }
    for (const document of reasonFilteredAuditSamples) {
      const disposition = resolvedSampleDispositions[document.id]
      if (disposition === 'manual') counts.manual += 1
      else if (disposition === 'approved') counts.approved += 1
      else counts.pending += 1
    }
    return counts
  }, [reasonFilteredAuditSamples, resolvedSampleDispositions])

  const visibleAuditSamples = useMemo(() => {
    if (auditDispositionFilter === 'all') return reasonFilteredAuditSamples
    return reasonFilteredAuditSamples.filter((document) => {
      const disposition = resolvedSampleDispositions[document.id]
      if (auditDispositionFilter === 'pending') return !disposition
      return disposition === auditDispositionFilter
    })
  }, [
    auditDispositionFilter,
    reasonFilteredAuditSamples,
    resolvedSampleDispositions,
  ])

  const activeAuditDocument = useMemo(
    () => documents.find((document) => document.id === activeDetailId) || null,
    [activeDetailId, documents]
  )
  const activeAuditIsDemo = Boolean(
    activeAuditDocument?.id?.startsWith('demo-')
  )

  const executionProcessedTotal = useMemo(
    () =>
      statusCounts.completed + statusCounts.failed + statusCounts.quarantined,
    [statusCounts.completed, statusCounts.failed, statusCounts.quarantined]
  )

  const executionSuccessRate = useMemo(() => {
    if (!executionProcessedTotal) return 0
    return Math.round((statusCounts.completed / executionProcessedTotal) * 100)
  }, [executionProcessedTotal, statusCounts.completed])

  const executionRetryRate = useMemo(() => {
    if (!executionProcessedTotal) return 0
    return Math.round(
      ((statusCounts.failed + statusCounts.quarantined) /
        executionProcessedTotal) *
        100
    )
  }, [executionProcessedTotal, statusCounts.failed, statusCounts.quarantined])

  const executionOcrUsageRate = useMemo(() => {
    const totalPdf = pdfDisposition.reduce((sum, item) => sum + item.count, 0)
    const ocrCount =
      pdfDisposition.find((item) => item.label === 'OCR')?.count ??
      pdfDisposition.find((item) => item.label === 'SCAN')?.count ??
      0
    if (!totalPdf) return 0
    return Math.round((ocrCount / totalPdf) * 100)
  }, [pdfDisposition])

  const executionAverageDuration = useMemo(() => {
    const value = durationPercentiles.p50 || durationPercentiles.p90 || 0
    return value ? `${value.toFixed(1)} min / 文件` : '-- / 文件'
  }, [durationPercentiles.p50, durationPercentiles.p90])

  const executionProcessingMode = useMemo(() => {
    if (demoMode) {
      return {
        value: '演示运行',
        detail: 'Demo 运行态',
        tone: 'text-info',
      }
    }

    if (!taskQueueSnapshot) {
      return {
        value: '观测中',
        detail: taskQueueStatusLabel,
        tone: 'text-muted-foreground',
      }
    }

    if (!taskQueueSnapshot.enabled) {
      return {
        value: '直连处理',
        detail: '队列未启用',
        tone: 'text-warning',
      }
    }

    if (!taskQueueSnapshot.broker_up) {
      return {
        value: '队列异常',
        detail: taskQueueSnapshot.error || 'Broker 异常',
        tone: 'text-rose',
      }
    }

    const queueDepth =
      taskQueueSnapshot.queue_depth == null
        ? '--'
        : `${taskQueueSnapshot.queue_depth}`
    const workersActive =
      taskQueueSnapshot.workers_active == null
        ? '--'
        : `${taskQueueSnapshot.workers_active}`

    return {
      value: '异步队列',
      detail: `深度 ${queueDepth} · Worker ${workersActive}`,
      tone: 'text-success',
    }
  }, [
    demoMode,
    taskQueueSnapshot,
    taskQueueStatusLabel,
  ])

  const executionCharacterFootprint = useMemo(() => {
    const totalCharacters = executionDocuments.reduce(
      (sum, document) => sum + Number(document.total_characters || 0),
      0
    )
    if (totalCharacters > 0) {
      return `${totalCharacters.toLocaleString('zh-CN')} 字符`
    }
    if (executionDocuments.length > 0) return '字数待统计'
    return '暂无字数'
  }, [executionDocuments])

  const executionRunStateCards = useMemo(
    () => [
      {
        label: '监控范围',
        value: selectedDatasetLabel,
        suffix: '',
        icon: FileSearch,
        tone: 'text-info',
        detail: `${selectedDatasetId ? '当前数据集' : '跨数据集'} · ${executionCharacterFootprint}`,
      },
      {
        label: '处理模式',
        value: executionProcessingMode.value,
        suffix: '',
        icon: Workflow,
        tone: executionProcessingMode.tone,
        detail: executionProcessingMode.detail,
      },
      {
        label: '当前吞吐',
        value: `${docsPerMinute?.toFixed(1) ?? '0.0'} docs/min`,
        suffix: '',
        icon: Activity,
        tone: 'text-accent',
        detail: `${recentThroughputDetail} · ${megabytesPerSecond?.toFixed(2) ?? '0.00'} MB/s`,
      },
    ],
    [
      docsPerMinute,
      executionCharacterFootprint,
      executionProcessingMode.detail,
      executionProcessingMode.tone,
      executionProcessingMode.value,
      megabytesPerSecond,
      recentThroughputDetail,
      selectedDatasetId,
      selectedDatasetLabel,
    ]
  )

  const executionFileTypeDistributionRows = useMemo(() => {
    const palette = [
      { color: '#2563eb', tone: 'bg-info' },
      { color: '#16a34a', tone: 'bg-success' },
      { color: '#d97706', tone: 'bg-warning' },
      { color: '#e11d48', tone: 'bg-rose' },
      { color: '#7c3aed', tone: 'bg-accent' },
      { color: '#0f766e', tone: 'bg-teal' },
    ]

    return buildFileTypeDistribution(executionDocuments).map((item, index) => {
      const swatch = palette[index % palette.length]
      return {
        color: swatch.color,
        label: item.label,
        tone: swatch.tone,
        value: item.count,
      }
    })
  }, [executionDocuments])
  const executionFileTypeDistributionTotal = useMemo(
    () =>
      executionFileTypeDistributionRows.reduce(
        (sum, item) => sum + item.value,
        0
      ),
    [executionFileTypeDistributionRows]
  )
  const executionFileTypeDistributionOption = useMemo<EChartsOption>(
    () =>
      ({
        tooltip: {
          appendTo: 'body',
          confine: true,
          extraCssText:
            'border-radius:10px;padding:6px 8px;box-shadow:0 12px 28px rgba(15,23,42,.14);',
          formatter: (params: unknown) => {
            const item = Array.isArray(params) ? params[0] : params
            const payload =
              item && typeof item === 'object'
                ? (item as {
                    marker?: unknown
                    name?: unknown
                    percent?: unknown
                    value?: unknown
                  })
                : {}
            const marker =
              typeof payload.marker === 'string'
                ? payload.marker.replace('margin-right:4px;', 'margin-left:2px;')
                : ''
            const name = escapeHtml(payload.name ?? '未知类型')
            const value = Number(payload.value || 0).toLocaleString('zh-CN')
            const percent = Number(payload.percent || 0).toFixed(1)

            return `<div style="display:flex;align-items:center;gap:7px;white-space:nowrap;font-size:11px;line-height:1.25;"><span>${name}</span><span style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;">${value} 个 · ${percent}%</span>${marker}</div>`
          },
          position: (
            point: number[],
            _params: unknown,
            _dom: unknown,
            _rect: unknown,
            size: { contentSize: number[]; viewSize: number[] }
          ) => {
            const [x, y] = point
            const tooltipWidth = size.contentSize[0] || 120
            const tooltipHeight = size.contentSize[1] || 34
            const viewWidth = size.viewSize[0] || 0
            const viewHeight = size.viewSize[1] || 0

            return [
              Math.min(Math.max(8, x + 14), Math.max(8, viewWidth - tooltipWidth - 8)),
              Math.min(Math.max(8, y - tooltipHeight / 2), Math.max(8, viewHeight - tooltipHeight - 8)),
            ]
          },
          renderMode: 'html',
          trigger: 'item',
        },
        series: [
          {
            avoidLabelOverlap: true,
            center: ['50%', '50%'],
            data: executionFileTypeDistributionRows.length
              ? executionFileTypeDistributionRows.map((item) => ({
                  itemStyle: { color: item.color },
                  name: item.label,
                  value: item.value,
                }))
              : [
                  {
                    itemStyle: { color: 'rgba(148,163,184,0.35)' },
                    name: '暂无数据',
                    value: 1,
                  },
                ],
            itemStyle: {
              borderColor: '#ffffff',
              borderRadius: 4,
              borderWidth: 2,
            },
            label: { show: false },
            labelLine: { show: false },
            name: '文件类型',
            radius: ['52%', '76%'],
            type: 'pie',
          },
        ],
      }),
    [executionFileTypeDistributionRows]
  )

  const executionPipelineState = useMemo(() => {
    const total = executionDocuments.length
    const safeTotal = Math.max(1, total)
    const executionStatusCounts = {
      completed: executionDocuments.filter(
        (document) => String(document.status || '').toLowerCase() === 'completed'
      ).length,
      failed: executionDocuments.filter(
        (document) => String(document.status || '').toLowerCase() === 'failed'
      ).length,
      quarantined: executionDocuments.filter(
        (document) => String(document.status || '').toLowerCase() === 'quarantined'
      ).length,
    }
    const parserFailures = executionStatusCounts.failed + executionStatusCounts.quarantined
    const processingDocuments = executionDocuments.filter(
      (document) => String(document.status || '').toLowerCase() === 'processing'
    )
    const totalChunks = executionDocuments.reduce(
      (sum, document) => sum + Number(document.chunk_count || 0),
      0
    )

    const stageIncludes = (document: Document, keywords: string[]) => {
      const stage = String(document.current_stage || '').toLowerCase()
      return keywords.some((keyword) => stage.includes(keyword))
    }
    const progressOf = (document: Document) =>
      Math.max(0, Math.min(100, Number(document.processing_progress || 0)))
    const isCompleted = (document: Document) =>
      String(document.status || '').toLowerCase() === 'completed'
    const isTerminal = (document: Document) =>
      ['completed', 'failed', 'quarantined'].includes(
        String(document.status || '').toLowerCase()
      )

    const parserDoneDocuments = executionDocuments.filter(
      (document) => isTerminal(document) || progressOf(document) >= 45
    )
    const parserDoneDocumentIds = new Set(parserDoneDocuments.map((document) => document.id))
    const parserRunning = processingDocuments.filter(
      (document) =>
        !parserDoneDocumentIds.has(document.id) &&
        (progressOf(document) < 45 ||
          stageIncludes(document, ['parse', 'parser', 'extract', 'ocr', 'mineru']))
    ).length
    const parserDone = parserDoneDocuments.length
    const parserWaiting = Math.max(0, total - parserDone - parserRunning)

    const chunkerDoneDocuments = executionDocuments.filter(
      (document) => isCompleted(document) || progressOf(document) >= 85
    )
    const chunkerDoneDocumentIds = new Set(chunkerDoneDocuments.map((document) => document.id))
    const chunkerRunning = processingDocuments.filter(
      (document) =>
        !chunkerDoneDocumentIds.has(document.id) &&
        (progressOf(document) >= 45 ||
          stageIncludes(document, [
            'chunk',
            'split',
            'segment',
            'embed',
            'index',
            'vector',
            'bm25',
          ]))
    ).length
    const chunkerDone = chunkerDoneDocuments.length
    const chunkerWaiting = Math.max(0, total - chunkerDone - chunkerRunning)

    const governanceQueue = reviewQueue + manualCount
    const governanceDone = Math.max(
      0,
      Math.min(total, executionStatusCounts.completed + approvedCount - governanceQueue)
    )
    const governanceWaiting = Math.max(
      0,
      total - governanceDone - governanceQueue
    )
    const exportReady = executionStatusCounts.completed
    const exportWaiting = Math.max(0, total - exportReady)

    const resolveStatus = ({
      done,
      running,
      waiting,
      failed = 0,
    }: {
      done: number
      running: number
      waiting: number
      failed?: number
    }) => {
      if (!total) return { label: '未开始', tone: 'bg-muted', cardTone: 'border-border bg-background/75' }
      if (failed > 0) return { label: '有失败', tone: 'bg-rose', cardTone: 'border-rose/25 bg-rose/[0.04]' }
      if (running > 0) return { label: '进行中', tone: 'bg-info', cardTone: 'border-info/28 bg-info/[0.04]' }
      if (done >= total && waiting <= 0) return { label: '已完成', tone: 'bg-success', cardTone: 'border-success/28 bg-success/[0.04]' }
      if (waiting > 0) return { label: '等待中', tone: 'bg-warning', cardTone: 'border-warning/24 bg-warning/[0.04]' }
      return { label: '未开始', tone: 'bg-muted', cardTone: 'border-border bg-background/75' }
    }

    const parserStatus = resolveStatus({
      done: parserDone,
      failed: parserFailures,
      running: parserRunning,
      waiting: parserWaiting,
    })
    const chunkerStatus = resolveStatus({
      done: chunkerDone,
      running: chunkerRunning,
      waiting: chunkerWaiting,
    })
    const governanceStatus = resolveStatus({
      done: governanceDone,
      running: governanceQueue,
      waiting: governanceWaiting,
    })
    const exportStatus = resolveStatus({
      done: exportReady,
      running: 0,
      waiting: exportWaiting,
    })

    const parserProgress = total
      ? Math.round((Math.min(total, parserDone) / safeTotal) * 100)
      : 0
    const chunkerProgress = total
      ? Math.round((Math.min(total, chunkerDone) / safeTotal) * 100)
      : 0
    const governanceProgress = total
      ? Math.round((Math.min(total, governanceDone + governanceQueue) / safeTotal) * 100)
      : 0
    const exportProgress = total
      ? Math.round((Math.min(total, exportReady) / safeTotal) * 100)
      : 0
    const overallProgress = Math.round(
      parserProgress * 0.3 +
        chunkerProgress * 0.3 +
        governanceProgress * 0.2 +
        exportProgress * 0.2
    )

    return {
      estimateLabel: taskQueueSnapshot?.enabled ? '队列联动' : '自动估算',
      overallProgress,
      cards: [
        {
          key: 'parser',
          label: 'Parser',
          progress: parserProgress,
          statusLabel: parserStatus.label,
          statusTone: parserStatus.tone,
          tone: parserStatus.cardTone,
          metrics: [
            ['完成文档', `${parserDone}`],
            ['失败', `${parserFailures}`],
            ['待处理', `${parserWaiting}`],
          ],
        },
        {
          key: 'chunker',
          label: 'Chunker',
          progress: chunkerProgress,
          statusLabel: chunkerStatus.label,
          statusTone: chunkerStatus.tone,
          tone: chunkerStatus.cardTone,
          metrics: [
            ['完成文档', `${chunkerDone}`],
            ['分块数', totalChunks ? `${totalChunks}` : '预估'],
            ['等待中', `${chunkerWaiting}`],
          ],
        },
        {
          key: 'governance',
          label: 'Governance',
          progress: governanceProgress,
          statusLabel: governanceStatus.label,
          statusTone: governanceStatus.tone,
          tone: governanceStatus.cardTone,
          metrics: [
            ['自动通过', `${governanceDone}`],
            ['待复核', `${governanceQueue}`],
            ['等待中', `${governanceWaiting}`],
          ],
        },
        {
          key: 'export',
          label: '导出',
          progress: exportProgress,
          statusLabel: exportStatus.label,
          statusTone: exportStatus.tone,
          tone: exportStatus.cardTone,
          metrics: [
            ['可导出', `${exportReady}`],
            ['待同步', `${exportWaiting}`],
            ['模式', selectedDatasetId ? '单数据集' : '跨数据集'],
          ],
        },
      ],
    }
  }, [
    approvedCount,
    executionDocuments,
    manualCount,
    reviewQueue,
    selectedDatasetId,
    taskQueueSnapshot?.enabled,
  ])
  const executionPipelineCards = executionPipelineState.cards
  const executionOverallProgress = executionPipelineState.overallProgress

  const executionKpiCards = useMemo(
    () => [
      ...executionRunStateCards,
      {
        label: '平均处理耗时',
        value: executionAverageDuration.replace(' / 文件', ''),
        suffix: '/ 文件',
        icon: Clock3,
        tone: 'text-indigo',
        detail: '近 5 分钟平均',
      },
      {
        label: 'OCR 使用率',
        value: `${executionOcrUsageRate}%`,
        suffix: '',
        icon: Gauge,
        tone: 'text-success',
        detail: `${pdfDisposition.reduce((sum, item) => sum + item.count, 0)} 个 PDF`,
      },
      {
        label: '解析成功率',
        value: `${executionSuccessRate}%`,
        suffix: '',
        icon: CheckCircle2,
        tone: 'text-success',
        detail: `${statusCounts.completed} / ${Math.max(1, executionProcessedTotal)} 成功`,
      },
      {
        label: '失败重试率',
        value: `${executionRetryRate}%`,
        suffix: '',
        icon: RefreshCcw,
        tone: 'text-warning',
        detail: `${statusCounts.failed + statusCounts.quarantined} / ${Math.max(1, executionProcessedTotal)} 文件`,
      },
    ],
    [
      executionAverageDuration,
      executionRunStateCards,
      executionOcrUsageRate,
      executionProcessedTotal,
      executionRetryRate,
      executionSuccessRate,
      pdfDisposition,
      statusCounts.completed,
      statusCounts.failed,
      statusCounts.quarantined,
    ]
  )

  const recentQueueOutcomes = useMemo(() => {
    const outcomes = taskQueueSnapshot?.recent_job_outcomes ?? []
    return outcomes.slice(0, 5).map((item, index) => {
      const jobName = String(
        item.job_name || item.run_id || item.document_id || `job-${index + 1}`
      )
      const ok = item.ok === true
      const finishedAt = item.finished_at
        ? String(item.finished_at)
        : taskQueueSnapshot?.generated_at || renderTimestamp
      const elapsed = Number(item.elapsed_sec || 0)
      const reason = getQueueOutcomeReason(item, ok)
      const elapsedLabel = elapsed ? `${elapsed.toFixed(2)}s` : reason
      return {
        detail: `${jobName} · ${elapsedLabel}`,
        id: `${jobName}-${index}`,
        stage: ok ? '队列完成' : '队列异常',
        time: formatClockSecondsLabel(finishedAt),
        tone: ok ? 'bg-success' : 'bg-rose',
      }
    })
  }, [
    renderTimestamp,
    taskQueueSnapshot?.generated_at,
    taskQueueSnapshot?.recent_job_outcomes,
  ])

  const executionRecentLogs = useMemo(() => {
    if (recentQueueOutcomes.length) return recentQueueOutcomes

    return [...executionDocuments]
      .sort((left, right) => {
        const rightTs = new Date(
          String(
            right.updated_at || right.processed_at || right.created_at || ''
          )
        ).getTime()
        const leftTs = new Date(
          String(left.updated_at || left.processed_at || left.created_at || '')
        ).getTime()
        return rightTs - leftTs
      })
      .slice(0, 5)
      .map((document) => {
        const status = String(document.status || '').toLowerCase()
        return {
          id: document.id,
          time: formatClockSecondsLabel(
            document.updated_at ||
              document.processed_at ||
              document.created_at ||
              renderTimestamp
          ),
          stage: String(document.current_stage || '系统'),
          detail: getRecentLogDetail(status, document.filename),
          tone: getRecentLogTone(status),
        }
      })
  }, [executionDocuments, recentQueueOutcomes, renderTimestamp])

  const executionTaskRows = useMemo(() => {
    return [...executionDocuments]
      .sort((left, right) => {
        const rightTs = new Date(
          String(
            right.updated_at || right.processed_at || right.created_at || ''
          )
        ).getTime()
        const leftTs = new Date(
          String(left.updated_at || left.processed_at || left.created_at || '')
        ).getTime()
        return rightTs - leftTs
      })
  }, [executionDocuments])
  const executionTaskPageCount = useMemo(
    () =>
      Math.max(
        1,
        Math.ceil(executionTaskRows.length / EXECUTION_TASK_PAGE_SIZE)
      ),
    [executionTaskRows.length]
  )
  const visibleExecutionTaskRows = useMemo(() => {
    const pageStart = (executionTaskPage - 1) * EXECUTION_TASK_PAGE_SIZE
    return executionTaskRows.slice(
      pageStart,
      pageStart + EXECUTION_TASK_PAGE_SIZE
    )
  }, [executionTaskPage, executionTaskRows])

  useEffect(() => {
    setExecutionTaskPage((page) =>
      Math.min(Math.max(page, 1), executionTaskPageCount)
    )
  }, [executionTaskPageCount])

  const forecastPoints = useMemo(() => {
    if (!throughputRows.length) return []
    const last = throughputRows.at(-1)
    const base = last?.total ?? 0
    const rate = docsPerMinute ?? 0
    const stepMinutes = summary.bucket_minutes || 20
    return Array.from({ length: 3 }, (_, index) => ({
      ts: (last?.ts ?? renderTimestamp) + (index + 1) * stepMinutes * 60_000,
      total: Number(
        (base + ((rate * stepMinutes) / 60) * (index + 1)).toFixed(1)
      ),
    }))
  }, [docsPerMinute, renderTimestamp, summary.bucket_minutes, throughputRows])

  const predictionOption = useMemo<EChartsOption>(() => {
    const actualSeries = throughputRows.map((row) => [row.ts, row.total])
    const lastActualPoint = actualSeries.at(-1)
    const forecastSeries = lastActualPoint
      ? [
          [
            lastActualPoint[0],
            lastActualPoint[1],
          ],
          ...forecastPoints.map((row) => [row.ts, row.total]),
        ]
      : []

    return {
      tooltip: {
        trigger: 'axis',
      },
      grid: {
        left: 40,
        right: 16,
        top: 24,
        bottom: 28,
      },
      xAxis: {
        type: 'time',
        axisLabel: {
          color: '#64748b',
          formatter: (value: number) =>
            throughputRowsSource === 'documents'
              ? formatMonthDayLabel(Number(value))
              : formatClockLabel(Number(value)),
        },
        axisLine: {
          lineStyle: { color: 'rgba(100,116,139,0.35)' },
        },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#64748b' },
        splitLine: {
          lineStyle: { color: 'rgba(148,163,184,0.18)' },
        },
      },
      series: [
        {
          name:
            throughputRowsSource === 'documents'
              ? '文档完成数'
              : '当前处理效率',
          type: 'line',
          smooth: true,
          showSymbol: false,
          lineStyle: { color: '#0f766e', width: 2.5 },
          areaStyle: {
            color: 'rgba(15,118,110,0.14)',
          },
          data: actualSeries,
        },
        {
          name: '预测',
          type: 'line',
          smooth: true,
          showSymbol: false,
          lineStyle: { color: '#b45309', width: 2, type: 'dashed' },
          areaStyle: {
            color: 'rgba(180,83,9,0.08)',
          },
          data: forecastSeries,
        },
      ],
    }
  }, [forecastPoints, throughputRows, throughputRowsSource])

  const costRadarValues = useMemo(() => {
    const pdfCount = executionDocuments.filter(
      (document) => String(document.file_type || '').toLowerCase() === 'pdf'
    ).length
    const totalFiles = Math.max(1, executionDocuments.length)
    const precheckSampleFiles = collectSalesAuditSampleFiles(salesAuditSamples)
    const totalCharacters = executionDocuments.reduce(
      (sum, document) => sum + Number(document.total_characters || 0),
      0
    )
    const totalPdfPagesFromSamples = precheckSampleFiles.reduce(
      (sum, file) =>
        sum +
        Number(file.pdf_pages?.page_count || 0),
      0
    )
    const pdfDocuments = executionDocuments.filter(
      (document) => String(document.file_type || '').toLowerCase() === 'pdf'
    )
    const totalPdfPagesFromDocuments = pdfDocuments.reduce(
      (sum, document) => sum + getDocumentRuntimeStats(document).pageCount,
      0
    )
    const totalPdfPagesEstimated = pdfDocuments.reduce(
      (sum, document) =>
        sum +
        estimatePdfPageCountFromSignals({
          characters: Number(document.total_characters || 0),
          fileSize: Number(document.file_size || 0),
        }),
      0
    )
    const totalPdfPages =
      totalPdfPagesFromSamples ||
      totalPdfPagesFromDocuments ||
      totalPdfPagesEstimated
    const totalImageAssets = executionDocuments.reduce(
      (sum, document) => sum + getDocumentRuntimeStats(document).imageCount,
      0
    )
    const totalSizeMb =
      executionDocuments.reduce((sum, document) => sum + Number(document.file_size || 0), 0) /
      (1024 * 1024)
    const p90Duration = durationPercentiles.p90 || durationPercentiles.p50 || 0

    return [
      Math.min(100, Math.round((pdfCount / totalFiles) * 100)),
      Math.min(100, Math.round((totalPdfPages / Math.max(1, pdfCount * 80)) * 100)),
      Math.min(100, Math.round((totalCharacters / Math.max(1, totalFiles * 50_000)) * 100)),
      Math.min(100, Math.round((totalSizeMb / Math.max(1, totalFiles * 20)) * 100)),
      Math.min(100, Math.round((totalImageAssets / Math.max(1, pdfCount * 120)) * 100)),
      Math.min(100, Math.round((p90Duration / 20) * 100)),
      executionRetryRate,
    ]
  }, [
    durationPercentiles.p50,
    durationPercentiles.p90,
    executionDocuments,
    executionRetryRate,
    salesAuditSamples,
  ])

  const radarOption = useMemo<EChartsOption>(
    () =>
      ({
        tooltip: { trigger: 'item' },
        radar: {
          radius: '56%',
          center: ['50%', '54%'],
          splitNumber: 4,
          axisName: { color: '#475569', fontSize: 9 },
          splitLine: { lineStyle: { color: 'rgba(148,163,184,0.22)' } },
          splitArea: {
            areaStyle: {
              color: ['rgba(248,250,252,0.82)', 'rgba(241,245,249,0.46)'],
            },
          },
          indicator: [
            { name: 'PDF 占比', max: 100 },
            { name: '页数压力', max: 100 },
            { name: '字数压力', max: 100 },
            { name: '体积压力', max: 100 },
            { name: '图片资源', max: 100 },
            { name: '耗时压力', max: 100 },
            { name: '失败重试', max: 100 },
          ],
        },
        series: [
          {
            type: 'radar',
            data: [
              {
                value: costRadarValues,
                areaStyle: { color: 'hsl(var(--primary) / 0.12)' },
                lineStyle: { color: 'hsl(var(--primary))', width: 2 },
                itemStyle: { color: 'hsl(var(--primary))' },
              },
            ],
          },
        ],
      }),
    [costRadarValues]
  )

  const salesAuditProfile = useMemo(
    () =>
      salesAuditSummary
        ? buildSalesAuditProfile(salesAuditSummary, salesAuditNearDup)
        : null,
    [salesAuditNearDup, salesAuditSummary]
  )

  const ingestionRecommendationLabel = useMemo(() => {
    if (!salesAuditProfile) return '待预检'
    const labelMap: Record<string, string> = {
      固定报价: '可直接入库',
      阶梯报价: '分批入库',
      POC优先: '先抽样确认',
    }
    return labelMap[salesAuditProfile.pricingMode] || '待确认'
  }, [salesAuditProfile])

  const executionBatchAnalysis = useMemo(() => {
    const average = (values: number[]) => {
      const valid = values.filter((value) => Number.isFinite(value) && value > 0)
      if (!valid.length) return 0
      return valid.reduce((sum, value) => sum + value, 0) / valid.length
    }
    const clampScore = (value: number) => Math.max(0, Math.min(100, Math.round(value)))

    const precheckTotalFiles = Number(salesAuditSummary?.total_files || 0)
    const totalFiles = precheckTotalFiles || executionDocuments.length
    const totalSizeBytes =
      Number(salesAuditSummary?.total_size_bytes || 0) ||
      executionDocuments.reduce((sum, document) => sum + Number(document.file_size || 0), 0)
    const precheckTypeCounts = Object.fromEntries(
      Object.entries(salesAuditSummary?.by_file_type ?? {})
        .map(([fileType, count]) => [
          String(fileType || '').toLowerCase(),
          Number(count || 0),
        ])
        .filter(([fileType, count]) => Boolean(fileType) && Number(count) > 0)
    ) as Record<string, number>
    const fallbackTypeCounts = executionDocuments.reduce<Record<string, number>>(
      (acc, document) => {
        const fileType =
          String(document.file_type || '').trim().toLowerCase() || 'unknown'
        acc[fileType] = (acc[fileType] ?? 0) + 1
        return acc
      },
      {}
    )
    const presentFileTypeCounts = Object.keys(precheckTypeCounts).length
      ? precheckTypeCounts
      : fallbackTypeCounts
    const presentTypeCount = Object.values(presentFileTypeCounts).filter(
      (count) => Number(count || 0) > 0
    ).length
    const precheckPdfTotal =
      Number(salesAuditSummary?.pdf_scan.scanned || 0) +
      Number(salesAuditSummary?.pdf_scan.not_scanned || 0) +
      Number(salesAuditSummary?.pdf_scan.unknown || 0)
    const fallbackPdfTotal = executionDocuments.filter(
      (document) => String(document.file_type || '').toLowerCase() === 'pdf'
    ).length
    const pdfTotal = precheckPdfTotal || fallbackPdfTotal
    const totalCharacters = executionDocuments.reduce(
      (sum, document) => sum + Number(document.total_characters || 0),
      0
    )
    const samplePool = collectSalesAuditSampleFiles(salesAuditSamples)
    const needsReviewCount = Object.values(salesAuditSamples?.needs_review ?? {}).flat().length
    const profileFiles = samplePool.length
      ? samplePool.map(buildPrecheckProfileFile)
      : executionDocuments.map(buildDocumentProfileFile)
    const pdfProfileFiles = profileFiles.filter(
      (file) => file.fileType.toLowerCase() === 'pdf'
    )
    const avgPdfChars = average(pdfProfileFiles.map((file) => file.chars))
    const avgPdfPages = average(pdfProfileFiles.map((file) => file.pdfPages))
    const avgPdfImages = average(pdfProfileFiles.map((file) => file.imageCount))
    const avgPdfTables = average(pdfProfileFiles.map((file) => file.tableCount))
    const avgPdfBlocks = average(pdfProfileFiles.map((file) => file.blockCount))
    const hasPdfProfiles = pdfProfileFiles.length > 0
    const hasEstimatedPdfPages = pdfProfileFiles.some(
      (file) => file.pdfPages > 0 && file.pageCountEstimated
    )
    const avgSizeMb = average(profileFiles.map((file) => file.fileSize)) / (1024 * 1024)
    const proportionalSampleTarget = totalFiles
      ? Math.ceil((totalFiles * PRECHECK_SAMPLE_NUMERATOR) / PRECHECK_SAMPLE_DENOMINATOR)
      : 0
    const sampleTarget = totalFiles
      ? Math.min(
          totalFiles,
          Math.min(
            PRECHECK_SAMPLE_MAX,
            Math.max(1, presentTypeCount, proportionalSampleTarget)
          )
        )
      : 0
    const sampleTargetDetail =
      totalFiles > 0
        ? `3/1000 抽样 · 覆盖 ${presentTypeCount || 0} 类，每类至少 1 个 / 总 ${totalFiles.toLocaleString()} 个`
        : '等待文件进入监控'
    const pdfRatio = totalFiles ? pdfTotal / totalFiles : 0
    const fallbackComplexity = resolveFallbackComplexity({
      durationP90: durationPercentiles.p90 || 0,
      executionRetryRate,
      pdfRatio,
      totalCharacters,
      totalSizeBytes,
    })

    return {
      complexity: salesAuditProfile?.complexity ?? fallbackComplexity,
      sampleTarget,
      sourceLabel: salesAuditSummary ? '来自最新预检扫描' : '来自后端文档统计',
      totalFiles,
      pricingMode: salesAuditProfile?.pricingMode ?? (fallbackComplexity === '高' ? 'POC优先' : '阶梯报价'),
      distributionBars: [
        {
          color: '#2563eb',
          detail: totalFiles ? `${pdfTotal.toLocaleString()} / ${totalFiles.toLocaleString()} 个` : '等待文件进入监控',
          label: 'PDF 占比',
          score: clampScore(pdfRatio * 100),
          value: totalFiles ? `${Math.round(pdfRatio * 100)}%` : '待统计',
        },
        {
          color: '#0f766e',
          detail: '按 PDF 样本 text_characters 均值',
          label: 'PDF 平均字数',
          score: clampScore((avgPdfChars / 50_000) * 100),
          value: avgPdfChars ? `${Math.round(avgPdfChars).toLocaleString()} chars` : '待统计',
        },
        {
          color: '#f97316',
          detail: '优先使用后端 page_count，缺失时才按字数/体量估算',
          label: 'PDF 平均页数',
          score: clampScore((avgPdfPages / 80) * 100),
          value: formatPdfPageAverageLabel({
            avgPdfPages,
            hasEstimatedPdfPages,
            hasPdfProfiles,
          }),
        },
        {
          color: '#64748b',
          detail: avgPdfImages
            ? '来自后端 image_count / elements 图片引用'
            : '后端未检测到图片引用',
          label: 'PDF 图片数',
          score: clampScore((avgPdfImages / 120) * 100),
          value: hasPdfProfiles ? `${Math.round(avgPdfImages)} 个` : '无 PDF',
        },
        {
          color: '#7c3aed',
          detail: avgPdfTables
            ? '来自后端 table_count / elements 表格引用'
            : `结构块均值 ${Math.round(avgPdfBlocks).toLocaleString()} 个`,
          label: '表格/结构块',
          score: clampScore(Math.max(avgPdfTables * 10, avgPdfBlocks / 8)),
          value: formatStructureAverageLabel({
            avgPdfBlocks,
            avgPdfTables,
            hasPdfProfiles,
          }),
        },
        {
          color: '#0891b2',
          detail: '按当前批次文件均值',
          label: '平均体积',
          score: clampScore((avgSizeMb / 20) * 100),
          value: avgSizeMb ? `${avgSizeMb.toFixed(1)} MB` : '待统计',
        },
        {
          color: '#dc2626',
          detail: `失败或隔离 ${statusCounts.failed + statusCounts.quarantined} 个`,
          label: '失败重试率',
          score: clampScore(executionRetryRate),
          value: `${executionRetryRate}%`,
        },
      ],
      imageProxyNote: hasEstimatedPdfPages
        ? '页数缺失的 PDF 已按字数/体量标注估算；图片、表格与结构块优先读取后端元数据和 elements。'
        : '图片、表格、页数与结构块均优先读取后端元数据和 elements，不再用扫描页代理。',
      samplePoolLabel: `已回传样本池 ${samplePool.length || sampleTarget || 0} 个 · 大文件 ${salesAuditSamples?.top_large_files?.length ?? 0} · 长文本 ${salesAuditSamples?.top_long_text?.length ?? 0} · 复核 ${needsReviewCount}`,
      sampleTargetDetail,
      totalSizeLabel: formatFileSize(totalSizeBytes),
    }
  }, [
    durationPercentiles.p90,
    executionDocuments,
    executionRetryRate,
    salesAuditProfile?.complexity,
    salesAuditProfile?.pricingMode,
    salesAuditSamples,
    salesAuditSummary,
    statusCounts.failed,
    statusCounts.quarantined,
  ])

  const batchProfileBarOption = useMemo<EChartsOption>(
    () =>
      ({
        grid: { bottom: 8, left: 86, right: 74, top: 8 },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow' },
        },
        xAxis: {
          max: 100,
          min: 0,
          splitLine: { lineStyle: { color: 'rgba(148,163,184,0.14)' } },
          type: 'value',
        },
        yAxis: {
          axisLabel: { color: '#475569', fontSize: 10 },
          axisLine: { show: false },
          axisTick: { show: false },
          data: executionBatchAnalysis.distributionBars.map((item) => item.label),
          inverse: true,
          type: 'category',
        },
        series: [
          {
            barWidth: 13,
            data: executionBatchAnalysis.distributionBars.map((item) => ({
              itemStyle: { color: item.color },
              value: item.score,
            })),
            label: {
              color: '#0f172a',
              fontSize: 10,
              formatter: (params: { dataIndex: number }) =>
                executionBatchAnalysis.distributionBars[params.dataIndex]?.value ?? '',
              position: 'right',
              show: true,
            },
            name: '批次画像',
            type: 'bar',
          },
        ],
      }),
    [executionBatchAnalysis.distributionBars]
  )

  const salesEvidenceItems = useMemo(() => {
    return collectSalesAuditSampleFiles(salesAuditSamples).slice(0, 12)
  }, [salesAuditSamples])

  const salesHeatmapData = useMemo(() => {
    if (!salesAuditSummary?.findings?.length) return []
    const peak = Math.max(
      1,
      ...salesAuditSummary.findings.map((item) => Number(item.count || 0))
    )
    const labelMap: Record<string, string> = {
      pdf_scanned: '扫描件',
      parse_failed: '解析失败',
      pii: '合敏感信息',
      exact_dup: '重复文件',
      near_dup: '版本冲突',
      other: '其他风险',
    }
    return salesAuditSummary.findings
      .filter((item) => Number(item.count || 0) > 0)
      .slice(0, 6)
      .map((item) => {
        const intensity = Number(item.count || 0) / peak
        return {
          name: labelMap[item.key] || item.label,
          count: Number(item.count || 0),
          formatLabel: item.severity.toUpperCase(),
          timeLabel: '入库风险',
          fill: getSeverityFill(item.severity, intensity),
        }
      })
  }, [salesAuditSummary])

  const salesCoreSummary = useMemo(() => {
    const totalFiles = Number(salesAuditSummary?.total_files || 0)
    const pdfScanned = Number(salesAuditSummary?.pdf_scan.scanned || 0)
    const pdfUnknown = Number(salesAuditSummary?.pdf_scan.unknown || 0)
    const scanRatio = totalFiles
      ? Math.round(((pdfScanned + pdfUnknown) / totalFiles) * 100)
      : 0

    return [
      ['文档总数', totalFiles.toLocaleString(), '全量预检范围'],
      [
        '总体体量',
        formatFileSize(salesAuditSummary?.total_size_bytes || 0),
        '估算工时与算力',
      ],
      [
        '阻断项',
        String(
          salesAuditProfile?.costDrivers.find((item) => item.key === 'blocking')
            ?.count ?? 0
        ),
        '需人工介入处理',
      ],
      ['扫描 / 混排', `${scanRatio}%`, 'OCR 前置处理占比'],
    ]
  }, [salesAuditProfile, salesAuditSummary])

  const salesProcessingLanes = useMemo<SalesProcessingLane[]>(() => {
    if (!salesAuditSummary) return []
    const countByFinding = (key: string) =>
      Number(
        salesAuditSummary.findings.find((item) => item.key === key)?.count || 0
      )
    return [
      {
        key: 'ocr',
        label: 'OCR 处理',
        count: countByFinding('pdf_scanned') + countByFinding('pdf_unknown'),
        tone: 'text-info bg-info/8 border-info/15',
      },
      {
        key: 'table',
        label: '格式转换',
        count:
          countByFinding('large_spreadsheet') +
          countByFinding('wide_spreadsheet') +
          countByFinding('merged_heavy_spreadsheet'),
        tone: 'text-orange bg-orange/8 border-orange/15',
      },
      {
        key: 'manual',
        label: '人工审核',
        count:
          countByFinding('pii') +
          countByFinding('secrets') +
          countByFinding('parse_failed'),
        tone: 'text-rose bg-rose/8 border-rose/15',
      },
      {
        key: 'straight',
        label: '去重处理',
        count: Math.max(
          0,
          Number(salesAuditSummary.total_files || 0) -
            (countByFinding('pdf_scanned') +
              countByFinding('pdf_unknown') +
              countByFinding('large_spreadsheet') +
              countByFinding('wide_spreadsheet') +
              countByFinding('merged_heavy_spreadsheet') +
              countByFinding('pii') +
              countByFinding('secrets') +
              countByFinding('parse_failed'))
        ),
        tone: 'text-success bg-success/8 border-success/15',
      },
    ]
  }, [salesAuditSummary])

  const salesPocCandidates = useMemo<SalesEvidenceTableRow[]>(() => {
    return salesEvidenceItems.slice(0, 5).map((file) => {
      const tags = buildEvidenceSlotTags(file)
      const firstTag = tags[0] || 'STRAIGHT_THROUGH'
      const presentation = getRiskTagPresentation(firstTag)

      return {
        id: String(file.name),
        fileName: anonymizeEvidenceName(file.name),
        fileType: file.file_type.toUpperCase(),
        fileSizeLabel: formatFileSize(file.file_size || 0),
        primaryRisk: presentation.primaryRisk,
        riskDescription: buildEvidenceSlotReason(file),
        actionLabel: presentation.actionLabel,
        icon: presentation.icon,
        iconTone: presentation.iconTone,
      }
    })
  }, [salesEvidenceItems])

  const salesHighRiskFiles = useMemo<SalesEvidenceTableRow[]>(() => {
    const reviewBuckets = Object.values(
      salesAuditSamples?.needs_review ?? {}
    ).flat()
    const source = (
      reviewBuckets.length ? reviewBuckets : salesEvidenceItems
    ).slice(0, 5)
    return source.map((file) => {
      const tags = buildEvidenceSlotTags(file)
      const firstTag = tags[0] || 'STRAIGHT_THROUGH'
      const presentation = getRiskTagPresentation(firstTag)

      return {
        id: String(file.name),
        fileName: anonymizeEvidenceName(file.name),
        fileType: file.file_type.toUpperCase(),
        fileSizeLabel: formatFileSize(file.file_size || 0),
        primaryRisk: presentation.primaryRisk,
        riskDescription: buildEvidenceSlotReason(file),
        actionLabel: '加入阻断',
        icon: presentation.icon,
        iconTone: presentation.iconTone,
      }
    })
  }, [salesAuditSamples?.needs_review, salesEvidenceItems])

  const salesPdfSplitOption = useMemo<EChartsOption>(() => {
    const pdfDetection = salesAuditSummary?.pdf_detection as
      | Record<string, unknown>
      | undefined
    const rows = [
      {
        name: 'TEXT',
        value: Number(
          pdfDetection?.text || salesAuditSummary?.pdf_scan.not_scanned || 0
        ),
      },
      { name: 'MIXED', value: Number(pdfDetection?.mixed || 0) },
      {
        name: 'SCAN',
        value: Number(
          pdfDetection?.scan || salesAuditSummary?.pdf_scan.scanned || 0
        ),
      },
    ].filter((row) => row.value > 0)

    return {
      tooltip: { trigger: 'item' },
      series: [
        {
          type: 'pie',
          radius: ['46%', '72%'],
          label: { color: '#475569' },
          data: rows.map((row) => ({
            ...row,
            itemStyle: {
              color: getPdfSplitColor(row.name),
            },
          })),
        },
      ],
    }
  }, [salesAuditSummary])

  const salesLengthOption = useMemo<EChartsOption>(() => {
    const histogram = salesAuditSummary?.length_histogram ?? []
    const p50 = Number(salesAuditSummary?.length_percentiles.p50 || 0)
    const p90 = Number(salesAuditSummary?.length_percentiles.p90 || 0)
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 20, top: 24, bottom: 36 },
      xAxis: {
        type: 'category',
        data: histogram.map((item) => item.label),
        axisLabel: { color: '#64748b' },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#64748b' },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.18)' } },
      },
      series: [
        {
          type: 'bar',
          data: histogram.map((item) => Number(item.count || 0)),
          itemStyle: { color: '#475569', borderRadius: [8, 8, 0, 0] },
          markLine: {
            symbol: 'none',
            label: { color: '#64748b' },
            lineStyle: { type: 'dashed', color: '#94a3b8' },
            data: [
              {
                name: 'P50',
                xAxis: histogram.findIndex(
                  (item) =>
                    p50 >= Number(item.min || 0) &&
                    p50 < Number(item.max || Number.POSITIVE_INFINITY)
                ),
              },
              {
                name: 'P90',
                xAxis: histogram.findIndex(
                  (item) =>
                    p90 >= Number(item.min || 0) &&
                    p90 < Number(item.max || Number.POSITIVE_INFINITY)
                ),
              },
            ].filter((item) => Number(item.xAxis) >= 0),
          },
        },
      ],
    }
  }, [salesAuditSummary])

  const salesRadarOption = useMemo<EChartsOption>(() => {
    if (!salesAuditSummary) return { series: [] }
    const totalFiles = Math.max(1, Number(salesAuditSummary.total_files || 0))
    const ocrRatio =
      (Number(salesAuditSummary.pdf_scan.scanned || 0) +
        Number(salesAuditSummary.pdf_scan.unknown || 0)) /
      Math.max(
        1,
        Number(salesAuditSummary.pdf_scan.scanned || 0) +
          Number(salesAuditSummary.pdf_scan.not_scanned || 0) +
          Number(salesAuditSummary.pdf_scan.unknown || 0)
      )
    const tableHeavyRatio =
      (Number(
        salesAuditSummary.findings.find(
          (item) => item.key === 'large_spreadsheet'
        )?.count || 0
      ) +
        Number(
          salesAuditSummary.findings.find(
            (item) => item.key === 'wide_spreadsheet'
          )?.count || 0
        ) +
        Number(
          salesAuditSummary.findings.find(
            (item) => item.key === 'merged_heavy_spreadsheet'
          )?.count || 0
        )) /
      totalFiles
    const sensitiveRatio =
      (Number(
        salesAuditSummary.findings.find((item) => item.key === 'pii')?.count ||
          0
      ) +
        Number(
          salesAuditSummary.findings.find((item) => item.key === 'secrets')
            ?.count || 0
        )) /
      totalFiles
    const successRatio =
      1 -
      Number(
        salesAuditSummary.findings.find((item) => item.key === 'parse_failed')
          ?.count || 0
      ) /
        totalFiles
    const imageHeavyProxy = Math.max(
      0,
      Math.min(
        1,
        Number(salesAuditSummary.pdf_scan.scanned || 0) / totalFiles +
          Number(
            (salesAuditSummary.by_file_type as Record<string, number>).pptx || 0
          ) /
            totalFiles
      )
    )

    return {
      tooltip: { trigger: 'item' },
      radar: {
        radius: '52%',
        center: ['50%', '54%'],
        splitNumber: 4,
        indicator: [
          { name: 'OCR 密度', max: 100 },
          { name: '表格复杂度', max: 100 },
          { name: '图片频率', max: 100 },
          { name: '敏感信息密度', max: 100 },
          { name: '解析成功率', max: 100 },
        ],
        axisName: { color: '#475569', fontSize: 9 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.22)' } },
        splitArea: {
          areaStyle: {
            color: ['rgba(248,250,252,0.82)', 'rgba(241,245,249,0.48)'],
          },
        },
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: [
                Math.round(ocrRatio * 100),
                Math.round(tableHeavyRatio * 100),
                Math.round(imageHeavyProxy * 100),
                Math.round(sensitiveRatio * 100),
                Math.round(successRatio * 100),
              ],
              itemStyle: { color: '#0f766e' },
              lineStyle: { color: '#0f766e', width: 2 },
              areaStyle: { color: 'rgba(15,118,110,0.12)' },
            },
          ],
        },
      ],
    }
  }, [salesAuditSummary])

  const persistExecutionMonitorDisposition = useCallback(
    async (documentId: string, disposition: SampleDisposition) => {
      const previousDisposition = resolvedSampleDispositions[documentId]
      const reviewedAt = new Date().toISOString()

      try {
        await documentApi.patchUserMetadata(documentId, {
          patch: {
            precheck_disposition: disposition,
            precheck_reviewed_at: reviewedAt,
          },
          replace: false,
        })
        await documentsQuery.refetch()
        if (disposition === 'approved') setSuccessPulseVisible(true)
        toast.success('已同步预检处置结论')
      } catch {
        setSampleDispositions((previous) => {
          const next = { ...previous }
          if (previousDisposition) next[documentId] = previousDisposition
          else delete next[documentId]
          return next
        })
        toast.error('同步预检处置失败，请稍后重试')
      }
    },
    [documentsQuery, resolvedSampleDispositions]
  )

  const persistSalesAuditDisposition = useCallback(
    async (fileName: string, disposition: SampleDisposition) => {
      const previousDisposition = resolvedSampleDispositions[fileName]

      if (!selectedDatasetId || !latestPrecheckRun?.id) {
        setSampleDispositions((previous) => {
          const next = { ...previous }
          if (previousDisposition) next[fileName] = previousDisposition
          else delete next[fileName]
          return next
        })
        toast.error('当前预检运行不存在，无法同步入库处置')
        return
      }

      try {
        await datasetApi.patchPrecheckSampleReview(
          selectedDatasetId,
          latestPrecheckRun.id,
          {
            file_name: fileName,
            disposition,
          }
        )
        await precheckSamplesQuery.refetch()
        if (disposition === 'approved') setSuccessPulseVisible(true)
        toast.success('已同步入库处置结论')
      } catch {
        setSampleDispositions((previous) => {
          const next = { ...previous }
          if (previousDisposition) next[fileName] = previousDisposition
          else delete next[fileName]
          return next
        })
        toast.error('同步入库处置失败，请稍后重试')
      }
    },
    [
      latestPrecheckRun?.id,
      precheckSamplesQuery,
      resolvedSampleDispositions,
      selectedDatasetId,
    ]
  )

  const handleSampleDisposition = useCallback(
    (documentId: string, disposition: SampleDisposition) => {
      setSampleDispositions((previous) => ({
        ...previous,
        [documentId]: disposition,
      }))

      if (mode === 'execution-monitor' && !demoMode) {
        persistExecutionMonitorDisposition(documentId, disposition)
        return
      }

      if (mode === 'sales-audit' && !demoMode) {
        persistSalesAuditDisposition(documentId, disposition)
        return
      }

      if (disposition === 'approved') setSuccessPulseVisible(true)
      toast.success(
        disposition === 'approved' ? '样本标记已更新' : '人工处理标记已更新'
      )
    },
    [
      demoMode,
      mode,
      persistExecutionMonitorDisposition,
      persistSalesAuditDisposition,
    ]
  )

  const handleSelectAudit = useCallback((documentId: string) => {
    setSelectedAuditIds((previous) =>
      previous.includes(documentId)
        ? previous.filter((item) => item !== documentId)
        : [...previous, documentId]
    )
  }, [])

  const handleOpenAuditSnapshot = useCallback((documentId: string) => {
    setDesktopScopeCollapsed(false)
    setActiveDetailId(documentId)
  }, [])

  const handleDownloadReport = useCallback(async () => {
    const html = buildReportHtml({
      datasetLabel: selectedDatasetLabel,
      totalDocs: documents.length,
      readyRate,
      manualQueue: reviewQueue + manualCount,
      efficiency: `${docsPerMinute?.toFixed(1) ?? '--'} docs/min`,
      latencyP90: `${durationPercentiles.p90 || 0} min`,
      selectedReason,
      documents: visibleAuditSamples.length ? visibleAuditSamples : documents,
      salesAuditSummary,
      salesPocCandidates,
      salesHighRiskFiles,
    })

    try {
      await renderReportHtmlToJpeg(
        html,
        buildSafeReportFilename(selectedDatasetLabel, '.audit-report.jpg')
      )
      toast.success('已导出 JPG 报告')
    } catch (error) {
      const previewUrl = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
      const reportWindow = globalThis.window.open(previewUrl, '_blank', 'noopener,noreferrer')
      if (reportWindow) {
        reportWindow.opener = null
        globalThis.window.setTimeout(() => URL.revokeObjectURL(previewUrl), 60_000)
        toast.error(
          error instanceof Error && error.message
            ? `JPG 生成失败，已回退到 HTML 预览：${error.message}`
            : 'JPG 生成失败，已回退到 HTML 预览'
        )
        return
      }
      URL.revokeObjectURL(previewUrl)

      downloadTextFile(
        'ingestion-audit-report.html',
        html,
        'text/html;charset=utf-8'
      )
      toast.error(
        error instanceof Error && error.message
          ? `JPG 生成失败，已回退到 HTML 文件：${error.message}`
          : 'JPG 生成失败，已回退到 HTML 文件'
      )
    }
  }, [
    docsPerMinute,
    documents,
    durationPercentiles.p90,
    manualCount,
    readyRate,
    reviewQueue,
    selectedDatasetLabel,
    selectedReason,
    salesAuditSummary,
    salesHighRiskFiles,
    salesPocCandidates,
    visibleAuditSamples,
  ])

  const handleExportSalesAuditReport = useCallback(async () => {
    if (demoMode || !selectedDatasetId || !latestPrecheckRun?.id) {
      await handleDownloadReport()
      return
    }

    try {
      const blob = await datasetApi.exportPrecheckHtml(
        selectedDatasetId,
        latestPrecheckRun.id,
        { redact: true }
      )
      const html = await blob.text()
      await renderReportHtmlToJpeg(
        html,
        buildSafeReportFilename(selectedDatasetLabel, '.precheck.jpg')
      )
      toast.success('已导出脱敏 JPG 报告')
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? `导出脱敏 JPG 报告失败，已回退到当前页面报告：${error.message}`
          : '导出脱敏 JPG 报告失败，已回退到当前页面报告'
      )
      await handleDownloadReport()
    }
  }, [
    demoMode,
    handleDownloadReport,
    latestPrecheckRun?.id,
    selectedDatasetId,
    selectedDatasetLabel,
  ])

  const handleUploadSampleAssessment = useCallback(() => {
    dropZoneRef.current?.triggerFilePicker({ precheckOnly: true })
  }, [])

  const handleUploadFormalIngest = useCallback(() => {
    dropZoneRef.current?.triggerFilePicker({ precheckOnly: false })
  }, [])

  useEffect(() => {
    const off = globalEventBus.on('ingestion:download-report', () => {
      if (mode === 'sales-audit') {
        handleExportSalesAuditReport()
        return
      }
      handleDownloadReport()
    })
    return off
  }, [handleDownloadReport, handleExportSalesAuditReport, mode])

  const handleHeatmapSelect = useCallback((reason: string) => {
    setSelectedReason((previous) => (previous === reason ? null : reason))
    setDesktopScopeCollapsed(false)
  }, [])

  const handleDatasetScopeChange = useCallback(
    (value: string) => {
      setDatasetScope(value)
      setSelectedAuditIds([])
      setSelectedReason(null)

      const params = new URLSearchParams(searchParams.toString())
      if (value === DATASET_ALL) {
        params.delete('datasetId')
      } else {
        params.set('datasetId', value)
      }
      if (mode === 'execution-monitor') {
        params.set('mode', 'execution-monitor')
      }

      const query = params.toString()
      router.replace(query ? `${pathname}?${query}` : pathname)
    },
    [mode, pathname, router, searchParams]
  )

  const handleOpenIngestionOperation = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())
    params.delete('mode')

    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname)
  }, [pathname, router, searchParams])

  const handleExitDemoMode = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())
    params.delete('demo')

    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname)
  }, [pathname, router, searchParams])

  const showEmptyState =
    mode === 'sales-audit'
      ? !demoMode &&
        !documentsQuery.isLoading &&
        !precheckSummaryQuery.isLoading &&
        !salesAuditSummary
      : false
  const showExecutionMonitorEmptyShell =
    mode === 'execution-monitor' &&
    !documentsQuery.isLoading &&
    executionTaskRows.length === 0
  const showDesktopAuditRail =
    mode === 'execution-monitor' && !showEmptyState && !desktopScopeCollapsed
  const showDesktopAuditRailToggle =
    mode === 'execution-monitor' && !showEmptyState
  const headerAnimation = getHeaderAnimation({
    headerCollapsed,
    mode,
    reduceMotion,
  })
  const salesAuditPocSampleLabel = salesAuditProfile
    ? `${salesAuditProfile.pocSampleCount} 份`
    : '待预检'

  return (
    <div
      ref={scrollContainerRef}
      data-ingestion-page-root="true"
      data-page-scroll-container="true"
      className={cn(
        'flex-1 h-full min-h-0 overflow-y-auto overscroll-contain no-scrollbar scroll-fade-bottom text-foreground',
        INGESTION_BACKGROUND_CLASS
      )}
    >
      <DropZone
        ref={dropZoneRef}
        datasetId={selectedDatasetId}
        precheckOnly
        onUploadComplete={() => {
          documentsQuery.refetch()
          summaryQuery.refetch()
          taskQueueQuery.refetch()
          precheckRunsQuery.refetch()
        }}
      />

      <div
        className={cn(
          'flex w-full max-w-none gap-0 px-3 pt-3 md:px-5 lg:px-6 xl:px-7 2xl:px-8',
          mode === 'sales-audit' ? 'pb-2' : 'pb-8'
        )}
      >
        <div
          className={cn(
            'relative flex w-full gap-0',
            mode === 'sales-audit' ? 'min-h-0' : 'min-h-[calc(100dvh-2rem)]'
          )}
        >
          <button
            type="button"
            aria-label="展开运行范围侧栏"
            onClick={() => setDesktopScopeCollapsed((previous) => !previous)}
            className={cn(
              'absolute left-0 top-7 z-40 hidden h-16 w-8 items-center justify-center gap-1 rounded-r-[0.9rem] border border-border/35 bg-background/78 text-[8px] font-semibold uppercase tracking-[0.16em] text-muted-foreground opacity-0 hover:opacity-100 focus-visible:opacity-100 shadow-none backdrop-blur-xl transition-all duration-200 hover:border-info/25 hover:bg-background/94 hover:text-info focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/30',
              showDesktopAuditRailToggle && desktopScopeCollapsed
                ? 'translate-x-0 pointer-events-auto lg:flex'
                : 'pointer-events-none -translate-x-3 opacity-0 lg:hidden'
            )}
          >
            <span
              aria-hidden="true"
              className="h-7 w-px rounded-full bg-info/35"
            />
            <span className="[writing-mode:vertical-rl]">范围</span>
          </button>

          <aside
            className={cn(
              'hidden shrink-0 overflow-hidden pr-3 transition-all duration-300 ease-out lg:block',
              showDesktopAuditRail
                ? 'w-[15.5rem] opacity-100'
                : 'w-0 opacity-0 -translate-x-4 pointer-events-none'
            )}
          >
            <div className="sticky top-4">
              <div className="overflow-hidden rounded-[0.95rem] border border-border/38 bg-background/64 p-1.5 shadow-none backdrop-blur-xl">
                <div className="flex items-center justify-between gap-2 px-1 pb-1.5">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-[0.65rem] border border-border/45 bg-muted/20 text-muted-foreground">
                      <Check className="h-3.5 w-3.5" />
                    </span>
                    <div className="min-w-0">
                      <div className="text-[10px] font-semibold text-foreground">
                        运行范围
                      </div>
                      <div className="mt-0.5 truncate text-[8px] text-muted-foreground">
                        轻量筛选数据集与线索
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border/45 bg-background/60 text-muted-foreground transition-colors hover:border-info/25 hover:text-foreground"
                    onClick={() => setDesktopScopeCollapsed(true)}
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="mb-1.5 rounded-[0.68rem] border border-border/35 bg-background/45 p-1.5">
                  <div className="mb-1 flex items-center justify-between gap-2 px-1">
                    <span className="text-[8px] font-medium text-muted-foreground">
                      数据集
                    </span>
                    <span className="font-mono text-[7px] text-muted-foreground">
                      {selectedDatasetId ? '单库' : '全部'}
                    </span>
                  </div>
                  <Select
                    value={datasetScope}
                    onValueChange={handleDatasetScopeChange}
                  >
                    <SelectTrigger className="h-7 rounded-[0.6rem] border-border/45 bg-background/70 px-2 text-[9px] font-medium shadow-none">
                      <SelectValue placeholder="全部项目" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={DATASET_ALL}>全部项目</SelectItem>
                      {datasets.map((dataset) => (
                        <SelectItem key={dataset.id} value={dataset.id}>
                          {dataset.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="mb-1.5 grid grid-cols-2 gap-1">
                  {([
                    ['pending', '待确认', auditRailCounts.pending],
                    ['manual', '人工处理', auditRailCounts.manual],
                    ['approved', '已确认', auditRailCounts.approved],
                  ] as const).map(([value, label, count]) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={auditDispositionFilter === value}
                      onClick={() => setAuditDispositionFilter(value)}
                      className={cn(
                        'rounded-[0.56rem] border px-1.5 py-1 text-left text-[8px] transition-colors',
                        auditDispositionFilter === value
                          ? 'border-info/25 bg-info/10 text-info'
                          : 'border-border/35 bg-background/50 text-muted-foreground hover:text-foreground'
                      )}
                    >
                      <span className="block font-medium">{label}</span>
                      <span className="font-mono tabular-nums">{count}</span>
                    </button>
                  ))}
                  <button
                    type="button"
                    aria-pressed={auditDispositionFilter === 'all'}
                    onClick={() => setAuditDispositionFilter('all')}
                    className={cn(
                      'rounded-[0.56rem] border px-1.5 py-1 text-left text-[8px] transition-colors',
                      auditDispositionFilter === 'all'
                        ? 'border-info/25 bg-info/10 text-info'
                        : 'border-border/35 bg-background/50 text-muted-foreground hover:text-foreground'
                    )}
                  >
                    <span className="block font-medium">全部</span>
                    <span className="font-mono tabular-nums">{auditRailCounts.all}</span>
                  </button>
                </div>

                <div className="space-y-1.5">
                  {visibleAuditSamples.map((document) => {
                        const kind = getDocumentKind(document.filename)
                        const disposition =
                          resolvedSampleDispositions[document.id]
                        const status = String(
                          document.status || ''
                        ).toLowerCase()
                        const progress = Math.max(
                          0,
                          Math.min(
                            100,
                            Number(document.processing_progress || 0)
                          )
                        )
                        const statusPresentation = getAuditRailStatusTone({
                          disposition,
                          status,
                        })
                        const stageLabel =
                          document.current_stage ||
                          (status === 'completed' ? 'completed' : status)
                        return (
                          <motion.article
                            key={document.id}
                            drag="x"
                            dragConstraints={{ left: 0, right: 0 }}
                            dragElastic={0.16}
                            onDragEnd={(_, info) => {
                              if (info.offset.x > 100)
                                handleSampleDisposition(document.id, 'approved')
                              if (info.offset.x < -100)
                                handleSampleDisposition(document.id, 'manual')
                            }}
                            className="group relative overflow-hidden rounded-[0.74rem] border border-border/38 bg-background/62 px-1.5 py-1.5 shadow-none transition-colors hover:border-info/25 hover:bg-background/82"
                          >
                            <div className="flex items-start gap-2">
                                <input
                                  checked={selectedAuditIds.includes(
                                    document.id
                                  )}
                                  onChange={() =>
                                    handleSelectAudit(document.id)
                                  }
                                  className="mt-1 h-2.5 w-2.5 rounded border-border/60 text-foreground"
                                  type="checkbox"
                                  aria-label={`选择 ${document.filename}`}
                                />
                                <span
                                  className={cn(
                                    'mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-[0.65rem] border text-[7px] font-semibold uppercase',
                                    getDocumentKindAccent(kind)
                                  )}
                                >
                                  {String(
                                    document.file_type || kind
                                  ).toUpperCase()}
                                </span>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center justify-between gap-2">
                                    <div className="min-w-0">
                                      <div className="truncate text-[10.5px] font-semibold leading-4 text-foreground">
                                        {document.filename}
                                      </div>
                                    </div>
                                    <span
                                      className={cn(
                                        'shrink-0 rounded-full border px-1.5 py-0.5 text-[8px] font-medium',
                                        statusPresentation.tone
                                      )}
                                    >
                                      {statusPresentation.label}
                                    </span>
                                  </div>

                                  <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[8px] text-muted-foreground">
                                    <span className="max-w-[6.5rem] truncate">
                                      {stageLabel}
                                    </span>
                                    <span className="font-mono tabular-nums">
                                      {formatFileSize(document.file_size || 0)}
                                    </span>
                                    <span className="font-mono tabular-nums">
                                      {Number(document.chunk_count || 0)} 块
                                    </span>
                                    <span className="font-mono tabular-nums">
                                      {progress}%
                                    </span>
                                  </div>

                                  {document.error_message ? (
                                    <div className="mt-1 line-clamp-1 rounded-[0.6rem] border border-destructive/15 bg-destructive/6 px-2 py-1 text-[8px] leading-3 text-destructive">
                                      {document.error_message}
                                    </div>
                                  ) : null}

                                  <div className="mt-1 h-0.5 overflow-hidden rounded-full bg-muted/45">
                                    <div
                                      className={cn(
                                        'h-full rounded-full transition-all',
                                        getProgressTone(status)
                                      )}
                                      style={{ width: `${progress}%` }}
                                    />
                                  </div>
                                </div>
                              </div>
                              <div className="mt-1.5 grid grid-cols-3 gap-1">
                                <button
                                  type="button"
                                  className="inline-flex h-5 items-center justify-center rounded-[0.45rem] border border-success/20 bg-success/8 px-1.5 text-[7.5px] font-medium text-success transition-colors hover:border-success/35 hover:bg-success/12"
                                  onClick={() =>
                                    handleSampleDisposition(
                                      document.id,
                                      'approved'
                                    )
                                  }
                                >
                                  确认
                                </button>
                                <button
                                  type="button"
                                  className="inline-flex h-5 items-center justify-center rounded-[0.45rem] border border-warning/20 bg-warning/8 px-1.5 text-[7.5px] font-medium text-warning transition-colors hover:border-warning/35 hover:bg-warning/12"
                                  onClick={() =>
                                    handleSampleDisposition(
                                      document.id,
                                      'manual'
                                    )
                                  }
                                >
                                  转人工
                                </button>
                                <button
                                  type="button"
                                  className="inline-flex h-5 items-center justify-center rounded-[0.45rem] border border-border/55 bg-background/70 px-1.5 text-[7.5px] font-medium text-foreground transition-colors hover:border-info/25 hover:text-info"
                                  onClick={() =>
                                    handleOpenAuditSnapshot(document.id)
                                  }
                                >
                                  快照
                                </button>
                              </div>
                          </motion.article>
                        )
                      })}
                  {visibleAuditSamples.length === 0 ? (
                    <div className="rounded-[0.78rem] border border-dashed border-border/55 bg-background/48 px-3 py-4 text-center text-[10px] text-muted-foreground">
                      暂无可见资产
                    </div>
                  ) : null}
                    <div className="flex items-center justify-between border-t border-border/45 px-1 pt-2 text-[9px] font-medium text-muted-foreground">
                      <span>共 {visibleAuditSamples.length} 项线索</span>
                      {selectedReason ? (
                        <button
                          type="button"
                          className="text-info transition-colors hover:text-info"
                          onClick={() => setSelectedReason(null)}
                        >
                          清除聚焦
                        </button>
                      ) : (
                        <span>范围筛选</span>
                      )}
                    </div>
                </div>
              </div>
            </div>
          </aside>

          <div className="min-w-0 flex-1">
            <div className="sticky top-3 z-30">
              <motion.div
                className={cn(
                  'relative overflow-hidden',
                  INGESTION_HERO_PANEL_CLASS
                )}
                animate={headerAnimation}
                transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
              >
                <div
                  className="pointer-events-none absolute inset-y-3 left-0 w-1 rounded-r-full bg-[linear-gradient(180deg,hsl(var(--info)),hsl(var(--primary)))]"
                  aria-hidden="true"
                />
                <div
                  className="pointer-events-none absolute -right-10 -top-14 size-44 rounded-full bg-info/30 blur-3xl"
                  aria-hidden="true"
                />
                <div
                  className="pointer-events-none absolute bottom-0 left-8 right-8 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--info)/0.38),transparent)]"
                  aria-hidden="true"
                />
                <div
                  className={cn(
                    'relative px-2.5 md:px-3',
                    mode === 'execution-monitor'
                      ? 'py-3 md:py-3.5'
                      : 'py-0'
                  )}
                >
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {showSalesPolicyBadge ? (
                          <span className="inline-flex items-center rounded-full border border-foreground/10 bg-foreground/[0.04] px-2 py-0.5 text-[7px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                            Sensitive Data Policy
                          </span>
                        ) : null}
                        {demoMode ? (
                          <span className="inline-flex items-center rounded-full border border-info/20 bg-info/10 px-2 py-0.5 text-[7px] font-medium uppercase tracking-[0.16em] text-info">
                            演示模式
                          </span>
                        ) : null}
                      </div>
                      <div
                        className={cn(
                          'overflow-hidden transition-[max-height,opacity,margin] duration-200 ease-out',
                          getHeaderBodyVisibilityClass(mode, headerCollapsed)
                        )}
                      >
                        <div className="flex min-w-0 items-start gap-2">
                          <div className="relative flex size-12 shrink-0 items-center justify-center rounded-[22px] border border-info/20 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.12))] text-info shadow-[inset_0_1px_0_hsl(var(--background)),0_18px_36px_-24px_hsl(var(--info)/0.9)]">
                            <span
                              className="absolute inset-x-2 top-1 h-px bg-card/70"
                              aria-hidden="true"
                            />
                            <PageTitleIcon name="ingestion-monitor" className="size-9" />
                          </div>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <h1 className="text-[clamp(0.96rem,1.18vw,1.26rem)] font-semibold tracking-[-0.015em] text-foreground">
                                <span className="bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent">
                                  {mode === 'sales-audit'
                                    ? '入库预检工作台'
                                    : '执行监控'}
                                </span>
                              </h1>
                              {mode === 'execution-monitor' ? (
                                <span
                                  className={cn(
                                    'inline-flex items-center rounded-full border px-2 py-0.5 text-[8px] font-medium',
                                    taskQueueStatusTone
                                  )}
                                >
                                  {taskQueueStatusLabel}
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-1 max-w-[52rem] text-[9px] leading-[1.42] text-muted-foreground">
                              {mode === 'sales-audit'
                                ? '选择目标数据集后先做入库预检，确认目录、策略、重复与风险，再把文件写入知识库；入库完成后可切换执行监控查看队列和失败重试。'
                                : '集中观察处理模式、吞吐、失败重试与运行态列表，快速判断入库链路是否健康。'}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-end gap-1">
                      <IngestionViewSwitch />
                      {demoMode ? (
                        <Button
                          type="button"
                          variant="outline"
                          className="h-7 rounded-lg px-2 text-[9px]"
                          onClick={handleExitDemoMode}
                        >
                          退出演示
                        </Button>
                      ) : null}
                      {mode === 'sales-audit' ? (
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={handleUploadSampleAssessment}
                          >
                            <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                            上传预检文件
                          </Button>
                          <Button
                            type="button"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={handleUploadFormalIngest}
                          >
                            <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                            正式入库
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={() => handleExportSalesAuditReport()}
                          >
                            <Download className="mr-1.5 h-3.5 w-3.5" />
                            入库预检报告
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            type="button"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={handleDownloadReport}
                          >
                            <Download className="mr-1.5 h-3.5 w-3.5" />
                            导出报告
                          </Button>
                        </>
                      )}
                    </div>
                  </div>

                  {mode === 'sales-audit' && (
                    <div className={cn('mt-2.5', SALES_SUMMARY_STRIP_CLASS)}>
                      <div className="grid gap-px sm:grid-cols-4">
                        {[
                          {
                            label: '范围',
                            value: selectedDatasetLabel,
                            icon: FileSearch,
                            tone: 'text-muted-foreground/65',
                            detail: '',
                          },
                          {
                            label: '入库建议',
                            value: ingestionRecommendationLabel,
                            icon: Workflow,
                            tone: 'text-accent',
                            detail: '',
                          },
                          {
                            label: '抽样确认量',
                            value: salesAuditPocSampleLabel,
                            icon: FileCheck2,
                            tone: 'text-info',
                            detail: '',
                          },
                          {
                            label: '处理复杂度',
                            value: salesAuditProfile?.complexity || '待预检',
                            icon: Radar,
                            tone: 'text-warning',
                            detail: '',
                          },
                        ].map(({ label, value, icon: Icon, tone, detail }) => (
                          <div
                            key={label}
                            className="relative min-h-[3.4rem] bg-background/78 px-2.5 py-2"
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="text-[7px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                                {label}
                              </div>
                              <span className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-border/45 bg-muted/30">
                                <Icon
                                  className={cn('h-2.5 w-2.5 shrink-0', tone)}
                                />
                              </span>
                            </div>
                            <div className="mt-1 font-mono text-[10px] tabular-nums leading-none text-foreground">
                              {value}
                            </div>
                            {detail ? (
                              <div className="mt-1 text-[7px] text-muted-foreground">
                                {detail}
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </motion.div>
            </div>

            <AnimatePresence>
              {successPulseVisible ? (
                <motion.div
                  initial={{ opacity: 0, scaleX: 0.92 }}
                  animate={{ opacity: 1, scaleX: 1 }}
                  exit={{ opacity: 0 }}
                  className="pointer-events-none relative mt-3 overflow-hidden rounded-[1.1rem] border border-success/15 bg-success/8 px-3 py-2.5"
                >
                  <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(16,185,129,0.24),transparent_62%)]" />
                  <div className="relative flex items-center gap-2 text-[12px] text-success">
                    <ShieldCheck className="h-4 w-4" />
                    入库确认反馈：当前数据集已出现健康可入库样本，可继续批量确认。
                  </div>
                </motion.div>
              ) : null}
            </AnimatePresence>

            <div className={cn(mode === 'sales-audit' ? 'mt-5' : 'mt-2.5')}>
              {mode === 'sales-audit' && showEmptyState && (
                  <EmptyState
                    mode="truly-empty"
                    onUploadSample={handleUploadSampleAssessment}
                    onUploadIngest={handleUploadFormalIngest}
                  />
              )}

              {mode === 'sales-audit' && !showEmptyState && (
                  <div
                    title="入库依据"
                    className={cn(
                      'relative overflow-hidden rounded-[1.3rem] border border-border/60 bg-background/86 p-2.5 shadow-[0_24px_68px_-44px_rgba(15,23,42,0.24)] md:p-3',
                      'bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] [background-size:28px_28px]'
                    )}
                  >
                    <div
                      aria-hidden
                      className="pointer-events-none absolute inset-0 opacity-70"
                      style={{
                        background: 'radial-gradient(circle at 36% 24%, rgba(255,255,255,0.48), transparent 28%)',
                      }}
                    />
                    <div className="relative z-10 space-y-2">
                      <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                        <div className="grid gap-1.5 xl:grid-cols-[184px_minmax(0,1fr)] xl:items-stretch">
                          <div className="rounded-[0.9rem] border border-border/50 bg-[linear-gradient(180deg,hsl(var(--card)),hsl(var(--muted)/0.3))] px-2.5 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-[7px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                入库依据
                              </div>
                              <FileDigit className="h-3 w-3 text-muted-foreground/65" />
                            </div>
                            <div className="mt-1 text-[11px] font-medium text-foreground">
                              核心摘要
                            </div>
                            <p className="mt-1 text-[9px] leading-3.5 text-muted-foreground">
                              默认输出脱敏后的客观事实，用于解释入库策略、预检范围与人工阻断来源。
                            </p>
                            <div className="mt-1.5 inline-flex items-center rounded-full border border-border/60 bg-background/80 px-1.5 py-0.5 text-[8px] font-medium text-muted-foreground">
                              Evidence-first · De-identified
                            </div>
                          </div>

                          <div className="grid gap-1 sm:grid-cols-2 xl:grid-cols-4">
                            {salesCoreSummary.map(
                              ([label, value, note], index) => {
                                const Icon = getSalesCoreIcon(index)
                                const iconTone = getSalesCoreIconTone(index)
                                return (
                                  <div
                                    key={label}
                                    className={cn(
                                      SALES_PANEL_INSET_CLASS,
                                      'px-1.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.58)]'
                                    )}
                                  >
                                    <div className="flex items-center gap-1.5">
                                      <div className="flex h-4 w-4 items-center justify-center rounded-full bg-muted/30">
                                        <Icon
                                          className={cn(
                                            'h-2.5 w-2.5',
                                            iconTone
                                          )}
                                        />
                                      </div>
                                      <div className="text-[8px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
                                        {label}
                                      </div>
                                    </div>
                                    <div className="mt-1 font-mono text-[11px] font-medium leading-none text-foreground">
                                      {value}
                                    </div>
                                    <div
                                      className={cn(
                                        'mt-0.5 text-[7px] leading-3',
                                        index === 2
                                          ? 'text-rose'
                                          : 'text-muted-foreground'
                                      )}
                                    >
                                      {note}
                                    </div>
                                  </div>
                                )
                              }
                            )}
                          </div>
                        </div>
                      </section>

                      <div className="grid gap-1.5 xl:grid-cols-[0.96fr_1.12fr_0.8fr]">
                        <section
                          className={cn(
                            SALES_PANEL_CLASS,
                            'flex h-full flex-col p-2.5'
                          )}
                        >
                          <SalesPanelHeader
                            title="PDF 类型分布"
                            icon={CircleDashed}
                          />
                          <div className="mt-1 h-[9rem]">
                            <EChart option={salesPdfSplitOption} />
                          </div>
                          <div className="mt-auto rounded-[0.75rem] border border-warning/15 bg-warning/6 px-2 py-1 text-[8px] leading-3.5 text-warning">
                            扫描型 PDF 需要先 OCR 处理，预计工期抬升较大。
                          </div>
                        </section>

                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="文档长度分布（按字符数）"
                            icon={FileSearch}
                          />
                          <div className="mt-1.5 grid gap-2 xl:grid-cols-[1fr_148px]">
                            <div className="h-[8rem]">
                              <EChart option={salesLengthOption} />
                            </div>
                            <div
                              className={cn(
                                SALES_PANEL_INSET_CLASS,
                                'space-y-1 px-2 py-1.5'
                              )}
                            >
                              {[
                                [
                                  'P50（中位数）',
                                  salesAuditSummary?.length_percentiles.p50 ||
                                    0,
                                ],
                                [
                                  'P90',
                                  salesAuditSummary?.length_percentiles.p90 ||
                                    0,
                                ],
                                [
                                  'P99',
                                  salesAuditSummary?.length_percentiles.p99 ||
                                    0,
                                ],
                                [
                                  '最大值',
                                  salesAuditSummary?.length_percentiles.p99 ||
                                    0,
                                ],
                              ].map(([label, value]) => (
                                <div
                                  key={label}
                                  className="flex items-center justify-between gap-2 text-[8px]"
                                >
                                  <span className="text-muted-foreground">
                                    {label}
                                  </span>
                                  <span className="font-mono text-[9px] text-foreground">
                                    {value}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </section>

                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="复杂度细节"
                            icon={Radar}
                            iconTone="text-accent"
                          />
                          <div className="mt-1.5 space-y-1">
                            {(salesAuditProfile?.costDrivers || []).map(
                              (driver) => (
                                <div
                                  key={driver.key}
                                  className={cn(
                                    SALES_PANEL_INSET_CLASS,
                                    'flex items-center justify-between gap-3 px-2 py-1 text-[8px]'
                                  )}
                                >
                                  <div className="flex items-center gap-2">
                                    <span
                                      className={cn(
                                        'h-2 w-2 rounded-full',
                                        getDriverDotTone(driver.key)
                                      )}
                                    />
                                    <span className="text-foreground">
                                      {driver.label}
                                    </span>
                                  </div>
                                  <span className="font-mono text-[9px] text-foreground">
                                    {driver.count}
                                  </span>
                                </div>
                              )
                            )}
                          </div>
                          <div className="mt-1.5 h-[7.25rem] overflow-visible">
                            <EChart option={salesRadarOption} />
                          </div>
                        </section>
                      </div>

                      <div className="grid gap-1.5 xl:grid-cols-[1.1fr_0.9fr]">
                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="风险热区（按风险类型）"
                            icon={ShieldAlert}
                            iconTone="text-rose"
                            actionLabel="查看全部"
                            onAction={() => setSelectedReason(null)}
                          />
                          <div className="mt-1.5 grid gap-1.5 sm:grid-cols-5">
                            {salesHeatmapData.slice(0, 5).map((item) => (
                              <button
                                key={item.name}
                                type="button"
                                onClick={() => handleHeatmapSelect(item.name)}
                                className={cn(
                                  SALES_PANEL_INSET_CLASS,
                                  'px-2 py-1.5 text-left'
                                )}
                              >
                                <div className="text-[8px] text-muted-foreground">
                                  {item.name}
                                </div>
                                <div className="mt-1 font-mono text-[12px] font-medium text-foreground">
                                  {item.count.toLocaleString()}
                                </div>
                                <div className="mt-0.5 text-[8px] text-muted-foreground">
                                  占比{' '}
                                  {(
                                    (item.count /
                                      Math.max(
                                        1,
                                        salesAuditSummary?.total_files || 1
                                      )) *
                                    100
                                  ).toFixed(1)}
                                  %
                                </div>
                              </button>
                            ))}
                          </div>
                        </section>

                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="处理清单（待处理文件数）"
                            icon={Workflow}
                            iconTone="text-info"
                            actionLabel="查看全部"
                            onAction={() => setSelectedReason(null)}
                          />
                          <div className="mt-1.5 grid gap-1.5 sm:grid-cols-4">
                            {salesProcessingLanes.map((lane) => (
                              <div
                                key={lane.key}
                                className={cn(
                                  'rounded-[0.9rem] border px-2 py-1.5',
                                  lane.tone
                                )}
                              >
                                <div className="text-[8px]">{lane.label}</div>
                                <div className="mt-1 text-center font-mono text-[14px] font-semibold">
                                  {lane.count.toLocaleString()}
                                </div>
                              </div>
                            ))}
                          </div>
                        </section>
                      </div>

                      <div className="grid gap-1.5 xl:grid-cols-[1.05fr_0.95fr]">
                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="入库抽样确认（5 份）"
                            icon={FileCheck2}
                            iconTone="text-success"
                            subtitle="按复杂度维度覆盖主风险项"
                            actionLabel="查看全部"
                          />
                          <div className="mt-1.5 overflow-hidden rounded-[0.9rem] border border-border/50">
                            <table className="w-full text-left text-[8px]">
                              <thead className="bg-muted/25 text-muted-foreground">
                                <tr>
                                  <th className="px-2 py-1 font-medium">
                                    文件名
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    类型
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    大小
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    主要风险
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    建议处理
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {salesPocCandidates.map((row) => (
                                  <tr
                                    key={row.id}
                                    className="border-t border-border/50"
                                  >
                                    <td className="px-2 py-1 font-mono text-foreground">
                                      {row.fileName}
                                    </td>
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {row.fileType}
                                    </td>
                                    <td className="px-2 py-1 font-mono text-muted-foreground">
                                      {row.fileSizeLabel}
                                    </td>
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {row.primaryRisk}
                                    </td>
                                    <td className="px-2 py-1">
                                      <span className="rounded-full border border-border/60 px-1.5 py-0.5 text-[7px] text-foreground">
                                        {row.actionLabel}
                                      </span>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </section>

                        <section className={cn(SALES_PANEL_CLASS, 'p-2.5')}>
                          <SalesPanelHeader
                            title="高风险文件（示例）"
                            icon={CircleAlert}
                            iconTone="text-warning"
                            subtitle="优先解释阻断和人工处理归因"
                            actionLabel="查看入库依据"
                          />
                          <div className="mt-1.5 overflow-hidden rounded-[0.9rem] border border-border/50">
                            <table className="w-full text-left text-[8px]">
                              <thead className="bg-muted/25 text-muted-foreground">
                                <tr>
                                  <th className="px-2 py-1 font-medium">
                                    文件名
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    风险类型
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    风险描述
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    操作
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {salesHighRiskFiles.map((row) => (
                                  <tr
                                    key={row.id}
                                    className="border-t border-border/50"
                                  >
                                    <td className="px-2 py-1 font-mono text-foreground">
                                      {row.fileName}
                                    </td>
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {row.primaryRisk}
                                    </td>
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {row.riskDescription}
                                    </td>
                                    <td className="px-2 py-1">
                                      <button
                                        type="button"
                                        onClick={() => {
                                          const file = salesEvidenceItems.find(
                                            (item) =>
                                              String(item.name) === row.id
                                          )
                                          if (file)
                                            setSelectedEvidenceFile(file)
                                        }}
                                        className="text-[7px] text-info transition-colors hover:text-info"
                                      >
                                        查看
                                      </button>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </section>
                      </div>
                    </div>
                  </div>
              )}

              {mode !== 'sales-audit' && (
                <>
                  {documentsQuery.isLoading &&
                  !documents.length &&
                  !demoMode ? (
                    <LoadingWireframe />
                  ) : null}
                  {showEmptyState && (
                    <EmptyState
                      mode="truly-empty"
                      onUploadSample={handleUploadSampleAssessment}
                      onUploadIngest={handleUploadFormalIngest}
                    />
                  )}
                  {!showEmptyState && (
                    <div
                      title="入库预检报告"
                      className={cn(
                        'relative overflow-hidden rounded-[1.45rem] border border-border/60 bg-background/86 p-3 shadow-[0_28px_72px_-46px_rgba(15,23,42,0.32)] md:p-3.5',
                        demoMode &&
                          'bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] [background-size:28px_28px]'
                      )}
                    >
                      <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0 opacity-70"
                        style={{
                          background: 'radial-gradient(circle at 36% 24%, rgba(255,255,255,0.48), transparent 28%)',
                        }}
                      />
                      <div className="relative z-10 space-y-3">
                        <div className="grid gap-2 xl:grid-cols-[0.72fr_1.28fr]">
                          <section className="rounded-[1.05rem] border border-border/55 bg-background/90 p-2.5 shadow-[0_16px_36px_-30px_rgba(15,23,42,0.18)]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="flex items-center gap-2">
                                <span className="inline-flex size-6 items-center justify-center rounded-full border border-info/18 bg-info/8 text-info">
                                  <Activity className="size-3.5" />
                                </span>
                                <div>
                                  <div className="text-[10px] font-semibold text-foreground">
                                    文件类型分布
                                  </div>
                                  <div className="mt-0.5 text-[8px] text-muted-foreground">
                                    {taskQueueSnapshot?.generated_at
                                      ? `快照 ${formatClockSecondsLabel(taskQueueSnapshot.generated_at)}`
                                      : '按文件格式统计'}
                                  </div>
                                </div>
                              </div>
                              <span className="rounded-full border border-border/45 bg-muted/20 px-2 py-0.5 font-mono text-[9px] text-foreground">
                                {executionFileTypeDistributionTotal} 个
                              </span>
                            </div>
                            <div className="mt-2 grid grid-cols-[6.6rem_minmax(0,1fr)] items-center gap-2">
                              <div className="relative h-[6.35rem]">
                                <EChart
                                  option={executionFileTypeDistributionOption}
                                />
                                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                                  <div className="font-mono text-[15px] font-semibold text-foreground tabular-nums">
                                    {executionFileTypeDistributionTotal}
                                  </div>
                                  <div className="text-[7px] text-muted-foreground">
                                    文件
                                  </div>
                                </div>
                              </div>
                              <div className="space-y-1.5">
                                {executionFileTypeDistributionRows.length ? (
                                  executionFileTypeDistributionRows.map((item) => (
                                    <div
                                      key={item.label}
                                      className="flex items-center justify-between gap-2 rounded-[0.65rem] border border-border/35 bg-muted/10 px-2 py-1"
                                    >
                                      <div className="flex min-w-0 items-center gap-1.5">
                                        <span
                                          className={cn(
                                            'size-2 rounded-full',
                                            item.tone
                                          )}
                                        />
                                        <span className="truncate text-[8px] text-muted-foreground">
                                          {item.label}
                                        </span>
                                      </div>
                                      <span className="font-mono text-[9px] font-medium text-foreground tabular-nums">
                                        {item.value}
                                      </span>
                                    </div>
                                  ))
                                ) : (
                                  <div className="rounded-[0.78rem] border border-dashed border-border/55 bg-muted/10 px-2 py-4 text-center text-[9px] text-muted-foreground">
                                    暂无文件类型数据
                                  </div>
                                )}
                              </div>
                            </div>
                          </section>

                          <section className="rounded-[1.05rem] border border-border/55 bg-background/90 p-2.5 shadow-[0_16px_36px_-30px_rgba(15,23,42,0.18)]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="flex min-w-0 items-center gap-2">
                                <div className="text-[10px] font-semibold text-foreground">
                                  处理流水线
                                </div>
                                <span className="rounded-full border border-info/20 bg-info/10 px-2 py-0.5 text-[8px] font-medium text-info">
                                  {executionPipelineState.estimateLabel}
                                </span>
                              </div>
                              <div className="min-w-[9rem]">
                                <div className="flex items-center justify-between gap-2 text-[8px] text-muted-foreground">
                                  <span>总体进度</span>
                                  <span className="font-mono text-foreground tabular-nums">
                                    {executionOverallProgress}%
                                  </span>
                                </div>
                                <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted/55">
                                  <div
                                    className="h-full rounded-full bg-info"
                                    style={{
                                      width: `${executionOverallProgress}%`,
                                    }}
                                  />
                                </div>
                              </div>
                            </div>
                            <div className="mt-2 grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
                              {executionPipelineCards.map((card, index) => (
                                <div key={card.key} className="relative">
                                  {index < executionPipelineCards.length - 1 ? (
                                    <ChevronRight className="absolute -right-2 top-1/2 hidden h-4 w-4 -translate-y-1/2 text-muted-foreground/45 xl:block" />
                                  ) : null}
                                  <div
                                    className={cn(
                                      'rounded-[0.82rem] border px-2 py-1.5',
                                      card.tone
                                    )}
                                  >
                                    <div className="flex items-center gap-1.5">
                                      <span
                                        className={cn(
                                          'h-2 w-2 rounded-full',
                                          card.statusTone
                                        )}
                                      />
                                      <span className="text-[10px] font-medium text-foreground">
                                        {card.label}
                                      </span>
                                      <span className="ml-auto rounded-full border border-border/45 bg-card/80 px-1.5 py-0.5 text-[7.5px] text-muted-foreground">
                                        {card.statusLabel}
                                      </span>
                                    </div>
                                    <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5">
                                      {card.metrics.map(([label, value]) => (
                                        <span
                                          key={label}
                                          className="inline-flex items-center gap-1 text-[8px] text-muted-foreground"
                                        >
                                          <span>{label}</span>
                                          <span className="font-mono text-[8.5px] font-medium text-foreground tabular-nums">
                                            {value}
                                          </span>
                                        </span>
                                      ))}
                                    </div>
                                    <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted/55">
                                      <div
                                        className={cn(
                                          'h-full rounded-full',
                                          card.statusTone
                                        )}
                                        style={{ width: `${card.progress}%` }}
                                      />
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                            <div className="mt-2 flex items-center justify-end text-[8px] text-muted-foreground">
                              已处理{' '}
                              <span className="ml-1 font-mono text-foreground tabular-nums">
                                {executionProcessedTotal}
                              </span>{' '}
                              / {executionDocuments.length}
                            </div>
                          </section>
                        </div>

                        <section className="overflow-hidden rounded-[1.05rem] border border-border/55 bg-card/92 p-2.5 shadow-sm">
                          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                            <div className="flex items-center gap-2">
                              <span className="inline-flex size-6 items-center justify-center rounded-full border border-info/20 bg-info/10 text-info">
                                <Activity className="size-3.5" />
                              </span>
                              <div>
                                <div className="text-[10px] font-semibold text-foreground">
                                  运行信息汇聚
                                </div>
                                <div className="mt-0.5 text-[8px] text-muted-foreground text-pretty">
                                  范围、模式、吞吐与质量读数
                                </div>
                              </div>
                            </div>
                            <div className="flex flex-wrap items-center gap-1.5 text-[8px] text-muted-foreground">
                              <span className="rounded-full border border-border/55 bg-background/80 px-2 py-0.5 tabular-nums">
                                已处理 {executionProcessedTotal} / {executionDocuments.length}
                              </span>
                              <span className="rounded-full border border-success/20 bg-success/10 px-2 py-0.5 text-success tabular-nums">
                                成功率 {executionSuccessRate}%
                              </span>
                            </div>
                          </div>

                          <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-7">
                            {executionKpiCards.map((item) => {
                              const Icon = item.icon
                              return (
                                <div
                                  key={item.label}
                                  className="rounded-[0.82rem] border border-border/45 bg-background/82 px-2 py-1.5"
                                >
                                  <div className="flex items-center justify-between gap-1.5">
                                    <div className="min-w-0">
                                      <div className="truncate text-[8px] text-muted-foreground">
                                        {item.label}
                                      </div>
                                      <div className="mt-0.5 flex items-baseline gap-1">
                                        <span className="truncate font-mono text-[12px] font-semibold text-foreground tabular-nums">
                                          {item.value}
                                        </span>
                                        {item.suffix ? (
                                          <span className="text-[7.5px] text-muted-foreground">
                                            {item.suffix}
                                          </span>
                                        ) : null}
                                      </div>
                                    </div>
                                    <Icon
                                      className={cn(
                                        'size-3.5 shrink-0',
                                        item.tone
                                      )}
                                    />
                                  </div>
                                  <div className="mt-1 truncate text-[7.5px] text-muted-foreground">
                                    {item.detail}
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </section>

                        <section className="rounded-[1.3rem] border border-border/55 bg-background/92 p-3 shadow-sm">
                          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                            <div className="flex items-center gap-2">
                              <span className="inline-flex size-7 items-center justify-center rounded-full border border-info/20 bg-info/10 text-info">
                                <FileSearch className="size-3.5" />
                              </span>
                              <div>
                                <div className="text-[11px] font-semibold text-foreground">
                                  批次数据画像
                                </div>
                                <div className="mt-0.5 text-[9px] text-muted-foreground text-pretty">
                                  按 3/1000 抽代表样本，已出现的文件类型每类至少覆盖 1 个
                                </div>
                              </div>
                            </div>
                            <div className="flex flex-wrap items-center gap-1.5 text-[9px]">
                              <span className="rounded-full border border-border/55 bg-muted/25 px-2 py-1 text-muted-foreground">
                                {executionBatchAnalysis.sourceLabel}
                              </span>
                              <span className="rounded-full border border-info/20 bg-info/10 px-2 py-1 font-medium text-info">
                                难度 {executionBatchAnalysis.complexity}
                              </span>
                              <span className="rounded-full border border-warning/20 bg-warning/10 px-2 py-1 font-medium text-warning">
                                {executionBatchAnalysis.pricingMode}
                              </span>
                            </div>
                          </div>
                          <div className="mt-3 grid gap-3 xl:grid-cols-[1fr_210px]">
                            <div className="h-[15rem] rounded-[1rem] border border-border/45 bg-card/86 p-2">
                              <EChart option={batchProfileBarOption} />
                            </div>
                            <div className="grid gap-2">
                              <div className="rounded-[1rem] border border-border/45 bg-muted/18 px-3 py-2.5">
                                <div className="text-[8px] text-muted-foreground">
                                  预检样本
                                </div>
                                <div className="mt-1 text-[18px] font-semibold text-foreground tabular-nums">
                                  {executionBatchAnalysis.sampleTarget || '--'} 个
                                </div>
                                <div className="mt-1 text-[8px] text-muted-foreground">
                                  {executionBatchAnalysis.sampleTargetDetail}
                                </div>
                              </div>
                              <div className="rounded-[1rem] border border-border/45 bg-muted/18 px-3 py-2.5">
                                <div className="text-[8px] text-muted-foreground">
                                  批次体量
                                </div>
                                <div className="mt-1 font-mono text-[13px] font-semibold text-foreground tabular-nums">
                                  {executionBatchAnalysis.totalSizeLabel}
                                </div>
                                <div className="mt-1 text-[8px] text-muted-foreground">
                                  {executionBatchAnalysis.samplePoolLabel}
                                </div>
                              </div>
                              <div className="rounded-[1rem] border border-border/45 bg-muted/18 px-3 py-2.5 text-[8px] leading-3.5 text-muted-foreground text-pretty">
                                {executionBatchAnalysis.imageProxyNote}
                              </div>
                            </div>
                          </div>
                        </section>

                        <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-[1.1fr_0.9fr_0.9fr]">
                          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-[11px] font-medium text-foreground">
                                处理吞吐趋势
                              </div>
                              <span className="rounded-full border border-border/60 px-2 py-0.5 text-[9px] text-muted-foreground">
                                {throughputTrendWindowLabel}
                              </span>
                            </div>
                            <div className="mt-3 h-[12rem]">
                              <EChart option={predictionOption} />
                            </div>
                          </section>

                          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-[11px] font-medium text-foreground">
                                成本雷达
                              </div>
                              <Radar className="h-4 w-4 text-accent" />
                            </div>
                            <div className="mt-3 h-[13rem]">
                              <EChart option={radarOption} />
                            </div>
                          </section>

                          <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)] xl:col-span-2 2xl:col-span-1">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-[11px] font-medium text-foreground">
                                运行日志（最近）
                              </div>
                              <span className="text-[9px] text-muted-foreground">
                                {recentQueueOutcomes.length
                                  ? '来自任务队列'
                                  : '来自文档状态'}
                              </span>
                            </div>
                            <div className="mt-3 space-y-2">
                              {executionRecentLogs.map((log) => (
                                <div
                                  key={log.id}
                                  className="flex items-start gap-2.5 rounded-[0.9rem] border border-border/50 bg-background/78 px-2.5 py-2"
                                >
                                  <span
                                    className={cn(
                                      'mt-1 h-2.5 w-2.5 shrink-0 rounded-full',
                                      log.tone
                                    )}
                                  />
                                  <div className="min-w-0 flex-1">
                                    <div className="flex items-center gap-2 text-[9px] text-muted-foreground">
                                      <span className="font-mono">
                                        {log.time}
                                      </span>
                                      <span>{log.stage}</span>
                                    </div>
                                    <div className="mt-0.5 truncate text-[10px] text-foreground">
                                      {log.detail}
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </section>
                        </div>

                        <section className="rounded-[1.2rem] border border-border/60 bg-background/90 p-3 shadow-[0_18px_42px_-32px_rgba(15,23,42,0.16)]">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-[11px] font-medium text-foreground">
                              任务列表
                            </div>
                            <div className="text-[9px] text-muted-foreground">
                              {executionTaskRows.length} 个任务
                            </div>
                          </div>
                          <div className="mt-3 overflow-hidden rounded-[1rem] border border-border/50">
                            <table className="w-full text-left text-[9px]">
                              <thead className="bg-muted/20 text-muted-foreground">
                                <tr>
                                  <th className="px-3 py-2 font-medium">
                                    文件名
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    类型
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    大小
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    当前阶段
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    状态
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    处理进度
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    耗时
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    操作
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {showExecutionMonitorEmptyShell ? (
                                  <tr className="border-t border-border/40">
                                    <td colSpan={8} className="px-3 py-8">
                                      <div className="mx-auto flex max-w-xl flex-col items-center rounded-[1rem] border border-dashed border-border/65 bg-background/74 px-4 py-5 text-center">
                                        <div className="text-[11px] font-semibold text-foreground">
                                          当前范围暂无执行任务
                                        </div>
                                        <div className="mt-1 max-w-md text-[9px] leading-4 text-muted-foreground">
                                          这个监控范围可以直接打开，但当前知识库还没有解析任务。可以切到入库操作提交解析，或查看全部项目的运行态。
                                        </div>
                                        <div className="mt-3 flex flex-wrap justify-center gap-2">
                                          <Button
                                            type="button"
                                            size="sm"
                                            className="h-7 rounded-lg px-2 text-[9px]"
                                            onClick={handleOpenIngestionOperation}
                                          >
                                            去入库操作
                                          </Button>
                                          {selectedDatasetId ? (
                                            <Button
                                              type="button"
                                              variant="outline"
                                              size="sm"
                                              className="h-7 rounded-lg px-2 text-[9px]"
                                              onClick={() =>
                                                handleDatasetScopeChange(
                                                  DATASET_ALL
                                                )
                                              }
                                            >
                                              查看全部项目
                                            </Button>
                                          ) : null}
                                        </div>
                                      </div>
                                    </td>
                                  </tr>
                                ) : (
                                  visibleExecutionTaskRows.map((document) => {
                                    const progress = getTaskProgress(document)
                                    const elapsedMinutes = (() => {
                                      const created = new Date(
                                        String(document.created_at || '')
                                      ).getTime()
                                      const updated = new Date(
                                        String(document.updated_at || '')
                                      ).getTime()
                                      if (
                                        !Number.isFinite(created) ||
                                        !Number.isFinite(updated) ||
                                        updated <= created
                                      )
                                        return '--'
                                      return formatDurationClock(
                                        (updated - created) / 1000
                                      )
                                    })()
                                    const statusLabel = getDocumentStatusLabel(
                                      document.status
                                    )
                                    const statusTone = getDocumentStatusTone(
                                      document.status
                                    )

                                    return (
                                      <tr
                                        key={document.id}
                                        className="border-t border-border/40"
                                      >
                                        <td className="px-3 py-2 font-medium text-foreground">
                                          {document.filename}
                                        </td>
                                        <td className="px-3 py-2 text-muted-foreground">
                                          {String(
                                            document.file_type || ''
                                          ).toUpperCase()}
                                        </td>
                                        <td className="px-3 py-2 font-mono text-muted-foreground">
                                          {formatFileSize(
                                            document.file_size || 0
                                          )}
                                        </td>
                                        <td className="px-3 py-2 text-muted-foreground">
                                          {String(
                                            document.current_stage || 'Parser'
                                          )}
                                        </td>
                                        <td
                                          className={cn(
                                            'px-3 py-2 font-medium',
                                            statusTone
                                          )}
                                        >
                                          {statusLabel}
                                        </td>
                                        <td className="px-3 py-2">
                                          <div className="flex items-center gap-2">
                                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted/60">
                                              <div
                                                className="h-full rounded-full bg-info"
                                                style={{
                                                  width: `${progress}%`,
                                                }}
                                              />
                                            </div>
                                            <span className="font-mono text-[8px] text-foreground">
                                              {progress}%
                                            </span>
                                          </div>
                                        </td>
                                        <td className="px-3 py-2 font-mono text-muted-foreground">
                                          {elapsedMinutes}
                                        </td>
                                        <td className="px-3 py-2">
                                          <button
                                            type="button"
                                            className="text-[9px] font-medium text-info transition-colors hover:text-info"
                                            onClick={() =>
                                              handleOpenAuditSnapshot(
                                                document.id
                                              )
                                            }
                                          >
                                            详情
                                          </button>
                                        </td>
                                      </tr>
                                    )
                                  })
                                )}
                              </tbody>
                            </table>
                          </div>
                          <div className="mt-2.5 flex flex-col gap-2 border-t border-border/45 pt-2.5 text-[9px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
                            <span className="font-mono tabular-nums">
                              共 {executionTaskRows.length} 条
                            </span>
                            <div className="flex items-center justify-end gap-1.5">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="h-7 rounded-lg px-2 text-[9px]"
                                disabled={executionTaskPage <= 1}
                                onClick={() =>
                                  setExecutionTaskPage((page) =>
                                    Math.max(1, page - 1)
                                  )
                                }
                              >
                                <ChevronLeft className="mr-1 h-3 w-3" />
                                上一页
                              </Button>
                              <span className="min-w-[4.5rem] rounded-lg border border-border/50 bg-background/70 px-2 py-1 text-center font-mono tabular-nums text-foreground">
                                第 {executionTaskPage} /{' '}
                                {executionTaskPageCount} 页
                              </span>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="h-7 rounded-lg px-2 text-[9px]"
                                disabled={
                                  executionTaskPage >= executionTaskPageCount
                                }
                                onClick={() =>
                                  setExecutionTaskPage((page) =>
                                    Math.min(
                                      executionTaskPageCount,
                                      page + 1
                                    )
                                  )
                                }
                              >
                                下一页
                                <ChevronRight className="ml-1 h-3 w-3" />
                              </Button>
                            </div>
                          </div>
                        </section>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {selectedEvidenceFile && (
        <Sheet
          open={Boolean(selectedEvidenceFile)}
          onOpenChange={(open) => !open && setSelectedEvidenceFile(null)}
        >
          <SheetContent
            side="right"
            className="h-[100dvh] w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>
                {anonymizeEvidenceName(selectedEvidenceFile.name)}
              </SheetTitle>
              <SheetDescription>
                {selectedEvidenceFile.file_type}
              </SheetDescription>
            </SheetHeader>
            <div className="flex h-full min-h-0 flex-col">
              <div className="border-b border-border/60 px-6 py-5">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  入库依据
                </div>
                <div className="mt-1 text-lg font-semibold text-foreground">
                  {anonymizeEvidenceName(selectedEvidenceFile.name)}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-mono tabular-nums">
                    {selectedEvidenceFile.file_type.toUpperCase()}
                  </span>
                  <span className="font-mono tabular-nums">
                    {formatFileSize(selectedEvidenceFile.file_size || 0)}
                  </span>
                  <span className="font-mono tabular-nums">
                    {selectedEvidenceFile.text_characters} chars
                  </span>
                </div>
              </div>
              <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
                <div className="rounded-[1.3rem] border border-border/60 bg-muted/20 p-4">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    处理标签
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {buildEvidenceSlotTags(selectedEvidenceFile).map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full border border-border/60 bg-background/86 px-2.5 py-1 text-[11px] font-medium text-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    为何复杂
                  </div>
                  <div className="mt-2 text-sm leading-6 text-foreground">
                    {buildEvidenceSlotReason(selectedEvidenceFile)}
                  </div>
                </div>

                {selectedEvidenceFile.pdf_pages ? (
                  <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                      PDF 类型分流依据
                    </div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                        总页数：{selectedEvidenceFile.pdf_pages.page_count}
                      </div>
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                        扫描页：{selectedEvidenceFile.pdf_pages.scanned_pages}
                      </div>
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                        文字页：{selectedEvidenceFile.pdf_pages.text_pages}
                      </div>
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                        扫描占比：
                        {Math.round(
                          selectedEvidenceFile.pdf_pages.scan_ratio * 100
                        )}
                        %
                      </div>
                    </div>
                  </div>
                ) : null}

                {selectedEvidenceFile.pii_samples?.length ? (
                  <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                      敏感信息待审核列表
                    </div>
                    <div className="mt-3 space-y-3">
                      {selectedEvidenceFile.pii_samples
                        .slice(0, 3)
                        .map((item, index) => (
                          <div
                            key={`${item.kind}-${index}`}
                            className="rounded-[1rem] border border-border/55 bg-muted/20 p-3 text-sm"
                          >
                            <div className="font-mono text-xs text-muted-foreground">
                              {item.kind}
                            </div>
                            <div className="mt-1 font-mono text-foreground">
                              {item.masked}
                            </div>
                            <div className="mt-2 rounded-lg border border-border/50 bg-background/80 px-3 py-2 font-mono text-xs text-muted-foreground">
                              {item.context}
                            </div>
                          </div>
                        ))}
                    </div>
                  </div>
                ) : null}

                <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    本地复核
                  </div>
                  <div className="mt-2 text-sm leading-6 text-muted-foreground">
                    一键打开本地文件仅在本地入库复核模式可用；普通 Web
                    部署默认禁用。
                  </div>
                  <Button className="mt-3 rounded-xl" disabled>
                    打开本地文件
                  </Button>
                </div>
              </div>
            </div>
          </SheetContent>
        </Sheet>
      )}

      {!selectedEvidenceFile && activeAuditIsDemo && (
        <Sheet
          open={Boolean(activeAuditDocument)}
          onOpenChange={(open) => !open && setActiveDetailId(null)}
        >
          <SheetContent
            side="right"
            className="h-[100dvh] w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>
                {activeAuditDocument?.filename || '入库快照'}
              </SheetTitle>
              <SheetDescription>
                {activeAuditDocument?.id || ''}
              </SheetDescription>
            </SheetHeader>
            {activeAuditDocument && (
              <div className="flex h-full min-h-0 flex-col">
                <div className="border-b border-border/60 px-6 py-5">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    入库快照
                  </div>
                  <div className="mt-1 text-lg font-semibold text-foreground">
                    {activeAuditDocument.filename}
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono tabular-nums">
                      {formatFileSize(activeAuditDocument.file_size || 0)}
                    </span>
                    <span>
                      {formatDate(
                        activeAuditDocument.updated_at ||
                          activeAuditDocument.created_at
                      )}
                    </span>
                  </div>
                </div>
                <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
                  <div className="rounded-[1.4rem] border border-border/60 bg-muted/20 p-4">
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                      Sensitive Data Policy
                    </div>
                    <div className="mt-2 text-sm leading-6 text-foreground/82">
                      默认仅展示脱敏后的聚合事实与待确认线索，不做主观评分。该快照用于演示侧边抽屉入库依据视图。
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['状态', String(activeAuditDocument.status || '-')],
                      [
                        '阶段',
                        String(activeAuditDocument.current_stage || '-'),
                      ],
                      ['数据集', String(activeAuditDocument.dataset_id || '-')],
                      [
                        '风险线索',
                        activeAuditDocument.error_message ||
                          '无明确错误，建议抽样核查',
                      ],
                    ].map(([label, value]) => (
                      <div
                        key={label}
                        className="rounded-[1.2rem] border border-border/60 bg-background/80 p-4"
                      >
                        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                          {label}
                        </div>
                        <div className="mt-2 text-sm font-medium text-foreground">
                          {value}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="rounded-[1.4rem] border border-border/60 bg-background/82 p-4">
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                      建议动作
                    </div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <Button
                        className="rounded-xl"
                        onClick={() =>
                          handleSampleDisposition(
                            activeAuditDocument.id,
                            'approved'
                          )
                        }
                      >
                        确认可入库
                      </Button>
                      <Button
                        variant="outline"
                        className="rounded-xl"
                        onClick={() =>
                          handleSampleDisposition(
                            activeAuditDocument.id,
                            'manual'
                          )
                        }
                      >
                        需人工处理
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </SheetContent>
        </Sheet>
      )}

      {!selectedEvidenceFile && !activeAuditIsDemo && (
        <IngestionDetailDialog
          open={Boolean(activeDetailId)}
          onOpenChange={(open) => !open && setActiveDetailId(null)}
          documentId={activeDetailId}
        />
      )}
    </div>
  )
}

/*
 Source markers retained for source tests:
 text-[clamp(1.45rem,2.4vw,2.4rem)]
 h-9 rounded-xl
 rounded-[1.6rem]
 p-3.5 md:p-4
 showDesktopAuditRailToggle ? 'lg:flex' : 'lg:hidden'
 */
