'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import {
  Activity,
  ArrowLeft,
  BarChart3,
  Download,
  FileSearch,
  Loader2,
  RotateCcw,
  RefreshCw,
  Settings2,
  Sparkles,
  Table2,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

import { datasetApi, documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatFileSize, formatDate, detachPromise } from '@/lib/utils'
import { useRouter } from '@/i18n/navigation'
import { Breadcrumb, usePathBreadcrumbs } from '@/components/ui/breadcrumb'

import type {
  Dataset,
  Document,
  DatasetProfileDocumentListResponse,
  DatasetProfileFindingListResponse,
  DatasetProfileFindingSummary,
  DatasetProfileScanRunCreateRequest,
  DatasetProfileScanRunOut,
  DatasetProfileSummary,
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

const PROFILE_SECTIONS = [
  { id: 'prof-overview', label: '概览' },
  { id: 'prof-distribution', label: '分布图表' },
  { id: 'prof-findings', label: '问题清单' },
  { id: 'prof-scan', label: '深度扫描' },
  { id: 'prof-history', label: '扫描历史' },
] as const

function ProfileAnchorNav() {
  const [activeId, setActiveId] = useState<string>(PROFILE_SECTIONS[0].id)

  useEffect(() => {
    const visibleMap = new Map<string, number>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          visibleMap.set(entry.target.id, entry.intersectionRatio)
        }
        let best: string = PROFILE_SECTIONS[0].id
        let bestRatio = -1
        for (const sec of PROFILE_SECTIONS) {
          const ratio = visibleMap.get(sec.id) ?? 0
          if (ratio > bestRatio) {
            bestRatio = ratio
            best = sec.id
          }
        }
        if (bestRatio > 0) setActiveId(best)
      },
      {
        root: document.querySelector('[data-page-scroll-container]'),
        threshold: [0, 0.1, 0.25, 0.5],
      },
    )

    for (const sec of PROFILE_SECTIONS) {
      const el = document.getElementById(sec.id)
      if (el) observer.observe(el)
    }

    return () => observer.disconnect()
  }, [])

  return (
    <div className="flex items-center gap-1 mb-5 overflow-x-auto no-scrollbar">
      {PROFILE_SECTIONS.map((sec) => (
        <button
          key={sec.id}
          type="button"
          onClick={() => document.getElementById(sec.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
          className={cn(
            'shrink-0 text-xs px-3 py-1.5 rounded-full transition-colors whitespace-nowrap',
            activeId === sec.id
              ? 'bg-primary/10 text-primary font-semibold'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
          )}
        >
          {sec.label}
        </button>
      ))}
    </div>
  )
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

export default function DatasetProfilePage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId(params?.id)
  const breadcrumbs = usePathBreadcrumbs()

  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [summary, setSummary] = useState<DatasetProfileSummary | null>(null)
  const [isLoading, setIsLoading] = useState(false)
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
  const [scanRuns, setScanRuns] = useState<DatasetProfileScanRunOut[]>([])
  const [compareA, setCompareA] = useState<string>('')
  const [compareB, setCompareB] = useState<string>('')

  const [findingOpen, setFindingOpen] = useState(false)
  const [selectedFinding, setSelectedFinding] = useState<DatasetProfileFindingSummary | null>(null)
  const [findingLoading, setFindingLoading] = useState(false)
  const [findingRes, setFindingRes] = useState<DatasetProfileFindingListResponse | null>(null)
  const [findingRetrying, setFindingRetrying] = useState(false)
  const [findingRetryingIds, setFindingRetryingIds] = useState<Record<string, boolean>>({})

  const [bucketOpen, setBucketOpen] = useState(false)
  const [bucketDim, setBucketDim] = useState<'file_type' | 'language' | 'directory' | 'quality_bucket' | null>(null)
  const [bucketKey, setBucketKey] = useState<string>('')
  const [bucketLoading, setBucketLoading] = useState(false)
  const [bucketRes, setBucketRes] = useState<DatasetProfileDocumentListResponse | null>(null)

  const stopPolling = useCallback(() => {
    const t = pollTimerRef.current
    if (t) globalThis.window.clearTimeout(t)
    pollTimerRef.current = null
  }, [])

  const load = useCallback(async () => {
    if (!datasetId) return
    setIsLoading(true)
    try {
      const [ds, prof, runList] = await Promise.all([
        datasetApi.get(datasetId),
        datasetApi.getProfileSummary(datasetId),
        datasetApi.listProfileScanRuns(datasetId, { skip: 0, limit: 20 }).catch(() => ({ total: 0, items: [] })),
      ])
      setDataset(ds)
      setSummary(prof)
      setScanRuns(runList.items || [])
      const completed = (runList.items || []).filter((r) => String(r.status || '').toLowerCase() === 'completed')
      setCompareA((prev) => prev || completed[0]?.id || '')
      setCompareB((prev) => prev || completed[1]?.id || '')
    } catch (e: any) {
      console.error('Failed to load dataset profile', e)
      toast.error(formatApiError(e, '加载数据画像失败'))
    } finally {
      setIsLoading(false)
    }
  }, [datasetId])

  useEffect(() => {
    detachPromise(load())
    return () => stopPolling()
  }, [load, stopPolling])

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
    return top
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
      { name: 'scanned', value: Number(s.scanned || 0) },
      { name: 'text', value: Number(s.not_scanned || 0) },
      { name: 'unknown', value: Number(s.unknown || 0) },
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
    async (finding: DatasetProfileFindingSummary) => {
      if (!datasetId) return
      setSelectedFinding(finding)
      setFindingOpen(true)
      setFindingLoading(true)
      try {
        const res = await datasetApi.listProfileFinding(datasetId, finding.key, { skip: 0, limit: 50 })
        setFindingRes(res)
      } catch (e: any) {
        console.error('Failed to load finding documents', e)
        toast.error(formatApiError(e, '加载清单失败'))
        setFindingRes(null)
      } finally {
        setFindingLoading(false)
      }
    },
    [datasetId]
  )

  const openBucket = useCallback(
    async (dim: 'file_type' | 'language' | 'directory' | 'quality_bucket', key: string) => {
      if (!datasetId) return
      if (!key || key === '__other__') return
      setBucketDim(dim)
      setBucketKey(key)
      setBucketOpen(true)
      setBucketLoading(true)
      try {
        const res = await datasetApi.listProfileBucketDocuments(datasetId, {
          dimension: dim,
          bucket: key,
          skip: 0,
          limit: 50,
          include_preview: true,
          preview_max_chars: 360,
        })
        setBucketRes(res)
      } catch (e: any) {
        console.error('Failed to load bucket documents', e)
        toast.error(formatApiError(e, '加载清单失败'))
        setBucketRes(null)
      } finally {
        setBucketLoading(false)
      }
    },
    [datasetId]
  )

  const loadMoreFinding = useCallback(async () => {
    if (!datasetId || !selectedFinding || !findingRes) return
    if (findingRes.items.length >= findingRes.total) return

    const nextSkip = findingRes.items.length
    setFindingLoading(true)
    try {
      const res = await datasetApi.listProfileFinding(datasetId, selectedFinding.key, { skip: nextSkip, limit: 50 })
      setFindingRes({ total: res.total, items: [...findingRes.items, ...(res.items || [])] })
    } catch (e: any) {
      console.error('Failed to load more finding documents', e)
      toast.error(formatApiError(e, '加载更多失败'))
    } finally {
      setFindingLoading(false)
    }
  }, [datasetId, selectedFinding, findingRes])

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
        detachPromise(load())
      } catch (e: any) {
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
    [load]
  )

  const loadMoreBucket = useCallback(async () => {
    if (!datasetId || !bucketDim || !bucketKey || !bucketRes) return
    if (bucketRes.items.length >= bucketRes.total) return
    setBucketLoading(true)
    try {
      const res = await datasetApi.listProfileBucketDocuments(datasetId, {
        dimension: bucketDim,
        bucket: bucketKey,
        skip: bucketRes.items.length,
        limit: 50,
        include_preview: true,
        preview_max_chars: 360,
      })
      setBucketRes({ total: res.total, items: [...bucketRes.items, ...(res.items || [])] })
    } catch (e: any) {
      console.error('Failed to load more bucket documents', e)
      toast.error(formatApiError(e, '加载更多失败'))
    } finally {
      setBucketLoading(false)
    }
  }, [datasetId, bucketDim, bucketKey, bucketRes])

  const pollScanRun = useCallback(
    async (datasetIdValue: string, runId: string) => {
      try {
        const next = await datasetApi.getProfileScanRun(datasetIdValue, runId)
        setScanRun(next)
        const st = String(next.status || '').toLowerCase()
        if (st === 'pending' || st === 'running') {
          pollTimerRef.current = globalThis.window.setTimeout(() => detachPromise(pollScanRun(datasetIdValue, runId)), 2000)
          return
        }
        setScanRunning(false)
        stopPolling()
        detachPromise(load())
      } catch (e: any) {
        console.error('Failed to poll scan run', e)
        setScanRunning(false)
        stopPolling()
      }
    },
    [load, stopPolling]
  )

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
        detachPromise(load())
      }
      toast.success('已启动深度扫描')
    } catch (e: any) {
      console.error('Failed to start scan', e)
      toast.error(formatApiError(e, '启动扫描失败'))
      setScanRunning(false)
    }
  }, [datasetId, scanConfig, pollScanRun, load])

  const exportJson = useCallback(async () => {
    if (!datasetId) return
    setIsExportingJson(true)
    try {
      const blob = await datasetApi.exportProfileSummary(datasetId)
      const safe = String(dataset?.name || 'dataset').replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.profile.json`)
      toast.success('已导出 JSON 报告')
    } catch (e: any) {
      console.error('Failed to export profile', e)
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
    } catch (e: any) {
      console.error('Failed to export profile html', e)
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
    const piiA = Object.values(sa.pii_hits_total || {}).reduce((acc: number, v: any) => acc + Number(v || 0), 0)
    const piiB = Object.values(sb.pii_hits_total || {}).reduce((acc: number, v: any) => acc + Number(v || 0), 0)
    const secA = Object.values(sa.secrets_hits_total || {}).reduce((acc: number, v: any) => acc + Number(v || 0), 0)
    const secB = Object.values(sb.secrets_hits_total || {}).reduce((acc: number, v: any) => acc + Number(v || 0), 0)
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

  return (
    <AppFrame>
      <PageScaffold
        title={`数据画像${dataset?.name ? ` · ${dataset.name}` : ''}`}
        badge="Dataset Profile"
        icon={BarChart3}
        iconColor="text-info"
        top={<Breadcrumb items={breadcrumbs} />}
        description={
          <span className="text-sm text-muted-foreground">
            基于文档库元数据的入库前/入库中质量画像（格式、长度、扫描件、PII、重复等）
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" className="gap-2" onClick={() => router.push('/datasets')}>
              <ArrowLeft className="w-4 h-4" />
              返回
            </Button>
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/health`)}>
                <Activity className="w-4 h-4" />
                健康
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                <Settings2 className="w-4 h-4" />
                入库策略
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/tables`)}>
                <Table2 className="w-4 h-4" />
                表格 / TAG
              </Button>
            ) : null}
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => detachPromise(load())}
              disabled={isLoading}
            >
              <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => detachPromise(exportJson())}
              disabled={isExportingJson || !summary}
            >
              {isExportingJson ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
              导出 JSON
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => detachPromise(exportHtml())}
              disabled={isExportingHtml || !summary}
            >
              {isExportingHtml ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
              导出 HTML
            </Button>
          </div>
        }
      >
        <ProfileAnchorNav />
        <div className="space-y-6">
          <div id="prof-overview">
          <Panel className="p-5">
            <StatsGrid>
              <StatCard icon={FileSearch} label="文档总数" value={summary?.total_documents ?? (isLoading ? '…' : 0)} color="cyan" />
              <StatCard icon={BarChart3} label="总大小" value={(() => {
    if (summary) {
        return formatFileSize(summary.total_size_bytes || 0);
    }
    else if (isLoading) {
            return '…';
        }
        else {
            return '-';
        }
})()} color="teal" />
              <StatCard icon={Sparkles} label="P50 长度" value={summary?.length_percentiles?.p50 ?? (isLoading ? '…' : 0)} subValue="chars" color="blue" />
              <StatCard icon={Sparkles} label="P90 长度" value={summary?.length_percentiles?.p90 ?? (isLoading ? '…' : 0)} subValue="chars" color="blue" />
              <StatCard icon={Sparkles} label="扫描 PDF" value={(() => {
    if (summary) {
        return `${summary.pdf_scan.scanned}/${summary.pdf_scan.scanned + summary.pdf_scan.not_scanned + summary.pdf_scan.unknown}`;
    }
    else if (isLoading) {
            return '…';
        }
        else {
            return '-';
        }
})()} color="orange" />
            </StatsGrid>
          </Panel>
          </div>

          <div id="prof-distribution" className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">格式分布</div>
                <div className="text-xs text-muted-foreground font-mono">
                  {summary?.generated_at ? `updated ${formatDate(summary.generated_at)}` : ''}
                </div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Tooltip />
                    <Pie
                      data={fileTypeChartData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={55}
                      outerRadius={95}
                      paddingAngle={2}
                    >
                      {fileTypeChartData.map((entry, idx) => (
                        <Cell key={String(entry.name ?? 'file-type')} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">状态分布</div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={statusChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">长度分布（chars）</div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={lengthHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">PDF 扫描占比</div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Tooltip />
                    <Pie data={pdfScanData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={95} paddingAngle={2}>
                      {pdfScanData.map((entry, idx) => (
                        <Cell key={String(entry.name ?? 'pdf-scan')} fill={['#fb7185', '#38bdf8', '#94a3b8'][idx % 3]} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">文件大小分布</div>
              </div>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={fileSizeHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="hsl(var(--chart-3))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">页数分布</div>
              </div>
              {pageCountHistogramData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={pageCountHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-7))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">Chunk 数分布（每文档）</div>
              </div>
              {chunkCountHistogramData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chunkCountHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-4))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">平均 Chunk 长度（chars/chunk）</div>
              </div>
              {avgChunkCharsHistogramData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={avgChunkCharsHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">Chunk 长度分布（chunk-level）</div>
              </div>
              {chunkLengthHistogramData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chunkLengthHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-6))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5 lg:col-span-2">
              <div className="flex items-center justify-between gap-4 mb-4">
                <div className="font-semibold">Chunk Targets（分布目标检查）</div>
                <div className="text-xs text-muted-foreground">
                  objective checks · suggestions
                </div>
              </div>

              {chunkTargets.length ? (
                <div className="space-y-3">
                  {chunkTargets.map((t, idx) => (
                    <div
                      key={String(t.key || t.label || idx)}
                      className="rounded-xl border border-border/60 bg-card/40 p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="font-medium truncate">{String(t.label || t.key || '')}</div>
                          {t.message ? (
                            <div className="mt-1 text-sm text-muted-foreground text-pretty">
                              {String(t.message)}
                            </div>
                          ) : null}
                        </div>
                        <Badge variant={targetBadgeVariant(String(t.status || ''))} className="font-mono text-xs">
                          {String(t.status || '')}
                        </Badge>
                      </div>

                      {t.suggestions.length ? (
                        <ul className="mt-2 pl-5 list-disc text-sm text-muted-foreground">
                          {t.suggestions.slice(0, 6).map((s) => (
                            <li key={String(s)} className="text-pretty">
                              {String(s)}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-10 text-center text-muted-foreground">
                  暂无数据（可运行深度扫描补齐 chunk token/coverage 等指标）
                </div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">解析质量分布</div>
                {parseLowQualityFinding ? (
                  <Button
                    variant="outline"
                    className="h-8 px-2 gap-1 text-xs"
                    onClick={() => detachPromise(openFinding(parseLowQualityFinding))}
                  >
                    <FileSearch className="w-3.5 h-3.5" />
                    低质量
                  </Button>
                ) : null}
              </div>
              {parseQualityHistogramData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={parseQualityHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">Parsing provenance / 路由</div>
              </div>

              {parsingBackendChartData.length ? (
                <div className="h-[220px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={parsingBackendChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[220px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">docs_with_provenance</div>
                  <div className="mt-1 font-mono font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.docs_with_provenance || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">fallback_docs</div>
                  <div className="mt-1 font-mono font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.fallback_docs || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">p50_elapsed_ms</div>
                  <div className="mt-1 font-mono font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.elapsed_ms_percentiles?.p50 || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">p90_elapsed_ms</div>
                  <div className="mt-1 font-mono font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.elapsed_ms_percentiles?.p90 || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">平均解析分</div>
                  <div className="mt-1 font-mono font-semibold tabular-nums">
                    {averageParseQuality == null ? '-' : averageParseQuality.toFixed(3)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                  <div className="text-xs text-muted-foreground">fallback_rate</div>
                  <div className="mt-1 font-mono font-semibold tabular-nums">
                    {fallbackRate == null ? '-' : `${(fallbackRate * 100).toFixed(1)}%`}
                  </div>
                </div>
              </div>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">语言分布</div>
              </div>
              {languageMixChartData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Tooltip />
                      <Pie
                        data={languageMixChartData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={55}
                        outerRadius={95}
                        paddingAngle={2}
                      >
                        {languageMixChartData.map((entry, idx) => (
                          <Cell key={String(entry.name ?? 'language')} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div className="font-semibold">目录分布（Top-level）</div>
                <div className="text-xs text-muted-foreground">click bar → drilldown</div>
              </div>
              {directoryChartData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={directoryChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} interval={0} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-5))" radius={[6, 6, 0, 0]}>
                        {directoryChartData.map((entry) => (
                          <Cell
                            key={String(entry.key ?? entry.name ?? 'directory')}
                            cursor={entry.key === '__other__' ? 'default' : 'pointer'}
                            onClick={() => (entry.key === '__other__' ? null : detachPromise(openBucket('directory', String(entry.key || 'root'))))}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between gap-3 mb-4">
                <div className="font-semibold">质量桶分布</div>
                <div className="text-xs text-muted-foreground">click bar → drilldown</div>
              </div>
              {qualityBucketChartData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={qualityBucketChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} interval={0} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]}>
                        {qualityBucketChartData.map((entry) => (
                          <Cell
                            key={String(entry.key ?? entry.name ?? 'quality')}
                            cursor="pointer"
                            onClick={() => detachPromise(openBucket('quality_bucket', String(entry.key || 'unknown')))}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">PII 命中（次数）</div>
              </div>
              {piiChartData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={piiChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-4))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">Secrets/Token 命中（次数）</div>
              </div>
              {secretsChartData.length ? (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={secretsChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-6))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>
          </div>

          <div id="prof-findings">
          <Panel className="p-5">
            <div className="flex items-center justify-between gap-4 mb-4">
              <div className="font-semibold">问题清单（可操作）</div>
              <div className="text-xs text-muted-foreground">
                点击卡片查看文件列表（分页）
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {(summary?.findings || []).map((f) => (
                <button
                  key={f.key}
                  type="button"
                  className={cn(
                    'text-left px-4 py-3 rounded-xl border border-border/60 bg-card/40 hover:bg-card/70 transition-colors',
                    'focus:outline-none focus:ring-2 focus:ring-primary/30'
                  )}
                  onClick={() => detachPromise(openFinding(f))}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium truncate">{f.label}</div>
                    <Badge variant={findingBadgeVariant(f.severity)} className="font-mono text-xs">
                      {f.count}
                    </Badge>
                  </div>
                  {f.description ? (
                    <div className="mt-1 text-xs text-muted-foreground line-clamp-2">{f.description}</div>
                  ) : null}
                </button>
              ))}
            </div>
          </Panel>
          </div>

          <div id="prof-scan">
          <Panel className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="font-semibold flex items-center gap-2">
                  深度扫描（补齐指标）
                  {latestRunStatus ? (
                    <Badge variant="outline" className="font-mono text-xs">
                      {String(latestRunStatus)}
                    </Badge>
                  ) : null}
                </div>
                <div className="text-sm text-muted-foreground mt-1">
                  用于补齐缺失的 pdf_quality / parsed_text_quality / chunking_stats；可选计算 file_sha256（用于完全重复）。
                </div>
              </div>

              <Button className="gap-2" onClick={() => detachPromise(startDeepScan())} disabled={scanRunning}>
                {scanRunning ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Sparkles className="w-4 h-4" />}
                启动
              </Button>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">补齐 PDF 指标</Label>
                <Switch
                  checked={!!scanConfig.backfill_pdf_quality}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_pdf_quality: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">补齐文本质量</Label>
                <Switch
                  checked={!!scanConfig.backfill_text_quality}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_text_quality: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">补齐 Chunk 分布</Label>
                <Switch
                  checked={!!scanConfig.backfill_chunk_stats}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_chunk_stats: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">计算 file_sha256</Label>
                <Switch
                  checked={!!scanConfig.compute_file_hash}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, compute_file_hash: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">最大文档数</Label>
                <Input
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
                  className="w-28 font-mono text-sm"
                />
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between gap-4">
              <div className="text-sm text-muted-foreground">
                进度：{(() => {
    if (scanRunning) {
        return `${latestRunProgress || 0}%`;
    }
    else if (latestRunProgress) {
            return `${latestRunProgress}%`;
        }
        else {
            return '-';
        }
})()}
                {effectiveScanRun.error_message ? <span className="ml-3 text-destructive">错误：{effectiveScanRun.error_message}</span> : null}
              </div>
            </div>
          </Panel>
          </div>

          <div id="prof-history">
          <Panel className="p-5">
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <div className="font-semibold">扫描历史 / 对比</div>
                <div className="text-sm text-muted-foreground mt-1">
                  深度扫描会把“缺失指标”补齐，并保存一次 summary 快照；可用于回溯与对比。
                </div>
              </div>
              <Button variant="outline" className="gap-2" onClick={() => detachPromise(load())} disabled={isLoading}>
                <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
                刷新
              </Button>
            </div>

            {scanRuns.length ? (
              <div className="rounded-xl border border-border/60 overflow-hidden">
                <table aria-label="数据集画像扫描运行记录" className="w-full text-sm text-left">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">时间</th>
                      <th className="px-3 py-2 font-medium">状态</th>
                      <th className="px-3 py-2 font-medium">进度</th>
                      <th className="px-3 py-2 font-medium">配置</th>
                      <th className="px-3 py-2 font-medium">错误</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scanRuns.map((r) => (
                      <tr key={r.id} className="border-t border-border/60">
                        <td className="px-3 py-2 font-mono text-xs">{r.created_at ? formatDate(r.created_at) : '-'}</td>
                        <td className="px-3 py-2">
                          <Badge variant="outline" className="font-mono text-xs">
                            {String(r.status || '')}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 font-mono text-xs">{typeof r.progress === 'number' ? `${r.progress}%` : '-'}</td>
                        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                          pdf:{r.config?.backfill_pdf_quality === false ? '0' : '1'} · text:{r.config?.backfill_text_quality === false ? '0' : '1'} · chunk:{r.config?.backfill_chunk_stats === false ? '0' : '1'} · sha:{r.config?.compute_file_hash ? '1' : '0'}
                        </td>
                        <td className="px-3 py-2 text-xs text-destructive">{r.error_message || ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-muted-foreground">暂无扫描记录</div>
            )}

            <div className="mt-5 grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2 rounded-xl border border-border/60 bg-card/40 p-4">
                <div className="font-medium mb-3">对比两次 completed 扫描快照</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label className="text-sm">Run A</Label>
                    <Select value={compareA} onValueChange={setCompareA}>
                      <SelectTrigger>
                        <SelectValue placeholder="选择 run" />
                      </SelectTrigger>
                      <SelectContent>
                        {completedRuns.map((r) => (
                          <SelectItem key={r.id} value={r.id}>
                            {r.created_at ? formatDate(r.created_at) : r.id.slice(0, 8)} · {r.id.slice(0, 8)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-sm">Run B</Label>
                    <Select value={compareB} onValueChange={setCompareB}>
                      <SelectTrigger>
                        <SelectValue placeholder="选择 run" />
                      </SelectTrigger>
                      <SelectContent>
                        {completedRuns.map((r) => (
                          <SelectItem key={r.id} value={r.id}>
                            {r.created_at ? formatDate(r.created_at) : r.id.slice(0, 8)} · {r.id.slice(0, 8)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                {compareDelta ? (
                  <div className="mt-4 grid grid-cols-2 lg:grid-cols-3 gap-3">
                    <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                      <div className="text-xs text-muted-foreground">文档数 Δ（B-A）</div>
                      <div className="font-mono font-semibold text-sm mt-1">{compareDelta.docs >= 0 ? `+${compareDelta.docs}` : String(compareDelta.docs)}</div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                      <div className="text-xs text-muted-foreground">总大小 Δ（B-A）</div>
                      <div className="font-mono font-semibold text-sm mt-1">
                        {compareDelta.bytes >= 0 ? '+' : '-'}
                        {formatFileSize(Math.abs(compareDelta.bytes))}
                      </div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                      <div className="text-xs text-muted-foreground">P90 长度 Δ（B-A）</div>
                      <div className="font-mono font-semibold text-sm mt-1">{compareDelta.p90 >= 0 ? `+${compareDelta.p90}` : String(compareDelta.p90)}</div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                      <div className="text-xs text-muted-foreground">扫描 PDF Δ（B-A）</div>
                      <div className="font-mono font-semibold text-sm mt-1">{compareDelta.scanned >= 0 ? `+${compareDelta.scanned}` : String(compareDelta.scanned)}</div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                      <div className="text-xs text-muted-foreground">PII 命中 Δ（B-A）</div>
                      <div className="font-mono font-semibold text-sm mt-1">{compareDelta.pii >= 0 ? `+${compareDelta.pii}` : String(compareDelta.pii)}</div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
                      <div className="text-xs text-muted-foreground">Secrets 命中 Δ（B-A）</div>
                      <div className="font-mono font-semibold text-sm mt-1">{compareDelta.secrets >= 0 ? `+${compareDelta.secrets}` : String(compareDelta.secrets)}</div>
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 text-sm text-muted-foreground">请选择两个 completed 的扫描记录</div>
                )}
              </div>

              <div className="rounded-xl border border-border/60 bg-card/40 p-4">
                <div className="font-medium mb-2">导出离线报告</div>
                <div className="text-sm text-muted-foreground">
                  用于售前/分享：单文件 HTML（默认脱敏）。
                </div>
                <div className="mt-4 flex items-center gap-2">
                  <Button
                    variant="outline"
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
          </div>
        </div>

        <Dialog open={findingOpen} onOpenChange={(open) => {
          setFindingOpen(open)
          if (!open) {
            setSelectedFinding(null)
            setFindingRes(null)
          }
        }}>
          <DialogContent className="max-w-4xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
            <DialogHeader>
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
                {selectedFinding?.description || '点击文件名可在知识库页查看详情（后续可做联动）'}
              </DialogDescription>
            </DialogHeader>

            <div className="mt-2">
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
                  <div className="rounded-xl border border-border/60 overflow-hidden">
                    <table aria-label="数据集画像 PII 命中明细" className="w-full text-sm text-left">
                      <thead className="bg-muted/40 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-medium">文件名</th>
                          <th className="px-3 py-2 font-medium">类型</th>
                          <th className="px-3 py-2 font-medium">大小</th>
                          <th className="px-3 py-2 font-medium">状态</th>
                          <th className="px-3 py-2 font-medium">长度</th>
                          {selectedFinding?.key === 'parse_low_quality' ? (
                            <th className="px-3 py-2 font-medium text-right">操作</th>
                          ) : null}
                        </tr>
                      </thead>
                      <tbody>
                        {findingRes.items.map((d) => (<tr key={d.id} className="border-t border-border/60 hover:bg-muted/20 transition-colors">
                            <td className="px-3 py-2">
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
                            <td className="px-3 py-2 font-mono text-xs">{d.file_type}</td>
                            <td className="px-3 py-2 font-mono text-xs">{formatFileSize(d.file_size || 0)}</td>
                            <td className="px-3 py-2">
                              <Badge variant="outline" className="font-mono text-xs">
                                {d.status}
                              </Badge>
                            </td>
                            <td className="px-3 py-2 font-mono text-xs">{d.total_characters}</td>
                            {selectedFinding?.key === 'parse_low_quality' ? (
                              <td className="px-3 py-2 text-right">
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
                    <Button variant="outline" className="gap-2" onClick={() => detachPromise(loadMoreFinding())} disabled={findingLoading || findingRes.items.length >= findingRes.total}>
                      {findingLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none"/> : null}
                      加载更多
                    </Button>
                  </div>
                </div>);
        }
        else {
            return (<div className="py-10 text-center text-muted-foreground">
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
            setBucketRes(null)
          }
        }}>
          <DialogContent className="max-w-5xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
            <DialogHeader>
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

            <div className="mt-2">
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
                  <div className="rounded-xl border border-border/60 overflow-hidden">
                    <table aria-label="数据集画像 Secrets 命中明细" className="w-full text-sm text-left">
                      <thead className="bg-muted/40 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-medium">文件名</th>
                          <th className="px-3 py-2 font-medium">类型</th>
                          <th className="px-3 py-2 font-medium">大小</th>
                          <th className="px-3 py-2 font-medium">状态</th>
                          <th className="px-3 py-2 font-medium">长度</th>
                          <th className="px-3 py-2 font-medium">样例（脱敏）</th>
                        </tr>
                      </thead>
                      <tbody>
                        {bucketRes.items.map((d) => (<tr key={d.id} className="border-t border-border/60 hover:bg-muted/20 transition-colors">
                            <td className="px-3 py-2">
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
                            <td className="px-3 py-2 font-mono text-xs">{d.file_type}</td>
                            <td className="px-3 py-2 font-mono text-xs">{formatFileSize(d.file_size || 0)}</td>
                            <td className="px-3 py-2">
                              <Badge variant="outline" className="font-mono text-xs">
                                {d.status}
                              </Badge>
                            </td>
                            <td className="px-3 py-2 font-mono text-xs">{d.total_characters}</td>
                            <td className="px-3 py-2 max-w-[520px]">
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
                    <Button variant="outline" className="gap-2" onClick={() => detachPromise(loadMoreBucket())} disabled={bucketLoading || bucketRes.items.length >= bucketRes.total}>
                      {bucketLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none"/> : null}
                      加载更多
                    </Button>
                  </div>
                </div>);
        }
        else {
            return (<div className="py-10 text-center text-muted-foreground">
                  暂无数据
                </div>);
        }
})()}
            </div>
          </DialogContent>
        </Dialog>
      </PageScaffold>
    </AppFrame>
  )
}
