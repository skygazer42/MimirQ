'use client'

import { type MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import {
  Check,
  CircleDashed,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Download,
  FileDigit,
  FileCheck2,
  FileSearch,
  GripVertical,
  LucideIcon,
  Radar,
  ShieldAlert,
  ShieldCheck,
  TableProperties,
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
} from '@/types'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { useDatasets } from '@/hooks/use-datasets'
import { usePathname, useRouter } from '@/i18n/navigation'
import { Button } from '@/components/ui/button'
import { EChart } from '@/components/ui/echart'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { DropZone, type DropZoneHandle } from '@/components/ingestion/drop-zone'
import { EmptyState } from '@/components/ingestion/empty-state'
import { ErrorTreemap } from '@/components/ingestion/error-treemap'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import { LiveVelocity, persistVelocityUnit, readStoredVelocityUnit } from '@/components/ingestion/live-velocity'
import {
  buildEvidenceSlotReason,
  buildEvidenceSlotTags,
  buildFileSizeDistribution,
  buildFileTypeDistribution,
  buildPdfDispositionBreakdown,
  buildSalesAuditProfile,
  buildThroughputAreaRows,
  computeDocsPerMinute,
  computeDurationPercentiles,
  computeMeanFileSize,
  computeMegabytesPerSecond,
  computeRemainingMinutesEstimate,
  getDocumentKind,
  getDocumentKindAccent,
  matchesReasonFilter,
} from '@/components/ingestion/monitor-utils'
import { StatCard } from '@/components/ingestion/stat-card'

import { buildDemoDocuments } from './demo-documents'

const DATASET_ALL = '__all__'

type IngestionMode = 'sales-audit' | 'execution-monitor'
type SampleDisposition = 'approved' | 'manual'
type TopologyFocus = 'parser' | 'chunker' | 'governance'

function safeNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function formatClockLabel(value: number): string {
  const date = new Date(value)
  const hours = `${date.getHours()}`.padStart(2, '0')
  const minutes = `${date.getMinutes()}`.padStart(2, '0')
  return `${hours}:${minutes}`
}

function downloadTextFile(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function buildFallbackSummary(
  documents: Document[],
  datasetId?: string | null
): IngestionDashboardSummaryResponse {
  const byStatus = documents.reduce<Record<string, number>>((acc, document) => {
    const key = String(document.status || 'unknown')
    acc[key] = (acc[key] ?? 0) + 1
    return acc
  }, {})

  const byStageProcessing = documents.reduce<Record<string, number>>((acc, document) => {
    const key = String(document.current_stage || document.status || 'queued')
    acc[key] = (acc[key] ?? 0) + 1
    return acc
  }, {})

  const topErrorReasons = documents.reduce<Record<string, number>>((acc, document) => {
    if (!document.error_message) return acc
    acc[document.error_message] = (acc[document.error_message] ?? 0) + 1
    return acc
  }, {})

  const bucketMinutes = 20
  const bucketCount = 8
  const now = Date.now()
  const completedBase = Math.max(1, byStatus.completed ?? 0)
  const failedBase = Math.max(0, byStatus.failed ?? 0)
  const quarantinedBase = Math.max(0, byStatus.quarantined ?? 0)
  const cancelledBase = Math.max(0, byStatus.cancelled ?? 0)

  const ts_ms = Array.from({ length: bucketCount }, (_, index) => now - (bucketCount - index - 1) * bucketMinutes * 60_000)
  const completed = ts_ms.map((_, index) => Math.max(0, Math.round((completedBase * (index + 2)) / (bucketCount + 2))))
  const failed = ts_ms.map((_, index) => (index % 3 === 0 ? failedBase : Math.max(0, failedBase - 1)))
  const quarantined = ts_ms.map((_, index) => (index % 4 === 0 ? quarantinedBase : Math.max(0, quarantinedBase - 1)))
  const cancelled = ts_ms.map((_, index) => (index === bucketCount - 2 ? cancelledBase : 0))

  return {
    window_hours: Math.round((bucketMinutes * bucketCount) / 60),
    bucket_minutes: bucketMinutes,
    window_start: new Date(ts_ms[0] ?? now).toISOString(),
    window_end: new Date(now).toISOString(),
    dataset_id: datasetId ?? null,
    created_count: documents.length,
    by_status: byStatus,
    by_stage_processing: byStageProcessing,
    avg_completed_latency_sec: computeDurationPercentiles(documents).p50 * 60,
    top_error_reasons: topErrorReasons,
    timeseries: {
      ts_ms,
      completed,
      failed,
      quarantined,
      cancelled,
    },
  }
}

function buildReportHtml({
  datasetLabel,
  totalDocs,
  readyRate,
  manualQueue,
  efficiency,
  latencyP90,
  selectedReason,
  documents,
}: Readonly<{
  datasetLabel: string
  totalDocs: number
  readyRate: number
  manualQueue: number
  efficiency: string
  latencyP90: string
  selectedReason: string | null
  documents: Document[]
}>) {
  const rows = documents
    .slice(0, 12)
    .map(
      (document) => `
        <tr>
          <td>${document.filename}</td>
          <td>${String(document.status || '-')}</td>
          <td>${String(document.current_stage || '-')}</td>
          <td>${formatFileSize(document.file_size || 0)}</td>
          <td>${document.error_message || '—'}</td>
        </tr>`
    )
    .join('')

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Audit Report</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 32px; color: #0f172a; }
    h1 { font-size: 28px; margin-bottom: 8px; }
    .muted { color: #475569; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 24px 0; }
    .card { border: 1px solid #cbd5e1; border-radius: 16px; padding: 16px; background: #f8fafc; }
    .label { font-size: 12px; text-transform: uppercase; letter-spacing: 0.16em; color: #64748b; }
    .value { margin-top: 8px; font-size: 22px; font-weight: 700; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; }
    th, td { border-bottom: 1px solid #e2e8f0; padding: 10px 8px; text-align: left; vertical-align: top; }
    th { font-size: 12px; text-transform: uppercase; color: #475569; }
  </style>
</head>
<body>
  <h1>项目数据盘点报告</h1>
  <div class="muted">Sensitive Data Policy: 默认仅展示脱敏后的聚合事实与待确认线索，不做主观评分；需要人工判断的项统一保留在样本槽与风险清单里。</div>
  <div class="grid">
    <div class="card"><div class="label">范围</div><div class="value">${datasetLabel}</div></div>
    <div class="card"><div class="label">文件总数</div><div class="value">${totalDocs}</div></div>
    <div class="card"><div class="label">健康可入库</div><div class="value">${readyRate}%</div></div>
    <div class="card"><div class="label">待人工处理</div><div class="value">${manualQueue}</div></div>
  </div>
  <div class="grid">
    <div class="card"><div class="label">处理效率</div><div class="value">${efficiency}</div></div>
    <div class="card"><div class="label">P90 周期</div><div class="value">${latencyP90}</div></div>
    <div class="card"><div class="label">当前聚焦线索</div><div class="value">${selectedReason || '全部'}</div></div>
    <div class="card"><div class="label">导出方式</div><div class="value">Print to PDF</div></div>
  </div>
  <table>
    <thead>
      <tr>
        <th>文件</th>
        <th>状态</th>
        <th>阶段</th>
        <th>大小</th>
        <th>线索</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
</body>
</html>`
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function anonymizeEvidenceName(name: string): string {
  const value = String(name || '')
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0
  }
  return `FILE_${hash.toString(36).toUpperCase().padStart(6, '0').slice(-6)}`
}

function buildDemoPrecheckSummary(documents: Document[]): DatasetPrecheckSummary {
  return {
    dataset_id: 'demo-dataset',
    scan_run_id: 'demo-run',
    generated_at: new Date().toISOString(),
    total_files: 12_543,
    total_size_bytes: Math.round(48.6 * 1024 * 1024 * 1024),
    by_file_type: { pdf: 7_854, docx: 2_112, xlsx: 1_420, pptx: 633, md: 524 },
    file_size_histogram: [
      { label: '<500KB', count: 3521 },
      { label: '500KB-2MB', count: 4873 },
      { label: '2MB-5MB', count: 2536 },
      { label: '5MB-10MB', count: 1140 },
      { label: '>10MB', count: 473 },
    ],
    length_percentiles: {
      p25: 812,
      p50: 1_876,
      p75: 5_314,
      p90: 9_816,
      p99: 23_654,
    },
    length_histogram: [
      { label: '<1k', count: 382 },
      { label: '1k-2k', count: 958 },
      { label: '2k-5k', count: 1731 },
      { label: '5k-10k', count: 1118 },
      { label: '10k-20k', count: 624 },
      { label: '20k-50k', count: 218 },
      { label: '50k-100k', count: 66 },
      { label: '>100k', count: 14 },
    ],
    pdf_scan: {
      scanned: 911,
      not_scanned: 8_645,
      unknown: 2_987,
    },
    pdf_detection: {
      text: 8_645,
      mixed: 2_987,
      scan: 911,
    },
    pii_hits_total: { phone: 524, email: 58, id_card: 19 },
    secrets_hits_total: {},
    findings: [
      { key: 'pdf_scanned', label: '扫描件', severity: 'warning', count: 1_956 },
      { key: 'parse_failed', label: '解析失败', severity: 'error', count: 412 },
      { key: 'pii', label: '合敏感信息', severity: 'warning', count: 736 },
      { key: 'exact_dup', label: '重复文件', severity: 'info', count: 1_128 },
      { key: 'near_dup', label: '版本冲突', severity: 'info', count: 342 },
      { key: 'other', label: '其他风险', severity: 'info', count: 289 },
    ],
  }
}

function buildDemoPrecheckSamples(documents: Document[]): DatasetPrecheckSamplesResponse {
  const fileItems: DatasetPrecheckFileOut[] = [
    {
      name: '财务报表_2024Q1.pdf',
      file_type: 'pdf',
      file_size: Math.round(138.5 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 220,
      estimated_text: false,
      pdf_scanned: true,
      pdf_pages: { page_count: 84, sampled_pages: 10, scanned_pages: 77, text_pages: 5, low_density_pages: 2, unknown_pages: 0, scan_ratio: 0.92, low_density_ratio: 0.02 },
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['pdf_scanned'],
      error_message: null,
    },
    {
      name: '员工手册_最新版.docx',
      file_type: 'docx',
      file_size: Math.round(24.3 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 12430,
      estimated_text: false,
      pdf_scanned: null,
      pdf_pages: null,
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['exact_dup', 'near_dup'],
      error_message: null,
    },
    {
      name: '合同_2024_v3.docx',
      file_type: 'docx',
      file_size: Math.round(12.7 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 9816,
      estimated_text: false,
      pdf_scanned: null,
      pdf_pages: null,
      spreadsheet: null,
      pii_hits: { phone: 2, email: 1 },
      secrets_hits: {},
      findings: ['pii'],
      error_message: null,
    },
    {
      name: '技术方案_无_汇总.pdf',
      file_type: 'pdf',
      file_size: Math.round(56.8 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 2310,
      estimated_text: false,
      pdf_scanned: false,
      pdf_pages: { page_count: 48, sampled_pages: 10, scanned_pages: 8, text_pages: 34, low_density_pages: 6, unknown_pages: 0, scan_ratio: 0.17, low_density_ratio: 0.12 },
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['near_dup'],
      error_message: null,
    },
    {
      name: '项目计划_需求.pptx',
      file_type: 'pptx',
      file_size: Math.round(18.2 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 1642,
      estimated_text: false,
      pdf_scanned: null,
      pdf_pages: null,
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['parse_failed'],
      error_message: '文档暂时解析失败',
    },
  ]

  return {
    requested: 5,
    strata_count: 4,
    representative: fileItems.slice(0, 3),
    needs_review: {
      pdf_scanned: fileItems.filter((file) => file.findings.includes('pdf_scanned')),
      parse_failed: fileItems.filter((file) => file.findings.includes('parse_failed')),
      pii: fileItems.filter((file) => file.findings.includes('pii')),
    },
    top_large_files: [...fileItems].sort((left, right) => right.file_size - left.file_size).slice(0, 5),
    top_long_text: [...fileItems].sort((left, right) => right.text_characters - left.text_characters).slice(0, 5),
  }
}

function buildDemoNearDupResponse(): DatasetPrecheckNearDupResponse {
  return {
    threshold: 5,
    max_pairs: 20,
    pairs_returned: 2,
    clusters_returned: 1,
    clusters: [{ id: 'demo-cluster-1', members: ['FILE_00A1BC', 'FILE_00A1BD'] }],
    pairs: [
      { a: 'FILE_00A1BC', b: 'FILE_00A1BD', distance: 2 },
      { a: 'FILE_00A1BE', b: 'FILE_00A1BF', distance: 3 },
    ],
  }
}

function LoadingWireframe() {
  return (
    <div className="space-y-4">
      <div className="rounded-[2rem] border border-border/50 bg-background/80 p-5">
        <div className="grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <div className="space-y-3 rounded-[1.5rem] border border-dashed border-border/60 bg-muted/20 p-4">
            <div className="h-4 w-32 rounded-full border border-border/50" />
            <div className="h-16 rounded-[1.25rem] border border-dashed border-border/60" />
            <div className="h-16 rounded-[1.25rem] border border-dashed border-border/60" />
            <div className="h-16 rounded-[1.25rem] border border-dashed border-border/60" />
          </div>
          <div className="space-y-4 rounded-[1.6rem] border border-dashed border-border/60 bg-background/90 p-4">
            <div className="h-12 rounded-[1rem] border border-border/50" />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <div key={index} className="h-24 rounded-[1.25rem] border border-dashed border-border/60 bg-muted/20" />
              ))}
            </div>
            <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
              <div className="h-[18rem] rounded-[1.25rem] border border-dashed border-border/60 bg-muted/15" />
              <div className="h-[18rem] rounded-[1.25rem] border border-dashed border-border/60 bg-muted/15" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

type SalesProcessingLane = {
  key: string
  label: string
  count: number
  tone: string
}

type SalesEvidenceTableRow = {
  id: string
  fileName: string
  fileType: string
  fileSizeLabel: string
  primaryRisk: string
  riskDescription: string
  actionLabel: string
  icon: LucideIcon
  iconTone: string
}

export default function KnowledgeIngestionPageClient() {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const reduceMotion = useReducedMotion()
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const dropZoneRef = useRef<DropZoneHandle>(null)
  const demoMode = searchParams.get('demo') === '1'
  const mode: IngestionMode = searchParams.get('mode') === 'execution-monitor' ? 'execution-monitor' : 'sales-audit'
  const [datasetScope, setDatasetScope] = useState(searchParams.get('datasetId') || DATASET_ALL)
  const [desktopScopeCollapsed, setDesktopScopeCollapsed] = useState(false)
  const [headerCollapsed, setHeaderCollapsed] = useState(false)
  const [topologyFocus, setTopologyFocus] = useState<TopologyFocus>('parser')
  const [selectedReason, setSelectedReason] = useState<string | null>(null)
  const [selectedAuditIds, setSelectedAuditIds] = useState<string[]>([])
  const [sampleDispositions, setSampleDispositions] = useState<Record<string, SampleDisposition>>({})
  const [activeDetailId, setActiveDetailId] = useState<string | null>(null)
  const [selectedEvidenceFile, setSelectedEvidenceFile] = useState<DatasetPrecheckFileOut | null>(null)
  const [velocityUnit, setVelocityUnit] = useState<'docs' | 'bytes'>(readStoredVelocityUnit)
  const [canvasGlow, setCanvasGlow] = useState({ x: 36, y: 24 })
  const [successPulseVisible, setSuccessPulseVisible] = useState(false)
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

  const precheckRunsQuery = useQuery({
    queryKey: ['knowledge-ingestion-precheck-runs', selectedDatasetId],
    queryFn: async () => {
      if (!selectedDatasetId) return []
      const response = await datasetApi.listPrecheckScanRuns(selectedDatasetId, { skip: 0, limit: 20 })
      return response.items ?? []
    },
    enabled: Boolean(selectedDatasetId) && !demoMode,
    staleTime: 10_000,
  })

  const latestPrecheckRun = useMemo(
    () =>
      (precheckRunsQuery.data ?? []).find((run) => String(run.status || '').toLowerCase() === 'completed') ??
      (precheckRunsQuery.data ?? [])[0] ??
      null,
    [precheckRunsQuery.data]
  )

  const precheckSummaryQuery = useQuery<DatasetPrecheckSummary | null>({
    queryKey: ['knowledge-ingestion-precheck-summary', selectedDatasetId, latestPrecheckRun?.id],
    queryFn: async () => {
      if (!selectedDatasetId || !latestPrecheckRun?.id) return null
      return await datasetApi.getPrecheckSummary(selectedDatasetId, latestPrecheckRun.id)
    },
    enabled: Boolean(selectedDatasetId && latestPrecheckRun?.id) && !demoMode,
    staleTime: 10_000,
  })

  const precheckSamplesQuery = useQuery<DatasetPrecheckSamplesResponse | null>({
    queryKey: ['knowledge-ingestion-precheck-samples', selectedDatasetId, latestPrecheckRun?.id],
    queryFn: async () => {
      if (!selectedDatasetId || !latestPrecheckRun?.id) return null
      return await datasetApi.getPrecheckSamples(selectedDatasetId, latestPrecheckRun.id, { prefer_artifact: true, size: 12 })
    },
    enabled: Boolean(selectedDatasetId && latestPrecheckRun?.id) && !demoMode,
    staleTime: 10_000,
  })

  const precheckNearDupQuery = useQuery<DatasetPrecheckNearDupResponse | null>({
    queryKey: ['knowledge-ingestion-precheck-near-dup', selectedDatasetId, latestPrecheckRun?.id],
    queryFn: async () => {
      if (!selectedDatasetId || !latestPrecheckRun?.id) return null
      return await datasetApi.getPrecheckNearDups(selectedDatasetId, latestPrecheckRun.id)
    },
    enabled: Boolean(selectedDatasetId && latestPrecheckRun?.id) && !demoMode,
    staleTime: 10_000,
  })

  const documents = useMemo(
    () => (demoMode ? buildDemoDocuments(documentsQuery.data ?? []) : documentsQuery.data ?? []),
    [demoMode, documentsQuery.data]
  )
  const summary = useMemo(
    () => summaryQuery.data ?? buildFallbackSummary(documents, selectedDatasetId),
    [documents, selectedDatasetId, summaryQuery.data]
  )
  const salesAuditSummary = useMemo(
    () => (demoMode ? buildDemoPrecheckSummary(documents) : precheckSummaryQuery.data),
    [demoMode, documents, precheckSummaryQuery.data]
  )
  const salesAuditSamples = useMemo(
    () => (demoMode ? buildDemoPrecheckSamples(documents) : precheckSamplesQuery.data),
    [demoMode, documents, precheckSamplesQuery.data]
  )
  const salesAuditNearDup = useMemo(
    () => (demoMode ? buildDemoNearDupResponse() : precheckNearDupQuery.data),
    [demoMode, precheckNearDupQuery.data]
  )

  useEffect(() => {
    const node = scrollContainerRef.current
    if (!node) return

    const handleScroll = () => {
      setHeaderCollapsed(node.scrollTop > 72)
    }

    handleScroll()
    node.addEventListener('scroll', handleScroll, { passive: true })
    return () => node.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    if (!successPulseVisible) return
    const timeoutId = globalThis.window.setTimeout(() => {
      setSuccessPulseVisible(false)
    }, 1400)
    return () => globalThis.window.clearTimeout(timeoutId)
  }, [successPulseVisible])

  const selectedDatasetLabel = useMemo(() => {
    if (!selectedDatasetId) return '全部项目'
    return datasets.find((dataset) => dataset.id === selectedDatasetId)?.name || selectedDatasetId
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

  const throughputRows = useMemo(() => buildThroughputAreaRows(summary.timeseries), [summary.timeseries])
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
  const megabytesPerSecond = useMemo(() => computeMegabytesPerSecond(documents), [documents])
  const durationPercentiles = useMemo(() => computeDurationPercentiles(documents), [documents])
  const meanFileSize = useMemo(() => computeMeanFileSize(documents), [documents])
  const fileTypeDistribution = useMemo(() => buildFileTypeDistribution(documents), [documents])
  const fileSizeDistribution = useMemo(() => buildFileSizeDistribution(documents), [documents])
  const pdfDisposition = useMemo(() => buildPdfDispositionBreakdown(documents), [documents])

  const reviewQueue = statusCounts.failed + statusCounts.quarantined
  const pendingQueue = statusCounts.processing + statusCounts.pending
  const approvedCount = Object.values(sampleDispositions).filter((value) => value === 'approved').length
  const manualCount = Object.values(sampleDispositions).filter((value) => value === 'manual').length
  const readyRate = documents.length
    ? Math.round(((statusCounts.completed + approvedCount) / documents.length) * 100)
    : 0

  const auditCandidates = useMemo(() => {
    const prioritised = documents.filter(
      (document) =>
        ['failed', 'quarantined', 'processing', 'pending'].includes(String(document.status)) || Boolean(document.error_message)
    )
    return (prioritised.length ? prioritised : documents).slice(0, 10)
  }, [documents])

  const heatmapData = useMemo(() => {
    const reasonMap = new Map<string, { count: number; formatLabel: string; timeLabel: string }>()

    auditCandidates.forEach((document) => {
      const reason = String(document.error_message || '敏感线索待确认').slice(0, 40)
      const formatLabel = String(document.file_type || 'unknown').toUpperCase()
      const updatedAt = new Date(String(document.updated_at || document.created_at || '')).getTime()
      const ageHours = Number.isFinite(updatedAt) ? (renderTimestamp - updatedAt) / 3_600_000 : 48
      const timeLabel = ageHours <= 6 ? '0-6h' : ageHours <= 24 ? '6-24h' : '24h+'
      const current = reasonMap.get(reason)
      reasonMap.set(reason, {
        count: (current?.count ?? 0) + 1,
        formatLabel,
        timeLabel,
      })
    })

    if (reasonMap.size === 0) {
      Object.entries(summary.top_error_reasons).forEach(([reason, count], index) => {
        reasonMap.set(reason.slice(0, 40), {
          count,
          formatLabel: fileTypeDistribution[index % Math.max(fileTypeDistribution.length, 1)]?.label || 'DOC',
          timeLabel: index % 2 === 0 ? '0-6h' : '6-24h',
        })
      })
    }

    const peak = Math.max(1, ...Array.from(reasonMap.values()).map((item) => item.count))
    return Array.from(reasonMap.entries())
      .map(([name, payload]) => {
        const intensity = payload.count / peak
        return {
          name,
          count: payload.count,
          formatLabel: payload.formatLabel,
          timeLabel: payload.timeLabel,
          fill: `linear-gradient(135deg, rgba(158,91,108,${0.18 + intensity * 0.35}), rgba(91,114,139,${0.36 + intensity * 0.25}))`,
        }
      })
      .sort((left, right) => right.count - left.count)
      .slice(0, 6)
  }, [auditCandidates, fileTypeDistribution, renderTimestamp, summary.top_error_reasons])

  const visibleAuditSamples = useMemo(
    () => auditCandidates.filter((document) => matchesReasonFilter(document, selectedReason)),
    [auditCandidates, selectedReason]
  )

  const selectedAuditDocuments = useMemo(
    () => documents.filter((document) => selectedAuditIds.includes(document.id)),
    [documents, selectedAuditIds]
  )

  const activeAuditDocument = useMemo(
    () => documents.find((document) => document.id === activeDetailId) || null,
    [activeDetailId, documents]
  )
  const activeAuditIsDemo = Boolean(activeAuditDocument?.id?.startsWith('demo-'))

  const remainingEstimate = useMemo(
    () => computeRemainingMinutesEstimate(pendingQueue, docsPerMinute),
    [docsPerMinute, pendingQueue]
  )

  const forecastPoints = useMemo(() => {
    if (!throughputRows.length) return []
    const last = throughputRows[throughputRows.length - 1]
    const base = last?.total ?? 0
    const rate = docsPerMinute ?? 0
    const stepMinutes = summary.bucket_minutes || 20
    return Array.from({ length: 3 }, (_, index) => ({
      ts: (last?.ts ?? renderTimestamp) + (index + 1) * stepMinutes * 60_000,
      total: Number((base + ((rate * stepMinutes) / 60) * (index + 1)).toFixed(1)),
    }))
  }, [docsPerMinute, renderTimestamp, summary.bucket_minutes, throughputRows])

  const predictionOption = useMemo<EChartsOption>(() => {
    const actualSeries = throughputRows.map((row) => [row.ts, row.total])
    const forecastSeries = actualSeries.length
      ? [[actualSeries[actualSeries.length - 1][0], actualSeries[actualSeries.length - 1][1]], ...forecastPoints.map((row) => [row.ts, row.total])]
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
          formatter: (value: number) => formatClockLabel(Number(value)),
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
          name: '当前处理效率',
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
    } as EChartsOption
  }, [forecastPoints, throughputRows])

  const ocrRadarValues = useMemo(() => {
    const pdfCount = documents.filter((document) => String(document.file_type || '').toLowerCase() === 'pdf').length
    const meanSizeMb = meanFileSize / (1024 * 1024)
    const formatVariety = Math.min(100, fileTypeDistribution.length * 18)
    const ocrComplexity = Math.min(100, pdfCount * 18 + meanSizeMb * 8)
    const formatRegularity = Math.max(12, 100 - formatVariety)
    const sensitiveDensity = Math.min(100, reviewQueue * 22 + manualCount * 12)
    return [ocrComplexity, formatRegularity, sensitiveDensity]
  }, [documents, fileTypeDistribution.length, manualCount, meanFileSize, reviewQueue])

  const radarOption = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: 'item' },
      radar: {
        radius: '62%',
        splitNumber: 4,
        axisName: { color: '#475569', fontSize: 11 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,0.22)' } },
        splitArea: { areaStyle: { color: ['rgba(248,250,252,0.82)', 'rgba(241,245,249,0.46)'] } },
        indicator: [
          { name: 'OCR 复杂度', max: 100 },
          { name: '格式规范度', max: 100 },
          { name: '敏感信息密度', max: 100 },
        ],
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: ocrRadarValues,
              areaStyle: { color: 'rgba(88,28,135,0.12)' },
              lineStyle: { color: '#6d28d9', width: 2 },
              itemStyle: { color: '#6d28d9' },
            },
          ],
        },
      ],
    } as EChartsOption),
    [ocrRadarValues]
  )

  const topologyPanels = useMemo(
    () => ({
      parser: {
        eyebrow: 'Parser',
        title: '解析段负载画像',
        summary: '优先处理 OCR 与混排 PDF，降低后续分块波动。',
        metrics: [
          ['OCR / Native / Mixed', pdfDisposition.map((item) => `${item.label} ${item.count}`).join(' · ')],
          ['风险线索', `${reviewQueue} 项待复核`],
          ['平均文件大小', formatFileSize(meanFileSize)],
        ],
      },
      chunker: {
        eyebrow: 'Chunker',
        title: '分块稳定性画像',
        summary: '文档格式越分散，越需要按策略分流而不是强行一刀切。',
        metrics: [
          ['格式分布', fileTypeDistribution.map((item) => `${item.label} ${item.count}`).join(' · ') || '无数据'],
          ['体积分布', fileSizeDistribution.map((item) => `${item.label} ${item.count}`).join(' · ')],
          ['P90 周期', `${durationPercentiles.p90 || 0} min`],
        ],
      },
      governance: {
        eyebrow: 'Governance',
        title: '治理优先级画像',
        summary: '只输出客观事实，所有主观判断回收到样本槽与风险清单。',
        metrics: [
          ['健康可入库', `${readyRate}%`],
          ['待人工处理', `${reviewQueue + manualCount} 项`],
          ['聚焦线索', selectedReason || '全部线索'],
        ],
      },
    }),
    [durationPercentiles.p90, fileSizeDistribution, fileTypeDistribution, manualCount, meanFileSize, pdfDisposition, readyRate, reviewQueue, selectedReason]
  )

  const salesAuditProfile = useMemo(
    () => (salesAuditSummary ? buildSalesAuditProfile(salesAuditSummary, salesAuditNearDup) : null),
    [salesAuditNearDup, salesAuditSummary]
  )

  const salesEvidenceItems = useMemo(() => {
    if (!salesAuditSamples) return []
    const representative = salesAuditSamples.representative ?? []
    const needsReview = Object.values(salesAuditSamples.needs_review ?? {}).flat()
    const topLargeFiles = salesAuditSamples.top_large_files ?? []
    const unique = new Map<string, DatasetPrecheckFileOut>()

    for (const file of [...needsReview, ...topLargeFiles, ...representative]) {
      unique.set(String(file.name), file)
    }

    return Array.from(unique.values()).slice(0, 12)
  }, [salesAuditSamples])

  const selectedSalesEvidence = useMemo(
    () => salesEvidenceItems.filter((file) => selectedAuditIds.includes(String(file.name))),
    [salesEvidenceItems, selectedAuditIds]
  )

  const salesHeatmapData = useMemo(() => {
    if (!salesAuditSummary?.findings?.length) return []
    const peak = Math.max(1, ...salesAuditSummary.findings.map((item) => Number(item.count || 0)))
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
          timeLabel: '报价风险',
          fill:
            item.severity === 'error'
              ? `linear-gradient(135deg, rgba(185,28,28,${0.16 + intensity * 0.32}), rgba(127,29,29,${0.24 + intensity * 0.28}))`
              : item.severity === 'warning'
                ? `linear-gradient(135deg, rgba(217,119,6,${0.16 + intensity * 0.32}), rgba(146,64,14,${0.24 + intensity * 0.28}))`
                : `linear-gradient(135deg, rgba(71,85,105,${0.16 + intensity * 0.32}), rgba(51,65,85,${0.24 + intensity * 0.28}))`,
        }
      })
  }, [salesAuditSummary])

  const salesCoreSummary = useMemo(
    () => {
      const totalFiles = Number(salesAuditSummary?.total_files || 0)
      const pdfScanned = Number(salesAuditSummary?.pdf_scan.scanned || 0)
      const pdfUnknown = Number(salesAuditSummary?.pdf_scan.unknown || 0)
      const scanRatio = totalFiles ? Math.round(((pdfScanned + pdfUnknown) / totalFiles) * 100) : 0

      return [
        ['文档总数', totalFiles.toLocaleString(), '全量摸底范围'],
        ['总体体量', formatFileSize(salesAuditSummary?.total_size_bytes || 0), '估算工时与算力'],
        ['阻断项', String(salesAuditProfile?.costDrivers.find((item) => item.key === 'blocking')?.count ?? 0), '需人工介入处理'],
        ['扫描 / 混排', `${scanRatio}%`, 'OCR 前置处理占比'],
      ]
    },
    [salesAuditProfile, salesAuditSummary]
  )

  const salesProcessingLanes = useMemo<SalesProcessingLane[]>(() => {
    if (!salesAuditSummary) return []
    const countByFinding = (key: string) => Number(salesAuditSummary.findings.find((item) => item.key === key)?.count || 0)
    return [
      { key: 'ocr', label: 'OCR 处理', count: countByFinding('pdf_scanned') + countByFinding('pdf_unknown'), tone: 'text-blue-600 bg-blue-500/8 border-blue-500/15' },
      { key: 'table', label: '格式转换', count: countByFinding('large_spreadsheet') + countByFinding('wide_spreadsheet') + countByFinding('merged_heavy_spreadsheet'), tone: 'text-orange-600 bg-orange-500/8 border-orange-500/15' },
      { key: 'manual', label: '人工审核', count: countByFinding('pii') + countByFinding('secrets') + countByFinding('parse_failed'), tone: 'text-rose-600 bg-rose-500/8 border-rose-500/15' },
      { key: 'straight', label: '去重处理', count: Math.max(0, Number(salesAuditSummary.total_files || 0) - (countByFinding('pdf_scanned') + countByFinding('pdf_unknown') + countByFinding('large_spreadsheet') + countByFinding('wide_spreadsheet') + countByFinding('merged_heavy_spreadsheet') + countByFinding('pii') + countByFinding('secrets') + countByFinding('parse_failed'))), tone: 'text-emerald-600 bg-emerald-500/8 border-emerald-500/15' },
    ]
  }, [salesAuditSummary])

  const salesPocCandidates = useMemo<SalesEvidenceTableRow[]>(() => {
    return salesEvidenceItems.slice(0, 5).map((file) => {
      const tags = buildEvidenceSlotTags(file)
      const firstTag = tags[0] || 'STRAIGHT_THROUGH'
      const primaryRisk =
        firstTag === 'OCR_REQUIRED'
          ? '扫描件'
          : firstTag === 'PARSE_FAILED'
            ? '解析失败'
            : firstTag === 'TABLE_HEAVY'
              ? '合并单元格'
              : firstTag === 'SENSITIVE_REVIEW'
                ? '敏感信息'
                : firstTag === 'VERSION_CONFLICT'
                  ? '版本冲突'
                  : '通用文档'
      const icon = firstTag === 'OCR_REQUIRED' ? CircleDashed : firstTag === 'TABLE_HEAVY' ? TableProperties : firstTag === 'PARSE_FAILED' ? CircleAlert : firstTag === 'SENSITIVE_REVIEW' ? ShieldAlert : FileDigit
      const iconTone = firstTag === 'OCR_REQUIRED' ? 'text-blue-500' : firstTag === 'TABLE_HEAVY' ? 'text-orange-500' : firstTag === 'PARSE_FAILED' ? 'text-rose-500' : firstTag === 'SENSITIVE_REVIEW' ? 'text-amber-500' : 'text-emerald-500'

      return {
        id: String(file.name),
        fileName: anonymizeEvidenceName(file.name),
        fileType: file.file_type.toUpperCase(),
        fileSizeLabel: formatFileSize(file.file_size || 0),
        primaryRisk,
        riskDescription: buildEvidenceSlotReason(file),
        actionLabel: firstTag === 'OCR_REQUIRED' ? 'OCR 处理' : firstTag === 'PARSE_FAILED' ? '人工审核' : firstTag === 'TABLE_HEAVY' ? '格式转换' : '纳入 POC',
        icon,
        iconTone,
      }
    })
  }, [salesEvidenceItems])

  const salesHighRiskFiles = useMemo<SalesEvidenceTableRow[]>(() => {
    const reviewBuckets = Object.values(salesAuditSamples?.needs_review ?? {}).flat()
    const source = (reviewBuckets.length ? reviewBuckets : salesEvidenceItems).slice(0, 5)
    return source.map((file) => {
      const tags = buildEvidenceSlotTags(file)
      const firstTag = tags[0] || 'STRAIGHT_THROUGH'
      const primaryRisk =
        firstTag === 'OCR_REQUIRED'
          ? '扫描件'
          : firstTag === 'PARSE_FAILED'
            ? '解析失败'
            : firstTag === 'TABLE_HEAVY'
              ? '合并单元格'
              : firstTag === 'SENSITIVE_REVIEW'
                ? '敏感信息'
                : firstTag === 'VERSION_CONFLICT'
                  ? '版本冲突'
                  : '通用文档'
      const icon = firstTag === 'OCR_REQUIRED' ? CircleDashed : firstTag === 'TABLE_HEAVY' ? TableProperties : firstTag === 'PARSE_FAILED' ? CircleAlert : firstTag === 'SENSITIVE_REVIEW' ? ShieldAlert : FileDigit
      const iconTone = firstTag === 'OCR_REQUIRED' ? 'text-blue-500' : firstTag === 'TABLE_HEAVY' ? 'text-orange-500' : firstTag === 'PARSE_FAILED' ? 'text-rose-500' : firstTag === 'SENSITIVE_REVIEW' ? 'text-amber-500' : 'text-emerald-500'

      return {
        id: String(file.name),
        fileName: anonymizeEvidenceName(file.name),
        fileType: file.file_type.toUpperCase(),
        fileSizeLabel: formatFileSize(file.file_size || 0),
        primaryRisk,
        riskDescription: buildEvidenceSlotReason(file),
        actionLabel: '查看',
        icon,
        iconTone,
      }
    })
  }, [salesAuditSamples?.needs_review, salesEvidenceItems])

  const visibleSalesEvidenceItems = useMemo(() => {
    if (!selectedReason) return salesEvidenceItems
    const matchedFinding = salesAuditSummary?.findings.find((item) => item.label === selectedReason)
    return salesEvidenceItems.filter((file) => {
      const tags = buildEvidenceSlotTags(file).join(' ')
      const reason = buildEvidenceSlotReason(file)
      const findings = (file.findings || []).map((item) => String(item || '').trim().toLowerCase())
      return (
        tags.includes(selectedReason) ||
        reason.includes(selectedReason) ||
        (matchedFinding ? findings.includes(matchedFinding.key) : false)
      )
    })
  }, [salesAuditSummary?.findings, salesEvidenceItems, selectedReason])

  const salesPdfSplitOption = useMemo<EChartsOption>(() => {
    const pdfDetection = salesAuditSummary?.pdf_detection as Record<string, unknown> | undefined
    const rows = [
      { name: 'TEXT', value: Number(pdfDetection?.text || salesAuditSummary?.pdf_scan.not_scanned || 0) },
      { name: 'MIXED', value: Number(pdfDetection?.mixed || 0) },
      { name: 'SCAN', value: Number(pdfDetection?.scan || salesAuditSummary?.pdf_scan.scanned || 0) },
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
              color: row.name === 'SCAN' ? '#f59e0b' : row.name === 'MIXED' ? '#94a3b8' : '#10b981',
            },
          })),
        },
      ],
    } as EChartsOption
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
              { name: 'P50', xAxis: histogram.findIndex((item) => p50 >= Number(item.min || 0) && p50 < Number(item.max || Number.POSITIVE_INFINITY)) },
              { name: 'P90', xAxis: histogram.findIndex((item) => p90 >= Number(item.min || 0) && p90 < Number(item.max || Number.POSITIVE_INFINITY)) },
            ].filter((item) => Number(item.xAxis) >= 0),
          },
        },
      ],
    } as EChartsOption
  }, [salesAuditSummary])

  const salesRadarOption = useMemo<EChartsOption>(() => {
    if (!salesAuditSummary) return { series: [] }
    const totalFiles = Math.max(1, Number(salesAuditSummary.total_files || 0))
    const ocrRatio = (Number(salesAuditSummary.pdf_scan.scanned || 0) + Number(salesAuditSummary.pdf_scan.unknown || 0)) / Math.max(
      1,
      Number(salesAuditSummary.pdf_scan.scanned || 0) + Number(salesAuditSummary.pdf_scan.not_scanned || 0) + Number(salesAuditSummary.pdf_scan.unknown || 0)
    )
    const tableHeavyRatio =
      (Number(salesAuditSummary.findings.find((item) => item.key === 'large_spreadsheet')?.count || 0) +
        Number(salesAuditSummary.findings.find((item) => item.key === 'wide_spreadsheet')?.count || 0) +
        Number(salesAuditSummary.findings.find((item) => item.key === 'merged_heavy_spreadsheet')?.count || 0)) /
      totalFiles
    const sensitiveRatio =
      (Number(salesAuditSummary.findings.find((item) => item.key === 'pii')?.count || 0) +
        Number(salesAuditSummary.findings.find((item) => item.key === 'secrets')?.count || 0)) /
      totalFiles
    const successRatio = 1 - Number(salesAuditSummary.findings.find((item) => item.key === 'parse_failed')?.count || 0) / totalFiles
    const imageHeavyProxy = Math.max(
      0,
      Math.min(1, Number(salesAuditSummary.pdf_scan.scanned || 0) / totalFiles + Number((salesAuditSummary.by_file_type as Record<string, number>).pptx || 0) / totalFiles)
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
        splitArea: { areaStyle: { color: ['rgba(248,250,252,0.82)', 'rgba(241,245,249,0.48)'] } },
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
    } as EChartsOption
  }, [salesAuditSummary])

  const handleToggleVelocity = useCallback(() => {
    setVelocityUnit((previous) => {
      const next = previous === 'docs' ? 'bytes' : 'docs'
      persistVelocityUnit(next)
      return next
    })
  }, [])

  const handleSampleDisposition = useCallback((documentId: string, disposition: SampleDisposition) => {
    setSampleDispositions((previous) => ({ ...previous, [documentId]: disposition }))
    if (disposition === 'approved') {
      setSuccessPulseVisible(true)
      toast.success('样本已标记为可入库')
      return
    }
    toast.success('样本已移入人工处理清单')
  }, [])

  const handleSelectAudit = useCallback((documentId: string) => {
    setSelectedAuditIds((previous) =>
      previous.includes(documentId) ? previous.filter((item) => item !== documentId) : [...previous, documentId]
    )
  }, [])

  const handleOpenAuditSnapshot = useCallback((documentId: string) => {
    setDesktopScopeCollapsed(false)
    setActiveDetailId(documentId)
  }, [])

  const handleChangeMode = useCallback(
    (nextMode: IngestionMode) => {
      const params = new URLSearchParams(searchParams.toString())
      if (nextMode === 'sales-audit') params.delete('mode')
      else params.set('mode', nextMode)
      const query = params.toString()
      router.replace(query ? `${pathname}?${query}` : pathname)
    },
    [pathname, router, searchParams]
  )

  const handleDownloadReport = useCallback(() => {
    const html = buildReportHtml({
      datasetLabel: selectedDatasetLabel,
      totalDocs: documents.length,
      readyRate,
      manualQueue: reviewQueue + manualCount,
      efficiency:
        velocityUnit === 'docs'
          ? `${docsPerMinute?.toFixed(1) ?? '--'} docs/min`
          : `${megabytesPerSecond?.toFixed(2) ?? '--'} MB/s`,
      latencyP90: `${durationPercentiles.p90 || 0} min`,
      selectedReason,
      documents: visibleAuditSamples.length ? visibleAuditSamples : documents,
    })

    const reportWindow = globalThis.window.open('', '_blank', 'noopener,noreferrer')
    if (reportWindow) {
      reportWindow.document.write(html)
      reportWindow.document.close()
      globalThis.window.setTimeout(() => {
        reportWindow.focus()
        reportWindow.print()
      }, 120)
      toast.success('已打开审计报告打印视图，可直接另存为 PDF')
      return
    }

    downloadTextFile('ingestion-audit-report.html', html, 'text/html;charset=utf-8')
  }, [
    docsPerMinute,
    documents,
    durationPercentiles.p90,
    manualCount,
    megabytesPerSecond,
    readyRate,
    reviewQueue,
    selectedDatasetLabel,
    selectedReason,
    velocityUnit,
    visibleAuditSamples,
  ])

  const handleExportSalesAuditReport = useCallback(async () => {
    if (demoMode || !selectedDatasetId || !latestPrecheckRun?.id) {
      handleDownloadReport()
      return
    }

    try {
      const blob = await datasetApi.exportPrecheckHtml(selectedDatasetId, latestPrecheckRun.id, { redact: true })
      downloadBlob(blob, `${selectedDatasetLabel}.precheck.html`)
      toast.success('已导出脱敏报告')
    } catch (error) {
      toast.error('导出脱敏报告失败，已回退到当前页面报告视图')
      handleDownloadReport()
    }
  }, [demoMode, handleDownloadReport, latestPrecheckRun?.id, selectedDatasetId, selectedDatasetLabel])

  useEffect(() => {
    const off = globalEventBus.on('ingestion:download-report', () => {
      if (mode === 'sales-audit') {
        void handleExportSalesAuditReport()
        return
      }
      handleDownloadReport()
    })
    return off
  }, [handleDownloadReport, handleExportSalesAuditReport, mode])

  const handleExportSelection = useCallback(() => {
    const payload = selectedAuditDocuments.map((document) => ({
      id: document.id,
      filename: document.filename,
      status: document.status,
      stage: document.current_stage,
      disposition: sampleDispositions[document.id] || 'pending',
      clue: document.error_message,
    }))

    downloadTextFile('audit-sample-selection.json', JSON.stringify(payload, null, 2), 'application/json;charset=utf-8')
    toast.success('已导出当前预检抽样清单')
  }, [sampleDispositions, selectedAuditDocuments])

  const handleBulkDisposition = useCallback(
    (disposition: SampleDisposition) => {
      selectedAuditIds.forEach((documentId) => {
        handleSampleDisposition(documentId, disposition)
      })
      setSelectedAuditIds([])
    },
    [handleSampleDisposition, selectedAuditIds]
  )

  const handleHeatmapSelect = useCallback((reason: string) => {
    setSelectedReason((previous) => (previous === reason ? null : reason))
    setDesktopScopeCollapsed(false)
  }, [])

  const handleToggleDemoMode = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())

    if (demoMode) {
      params.delete('demo')
    } else {
      params.set('demo', '1')
    }

    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname)
  }, [demoMode, pathname, router, searchParams])

  const handleCanvasMove = useCallback((event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - rect.left) / rect.width) * 100
    const y = ((event.clientY - rect.top) / rect.height) * 100
    setCanvasGlow({ x, y })
  }, [])

  const showEmptyState =
    mode === 'sales-audit'
      ? !demoMode && (!selectedDatasetId || (!precheckSummaryQuery.isLoading && !salesAuditSummary))
      : !documentsQuery.isLoading && documents.length === 0
  const showDesktopAuditRail = mode === 'execution-monitor' && !showEmptyState && !desktopScopeCollapsed
  const showDesktopAuditRailToggle = mode === 'execution-monitor' && !showEmptyState

  useEffect(() => {
    const offToggleDemo = globalEventBus.on('ingestion:toggle-demo-mode', () => {
      handleToggleDemoMode()
    })

    return offToggleDemo
  }, [handleToggleDemoMode])

  return (
      <div
        ref={scrollContainerRef}
        data-page-scroll-container="true"
        className="flex-1 h-full min-h-0 overflow-y-auto overscroll-contain no-scrollbar scroll-fade-bottom bg-[radial-gradient(circle_at_top,rgba(148,163,184,0.18),transparent_42%),linear-gradient(180deg,rgba(248,250,252,0.98),rgba(241,245,249,0.92))] text-foreground"
      >
      <DropZone
        ref={dropZoneRef}
        datasetId={selectedDatasetId}
        onUploadComplete={() => {
          void documentsQuery.refetch()
          void summaryQuery.refetch()
        }}
      />

      <div className={cn('flex w-full max-w-none gap-0 px-3 pt-3 md:px-5 lg:px-6 xl:px-7 2xl:px-8', mode === 'sales-audit' ? 'pb-2' : 'pb-8')}>
        <div className={cn('relative flex w-full gap-0', mode === 'sales-audit' ? 'min-h-0' : 'min-h-[calc(100dvh-2rem)]')}>
          <button
            type="button"
            aria-label={desktopScopeCollapsed ? '展开预检抽样侧栏' : '收起预检抽样侧栏'}
            onClick={() => setDesktopScopeCollapsed((previous) => !previous)}
            className={cn(
              'fixed left-0 top-[38dvh] z-40 hidden h-16 w-8 items-center justify-center rounded-r-full border border-border/60 bg-background/88 text-muted-foreground shadow-[0_20px_60px_-26px_rgba(15,23,42,0.28)] backdrop-blur-xl transition-colors hover:text-foreground',
              showDesktopAuditRailToggle ? 'lg:flex' : 'lg:hidden'
            )}
          >
            {desktopScopeCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>

          <aside
            className={cn(
              'hidden shrink-0 overflow-hidden pr-4 transition-all duration-300 ease-out lg:block',
              showDesktopAuditRail ? 'w-[19.5rem] opacity-100' : 'w-0 opacity-0 -translate-x-4 pointer-events-none'
            )}
          >
            <div className="sticky top-4 space-y-3">
              <div className="rounded-[1.35rem] border border-border/60 bg-background/86 p-3 shadow-[0_24px_70px_-34px_rgba(15,23,42,0.28)] backdrop-blur-xl">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      {mode === 'sales-audit' ? '证据槽' : '预检抽样'}
                    </div>
                    <div className="mt-0.5 text-[15px] font-semibold text-foreground">{mode === 'sales-audit' ? '报价证据' : '待确认线索'}</div>
                  </div>
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/60 bg-background/70 text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => setDesktopScopeCollapsed(true)}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                </div>

                <div className="mt-3 space-y-2.5">
                  <div className="rounded-[1.1rem] border border-border/60 bg-muted/20 p-2.5">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      Dataset Scope
                    </div>
                    <Select value={datasetScope} onValueChange={setDatasetScope}>
                      <SelectTrigger className="mt-2 h-10 rounded-xl border-border/60 bg-background/80">
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

                  <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
                    <button
                      type="button"
                      onClick={() => setSelectedReason(null)}
                      className={cn(
                        'rounded-full border px-2.5 py-1 transition-colors',
                        !selectedReason
                          ? 'border-foreground/15 bg-foreground/6 text-foreground'
                          : 'border-border/60 bg-background/70 hover:text-foreground'
                      )}
                    >
                      全部线索
                    </button>
                    {selectedReason ? (
                      <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2.5 py-1 text-amber-700">
                        {selectedReason}
                      </span>
                    ) : null}
                  </div>
                </div>

                <div className="mt-3 space-y-2.5">
                  {mode === 'sales-audit'
                    ? visibleSalesEvidenceItems.map((file) => {
                        const selectionKey = String(file.name)
                        const disposition = sampleDispositions[selectionKey]
                        const tags = buildEvidenceSlotTags(file)
                        const reason = buildEvidenceSlotReason(file)
                        return (
                          <motion.article
                            key={selectionKey}
                            className="relative overflow-hidden rounded-[1rem] border border-border/60 bg-background/82 p-2 shadow-[0_18px_40px_-30px_rgba(15,23,42,0.4)]"
                          >
                            <div className="relative z-10 rounded-[0.85rem] bg-background/92 p-2">
                              <div className="flex items-start gap-3">
                                <input
                                  checked={selectedAuditIds.includes(selectionKey)}
                                  onChange={() => handleSelectAudit(selectionKey)}
                                  className="mt-1 h-4 w-4 rounded border-border/60 text-foreground"
                                  type="checkbox"
                                  aria-label={`选择 ${selectionKey}`}
                                />
                                <div className="min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase text-foreground">
                                      {anonymizeEvidenceName(file.name)}
                                    </span>
                                    {tags.map((tag) => (
                                      <span
                                        key={tag}
                                        className={cn(
                                          'rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase',
                                          tag === 'OCR_REQUIRED'
                                            ? 'border-amber-500/25 bg-amber-500/10 text-amber-700'
                                            : tag === 'PARSE_FAILED'
                                              ? 'border-red-500/25 bg-red-500/10 text-red-700'
                                              : tag === 'SENSITIVE_REVIEW'
                                                ? 'border-rose-500/25 bg-rose-500/10 text-rose-700'
                                                : tag === 'TABLE_HEAVY'
                                                  ? 'border-slate-500/25 bg-slate-500/10 text-slate-700'
                                                  : 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700'
                                        )}
                                      >
                                        {tag}
                                      </span>
                                    ))}
                                    {disposition ? (
                                      <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                                        {disposition === 'approved' ? '已入 POC' : '已加阻断'}
                                      </span>
                                    ) : null}
                                  </div>
                                  <div className="mt-1 text-[13px] font-semibold text-foreground">{file.file_type.toUpperCase()}</div>
                                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                                    <span className="font-mono tabular-nums">{formatFileSize(file.file_size || 0)}</span>
                                    <span className="font-mono tabular-nums">{file.text_characters} chars</span>
                                  </div>
                                  <div className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground">{reason}</div>
                                </div>
                              </div>
                              <div className="mt-2.5 grid grid-cols-3 gap-1.5">
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-lg border-emerald-600/20 bg-emerald-600/8 px-2 text-[9px] text-emerald-700"
                                  onClick={() => handleSampleDisposition(selectionKey, 'approved')}
                                >
                                  纳入 POC
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-lg border-amber-600/20 bg-amber-600/8 px-2 text-[9px] text-amber-700"
                                  onClick={() => handleSampleDisposition(selectionKey, 'manual')}
                                >
                                  加入阻断
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-lg px-2 text-[9px]"
                                  onClick={() => setSelectedEvidenceFile(file)}
                                >
                                  查看审计依据
                                </Button>
                              </div>
                            </div>
                          </motion.article>
                        )
                      })
                    : visibleAuditSamples.map((document) => {
                        const kind = getDocumentKind(document.filename)
                        const disposition = sampleDispositions[document.id]
                        return (
                          <motion.article
                            key={document.id}
                            drag="x"
                            dragConstraints={{ left: 0, right: 0 }}
                            dragElastic={0.16}
                            onDragEnd={(_, info) => {
                              if (info.offset.x > 100) handleSampleDisposition(document.id, 'approved')
                              if (info.offset.x < -100) handleSampleDisposition(document.id, 'manual')
                            }}
                            className="relative overflow-hidden rounded-[1rem] border border-border/60 bg-background/82 p-2 shadow-[0_18px_40px_-30px_rgba(15,23,42,0.4)]"
                          >
                            <div className="absolute inset-y-0 left-0 flex w-16 items-center justify-center bg-emerald-600/10 text-emerald-700">
                              <Check className="h-4 w-4" />
                            </div>
                            <div className="absolute inset-y-0 right-0 flex w-16 items-center justify-center bg-amber-600/10 text-amber-700">
                              <CircleAlert className="h-4 w-4" />
                            </div>
                            <div className="relative z-10 rounded-[0.85rem] bg-background/92 p-2">
                              <div className="flex items-start gap-3">
                                <input
                                  checked={selectedAuditIds.includes(document.id)}
                                  onChange={() => handleSelectAudit(document.id)}
                                  className="mt-1 h-4 w-4 rounded border-border/60 text-foreground"
                                  type="checkbox"
                                  aria-label={`选择 ${document.filename}`}
                                />
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2">
                                    <span className={cn('rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase', getDocumentKindAccent(kind))}>
                                      {String(document.file_type || kind).toUpperCase()}
                                    </span>
                                    {disposition ? (
                                      <span
                                        className={cn(
                                          'rounded-full border px-2 py-0.5 text-[10px] font-semibold',
                                          disposition === 'approved'
                                            ? 'border-emerald-600/20 bg-emerald-600/10 text-emerald-700'
                                            : 'border-amber-600/25 bg-amber-600/10 text-amber-700'
                                        )}
                                      >
                                        {disposition === 'approved' ? '已确认' : '转人工'}
                                      </span>
                                    ) : null}
                                  </div>
                                  <div className="mt-1 truncate text-[13px] font-semibold text-foreground">{document.filename}</div>
                                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                                    <span className="font-mono tabular-nums">{formatFileSize(document.file_size || 0)}</span>
                                    <span>{formatDate(document.updated_at || document.created_at)}</span>
                                  </div>
                                  <div className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground">
                                    {document.error_message || '无明确异常文本，建议抽样核查内容密度与脱敏边界。'}
                                  </div>
                                </div>
                              </div>
                              <div className="mt-2.5 grid grid-cols-3 gap-1.5">
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-lg border-emerald-600/20 bg-emerald-600/8 px-2 text-[9px] text-emerald-700"
                                  onClick={() => handleSampleDisposition(document.id, 'approved')}
                                >
                                  确认可入库
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-lg border-amber-600/20 bg-amber-600/8 px-2 text-[9px] text-amber-700"
                                  onClick={() => handleSampleDisposition(document.id, 'manual')}
                                >
                                  需人工处理
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-8 rounded-lg px-2 text-[9px]"
                                  onClick={() => handleOpenAuditSnapshot(document.id)}
                                >
                                  打开审计快照
                                </Button>
                              </div>
                            </div>
                          </motion.article>
                        )
                      })}
                </div>
              </div>
            </div>
          </aside>

          <div className="min-w-0 flex-1">
            <div className="sticky top-3 z-30">
              <motion.div
                className="overflow-hidden rounded-[1.35rem] border border-border/60 bg-background/84 shadow-[0_20px_56px_-34px_rgba(15,23,42,0.2)] backdrop-blur-xl"
                animate={
                  reduceMotion
                    ? undefined
                    : {
                        paddingTop: headerCollapsed ? 9 : 13,
                        paddingBottom: headerCollapsed ? 9 : 13,
                      }
                }
                transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
              >
                <div className="px-2.5 md:px-3">
                  <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <div className="inline-flex items-center rounded-full border border-border/60 bg-background/72 p-0.5">
                          {([
                            ['sales-audit', '售前摸底'],
                            ['execution-monitor', '执行监控'],
                          ] as const).map(([value, label]) => (
                            <button
                              key={value}
                              type="button"
                              onClick={() => handleChangeMode(value)}
                              className={cn(
                                'rounded-full px-2.5 py-0.5 text-[8px] font-semibold transition-colors',
                                mode === value ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground'
                              )}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                        <span className="inline-flex items-center rounded-full border border-foreground/10 bg-foreground/[0.04] px-2 py-0.5 text-[7px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                          Sensitive Data Policy
                        </span>
                        {demoMode ? (
                          <span className="inline-flex items-center rounded-full border border-sky-600/20 bg-sky-600/10 px-2 py-0.5 text-[7px] font-semibold uppercase tracking-[0.16em] text-sky-700">
                            Demo Canvas
                          </span>
                        ) : null}
                      </div>
                      {!headerCollapsed ? (
                        <>
                          <h1 className="mt-1.5 text-[clamp(0.96rem,1.18vw,1.26rem)] font-black tracking-[-0.05em] text-foreground">
                            {mode === 'sales-audit' ? '售前报价证据台' : '执行监控工作台'}
                          </h1>
                          <p className="mt-1 max-w-[52rem] text-[9px] leading-[1.42] text-muted-foreground">
                            {mode === 'sales-audit'
                              ? '先回答怎么报价、是否需要先做付费 POC，再下钻到复杂度细节与证据样本。默认展示脱敏后的客观事实，不做主观评分。'
                              : '聚焦处理队列、吞吐、失败重试与运行态列表，供交付阶段持续观察执行状态。'}
                          </p>
                        </>
                      ) : null}
                    </div>

                    <div className="flex flex-wrap items-center gap-1">
                      <Button type="button" variant="outline" className="h-7 rounded-lg px-2 text-[9px]" onClick={handleToggleDemoMode}>
                        {demoMode ? '退出 Demo' : '打开 Demo'}
                      </Button>
                      {mode === 'sales-audit' ? (
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={() => {
                              if (selectedDatasetId) {
                                router.push(`/datasets/${selectedDatasetId}/precheck`)
                                return
                              }
                              toast.error('请先选择一个数据集')
                            }}
                          >
                            <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                            数据预检
                          </Button>
                          <Button type="button" className="h-7 rounded-lg px-2 text-[9px]" onClick={() => void handleExportSalesAuditReport()}>
                            <Download className="mr-1.5 h-3.5 w-3.5" />
                            脱敏报告导出
                          </Button>
                        </>
                      ) : (
                        <>
                          <LiveVelocity
                            unit={velocityUnit}
                            docsPerMinute={docsPerMinute}
                            megabytesPerSecond={megabytesPerSecond}
                            onToggle={handleToggleVelocity}
                          />
                          <Button
                            type="button"
                            variant="outline"
                            className="h-7 rounded-lg px-2 text-[9px]"
                            onClick={() => dropZoneRef.current?.triggerFilePicker()}
                          >
                            <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                            上传样本
                          </Button>
                          <Button type="button" className="h-7 rounded-lg px-2 text-[9px]" onClick={handleDownloadReport}>
                            <Download className="mr-1.5 h-3.5 w-3.5" />
                            /report
                          </Button>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="mt-2.5 overflow-hidden rounded-[0.9rem] border border-border/55 bg-border/35">
                    <div className="grid gap-px sm:grid-cols-4">
                      {(mode === 'sales-audit'
                        ? [
                            { label: '范围', value: selectedDatasetLabel, icon: FileSearch, tone: 'text-slate-400' },
                            { label: '建议报价模式', value: salesAuditProfile?.pricingMode || '待预检', icon: Workflow, tone: 'text-violet-400' },
                            { label: '建议 POC 样本量', value: salesAuditProfile ? `${salesAuditProfile.pocSampleCount} 份` : '待预检', icon: FileCheck2, tone: 'text-sky-400' },
                            { label: '复杂度', value: salesAuditProfile?.complexity || '待预检', icon: Radar, tone: 'text-amber-400' },
                          ]
                        : [
                            { label: '范围', value: selectedDatasetLabel, icon: FileSearch, tone: 'text-slate-400' },
                            { label: '健康可入库', value: `${readyRate}%`, icon: ShieldCheck, tone: 'text-emerald-400' },
                            { label: '待人工处理', value: `${reviewQueue + manualCount}`, icon: ShieldAlert, tone: 'text-amber-400' },
                            { label: '预测完成', value: remainingEstimate ? `${remainingEstimate} min` : '观测中', icon: Radar, tone: 'text-sky-400' },
                          ]
                      ).map(({ label, value, icon: Icon, tone }) => (
                        <div key={label} className="bg-background/76 px-2 py-1.5">
                          <div className="flex items-start justify-between gap-2">
                            <div className="text-[7px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                              {label}
                            </div>
                            <Icon className={cn('mt-[1px] h-3 w-3 shrink-0', tone)} />
                          </div>
                          <div className="mt-0.5 font-mono text-[10px] font-semibold tabular-nums leading-none text-foreground">{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </motion.div>
            </div>

            <AnimatePresence>
              {successPulseVisible ? (
                <motion.div
                  initial={{ opacity: 0, scaleX: 0.92 }}
                  animate={{ opacity: 1, scaleX: 1 }}
                  exit={{ opacity: 0 }}
                  className="pointer-events-none relative mt-3 overflow-hidden rounded-[1.1rem] border border-emerald-600/15 bg-emerald-600/8 px-3 py-2.5"
                >
                  <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(16,185,129,0.24),transparent_62%)]" />
                  <div className="relative flex items-center gap-2 text-[12px] text-emerald-700">
                    <ShieldCheck className="h-4 w-4" />
                    审计成功反馈：当前数据集已出现健康可入库样本，可继续批量确认。
                  </div>
                </motion.div>
              ) : null}
            </AnimatePresence>

            <div className={cn(mode === 'sales-audit' ? 'mt-5' : 'mt-3')}>
              {mode === 'sales-audit' ? (
                showEmptyState ? (
                  <EmptyState mode="truly-empty" />
                ) : (
                  <div
                    title="报价依据"
                    onMouseMove={handleCanvasMove}
                    className={cn(
                      'relative overflow-hidden rounded-[1.3rem] border border-border/60 bg-background/86 p-2.5 shadow-[0_24px_68px_-44px_rgba(15,23,42,0.24)] md:p-3',
                      'bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] [background-size:28px_28px]'
                    )}
                  >
                    <div
                      aria-hidden
                      className="pointer-events-none absolute inset-0 opacity-70"
                      style={{
                        background: `radial-gradient(circle at ${canvasGlow.x}% ${canvasGlow.y}%, rgba(255,255,255,0.48), transparent 28%)`,
                      }}
                    />
                    <div className="relative z-10 space-y-2">
                      <section className="rounded-[0.95rem] border border-border/60 bg-background/92 p-2 shadow-[0_16px_34px_-32px_rgba(15,23,42,0.18)]">
                        <div className="grid gap-1.5 xl:grid-cols-[184px_minmax(0,1fr)] xl:items-stretch">
                          <div className="rounded-[0.9rem] border border-border/55 bg-[linear-gradient(180deg,rgba(255,255,255,0.86),rgba(248,250,252,0.88))] px-2.5 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-[7px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">报价依据</div>
                              <FileDigit className="h-3 w-3 text-slate-400" />
                            </div>
                            <div className="mt-1 text-[11px] font-semibold tracking-[-0.03em] text-foreground">核心摘要</div>
                            <p className="mt-1 text-[9px] leading-3.5 text-muted-foreground">
                              默认输出脱敏后的客观事实，用于解释报价、POC 范围与人工阻断来源。
                            </p>
                            <div className="mt-1.5 inline-flex items-center rounded-full border border-border/60 bg-background/80 px-1.5 py-0.5 text-[8px] font-medium text-muted-foreground">
                              Evidence-first · De-identified
                            </div>
                          </div>

                          <div className="grid gap-1 sm:grid-cols-2 xl:grid-cols-4">
                            {salesCoreSummary.map(([label, value, note], index) => {
                              const Icon = index === 0 ? FileSearch : index === 1 ? Workflow : index === 2 ? CircleAlert : ShieldAlert
                              const iconTone = index === 0 ? 'text-slate-500' : index === 1 ? 'text-violet-500' : index === 2 ? 'text-rose-500' : 'text-amber-500'
                              return (
                                <div key={label} className="rounded-[0.8rem] border border-border/55 bg-background/82 px-1.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.58)]">
                                  <div className="flex items-center gap-1.5">
                                    <div className="flex h-4 w-4 items-center justify-center rounded-full bg-muted/30">
                                      <Icon className={cn('h-2.5 w-2.5', iconTone)} />
                                    </div>
                                    <div className="text-[8px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">{label}</div>
                                  </div>
                                  <div className="mt-1 font-mono text-[11px] font-semibold leading-none text-foreground">{value}</div>
                                  <div className={cn('mt-0.5 text-[7px] leading-3', index === 2 ? 'text-rose-500' : 'text-muted-foreground')}>
                                    {note}
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      </section>

                      <div className="grid gap-1.5 xl:grid-cols-[0.96fr_1.12fr_0.8fr]">
                        <section className="flex h-full flex-col rounded-[0.95rem] border border-border/60 bg-background/92 p-2">
                          <div className="text-[10px] font-semibold text-foreground">PDF 类型分布</div>
                          <div className="mt-1 h-[9rem]">
                            <EChart option={salesPdfSplitOption} />
                          </div>
                          <div className="mt-auto rounded-[0.75rem] border border-amber-400/15 bg-amber-400/6 px-2 py-1 text-[8px] leading-3.5 text-amber-700">
                            扫描型 PDF 需要先 OCR 处理，预计工期抬升较大。
                          </div>
                        </section>

                        <section className="rounded-[0.95rem] border border-border/60 bg-background/92 p-2">
                          <div className="text-[10px] font-semibold text-foreground">文档长度分布（按字符数）</div>
                          <div className="mt-1.5 grid gap-2 xl:grid-cols-[1fr_148px]">
                            <div className="h-[8rem]">
                              <EChart option={salesLengthOption} />
                            </div>
                            <div className="space-y-1 rounded-[0.8rem] border border-border/55 bg-background/80 px-2 py-1.5">
                              {[
                                ['P50（中位数）', salesAuditSummary?.length_percentiles.p50 || 0],
                                ['P90', salesAuditSummary?.length_percentiles.p90 || 0],
                                ['P99', salesAuditSummary?.length_percentiles.p99 || 0],
                                ['最大值', salesAuditSummary?.length_percentiles.p99 || 0],
                              ].map(([label, value]) => (
                                <div key={label} className="flex items-center justify-between gap-2 text-[8px]">
                                  <span className="text-muted-foreground">{label}</span>
                                  <span className="font-mono text-[9px] text-foreground">{value}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </section>

                        <section className="rounded-[0.95rem] border border-border/60 bg-background/92 p-2">
                          <div className="text-[10px] font-semibold text-foreground">复杂度细节</div>
                          <div className="mt-1.5 space-y-1">
                            {(salesAuditProfile?.costDrivers || []).map((driver) => (
                              <div key={driver.key} className="flex items-center justify-between gap-3 rounded-[0.8rem] border border-border/55 bg-background/80 px-2 py-1 text-[8px]">
                                <div className="flex items-center gap-2">
                                  <span
                                    className={cn(
                                      'h-2 w-2 rounded-full',
                                      driver.key === 'ocr'
                                        ? 'bg-blue-500'
                                        : driver.key === 'table_heavy'
                                          ? 'bg-amber-500'
                                          : driver.key === 'blocking'
                                            ? 'bg-rose-500'
                                            : 'bg-violet-500'
                                    )}
                                  />
                                  <span className="text-foreground">{driver.label}</span>
                                </div>
                                <span className="font-mono text-[9px] text-foreground">{driver.count}</span>
                              </div>
                            ))}
                          </div>
                          <div className="mt-1.5 h-[7.25rem] overflow-visible">
                            <EChart option={salesRadarOption} />
                          </div>
                        </section>
                      </div>

                      <div className="grid gap-1.5 xl:grid-cols-[1.1fr_0.9fr]">
                        <section className="rounded-[0.95rem] border border-border/60 bg-background/92 p-2">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-[10px] font-semibold text-foreground">风险热区（按风险类型）</div>
                            <button
                              type="button"
                              onClick={() => setSelectedReason(null)}
                              className="text-[8px] text-blue-500 transition-colors hover:text-blue-600"
                            >
                              查看全部 →
                            </button>
                          </div>
                          <div className="mt-1.5 grid gap-1.5 sm:grid-cols-5">
                            {salesHeatmapData.slice(0, 5).map((item) => (
                              <button
                                key={item.name}
                                type="button"
                                onClick={() => handleHeatmapSelect(item.name)}
                                className="rounded-[0.8rem] border border-border/55 bg-background/80 px-2 py-1.5 text-left"
                              >
                                <div className="text-[8px] text-muted-foreground">{item.name}</div>
                                <div className="mt-1 font-mono text-[12px] font-semibold text-foreground">{item.count.toLocaleString()}</div>
                                <div className="mt-0.5 text-[8px] text-muted-foreground">占比 {((item.count / Math.max(1, salesAuditSummary?.total_files || 1)) * 100).toFixed(1)}%</div>
                              </button>
                            ))}
                          </div>
                        </section>

                        <section className="rounded-[0.95rem] border border-border/60 bg-background/92 p-2">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-[10px] font-semibold text-foreground">处理清单（待处理文件数）</div>
                            <button
                              type="button"
                              onClick={() => setSelectedReason(null)}
                              className="text-[8px] text-blue-500 transition-colors hover:text-blue-600"
                            >
                              查看全部 →
                            </button>
                          </div>
                          <div className="mt-1.5 grid gap-1.5 sm:grid-cols-4">
                            {salesProcessingLanes.map((lane) => (
                              <div key={lane.key} className={cn('rounded-[0.8rem] border px-2 py-1.5', lane.tone)}>
                                <div className="text-[8px]">{lane.label}</div>
                                <div className="mt-1 text-center font-mono text-[14px] font-semibold">{lane.count.toLocaleString()}</div>
                              </div>
                            ))}
                          </div>
                        </section>
                      </div>

                      <div className="grid gap-1.5 xl:grid-cols-[1.05fr_0.95fr]">
                        <section className="rounded-[0.95rem] border border-border/60 bg-background/92 p-2">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-[10px] font-semibold text-foreground">建议 POC 样本（5 份）</div>
                              <div className="mt-0.5 text-[8px] text-muted-foreground">按复杂度维度覆盖主风险项</div>
                            </div>
                            <button type="button" className="text-[8px] text-blue-500 transition-colors hover:text-blue-600">
                              查看全部 →
                            </button>
                          </div>
                          <div className="mt-1.5 overflow-hidden rounded-[0.85rem] border border-border/55">
                            <table className="w-full text-left text-[8px]">
                              <thead className="bg-muted/25 text-muted-foreground">
                                <tr>
                                  <th className="px-2 py-1 font-medium">文件名</th>
                                  <th className="px-2 py-1 font-medium">类型</th>
                                  <th className="px-2 py-1 font-medium">大小</th>
                                  <th className="px-2 py-1 font-medium">主要风险</th>
                                  <th className="px-2 py-1 font-medium">建议处理</th>
                                </tr>
                              </thead>
                              <tbody>
                                {salesPocCandidates.map((row) => (
                                  <tr key={row.id} className="border-t border-border/50">
                                    <td className="px-2 py-1 font-mono text-foreground">{row.fileName}</td>
                                    <td className="px-2 py-1 text-muted-foreground">{row.fileType}</td>
                                    <td className="px-2 py-1 font-mono text-muted-foreground">{row.fileSizeLabel}</td>
                                    <td className="px-2 py-1 text-muted-foreground">{row.primaryRisk}</td>
                                    <td className="px-2 py-1">
                                      <span className="rounded-full border border-border/60 px-1.5 py-0.5 text-[7px] text-foreground">{row.actionLabel}</span>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </section>

                        <section className="rounded-[0.95rem] border border-border/60 bg-background/92 p-2">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-[10px] font-semibold text-foreground">高风险文件（示例）</div>
                              <div className="mt-0.5 text-[8px] text-muted-foreground">优先解释高报价的归因</div>
                            </div>
                            <button type="button" className="text-[8px] text-blue-500 transition-colors hover:text-blue-600">
                              查看全部 →
                            </button>
                          </div>
                          <div className="mt-1.5 overflow-hidden rounded-[0.85rem] border border-border/55">
                            <table className="w-full text-left text-[8px]">
                              <thead className="bg-muted/25 text-muted-foreground">
                                <tr>
                                  <th className="px-2 py-1 font-medium">文件名</th>
                                  <th className="px-2 py-1 font-medium">风险类型</th>
                                  <th className="px-2 py-1 font-medium">风险描述</th>
                                  <th className="px-2 py-1 font-medium">操作</th>
                                </tr>
                              </thead>
                              <tbody>
                                {salesHighRiskFiles.map((row) => (
                                  <tr key={row.id} className="border-t border-border/50">
                                    <td className="px-2 py-1 font-mono text-foreground">{row.fileName}</td>
                                    <td className="px-2 py-1 text-muted-foreground">{row.primaryRisk}</td>
                                    <td className="px-2 py-1 text-muted-foreground">{row.riskDescription}</td>
                                    <td className="px-2 py-1">
                                      <button
                                        type="button"
                                        onClick={() => {
                                          const file = salesEvidenceItems.find((item) => String(item.name) === row.id)
                                          if (file) setSelectedEvidenceFile(file)
                                        }}
                                        className="text-[7px] text-blue-500 transition-colors hover:text-blue-600"
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
                )
              ) : (
                <>
                  {documentsQuery.isLoading && !documents.length && !demoMode ? <LoadingWireframe /> : null}
                  {showEmptyState ? (
                    <EmptyState mode="truly-empty" />
                  ) : (
                    <div
                      title="项目数据盘点报告"
                      onMouseMove={handleCanvasMove}
                      className={cn(
                        'relative overflow-hidden rounded-[1.6rem] border border-border/60 bg-background/86 p-3.5 shadow-[0_32px_90px_-44px_rgba(15,23,42,0.35)] md:p-4',
                        demoMode &&
                          'bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] [background-size:28px_28px]'
                      )}
                    >
                      <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0 opacity-70"
                        style={{
                          background: `radial-gradient(circle at ${canvasGlow.x}% ${canvasGlow.y}%, rgba(255,255,255,0.48), transparent 28%)`,
                        }}
                      />
                      <div className="relative z-10 space-y-5">
                        <div className="grid gap-5 xl:grid-cols-[1.45fr_0.95fr]">
                          <section className="rounded-[1.6rem] border border-border/60 bg-background/88 p-3.5 md:p-4">
                            <div className="flex flex-col gap-4">
                              <div className="rounded-[1.45rem] border border-border/55 bg-[linear-gradient(180deg,rgba(255,255,255,0.72),rgba(248,250,252,0.92))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.6)]">
                                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                                  <div>
                                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">执行态势</div>
                                    <div className="mt-1.5 max-w-3xl text-xs leading-5 text-foreground/82">监控处理效率、吞吐、失败重试与运行态列表。</div>
                                  </div>
                                  <div className="rounded-[1.2rem] border border-border/60 bg-background/86 px-4 py-3">
                                    <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">处理通道指标</div>
                                    <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-foreground">{documents.length} files · {statusCounts.completed} ready · {reviewQueue} flagged</div>
                                  </div>
                                </div>
                              </div>
                              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                                <StatCard label="文件总量" value={documents.length} icon={FileSearch} color="text-slate-900" iconSurface="bg-slate-900/6" border="border border-border/55 bg-background/72 rounded-[1.3rem]" sparklineMode="real" sparklineValues={throughputRows.map((row) => row.total || 0)} delta={null} />
                                <StatCard label="健康可入库" value={`${readyRate}%`} icon={ShieldCheck} color="text-emerald-700" iconSurface="bg-emerald-600/10" border="border border-emerald-600/18 bg-emerald-600/[0.04] rounded-[1.3rem]" sparklineMode="real" sparklineValues={throughputRows.map((row) => row.completed || 0)} delta={null} pulse ringColor="bg-emerald-500" />
                                <StatCard label="待人工处理" value={reviewQueue + manualCount} icon={ShieldAlert} color="text-amber-700" iconSurface="bg-amber-600/10" border="border border-amber-600/18 bg-amber-600/[0.05] rounded-[1.3rem]" sparklineMode="real" sparklineValues={throughputRows.map((row) => row.failed + row.quarantined)} delta={null} />
                                <StatCard label="P90 周期" value={`${durationPercentiles.p90 || 0}m`} icon={Workflow} color="text-violet-700" iconSurface="bg-violet-600/10" border="border border-violet-600/18 bg-violet-600/[0.04] rounded-[1.3rem]" sparklineMode="real" sparklineValues={throughputRows.map((row) => row.total || 0)} delta={null} />
                              </div>
                              <div className="grid gap-3 xl:grid-cols-[1.25fr_0.75fr]">
                                <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                                  <div className="flex items-center justify-between gap-3">
                                    <div>
                                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">处理效率预测</div>
                                      <div className="mt-1 text-sm font-semibold text-foreground">末端虚线为预测区，帮助交付经理判断全量入库时间窗口</div>
                                    </div>
                                    <div className="text-right text-[11px] text-muted-foreground">
                                      <div>处理效率</div>
                                      <div className="font-mono text-sm font-semibold tabular-nums text-foreground">{velocityUnit === 'docs' ? `${docsPerMinute?.toFixed(1) ?? '--'} docs/min` : `${megabytesPerSecond?.toFixed(2) ?? '--'} MB/s`}</div>
                                    </div>
                                  </div>
                                  <div className="mt-3 h-[15rem]">
                                    <EChart option={predictionOption} />
                                  </div>
                                </div>
                                <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                                  <div className="flex items-center justify-between gap-3">
                                    <div>
                                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">OCR 成本预警雷达</div>
                                      <div className="mt-1 text-sm font-semibold text-foreground">快速判断这个项目到底好不好做</div>
                                    </div>
                                    <Radar className="h-4 w-4 text-violet-700" />
                                  </div>
                                  <div className="mt-3 h-[15rem]">
                                    <EChart option={radarOption} />
                                  </div>
                                </div>
                              </div>
                            </div>
                          </section>
                          <section className="space-y-4">
                            <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">风险重灾区热力图</div>
                                  <div className="mt-1 text-sm font-semibold text-foreground">颜色越深，代表格式与时间片上的异常越集中</div>
                                </div>
                                {selectedReason ? (
                                  <button type="button" onClick={() => setSelectedReason(null)} className="rounded-full border border-border/60 px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground">
                                    清除聚焦
                                  </button>
                                ) : null}
                              </div>
                              <div className="mt-4">
                                <ErrorTreemap data={heatmapData} selectedReason={selectedReason} onReasonSelect={handleHeatmapSelect} />
                              </div>
                            </div>
                            <div className="rounded-[1.2rem] border border-border/60 bg-background/82 p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">项目拓扑</div>
                                  <div className="mt-1 text-sm font-semibold text-foreground">点击 Parser / Chunker / Governance 节点切换查看参数画像</div>
                                </div>
                                <GripVertical className="h-4 w-4 text-muted-foreground" />
                              </div>
                              <div className="mt-4 rounded-[1.3rem] border border-border/55 bg-[linear-gradient(180deg,rgba(248,250,252,0.85),rgba(241,245,249,0.68))] p-4">
                                <div className="relative flex items-center justify-between gap-4">
                                  <div className="absolute left-[18%] right-[18%] top-1/2 h-px -translate-y-1/2 bg-[linear-gradient(90deg,rgba(148,163,184,0.18),rgba(51,65,85,0.32),rgba(148,163,184,0.18))]" />
                                  {([
                                    ['parser', 'Parser'],
                                    ['chunker', 'Chunker'],
                                    ['governance', 'Governance'],
                                  ] as const).map(([key, label]) => (
                                    <button key={key} type="button" onClick={() => setTopologyFocus(key)} className={cn('relative z-10 flex h-20 w-20 flex-col items-center justify-center rounded-full border text-[11px] font-semibold transition-all', topologyFocus === key ? 'border-foreground/15 bg-foreground text-background shadow-[0_18px_42px_-28px_rgba(15,23,42,0.7)]' : 'border-border/60 bg-background/86 text-foreground hover:border-foreground/15')}>
                                      {label}
                                    </button>
                                  ))}
                                </div>
                                <div className="mt-5 rounded-[1.15rem] border border-border/60 bg-background/86 p-4">
                                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{topologyPanels[topologyFocus].eyebrow}</div>
                                  <div className="mt-1 text-lg font-semibold text-foreground">{topologyPanels[topologyFocus].title}</div>
                                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{topologyPanels[topologyFocus].summary}</p>
                                  <div className="mt-4 grid gap-3">
                                    {topologyPanels[topologyFocus].metrics.map(([label, value]) => (
                                      <div key={label} className="flex items-start justify-between gap-4 rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                                        <span className="text-muted-foreground">{label}</span>
                                        <span className="max-w-[16rem] text-right font-mono tabular-nums text-foreground">{value}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </section>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {selectedEvidenceFile ? (
        <Sheet open={Boolean(selectedEvidenceFile)} onOpenChange={(open) => !open && setSelectedEvidenceFile(null)}>
          <SheetContent
            side="right"
            className="h-[100dvh] w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{anonymizeEvidenceName(selectedEvidenceFile.name)}</SheetTitle>
              <SheetDescription>{selectedEvidenceFile.file_type}</SheetDescription>
            </SheetHeader>
            <div className="flex h-full min-h-0 flex-col">
              <div className="border-b border-border/60 px-6 py-5">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">审计依据</div>
                <div className="mt-1 text-lg font-semibold text-foreground">{anonymizeEvidenceName(selectedEvidenceFile.name)}</div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-mono tabular-nums">{selectedEvidenceFile.file_type.toUpperCase()}</span>
                  <span className="font-mono tabular-nums">{formatFileSize(selectedEvidenceFile.file_size || 0)}</span>
                  <span className="font-mono tabular-nums">{selectedEvidenceFile.text_characters} chars</span>
                </div>
              </div>
              <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
                <div className="rounded-[1.3rem] border border-border/60 bg-muted/20 p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">处理标签</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {buildEvidenceSlotTags(selectedEvidenceFile).map((tag) => (
                      <span key={tag} className="rounded-full border border-border/60 bg-background/86 px-2.5 py-1 text-[11px] font-semibold text-foreground">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">为何复杂</div>
                  <div className="mt-2 text-sm leading-6 text-foreground">{buildEvidenceSlotReason(selectedEvidenceFile)}</div>
                </div>

                {selectedEvidenceFile.pdf_pages ? (
                  <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">PDF 类型分流依据</div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">总页数：{selectedEvidenceFile.pdf_pages.page_count}</div>
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">扫描页：{selectedEvidenceFile.pdf_pages.scanned_pages}</div>
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">文字页：{selectedEvidenceFile.pdf_pages.text_pages}</div>
                      <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">扫描占比：{Math.round(selectedEvidenceFile.pdf_pages.scan_ratio * 100)}%</div>
                    </div>
                  </div>
                ) : null}

                {selectedEvidenceFile.pii_samples?.length ? (
                  <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">敏感信息待审核列表</div>
                    <div className="mt-3 space-y-3">
                      {selectedEvidenceFile.pii_samples.slice(0, 3).map((item, index) => (
                        <div key={`${item.kind}-${index}`} className="rounded-[1rem] border border-border/55 bg-muted/20 p-3 text-sm">
                          <div className="font-mono text-xs text-muted-foreground">{item.kind}</div>
                          <div className="mt-1 font-mono text-foreground">{item.masked}</div>
                          <div className="mt-2 rounded-lg border border-border/50 bg-background/80 px-3 py-2 font-mono text-xs text-muted-foreground">
                            {item.context}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">本地复核</div>
                  <div className="mt-2 text-sm leading-6 text-muted-foreground">一键打开本地文件仅在本地审计模式可用；普通 Web 部署默认禁用。</div>
                  <Button className="mt-3 rounded-xl" disabled>
                    打开本地文件
                  </Button>
                </div>
              </div>
            </div>
          </SheetContent>
        </Sheet>
      ) : activeAuditIsDemo ? (
        <Sheet open={Boolean(activeAuditDocument)} onOpenChange={(open) => !open && setActiveDetailId(null)}>
          <SheetContent
            side="right"
            className="h-[100dvh] w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{activeAuditDocument?.filename || '审计快照'}</SheetTitle>
              <SheetDescription>{activeAuditDocument?.id || ''}</SheetDescription>
            </SheetHeader>
            {activeAuditDocument ? (
              <div className="flex h-full min-h-0 flex-col">
                <div className="border-b border-border/60 px-6 py-5">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    审计快照
                  </div>
                  <div className="mt-1 text-lg font-semibold text-foreground">{activeAuditDocument.filename}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono tabular-nums">{formatFileSize(activeAuditDocument.file_size || 0)}</span>
                    <span>{formatDate(activeAuditDocument.updated_at || activeAuditDocument.created_at)}</span>
                  </div>
                </div>
                <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
                  <div className="rounded-[1.4rem] border border-border/60 bg-muted/20 p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      Sensitive Data Policy
                    </div>
                    <div className="mt-2 text-sm leading-6 text-foreground/82">
                      默认仅展示脱敏后的聚合事实与待确认线索，不做主观评分。该快照用于演示侧边抽屉审计视图。
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      ['状态', String(activeAuditDocument.status || '-')],
                      ['阶段', String(activeAuditDocument.current_stage || '-')],
                      ['数据集', String(activeAuditDocument.dataset_id || '-')],
                      ['风险线索', activeAuditDocument.error_message || '无明确错误，建议抽样核查'],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-[1.2rem] border border-border/60 bg-background/80 p-4">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                          {label}
                        </div>
                        <div className="mt-2 text-sm font-medium text-foreground">{value}</div>
                      </div>
                    ))}
                  </div>
                  <div className="rounded-[1.4rem] border border-border/60 bg-background/82 p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      建议动作
                    </div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <Button className="rounded-xl" onClick={() => handleSampleDisposition(activeAuditDocument.id, 'approved')}>
                        确认可入库
                      </Button>
                      <Button variant="outline" className="rounded-xl" onClick={() => handleSampleDisposition(activeAuditDocument.id, 'manual')}>
                        需人工处理
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </SheetContent>
        </Sheet>
      ) : (
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
*/
