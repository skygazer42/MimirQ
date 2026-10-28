'use client'

import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import {
  Activity,
  ArrowLeft,
  BarChart3,
  Cloud,
  Database,
  Download,
  FileSearch,
  Loader2,
  RotateCcw,
  RefreshCw,
  Settings2,
  Sparkles,
  Table2,
} from '@/components/icons'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { OperationalWorkspace, WorkspaceMetrics, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { MoreHorizontal } from '@/components/icons'
import { Panel } from '@/components/ui/panel'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'

import { datasetApi, documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'
import { cn, formatFileSize, formatDate, detachPromise } from '@/lib/utils'
import { useRouter } from '@/i18n/navigation'

import type {
  Document,
  DatasetProfileFindingSummary,
  DatasetProfileScanRunCreateRequest,
  DatasetProfileScanRunOut,
} from '@/types'

const PIE_COLORS = [
  'hsl(var(--chart-1))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-6))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-7))',
  'hsl(var(--chart-5))',
  'hsl(var(--chart-8))',
]
const EMPTY_SCAN_RUNS: DatasetProfileScanRunOut[] = []
const PROFILE_DOCUMENT_PAGE_SIZE = 50
const PROFILE_BUCKET_PREVIEW_MAX_CHARS = 360
const profilePanelClass = ws.section
const profileChartProps = { className: 'h-[220px]', minHeight: 220 } as const
const profileEmptyChartClass = 'flex h-[220px] items-center justify-center text-sm text-muted-foreground'
const profileSectionTitleClass = ws.sectionTitle
const profileSectionCaptionClass = ws.sectionDescription

function ProfileCardHeader({
  title,
  caption,
  meta,
  action,
}: Readonly<{
  title: string
  caption?: string
  meta?: ReactNode
  action?: ReactNode
}>) {
  return (
    <div className="mb-2.5 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className={profileSectionTitleClass}>{title}</div>
        {caption ? <div className={profileSectionCaptionClass}>{caption}</div> : null}
      </div>
      {action || meta ? (
        <div className="shrink-0">
          {action || <div className="font-mono text-[10px] leading-none text-muted-foreground/55">{meta}</div>}
        </div>
      ) : null}
    </div>
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function readRecordNumber(value: unknown, key: string): number {
  if (!isRecord(value)) return 0
  const next = value[key]
  return typeof next === 'number' ? next : Number(next || 0) || 0
}

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function findingBadgeVariant(sev: string): 'secondary' | 'outline' | 'soft' | 'destructive' {
  const s = String(sev || '').toLowerCase()
  if (s === 'error') return 'destructive'
  if (s === 'warning') return 'soft'
  return 'outline'
}

function targetBadgeVariant(status: string): 'secondary' | 'outline' | 'soft' | 'destructive' {
  const s = String(status || '').toLowerCase()
  if (s === 'fail') return 'destructive'
  if (s === 'warn') return 'soft'
  if (s === 'pass') return 'outline'
  return 'secondary'
}

function formatChunkTargetLabel(value: unknown): string {
  return String(value || '')
    .replace('Chunk tokens', '切片 token')
    .replace('Coverage', '正文覆盖')
    .replace('Overlap waste', '重叠成本')
}

function asDocumentStatus(status: string | null | undefined): Document['status'] {
  switch (status) {
    case 'pending':
    case 'processing':
    case 'completed':
    case 'failed':
    case 'quarantined':
    case 'cancelled':
      return status
    default:
      return 'pending'
  }
}

function formatProfileRunStatus(status: string | null | undefined): string {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'pending') return '排队中'
  if (normalized === 'running') return '扫描中'
  if (normalized === 'completed') return '已完成'
  if (normalized === 'failed') return '失败'
  if (normalized === 'cancelled' || normalized === 'canceled') return '已取消'
  return '未扫描'
}

export default function DatasetProfilePage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId(params?.id)

  const [scanConfigOpen, setScanConfigOpen] = useState(false)
  const [isExportingJson, setIsExportingJson] = useState(false)
  const [isExportingHtml, setIsExportingHtml] = useState(false)

  const [scanConfig, setScanConfig] = useState<DatasetProfileScanRunCreateRequest>({
    backfill_pdf_quality: true,
    backfill_text_quality: true,
    backfill_chunk_stats: true,
    compute_file_hash: false,
    max_documents: null,
  })
  const [scanRun, setScanRun] = useState<DatasetProfileScanRunOut | null>(null)
  const [scanRunning, setScanRunning] = useState(false)
  const pollTimerRef = useRef<number | null>(null)
  const pollScanRunRef = useRef<(datasetIdValue: string, runId: string) => Promise<void>>(async () => {})
  const [compareA, setCompareA] = useState<string>('')
  const [compareB, setCompareB] = useState<string>('')

  const [findingOpen, setFindingOpen] = useState(false)
  const [selectedFinding, setSelectedFinding] = useState<DatasetProfileFindingSummary | null>(null)
  const [findingRetrying, setFindingRetrying] = useState(false)
  const [findingRetryingIds, setFindingRetryingIds] = useState<Record<string, boolean>>({})

  const [bucketOpen, setBucketOpen] = useState(false)
  const [bucketDim, setBucketDim] = useState<'file_type' | 'language' | 'directory' | 'quality_bucket' | null>(null)
  const [bucketKey, setBucketKey] = useState<string>('')

  const stopPolling = useCallback(() => {
    const t = pollTimerRef.current
    if (t) globalThis.window.clearTimeout(t)
    pollTimerRef.current = null
  }, [])

  const datasetQuery = useQuery({
    queryKey: datasetId ? queryKeys.datasets.detail(datasetId) : queryKeys.datasets.detail(''),
    enabled: Boolean(datasetId),
    queryFn: () => datasetApi.get(datasetId!),
  })
  const summaryQuery = useQuery({
    queryKey: datasetId ? queryKeys.datasets.profileSummary(datasetId) : queryKeys.datasets.profileSummary(''),
    enabled: Boolean(datasetId),
    queryFn: () => datasetApi.getProfileSummary(datasetId!),
  })
  const scanRunsQuery = useQuery({
    queryKey: datasetId
      ? queryKeys.datasets.profileScanRuns(datasetId, { skip: 0, limit: 20 })
      : queryKeys.datasets.profileScanRuns('', { skip: 0, limit: 20 }),
    enabled: Boolean(datasetId),
    queryFn: () => datasetApi.listProfileScanRuns(datasetId!, { skip: 0, limit: 20 }),
  })

  const dataset = datasetQuery.data ?? null
  const summary = summaryQuery.data ?? null
  const scanRuns = scanRunsQuery.data?.items ?? EMPTY_SCAN_RUNS
  const isLoading = datasetQuery.isLoading || summaryQuery.isLoading || scanRunsQuery.isLoading
  const selectedFindingKey = selectedFinding?.key || ''

  const findingDocumentsQuery = useInfiniteQuery({
    queryKey: queryKeys.datasets.profileFindingDocuments(datasetId || '', selectedFindingKey, {
      limit: PROFILE_DOCUMENT_PAGE_SIZE,
    }),
    enabled: Boolean(datasetId && selectedFindingKey && findingOpen),
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      if (!datasetId || !selectedFindingKey) throw new Error('缺少画像清单 ID')
      return datasetApi.listProfileFinding(datasetId, selectedFindingKey, {
        skip: Number(pageParam) || 0,
        limit: PROFILE_DOCUMENT_PAGE_SIZE,
      })
    },
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((acc, page) => acc + (page.items?.length || 0), 0)
      return loaded < (lastPage.total || 0) ? loaded : undefined
    },
  })
  const bucketDocumentsQuery = useInfiniteQuery({
    queryKey: queryKeys.datasets.profileBucketDocuments(datasetId || '', {
      dimension: bucketDim || '',
      bucket: bucketKey,
      include_preview: true,
      limit: PROFILE_DOCUMENT_PAGE_SIZE,
      preview_max_chars: PROFILE_BUCKET_PREVIEW_MAX_CHARS,
    }),
    enabled: Boolean(datasetId && bucketDim && bucketKey && bucketOpen),
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      if (!datasetId || !bucketDim || !bucketKey) throw new Error('缺少画像分桶 ID')
      return datasetApi.listProfileBucketDocuments(datasetId, {
        dimension: bucketDim,
        bucket: bucketKey,
        skip: Number(pageParam) || 0,
        limit: PROFILE_DOCUMENT_PAGE_SIZE,
        include_preview: true,
        preview_max_chars: PROFILE_BUCKET_PREVIEW_MAX_CHARS,
      })
    },
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((acc, page) => acc + (page.items?.length || 0), 0)
      return loaded < (lastPage.total || 0) ? loaded : undefined
    },
  })
  const findingLoading = findingDocumentsQuery.isFetching
  const findingRes = useMemo(() => {
    const pages = findingDocumentsQuery.data?.pages || []
    if (!pages.length) return null
    const items = pages.flatMap((page) => page.items || [])
    return {
      total: pages[pages.length - 1]?.total || 0,
      items,
    }
  }, [findingDocumentsQuery.data])
  const bucketLoading = bucketDocumentsQuery.isFetching
  const bucketRes = useMemo(() => {
    const pages = bucketDocumentsQuery.data?.pages || []
    if (!pages.length) return null
    const items = pages.flatMap((page) => page.items || [])
    return {
      total: pages[pages.length - 1]?.total || 0,
      items,
    }
  }, [bucketDocumentsQuery.data])
  const { fetchNextPage: fetchNextFindingPage, hasNextPage: hasNextFindingPage } = findingDocumentsQuery
  const { fetchNextPage: fetchNextBucketPage, hasNextPage: hasNextBucketPage } = bucketDocumentsQuery

  const refreshProfileOverview = useCallback(async () => {
    await Promise.all([
      datasetQuery.refetch(),
      summaryQuery.refetch(),
      scanRunsQuery.refetch(),
    ])
  }, [datasetQuery, summaryQuery, scanRunsQuery])

  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  useEffect(() => {
    const completed = scanRuns.filter((r) => String(r.status || '').toLowerCase() === 'completed')
    setCompareA((prev) => prev || completed[0]?.id || '')
    setCompareB((prev) => prev || completed[1]?.id || '')
  }, [scanRuns])

  useEffect(() => {
    const firstError = datasetQuery.error || summaryQuery.error
    if (!firstError) return
    reportClientError('Failed to load dataset profile', firstError)
  }, [datasetQuery.error, summaryQuery.error])

  useEffect(() => {
    const error = findingDocumentsQuery.error
    if (!error) return
    reportClientError('Failed to load finding documents', error)
    toast.error(formatApiError(error, '加载清单失败'))
  }, [findingDocumentsQuery.error, findingDocumentsQuery.errorUpdatedAt])

  useEffect(() => {
    const error = bucketDocumentsQuery.error
    if (!error) return
    reportClientError('Failed to load bucket documents', error)
    toast.error(formatApiError(error, '加载清单失败'))
  }, [bucketDocumentsQuery.error, bucketDocumentsQuery.errorUpdatedAt])

  const fileTypeChartData = useMemo(() => {
    const m = summary?.by_file_type || {}
    const entries = Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)

    const top = entries.slice(0, 10)
    const rest = entries.slice(10)
    const other = rest.reduce((acc, x) => acc + x.value, 0)
    if (other > 0) top.push({ name: '其他', value: other })
    return top.map((entry, idx) => ({ ...entry, fill: PIE_COLORS[idx % PIE_COLORS.length] }))
  }, [summary])

  const statusChartData = useMemo(() => {
    const m = summary?.by_status || {}
    return Object.entries(m).map(([name, value]) => ({ name, value: Number(value || 0) }))
  }, [summary])

  const lengthHistogramData = useMemo(() => {
    return (summary?.length_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const fileSizeHistogramData = useMemo(() => {
    return (summary?.file_size_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const pageCountHistogramData = useMemo(() => {
    return (summary?.page_number_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const parseQualityHistogramData = useMemo(() => {
    return (summary?.parse_quality_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const chunkCountHistogramData = useMemo(() => {
    return (summary?.chunk_count_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const avgChunkCharsHistogramData = useMemo(() => {
    return (summary?.avg_chunk_chars_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const chunkLengthHistogramData = useMemo(() => {
    return (summary?.chunk_length_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const languageMixChartData = useMemo(() => {
    const m = summary?.language_mix || {}
    const order = ['zh', 'en', 'mixed', 'unknown']
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name))
      .map((entry, idx) => ({ ...entry, fill: PIE_COLORS[idx % PIE_COLORS.length] }))
  }, [summary])

  const directoryChartData = useMemo(() => {
    const m = summary?.by_directory || {}
    const entries = Object.entries(m)
      .map(([key, value]) => ({ key: String(key || 'root'), name: String(key || 'root'), value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)

    const top = entries.slice(0, 12)
    const rest = entries.slice(12)
    const other = rest.reduce((acc, x) => acc + x.value, 0)
    if (other > 0) top.push({ key: '__other__', name: '其他', value: other })
    return top
  }, [summary])

  function qualityBucketLabel(key: string): string {
    switch (String(key || '').toLowerCase()) {
      case 'high_density':
        return '高密度'
      case 'mid_density':
        return '中密度'
      case 'low_density':
        return '低密度'
      case 'outline_heavy':
        return '目录/标题占比高'
      case 'tiny':
        return '内容过短'
      case 'unknown':
      default:
        return '未知'
    }
  }

  const qualityBucketChartData = useMemo(() => {
    const m = summary?.by_quality_bucket || {}
    const order = ['high_density', 'mid_density', 'low_density', 'outline_heavy', 'tiny', 'unknown']
    return Object.entries(m)
      .map(([key, value]) => ({
        key: String(key || 'unknown'),
        name: qualityBucketLabel(String(key || 'unknown')),
        value: Number(value || 0),
      }))
      .filter((x) => x.value > 0)
      .sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key))
  }, [summary])

  const pdfScanData = useMemo(() => {
    const s = summary?.pdf_scan
    if (!s) return []
    return [
      { name: 'scanned', value: Number(s.scanned || 0), fill: '#fb7185' },
      { name: 'text', value: Number(s.not_scanned || 0), fill: '#38bdf8' },
      { name: 'unknown', value: Number(s.unknown || 0), fill: '#94a3b8' },
    ]
  }, [summary])

  const piiChartData = useMemo(() => {
    const m = summary?.pii_hits_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [summary])

  const secretsChartData = useMemo(() => {
    const m = summary?.secrets_hits_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [summary])

  const parsingBackendChartData = useMemo(() => {
    const m = summary?.parsing_provenance?.by_resolved_backend || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [summary])

  const chunkTargets = useMemo(() => {
    return (summary?.chunk_targets || []).slice()
  }, [summary])

  const parseLowQualityFinding = useMemo(() => {
    return (summary?.findings || []).find((f) => f.key === 'parse_low_quality') || null
  }, [summary])

  const averageParseQuality = useMemo(() => {
    const bins = summary?.parse_quality_histogram || []
    let weighted = 0
    let total = 0
    for (const bin of bins) {
      const count = Number(bin.count || 0)
      if (count <= 0) continue
      const label = String(bin.label || '')
      const [rawLo, rawHi] = label.split('-', 2)
      const lo = Number.parseFloat(rawLo)
      const hi = Number.parseFloat(rawHi)
      const midpoint = Number.isFinite(lo) && Number.isFinite(hi) ? (lo + hi) / 2 : 0
      weighted += midpoint * count
      total += count
    }
    return total > 0 ? weighted / total : null
  }, [summary])

  const fallbackRate = useMemo(() => {
    const docsWithProvenance = Number(summary?.parsing_provenance?.docs_with_provenance || 0)
    const fallbackDocs = Number(summary?.parsing_provenance?.fallback_docs || 0)
    if (docsWithProvenance <= 0) return null
    return fallbackDocs / docsWithProvenance
  }, [summary])

  const openFinding = useCallback(
    (finding: DatasetProfileFindingSummary) => {
      if (!datasetId) return
      setSelectedFinding(finding)
      setFindingOpen(true)
    },
    [datasetId]
  )

  const openBucket = useCallback(
    (dim: 'file_type' | 'language' | 'directory' | 'quality_bucket', key: string) => {
      if (!datasetId) return
      if (!key || key === '__other__') return
      setBucketDim(dim)
      setBucketKey(key)
      setBucketOpen(true)
    },
    [datasetId]
  )

  const loadMoreFindingPage = useCallback(async () => {
    if (!hasNextFindingPage) return
    await fetchNextFindingPage()
  }, [fetchNextFindingPage, hasNextFindingPage])

  const retryDocuments = useCallback(
    async (docIds: string[], scope: 'batch' | 'single') => {
      if (!docIds.length) return
      if (scope === 'batch') setFindingRetrying(true)
      try {
        if (scope === 'single') {
          setFindingRetryingIds((prev) => ({ ...prev, [docIds[0]]: true }))
        }
        await documentApi.batchRetry({ document_ids: docIds, force: true, skip_if_unchanged: false })
        toast.success(`已触发重试：${docIds.length} 个文档`)
        detachPromise(refreshProfileOverview())
      } catch (e) {
        toast.error(formatApiError(e, '触发重试失败'))
      } finally {
        if (scope === 'batch') setFindingRetrying(false)
        if (scope === 'single') {
          setFindingRetryingIds((prev) => {
            const next = { ...prev }
            delete next[docIds[0]]
            return next
          })
        }
      }
    },
    [refreshProfileOverview]
  )

  const loadMoreBucketPage = useCallback(async () => {
    if (!hasNextBucketPage) return
    await fetchNextBucketPage()
  }, [fetchNextBucketPage, hasNextBucketPage])

  const pollScanRun = useCallback(
    async (datasetIdValue: string, runId: string) => {
      try {
        const next = await datasetApi.getProfileScanRun(datasetIdValue, runId)
        setScanRun(next)
        const st = String(next.status || '').toLowerCase()
        if (st === 'pending' || st === 'running') {
          pollTimerRef.current = globalThis.window.setTimeout(() => detachPromise(pollScanRunRef.current(datasetIdValue, runId)), 2000)
          return
        }
        setScanRunning(false)
        stopPolling()
        detachPromise(refreshProfileOverview())
      } catch (e) {
        reportClientError('Failed to poll dataset profile scan run', e)
        setScanRunning(false)
        stopPolling()
      }
    },
    [refreshProfileOverview, stopPolling]
  )

  useEffect(() => {
    pollScanRunRef.current = pollScanRun
  }, [pollScanRun])

  // If a scan run is already running (e.g., user refreshed the page), resume polling.
  useEffect(() => {
    if (!datasetId) return
    const run = summary?.latest_scan_run
    const st = String(run?.status || '').toLowerCase()
    if (!run?.id) return
    if (st !== 'pending' && st !== 'running') return
    if (pollTimerRef.current) return
    setScanRunning(true)
    pollTimerRef.current = globalThis.window.setTimeout(() => detachPromise(pollScanRun(datasetId, String(run.id))), 500)
  }, [datasetId, pollScanRun, summary?.latest_scan_run])

  const startDeepScan = useCallback(async () => {
    if (!datasetId) return
    setScanRunning(true)
    try {
      const run = await datasetApi.startProfileScan(datasetId, scanConfig)
      setScanRun(run)
      const st = String(run.status || '').toLowerCase()
      if (st === 'pending' || st === 'running') {
        pollTimerRef.current = globalThis.window.setTimeout(() => detachPromise(pollScanRun(datasetId, run.id)), 1200)
      } else {
        setScanRunning(false)
        detachPromise(refreshProfileOverview())
      }
      toast.success('已启动深度扫描')
    } catch (e) {
      reportClientError('Failed to start dataset profile scan', e)
      toast.error(formatApiError(e, '启动扫描失败'))
      setScanRunning(false)
    }
  }, [datasetId, scanConfig, pollScanRun, refreshProfileOverview])

  const exportJson = useCallback(async () => {
    if (!datasetId) return
    setIsExportingJson(true)
    try {
      const blob = await datasetApi.exportProfileSummary(datasetId)
      const safe = String(dataset?.name || 'dataset').replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.profile.json`)
      toast.success('已导出 JSON 报告')
    } catch (e) {
      reportClientError('Failed to export dataset profile JSON', e)
      toast.error(formatApiError(e, '导出失败'))
    } finally {
      setIsExportingJson(false)
    }
  }, [datasetId, dataset?.name])

  const exportHtml = useCallback(async () => {
    if (!datasetId) return
    setIsExportingHtml(true)
    try {
      const blob = await datasetApi.exportProfileHtml(datasetId, { redact: true })
      const safe = String(dataset?.name || 'dataset').replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.profile.html`)
      toast.success('已导出 HTML 报告')
    } catch (e) {
      reportClientError('Failed to export dataset profile HTML', e)
      toast.error(formatApiError(e, '导出失败'))
    } finally {
      setIsExportingHtml(false)
    }
  }, [datasetId, dataset?.name])

  const effectiveScanRun = useMemo(() => {
    const srStatus = String(scanRun?.status || '').toLowerCase()
    if (scanRun && (srStatus === 'pending' || srStatus === 'running')) {
      return { status: scanRun.status, progress: scanRun.progress ?? 0, error_message: scanRun.error_message }
    }
    if (summary?.latest_scan_run) {
      return {
        status: summary.latest_scan_run.status,
        progress: summary.latest_scan_run.progress ?? 0,
        error_message: summary.latest_scan_run.error_message,
      }
    }
    if (scanRun) return { status: scanRun.status, progress: scanRun.progress ?? 0, error_message: scanRun.error_message }
    return { status: undefined, progress: 0, error_message: undefined }
  }, [scanRun, summary?.latest_scan_run])

  const latestRunStatus = effectiveScanRun.status
  const latestRunProgress = effectiveScanRun.progress
  const totalSizeLabel = summary ? formatFileSize(summary.total_size_bytes || 0) : (isLoading ? '…' : '-')
  const scannedPdfCount = summary
    ? `${summary.pdf_scan.scanned}/${summary.pdf_scan.scanned + summary.pdf_scan.not_scanned + summary.pdf_scan.unknown}`
    : (isLoading ? '…' : '-')
  const totalFindingCount = (summary?.findings || []).reduce((acc, finding) => acc + Number(finding.count || 0), 0)
  const generatedAtLabel = summary?.generated_at ? formatDate(summary.generated_at) : '--'
  const latestRunLabel = formatProfileRunStatus(latestRunStatus)
  const activeFindings = useMemo(
    () => (summary?.findings || []).filter((finding) => Number(finding.count || 0) > 0),
    [summary?.findings]
  )
  const clearFindings = useMemo(
    () => (summary?.findings || []).filter((finding) => Number(finding.count || 0) <= 0),
    [summary?.findings]
  )

  const completedRuns = useMemo(
    () => (scanRuns || []).filter((r) => String(r.status || '').toLowerCase() === 'completed'),
    [scanRuns]
  )

  const compareDelta = useMemo(() => {
    const a = completedRuns.find((r) => r.id === compareA)
    const b = completedRuns.find((r) => r.id === compareB)
    const sa = a?.summary || {}
    const sb = b?.summary || {}
    if (!a || !b || !sa || !sb) return null
    const docsA = Number(sa.total_documents || 0)
    const docsB = Number(sb.total_documents || 0)
    const bytesA = Number(sa.total_size_bytes || 0)
    const bytesB = Number(sb.total_size_bytes || 0)
    const p90A = readRecordNumber(sa.length_percentiles, 'p90')
    const p90B = readRecordNumber(sb.length_percentiles, 'p90')
    const scannedA = readRecordNumber(sa.pdf_scan, 'scanned')
    const scannedB = readRecordNumber(sb.pdf_scan, 'scanned')
    const piiA = Object.values(sa.pii_hits_total || {}).reduce((acc: number, v: unknown) => acc + Number(v || 0), 0)
    const piiB = Object.values(sb.pii_hits_total || {}).reduce((acc: number, v: unknown) => acc + Number(v || 0), 0)
    const secA = Object.values(sa.secrets_hits_total || {}).reduce((acc: number, v: unknown) => acc + Number(v || 0), 0)
    const secB = Object.values(sb.secrets_hits_total || {}).reduce((acc: number, v: unknown) => acc + Number(v || 0), 0)
    return {
      a,
      b,
      docs: docsB - docsA,
      bytes: bytesB - bytesA,
      p90: p90B - p90A,
      scanned: scannedB - scannedA,
      pii: piiB - piiA,
      secrets: secB - secA,
    }
  }, [compareA, compareB, completedRuns])

  return <AppFrame><OperationalWorkspace title="数据画像" icon="profile-discovery" context={dataset?.name ?? (datasetQuery.isPending ? '正在读取数据集…' : '数据集未取得')} back={() => router.push('/datasets')} actions={<>
    <Button disabled={scanRunning} onClick={() => setScanConfigOpen(true)}><Sparkles />{scanRunning ? '正在扫描…' : '深度扫描'}</Button>
    <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" aria-label="导出画像" disabled={!summary || isExportingJson || isExportingHtml}><Download />导出</Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => { void exportJson() }}>JSON 报告</DropdownMenuItem><DropdownMenuItem onSelect={() => { void exportHtml() }}>HTML 报告</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
    <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="数据集操作"><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/health`)}>健康概览</DropdownMenuItem><DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/precheck`)}>文档预检</DropdownMenuItem><DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/ingestion`)}>入库策略</DropdownMenuItem><DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/tables`)}>表格资产</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
  </>}>
    {datasetQuery.isError || summaryQuery.isError ? <WorkspaceNotice retry={() => { void datasetQuery.refetch(); void summaryQuery.refetch() }} retryLabel="重新读取画像" pending={datasetQuery.isFetching || summaryQuery.isFetching}>{formatApiError(datasetQuery.error || summaryQuery.error, '画像读取失败')}</WorkspaceNotice> : null}
    {!summary ? <div className={ws.empty} role="status">{summaryQuery.isPending ? '正在读取数据画像…' : '当前画像暂不可用。'}</div> : <Tabs defaultValue="overview"><TabsList className={ws.tabList} aria-label="数据画像视图"><TabsTrigger value="overview">问题与概览</TabsTrigger><TabsTrigger value="distribution">分布分析</TabsTrigger><TabsTrigger value="history">扫描历史</TabsTrigger></TabsList>
      <TabsContent value="overview" className={ws.tabContent}><WorkspaceMetrics items={[{ label: '文档总数', value: summary.total_documents },{ label: '总大小', value: totalSizeLabel },{ label: '正文长度中位数', value: summary.length_percentiles.p50, detail: '字符' },{ label: '正文长度 P90', value: summary.length_percentiles.p90, detail: '字符' },{ label: '扫描版 PDF', value: scannedPdfCount }]} />
        <section className={ws.section}><div className={ws.sectionHeading}><h2 className={ws.sectionTitle}>问题清单</h2><span className={ws.muted}>{activeFindings.length} 类问题</span></div>{activeFindings.length ? <div className={ws.tableScroll}><table className={ws.table} aria-label="画像问题清单"><thead><tr><th>问题与说明</th><th>级别</th><th>命中文件</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{activeFindings.map(finding => <tr key={finding.key}><td><strong className="font-medium">{finding.label}</strong>{finding.description ? <p>{finding.description}</p> : null}</td><td><span className={finding.severity === 'error' ? 'text-destructive' : finding.severity === 'warning' ? ws.warning : ws.muted}>{finding.severity === 'error' ? '错误' : finding.severity === 'warning' ? '注意' : '提示'}</span></td><td className="tabular-nums">{finding.count}</td><td className="text-right"><Button variant="ghost" aria-label={`查看${finding.label}文件`} onClick={() => openFinding(finding)}>查看文件</Button></td></tr>)}</tbody></table></div> : <p className={ws.muted}>当前报告没有命中的问题条目。</p>}{clearFindings.length ? <details className="mt-4 text-sm"><summary className="cursor-pointer text-muted-foreground">已检查但未命中 · {clearFindings.length} 项</summary><div className="mt-3 flex flex-wrap gap-3">{clearFindings.map(finding => <span key={finding.key}>{finding.label}</span>)}</div></details> : null}</section>
        <section className={ws.section}><h2 className={ws.sectionTitle}>最近扫描</h2><div className="mt-3 flex flex-wrap items-center gap-4 text-sm"><span>{latestRunLabel}</span><span className="text-muted-foreground">画像更新于 {generatedAtLabel}</span>{scanRunning ? <span>{latestRunProgress}%</span> : null}</div>{effectiveScanRun.error_message ? <p className="mt-3 text-sm text-destructive">{effectiveScanRun.error_message}</p> : null}</section>
      </TabsContent>
      <TabsContent value="distribution" className={ws.tabContent}><Tabs defaultValue="documents"><TabsList className={ws.tabList} aria-label="分布分析分类"><TabsTrigger value="documents">文档分布</TabsTrigger><TabsTrigger value="chunks">切片质量</TabsTrigger><TabsTrigger value="risk">解析与风险</TabsTrigger></TabsList><TabsContent value="documents" className={ws.tabContent}><div className={ws.charts}><Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader
                title="格式分布"
                caption="文件类型占比"
                meta={summary?.generated_at ? formatDate(summary.generated_at) : ''}
              />
              <SafeResponsiveChart {...profileChartProps}>
                  <PieChart>
                    <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                    <Pie
                      data={fileTypeChartData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={42}
                      outerRadius={72}
                      paddingAngle={2}
                    />
                  </PieChart>
                </SafeResponsiveChart>
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="状态分布" caption="按文档处理状态聚合" />
              <SafeResponsiveChart {...profileChartProps}>
                  <BarChart data={statusChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                    <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </SafeResponsiveChart>
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="长度分布" caption="按字符长度区间统计" />
              <SafeResponsiveChart {...profileChartProps}>
                  <BarChart data={lengthHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                    <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </SafeResponsiveChart>
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="PDF 扫描占比" caption="扫描件、文本型与未知类型" />
              <SafeResponsiveChart {...profileChartProps}>
                  <PieChart>
                    <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                    <Pie isAnimationActive={false} data={pdfScanData} dataKey="value" nameKey="name" innerRadius={42} outerRadius={72} paddingAngle={2} />
                  </PieChart>
                </SafeResponsiveChart>
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="文件大小分布" caption="用于发现异常大文件或碎片文件" />
              <SafeResponsiveChart {...profileChartProps}>
                  <BarChart data={fileSizeHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                    <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-3))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </SafeResponsiveChart>
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="页数分布" caption="PDF / Office 页数画像" />
              {pageCountHistogramData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={pageCountHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-7))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="语言分布" caption="中文、英文、混合和未知语言占比" />
              {languageMixChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <PieChart>
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Pie
                        data={languageMixChartData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={42}
                        outerRadius={72}
                        paddingAngle={2}
                      />
                    </PieChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="目录分布" caption="点击柱子查看对应文件" />
              {directoryChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={directoryChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} interval={0} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar
                        dataKey="value"
                        fill="hsl(var(--chart-5))"
                        radius={[6, 6, 0, 0]}
                        cursor="pointer"
                        onClick={(entry) => {
                          const key = String(entry?.key || 'root')
                          if (key !== '__other__') detachPromise(openBucket('directory', key))
                        }}
                      />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel></div></TabsContent><TabsContent value="chunks" className={ws.tabContent}><div className={ws.charts}><Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="切片数量分布" caption="每个文档生成的切片数量" />
              {chunkCountHistogramData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={chunkCountHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-4))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="平均切片长度" caption="按文档聚合的平均切片长度" />
              {avgChunkCharsHistogramData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={avgChunkCharsHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="切片长度分布" caption="按切片粒度统计字符长度" />
              {chunkLengthHistogramData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={chunkLengthHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-6))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>
<Panel variant="seamless" className={cn(profilePanelClass, 'lg:col-span-2')}>
              <div className="mb-3 flex items-start justify-between gap-4">
                <div>
                  <div className={profileSectionTitleClass}>切块目标检查</div>
                  <div className={profileSectionCaptionClass}>
                    检查 token 分布、正文覆盖和重叠成本；缺统计只提示补采集，不代表入库失败。
                  </div>
                </div>
                <Badge variant="outline" className="shrink-0 border-border bg-card/70 px-2 py-0.5 text-xs font-mono text-muted-foreground">
                  可选门禁
                </Badge>
              </div>

              {chunkTargets.length ? (
                <div className="grid gap-2 md:grid-cols-3">
                  {chunkTargets.map((t, idx) => (
                    <div
                      key={String(t.key || t.label || idx)}
                      className={cn(
                        'relative overflow-hidden rounded-xl border bg-card/60 px-2.5 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] dark:bg-muted/20',
                        String(t.status || '').toLowerCase() === 'fail'
                          ? 'border-destructive/30'
                          : String(t.status || '').toLowerCase() === 'warn'
                            ? 'border-warning/30'
                            : 'border-border/60 dark:border-border/60',
                      )}
                    >
                      <div
                        className={cn(
                          'absolute inset-y-2 left-0 w-1 rounded-r-full',
                          String(t.status || '').toLowerCase() === 'fail'
                            ? 'bg-destructive'
                            : String(t.status || '').toLowerCase() === 'warn'
                              ? 'bg-warning'
                              : 'bg-info/30',
                        )}
                      />
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-1.5 pl-2">
                          <div className="truncate text-[12px] font-semibold text-foreground/85">{formatChunkTargetLabel(t.label || t.key)}</div>
                          <Badge variant={targetBadgeVariant((t.status))} className="h-5 shrink-0 px-1.5 text-xs font-mono uppercase">
                            {String(t.status || '')}
                          </Badge>
                        </div>
                        {t.message ? (
                          <div className="mt-1 line-clamp-2 pl-2 text-xs leading-4 text-muted-foreground text-pretty">
                            {String(t.message)}
                          </div>
                        ) : null}
                      </div>

                      {t.suggestions.length ? (
                        <div className="mt-2 rounded-lg bg-muted/40 px-2.5 py-1.5 text-xs leading-4 text-muted-foreground/70 dark:bg-muted/30">
                          {String(t.suggestions[0])}
                          {t.suggestions.length > 1 ? (
                            <span className="ml-1 text-muted-foreground/45">+{t.suggestions.length - 1}</span>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-8 text-center text-xs text-muted-foreground">
                  暂无数据（可运行深度扫描补齐 chunk token/coverage 等指标）
                </div>
              )}
            </Panel></div></TabsContent><TabsContent value="risk" className={ws.tabContent}><div className={ws.charts}><Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader
                title="解析质量分布"
                caption="解析文本质量评分区间"
                action={parseLowQualityFinding ? (
                  <Button
                    variant="outline"
                    className="h-8 px-2 gap-1 text-xs"
                    onClick={() => detachPromise(openFinding(parseLowQualityFinding))}
                  >
                    <FileSearch className="w-3.5 h-3.5" />
                    低质量
                  </Button>
                ) : null}
              />
              {parseQualityHistogramData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={parseQualityHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="解析路由" caption="解析后端、耗时和后备路径概览" />

              {parsingBackendChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={parsingBackendChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}

              <div className="mt-2 grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-xs text-muted-foreground">覆盖文档</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.docs_with_provenance || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-xs text-muted-foreground">后备解析</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.fallback_docs || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-xs text-muted-foreground">P50 耗时 ms</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.elapsed_ms_percentiles?.p50 || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-xs text-muted-foreground">P90 耗时 ms</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.elapsed_ms_percentiles?.p90 || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-xs text-muted-foreground">平均解析分</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {averageParseQuality == null ? '-' : averageParseQuality.toFixed(3)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-xs text-muted-foreground">后备率</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {fallbackRate == null ? '-' : `${(fallbackRate * 100).toFixed(1)}%`}
                  </div>
                </div>
              </div>
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="质量桶分布" caption="点击柱子查看对应文件" />
              {qualityBucketChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={qualityBucketChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} interval={0} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar
                        dataKey="value"
                        fill="hsl(var(--chart-2))"
                        radius={[6, 6, 0, 0]}
                        cursor="pointer"
                        onClick={(entry) => detachPromise(openBucket('quality_bucket', String(entry?.key || 'unknown')))}
                      />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="PII 命中" caption="手机号、邮箱、身份证等敏感信息次数" />
              {piiChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={piiChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-4))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>
<Panel variant="seamless" className={profilePanelClass}>
              <ProfileCardHeader title="密钥 / Token 命中" caption="疑似密钥、Token 和凭证命中次数" />
              {secretsChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={secretsChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--popover))', color: 'hsl(var(--popover-foreground))', borderColor: 'hsl(var(--border))' }} itemStyle={{ color: 'hsl(var(--popover-foreground))' }} />
                      <Bar isAnimationActive={false} dataKey="value" fill="hsl(var(--chart-6))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel></div></TabsContent></Tabs></TabsContent>
      <TabsContent value="history" className={ws.tabContent}><div className={ws.sectionHeading}><h2 className={ws.sectionTitle}>扫描历史</h2><Button variant="ghost" disabled={scanRunsQuery.isFetching} onClick={() => { void scanRunsQuery.refetch() }}>重新读取扫描历史</Button></div>{scanRunsQuery.isError ? <WorkspaceNotice retry={() => { void scanRunsQuery.refetch() }} pending={scanRunsQuery.isFetching}>{formatApiError(scanRunsQuery.error, '扫描历史读取失败')}</WorkspaceNotice> :           <div id="prof-history">
          <Panel variant="seamless" className={cn(profilePanelClass, 'p-3')}>
            <div className="mb-3">
              <div>
                <div className={profileSectionTitleClass}>扫描历史 / 对比</div>
                <div className={profileSectionCaptionClass}>
                  保存深度扫描 summary 快照，用于回溯指标变化。
                </div>
              </div>
            </div>

            {scanRuns.length ? (
              <div className="rounded-xl border border-border/60 overflow-hidden">
                <table aria-label="数据集画像扫描运行记录" className="w-full text-left text-xs">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>
                      <th className="px-2 py-1.5 font-medium">时间</th>
                      <th className="px-2 py-1.5 font-medium">状态</th>
                      <th className="px-2 py-1.5 font-medium">进度</th>
                      <th className="px-2 py-1.5 font-medium">配置</th>
                      <th className="px-2 py-1.5 font-medium">错误</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scanRuns.map((r) => (
                      <tr key={r.id} className="border-t border-border/60">
                        <td className="px-2 py-1.5 font-mono text-xs">{r.created_at ? formatDate(r.created_at) : '-'}</td>
                        <td className="px-2 py-1.5">
                          <Badge variant="outline" className="font-mono text-xs">
                            {String(r.status || '')}
                          </Badge>
                        </td>
                        <td className="px-2 py-1.5 font-mono text-xs">{typeof r.progress === 'number' ? `${r.progress}%` : '-'}</td>
                        <td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">
                          PDF:{r.config?.backfill_pdf_quality === false ? '0' : '1'} · 文本:{r.config?.backfill_text_quality === false ? '0' : '1'} · 切片:{r.config?.backfill_chunk_stats === false ? '0' : '1'} · 哈希:{r.config?.compute_file_hash ? '1' : '0'}
                        </td>
                        <td className="px-2 py-1.5 text-xs text-destructive">{r.error_message || ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="rounded-xl border border-border/45 bg-muted/40 px-2 py-1.5 text-xs text-muted-foreground dark:bg-muted/20">
                暂无扫描记录。启动一次深度扫描后，这里会显示快照和可对比版本。
              </div>
            )}

            <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_280px]">
              <div className={ws.section}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-[13px] font-semibold text-foreground/85">快照对比</div>
                  <Badge variant="outline" className="h-5 px-1.5 text-xs font-mono text-muted-foreground">
                    已完成 {completedRuns.length}
                  </Badge>
                </div>

                {completedRuns.length >= 2 ? (
                  <>
                    <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">基准快照</Label>
                        <Select value={compareA} onValueChange={setCompareA}>
                          <SelectTrigger className="h-8 bg-card/70 text-xs dark:bg-card/60">
                            <SelectValue placeholder="选择 run" />
                          </SelectTrigger>
                          <SelectContent>
                            {completedRuns.map((r) => (
                              <SelectItem key={r.id} value={r.id} className="text-xs">
                                {r.created_at ? formatDate(r.created_at) : r.id.slice(0, 8)} · {r.id.slice(0, 8)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">对比快照</Label>
                        <Select value={compareB} onValueChange={setCompareB}>
                          <SelectTrigger className="h-8 bg-card/70 text-xs dark:bg-card/60">
                            <SelectValue placeholder="选择 run" />
                          </SelectTrigger>
                          <SelectContent>
                            {completedRuns.map((r) => (
                              <SelectItem key={r.id} value={r.id} className="text-xs">
                                {r.created_at ? formatDate(r.created_at) : r.id.slice(0, 8)} · {r.id.slice(0, 8)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    {compareDelta ? (
                      <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-3">
                        <div className="border-b border-border py-3">
                          <div className="text-xs text-muted-foreground">文档数 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.docs >= 0 ? `+${compareDelta.docs}` : String(compareDelta.docs)}</div>
                        </div>
                        <div className="border-b border-border py-3">
                          <div className="text-xs text-muted-foreground">总大小 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">
                            {compareDelta.bytes >= 0 ? '+' : '-'}
                            {formatFileSize(Math.abs(compareDelta.bytes))}
                          </div>
                        </div>
                        <div className="border-b border-border py-3">
                          <div className="text-xs text-muted-foreground">P90 长度 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.p90 >= 0 ? `+${compareDelta.p90}` : String(compareDelta.p90)}</div>
                        </div>
                        <div className="border-b border-border py-3">
                          <div className="text-xs text-muted-foreground">扫描 PDF Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.scanned >= 0 ? `+${compareDelta.scanned}` : String(compareDelta.scanned)}</div>
                        </div>
                        <div className="border-b border-border py-3">
                          <div className="text-xs text-muted-foreground">PII 命中 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.pii >= 0 ? `+${compareDelta.pii}` : String(compareDelta.pii)}</div>
                        </div>
                        <div className="border-b border-border py-3">
                          <div className="text-xs text-muted-foreground">Secrets 命中 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.secrets >= 0 ? `+${compareDelta.secrets}` : String(compareDelta.secrets)}</div>
                        </div>
                      </div>
                    ) : (
                    <div className="mt-3 rounded-lg bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground dark:bg-muted/20">
                        请选择两个已完成扫描记录。
                      </div>
                    )}
                  </>
                ) : (
                  <div className="rounded-lg border border-dashed border-border/55 bg-muted/40 px-3 py-2 text-xs leading-4 text-muted-foreground dark:bg-muted/20">
                    <div className="font-medium text-foreground/75">暂无可对比快照</div>
                    <div className="mt-0.5">
                      至少需要 2 次已完成深度扫描；当前 {completedRuns.length} 次。完成后这里会出现基准/对比快照下拉。
                    </div>
                  </div>
                )}
              </div>

              <div className={ws.section}>
                <div className="text-[13px] font-semibold text-foreground/85">离线报告</div>
                <div className="text-xs leading-4 text-muted-foreground">
                  导出单文件 HTML，默认脱敏，适合离线分享。
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={() => detachPromise(exportHtml())}
                    disabled={!summary || isExportingHtml}
                  >
                    {isExportingHtml ? (
                      <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <Download className="w-4 h-4" />
                    )}
                    导出 HTML
                  </Button>
                </div>
              </div>
            </div>
          </Panel>
</div>}</TabsContent>
    </Tabs>}
    <Dialog open={scanConfigOpen} onOpenChange={setScanConfigOpen}><DialogContent className={ws.dialog}><DialogHeader className={ws.dialogHeader}><DialogTitle>深度扫描</DialogTitle><DialogDescription>补齐现有文档的质量指标，不执行重新入库。</DialogDescription></DialogHeader><div className={ws.dialogBody}>            <div className={ws.formRows}>
              <div className={ws.formRow}>
                <Label className="text-xs text-foreground/80">PDF 指标</Label>
                <Switch aria-label="PDF 指标"
                  checked={!!scanConfig.backfill_pdf_quality}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_pdf_quality: !!v }))}
                />
              </div>
              <div className={ws.formRow}>
                <Label className="text-xs text-foreground/80">文本质量</Label>
                <Switch aria-label="文本质量"
                  checked={!!scanConfig.backfill_text_quality}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_text_quality: !!v }))}
                />
              </div>
              <div className={ws.formRow}>
                <Label className="text-xs text-foreground/80">切片分布</Label>
                <Switch aria-label="切片分布"
                  checked={!!scanConfig.backfill_chunk_stats}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_chunk_stats: !!v }))}
                />
              </div>
              <div className={ws.formRow}>
                <Label className="text-xs text-foreground/80">文件哈希</Label>
                <Switch aria-label="文件哈希"
                  checked={!!scanConfig.compute_file_hash}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, compute_file_hash: !!v }))}
                />
              </div>
              <div className={ws.formRow}>
                <Label className="text-xs text-foreground/80">最大文档数</Label>
                <Input aria-label="最大文档数"
                  value={scanConfig.max_documents ?? ''}
                  placeholder="不限"
                  onChange={(e) => {
                    const raw = e.target.value.trim()
                    if (!raw) {
                      setScanConfig((prev) => ({ ...prev, max_documents: null }))
                      return
                    }
                    const n = Number(raw)
                    setScanConfig((prev) => ({ ...prev, max_documents: Number.isFinite(n) ? Math.max(0, Math.floor(n)) : null }))
                  }}
                  className="h-7 w-20 font-mono text-xs"
                />
              </div>
            </div>

</div><div className={ws.dialogFooter}><Button variant="ghost" onClick={() => setScanConfigOpen(false)}>关闭</Button><Button disabled={scanRunning} onClick={() => { void startDeepScan() }}>{scanRunning ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Sparkles />}{scanRunning ? '正在扫描…' : '开始扫描'}</Button></div></DialogContent></Dialog>
        <Dialog open={findingOpen} onOpenChange={(open) => {
           setFindingOpen(open)
           if (!open) {
             setSelectedFinding(null)
           }
         }}>
          <DialogContent className={ws.dialog}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle className="text-xl font-bold text-foreground flex items-center justify-between gap-3">
                <span className="flex items-center gap-2">
                  {selectedFinding?.label || '清单'}
                  {selectedFinding ? (
                    <Badge variant={findingBadgeVariant(selectedFinding.severity)} className="font-mono text-xs">
                      {selectedFinding.count}
                    </Badge>
                  ) : null}
                </span>
                {selectedFinding?.key === 'parse_low_quality' && findingRes?.items?.length ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    disabled={findingRetrying || findingLoading}
                    onClick={() => retryDocuments(findingRes.items.map((d) => String(d.id)), 'batch')}
                    title="对当前清单触发重新处理（best-effort）"
                  >
                    {findingRetrying ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
                    <RefreshCw className="w-4 h-4" />
                    一键重试
                  </Button>
                ) : null}
              </DialogTitle>
              <DialogDescription className="text-muted-foreground">
                {selectedFinding?.description || '点击文件名可在知识库页查看详情（按文件查看详情）'}
              </DialogDescription>
            </DialogHeader>

            <div className={ws.dialogBody}>
              {(() => {
    if (findingLoading && !findingRes) {
        return (<div className="py-10 flex items-center justify-center text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none mr-2"/>
                  加载中…
                </div>);
    }
    else if (findingRes) {
            return (<div className="space-y-3">
                  <div className="text-xs text-muted-foreground font-mono">
                    showing {findingRes.items.length}/{findingRes.total}
                  </div>
                  <div className={ws.tableScroll}>
                    <table aria-label="数据集画像 PII 命中明细" className="w-full text-left text-xs">
                      <thead className="bg-muted/40 text-muted-foreground">
                        <tr>
                          <th className="px-2 py-1.5 font-medium">文件名</th>
                          <th className="px-2 py-1.5 font-medium">类型</th>
                          <th className="px-2 py-1.5 font-medium">大小</th>
                          <th className="px-2 py-1.5 font-medium">状态</th>
                          <th className="px-2 py-1.5 font-medium">长度</th>
                          {selectedFinding?.key === 'parse_low_quality' ? (
                            <th className="px-2 py-1.5 font-medium text-right">操作</th>
                          ) : null}
                        </tr>
                      </thead>
                      <tbody>
                        {findingRes.items.map((d) => (<tr key={d.id} className="border-t border-border/60 hover:bg-muted/20 transition-colors">
                            <td className="px-2 py-1.5">
                              <DocumentDetailDialog document={{
                        id: d.id,
                        filename: d.filename,
                        file_type: d.file_type,
                        file_size: d.file_size,
                        status: asDocumentStatus(d.status),
                        processing_progress: 0,
                        chunk_count: d.chunk_count || 0,
                        total_characters: d.total_characters || 0,
                        created_at: d.created_at || new Date().toISOString(),
                        updated_at: d.updated_at || new Date().toISOString(),
                        error_message: d.error_message || undefined,
                        metadata: d.metadata || {},
                        dataset_id: datasetId || undefined,
                    } as Document} trigger={<button type="button" className="text-primary hover:underline">
                                    {d.filename}
                                  </button>}/>
                            </td>
                            <td className="px-2 py-1.5 font-mono text-xs">{d.file_type}</td>
                            <td className="px-2 py-1.5 font-mono text-xs">{formatFileSize(d.file_size || 0)}</td>
                            <td className="px-2 py-1.5">
                              <Badge variant="outline" className="font-mono text-xs">
                                {d.status}
                              </Badge>
                            </td>
                            <td className="px-2 py-1.5 font-mono text-xs">{d.total_characters}</td>
                            {selectedFinding?.key === 'parse_low_quality' ? (
                              <td className="px-2 py-1.5 text-right">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-8 px-2 gap-2 text-xs"
                                  disabled={findingRetrying || findingLoading || Boolean(findingRetryingIds[String(d.id)])}
                                  onClick={() => retryDocuments([String(d.id)], 'single')}
                                >
                                  {findingRetryingIds[String(d.id)] ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                                  ) : (
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  )}
                                  重试
                                </Button>
                              </td>
                            ) : null}
                          </tr>))}
                      </tbody>
                    </table>
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="text-xs text-muted-foreground">
                      {findingRes.items.length >= findingRes.total ? '已加载全部' : ''}
                    </div>
                    <Button variant="outline" className="gap-2" onClick={() => detachPromise(loadMoreFindingPage())} disabled={findingLoading || !hasNextFindingPage}>
                      {findingLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none"/> : null}
                      加载更多
                    </Button>
                  </div>
                </div>);
        }
        else {
            return (<div className="py-10 text-center text-[11px] text-muted-foreground/60">
                  暂无数据
                </div>);
        }
})()}
            </div>
          </DialogContent>
        </Dialog>

        <Dialog open={bucketOpen} onOpenChange={(open) => {
          setBucketOpen(open)
           if (!open) {
             setBucketDim(null)
             setBucketKey('')
           }
         }}>
          <DialogContent className={ws.dialog}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
                {(() => {
                  const label =
                    (() => {
    if (bucketDim === 'file_type') {
        return '格式';
    }
    else if (bucketDim === 'language') {
            return '语言';
        }
        else if (bucketDim === 'directory') {
                return '目录';
            }
            else if (bucketDim === 'quality_bucket') {
                    return '质量桶';
                }
                else {
                    return '清单';
                }
})()
                  return bucketDim ? `${label}: ${bucketKey || ''}` : '清单'
                })()}
                {bucketRes ? (
                  <Badge variant="outline" className="font-mono text-xs">
                    {bucketRes.total}
                  </Badge>
                ) : null}
              </DialogTitle>
              <DialogDescription className="text-muted-foreground">
                Preview 已做 PII/Secrets 脱敏（best-effort）。点击文件名可查看文档详情。
              </DialogDescription>
            </DialogHeader>

            <div className={ws.dialogBody}>
              {(() => {
    if (bucketLoading && !bucketRes) {
        return (<div className="py-10 flex items-center justify-center text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none mr-2"/>
                  加载中…
                </div>);
    }
    else if (bucketRes) {
            return (<div className="space-y-3">
                  <div className="text-xs text-muted-foreground font-mono">
                    showing {bucketRes.items.length}/{bucketRes.total}
                  </div>
                  <div className={ws.tableScroll}>
                    <table aria-label="数据集画像 Secrets 命中明细" className="w-full text-left text-xs">
                      <thead className="bg-muted/40 text-muted-foreground">
                        <tr>
                          <th className="px-2 py-1.5 font-medium">文件名</th>
                          <th className="px-2 py-1.5 font-medium">类型</th>
                          <th className="px-2 py-1.5 font-medium">大小</th>
                          <th className="px-2 py-1.5 font-medium">状态</th>
                          <th className="px-2 py-1.5 font-medium">长度</th>
                          <th className="px-2 py-1.5 font-medium">样例（脱敏）</th>
                        </tr>
                      </thead>
                      <tbody>
                        {bucketRes.items.map((d) => (<tr key={d.id} className="border-t border-border/60 hover:bg-muted/20 transition-colors">
                            <td className="px-2 py-1.5">
                              <DocumentDetailDialog document={{
                        id: d.id,
                        filename: d.filename,
                        file_type: d.file_type,
                        file_size: d.file_size,
                        status: asDocumentStatus(d.status),
                        processing_progress: 0,
                        chunk_count: d.chunk_count || 0,
                        total_characters: d.total_characters || 0,
                        created_at: d.created_at || new Date().toISOString(),
                        updated_at: d.updated_at || new Date().toISOString(),
                        error_message: d.error_message || undefined,
                        metadata: d.metadata || {},
                        dataset_id: datasetId || undefined,
                    } as Document} trigger={<button type="button" className="text-primary hover:underline">
                                    {d.filename}
                                  </button>}/>
                            </td>
                            <td className="px-2 py-1.5 font-mono text-xs">{d.file_type}</td>
                            <td className="px-2 py-1.5 font-mono text-xs">{formatFileSize(d.file_size || 0)}</td>
                            <td className="px-2 py-1.5">
                              <Badge variant="outline" className="font-mono text-xs">
                                {d.status}
                              </Badge>
                            </td>
                            <td className="px-2 py-1.5 font-mono text-xs">{d.total_characters}</td>
                            <td className="px-2 py-1.5 max-w-[520px]">
                              {d.preview ? (<div className="text-xs text-muted-foreground line-clamp-2" title={String(d.preview || '')}>
                                  {String(d.preview)}
                                  {d.preview_truncated ? '…' : ''}
                                </div>) : (<span className="text-xs text-muted-foreground">-</span>)}
                            </td>
                          </tr>))}
                      </tbody>
                    </table>
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="text-xs text-muted-foreground">
                      {bucketRes.items.length >= bucketRes.total ? '已加载全部' : ''}
                    </div>
                    <Button variant="outline" className="gap-2" onClick={() => detachPromise(loadMoreBucketPage())} disabled={bucketLoading || !hasNextBucketPage}>
                      {bucketLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none"/> : null}
                      加载更多
                    </Button>
                  </div>
                </div>);
        }
        else {
            return (<div className="py-10 text-center text-[11px] text-muted-foreground/60">
                  暂无数据
                </div>);
        }
})()}
            </div>
          </DialogContent>
        </Dialog>
</OperationalWorkspace></AppFrame>
}
