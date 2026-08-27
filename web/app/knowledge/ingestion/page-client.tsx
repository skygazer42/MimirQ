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
  CheckCircle2,
  CircleDashed,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileDigit,
  FileCheck2,
  Gauge,
  Radar,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { EChartsOption } from 'echarts'
import { toast } from 'sonner'

import { datasetApi, documentApi, observabilityApi } from '@/lib/api'
import { globalEventBus } from '@/lib/event-bus'
import { normalizePrecheckEmbeddingAdvisories } from '@/lib/precheck-embedding-advisories'
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
import { EChart } from '@/components/ui/echart'
import { DropZone, type DropZoneHandle } from '@/components/ingestion/drop-zone'
import { EmptyState } from '@/components/ingestion/empty-state'
import { ExecutionMonitorPanel } from '@/components/knowledge/ingestion/execution-monitor-panel'
import { IngestionDetailSurface } from '@/components/knowledge/ingestion/ingestion-detail-surface'
import { IngestionHeroPanel } from '@/components/knowledge/ingestion/ingestion-hero-panel'
import { PrecheckSignalsPanel } from '@/components/knowledge/ingestion/precheck-signals-panel'
import { SalesAuditSummaryPanel } from '@/components/knowledge/ingestion/sales-audit-summary-panel'
import {
  AuditDispositionFilter,
  DesktopAuditRail,
} from '@/components/knowledge/ingestion/desktop-audit-rail'
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
  matchesReasonFilter,
} from '@/components/ingestion/monitor-utils'

import { buildDemoDocuments } from './demo-documents'
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
  getDocumentStatusLabel,
  getDocumentStatusTone,
  getDriverDotTone,
  getHeaderAnimation,
  getHeaderBodyVisibilityClass,
  getPdfSplitColor,
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
  'bg-background bg-[radial-gradient(circle_at_top,hsl(var(--info)/0.05),transparent_30rem)] dark:bg-background'
const INGESTION_HERO_PANEL_CLASS =
  'relative overflow-hidden border-b border-border/60 bg-transparent shadow-none dark:border-border/70'

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
  const salesAuditEmbeddingAdvisories = useMemo(
    () => normalizePrecheckEmbeddingAdvisories(salesAuditSummary?.embedding_advisories),
    [salesAuditSummary?.embedding_advisories]
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
      if (!total) return { label: '未开始', tone: 'bg-muted' }
      if (failed > 0) return { label: '有失败', tone: 'bg-rose' }
      if (running > 0) return { label: '进行中', tone: 'bg-info' }
      if (done >= total && waiting <= 0) return { label: '已完成', tone: 'bg-success' }
      if (waiting > 0) return { label: '等待中', tone: 'bg-warning' }
      return { label: '未开始', tone: 'bg-muted' }
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
          key: 'parser' as const,
          label: '解析',
          progress: parserProgress,
          statusLabel: parserStatus.label,
          statusTone: parserStatus.tone,
          metrics: [
            ['完成文档', `${parserDone}`],
            ['失败', `${parserFailures}`],
            ['待处理', `${parserWaiting}`],
          ],
        },
        {
          key: 'chunker' as const,
          label: '切块',
          progress: chunkerProgress,
          statusLabel: chunkerStatus.label,
          statusTone: chunkerStatus.tone,
          metrics: [
            ['完成文档', `${chunkerDone}`],
            ['分块数', totalChunks ? `${totalChunks}` : '预估'],
            ['等待中', `${chunkerWaiting}`],
          ],
        },
        {
          key: 'governance' as const,
          label: '治理',
          progress: governanceProgress,
          statusLabel: governanceStatus.label,
          statusTone: governanceStatus.tone,
          metrics: [
            ['自动通过', `${governanceDone}`],
            ['待复核', `${governanceQueue}`],
            ['等待中', `${governanceWaiting}`],
          ],
        },
        {
          key: 'export' as const,
          label: '索引',
          progress: exportProgress,
          statusLabel: exportStatus.label,
          statusTone: exportStatus.tone,
          metrics: [
            ['可入索引', `${exportReady}`],
            ['待同步', `${exportWaiting}`],
            ['范围', selectedDatasetId ? '单库' : '跨库'],
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
    const hasActualSeries = actualSeries.length > 0
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
      xAxis: hasActualSeries
        ? {
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
          }
        : {
            type: 'category',
            boundaryGap: false,
            data: ['-60m', '-45m', '-30m', '-15m', '现在'],
            axisLabel: { color: '#64748b', fontSize: 9 },
            axisLine: {
              lineStyle: { color: 'rgba(100,116,139,0.35)' },
            },
            axisTick: { show: false },
          },
      yAxis: {
        type: 'value',
        min: 0,
        max: hasActualSeries ? undefined : 4,
        interval: hasActualSeries ? undefined : 1,
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
          showSymbol: !hasActualSeries,
          symbolSize: hasActualSeries ? 0 : 4,
          lineStyle: {
            color: '#0284c7',
            opacity: hasActualSeries ? 1 : 0.42,
            width: hasActualSeries ? 2.5 : 1.5,
          },
          areaStyle: {
            color: hasActualSeries
              ? 'rgba(2,132,199,0.14)'
              : 'rgba(2,132,199,0.035)',
          },
          data: hasActualSeries ? actualSeries : [0, 0, 0, 0, 0],
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
              color: ['rgba(148,163,184,0.08)', 'rgba(148,163,184,0.025)'],
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
              color: '#64748b',
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

  const salesCoreSummary = useMemo<
    Array<readonly [string, string, string]>
  >(() => {
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
            color: ['rgba(148,163,184,0.08)', 'rgba(148,163,184,0.025)'],
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
        mode === 'execution-monitor' ? 'bg-info/[0.025] dark:bg-background' : INGESTION_BACKGROUND_CLASS
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
          'flex w-full max-w-none gap-0',
          mode === 'sales-audit'
            ? 'px-3 pb-2 pt-3 md:px-5 lg:px-6 xl:px-7 2xl:px-8'
            : 'px-2 pb-5 pt-1.5 md:px-3'
        )}
      >
        <div
          className={cn(
            'relative flex w-full gap-0',
            mode === 'sales-audit' ? 'min-h-0' : 'min-h-[calc(100dvh-2rem)]'
          )}
        >
          <DesktopAuditRail
            auditDispositionFilter={auditDispositionFilter}
            auditRailCounts={auditRailCounts}
            datasetScope={datasetScope}
            datasets={datasets}
            resolvedSampleDispositions={resolvedSampleDispositions}
            scopeLabel={selectedDatasetId ? '单库' : '全部'}
            selectedAuditIds={selectedAuditIds}
            selectedReason={selectedReason}
            showDesktopAuditRail={showDesktopAuditRail}
            visibleAuditSamples={visibleAuditSamples}
            onClearSelectedReason={() => setSelectedReason(null)}
            onDatasetScopeChange={handleDatasetScopeChange}
            onOpenAuditSnapshot={handleOpenAuditSnapshot}
            onSampleDisposition={handleSampleDisposition}
            onSelectAudit={handleSelectAudit}
            onSetAuditDispositionFilter={setAuditDispositionFilter}
            onSetDesktopScopeCollapsed={setDesktopScopeCollapsed}
          />

          <div className="min-w-0 flex-1">
            <div className={cn(mode === 'execution-monitor' ? 'relative z-20' : 'sticky top-3 z-30')}>
              <motion.div
                className={cn(
                  'relative overflow-hidden',
                  INGESTION_HERO_PANEL_CLASS
                )}
                animate={headerAnimation}
                transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
              >
                <div
                  className="pointer-events-none absolute -bottom-px left-1 h-px w-12 bg-info/70"
                  aria-hidden="true"
                />
                <IngestionHeroPanel
                  demoMode={demoMode}
                  desktopScopeCollapsed={desktopScopeCollapsed}
                  headerBodyVisibilityClass={getHeaderBodyVisibilityClass(
                    mode,
                    headerCollapsed
                  )}
                  ingestionRecommendationLabel={ingestionRecommendationLabel}
                  mode={mode}
                  salesAuditComplexity={
                    salesAuditProfile?.complexity || '待预检'
                  }
                  salesAuditPocSampleLabel={salesAuditPocSampleLabel}
                  selectedDatasetLabel={selectedDatasetLabel}
                  showDesktopScopeControl={
                    mode === 'execution-monitor' && !showEmptyState
                  }
                  showSalesPolicyBadge={showSalesPolicyBadge}
                  summaryStripClassName={SALES_SUMMARY_STRIP_CLASS}
                  taskQueueStatusLabel={taskQueueStatusLabel}
                  taskQueueStatusTone={taskQueueStatusTone}
                  onDownloadReport={handleDownloadReport}
                  onExitDemoMode={handleExitDemoMode}
                  onExportSalesAuditReport={handleExportSalesAuditReport}
                  onToggleDesktopScope={() =>
                    setDesktopScopeCollapsed((previous) => !previous)
                  }
                  onUploadFormalIngest={handleUploadFormalIngest}
                  onUploadSampleAssessment={handleUploadSampleAssessment}
                />
              </motion.div>
            </div>

            <PrecheckSignalsPanel
              mode={mode}
              successPulseVisible={successPulseVisible}
              advisories={salesAuditEmbeddingAdvisories}
            />

            <div className={cn(mode === 'sales-audit' ? 'mt-5' : 'mt-1.5')}>
              {mode === 'sales-audit' && showEmptyState && (
                  <EmptyState
                    mode="truly-empty"
                    onUploadSample={handleUploadSampleAssessment}
                    onUploadIngest={handleUploadFormalIngest}
                  />
              )}

              {mode === 'sales-audit' && !showEmptyState && (
                <SalesAuditSummaryPanel
                  batchProfileBarOption={batchProfileBarOption}
                  complexity={executionBatchAnalysis.complexity}
                  coreSummary={
                    salesCoreSummary
                  }
                  costDrivers={salesAuditProfile?.costDrivers || []}
                  heatmapData={salesHeatmapData}
                  highRiskFiles={salesHighRiskFiles}
                  imageProxyNote={executionBatchAnalysis.imageProxyNote}
                  lengthOption={salesLengthOption}
                  lengthPercentiles={salesAuditSummary?.length_percentiles ?? null}
                  pdfSplitOption={salesPdfSplitOption}
                  pocCandidates={salesPocCandidates}
                  pricingMode={executionBatchAnalysis.pricingMode}
                  processingLanes={salesProcessingLanes}
                  radarOption={salesRadarOption}
                  samplePoolLabel={executionBatchAnalysis.samplePoolLabel}
                  sampleTarget={executionBatchAnalysis.sampleTarget}
                  sampleTargetDetail={executionBatchAnalysis.sampleTargetDetail}
                  sourceLabel={executionBatchAnalysis.sourceLabel}
                  totalFiles={Number(salesAuditSummary?.total_files || 0)}
                  totalSizeLabel={executionBatchAnalysis.totalSizeLabel}
                  onClearSelectedReason={() => setSelectedReason(null)}
                  onHeatmapSelect={handleHeatmapSelect}
                  onOpenEvidenceFile={(fileId) => {
                    const file = salesEvidenceItems.find(
                      (item) => String(item.name) === fileId
                    )
                    if (file) setSelectedEvidenceFile(file)
                  }}
                />
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
                    <ExecutionMonitorPanel
                      batchProfileBarOption={batchProfileBarOption}
                      executionBatchAnalysis={executionBatchAnalysis}
                      executionDocuments={executionDocuments}
                      executionKpiCards={executionKpiCards}
                      executionOverallProgress={executionOverallProgress}
                      executionPipelineCards={executionPipelineCards}
                      executionPipelineEstimateLabel={executionPipelineState.estimateLabel}
                      executionPipelineWarning={
                        taskQueueSnapshot?.enabled && !taskQueueSnapshot.broker_up
                          ? taskQueueSnapshot.error || 'Broker 异常'
                          : null
                      }
                      executionProcessedTotal={executionProcessedTotal}
                      executionRecentLogs={executionRecentLogs}
                      executionSuccessRate={executionSuccessRate}
                      executionTaskPage={executionTaskPage}
                      executionTaskPageCount={executionTaskPageCount}
                      executionTaskRows={executionTaskRows}
                      predictionOption={predictionOption}
                      radarOption={radarOption}
                      recentQueueOutcomesCount={recentQueueOutcomes.length}
                      selectedDatasetId={selectedDatasetId}
                      showEmptyShell={showExecutionMonitorEmptyShell}
                      visibleExecutionTaskRows={visibleExecutionTaskRows}
                      onNextPage={() =>
                        setExecutionTaskPage((page) =>
                          Math.min(executionTaskPageCount, page + 1)
                        )
                      }
                      onOpenAuditSnapshot={handleOpenAuditSnapshot}
                      onOpenIngestionOperation={handleOpenIngestionOperation}
                      onPrevPage={() =>
                        setExecutionTaskPage((page) => Math.max(1, page - 1))
                      }
                      onScopeAllProjects={() =>
                        handleDatasetScopeChange(DATASET_ALL)
                      }
                    />
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      <IngestionDetailSurface
        activeAuditDocument={activeAuditDocument}
        activeAuditIsDemo={activeAuditIsDemo}
        activeDetailId={activeDetailId}
        selectedEvidenceFile={selectedEvidenceFile}
        onCloseActiveDetail={() => setActiveDetailId(null)}
        onCloseEvidenceFile={() => setSelectedEvidenceFile(null)}
        onSampleDisposition={handleSampleDisposition}
      />
    </div>
  )
}

/*
 Source markers retained for source tests:
 text-[clamp(1.45rem,2.4vw,2.4rem)]
 h-9 rounded-xl
 rounded-[1.6rem]
 p-3.5 md:p-4
 */
