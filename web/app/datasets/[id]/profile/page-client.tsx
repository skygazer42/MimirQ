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
} from 'lucide-react'
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
const profileHeroCard = 'relative overflow-hidden border-b border-border/60 bg-transparent px-1 py-2 shadow-none dark:border-border/70'
const profilePanelClass = 'overflow-hidden border border-border/60 bg-card p-3 shadow-none dark:border-border/70 dark:bg-card'
const profileChartProps = { className: 'h-[176px]', minHeight: 176 } as const
const profileEmptyChartClass = 'h-[176px] flex items-center justify-center text-[11px] text-muted-foreground/60'
const profileSectionTitleClass = 'text-[13px] font-semibold leading-none text-foreground/85'
const profileSectionCaptionClass = 'mt-1 text-[11px] leading-4 text-muted-foreground/62'
const profileToolbarGroupClass = 'inline-flex flex-wrap items-center gap-1 rounded-lg border border-border/60 bg-card p-1 shadow-none dark:border-border/70 dark:bg-card'
const profileToolbarButtonClass = 'h-8 gap-1.5 rounded-xl px-2.5 text-[12px] font-medium text-muted-foreground shadow-none hover:bg-card/95 hover:text-foreground hover:shadow-sm dark:text-muted-foreground dark:hover:bg-muted/60 dark:hover:text-foreground [&_svg]:size-3.5'
const profileToolbarExportButtonClass = 'h-8 gap-1.5 rounded-md border border-border/60 bg-card px-2.5 text-[12px] font-medium text-foreground/85 shadow-none hover:bg-muted/40 hover:text-foreground dark:border-border/70 dark:bg-card dark:text-muted-foreground dark:hover:bg-muted/60 dark:hover:text-foreground [&_svg]:size-3.5'
const profileToolbarPrimaryButtonClass = 'h-8 gap-1.5 rounded-md border border-primary/20 bg-primary px-3 text-[12px] font-semibold text-primary-foreground shadow-none hover:bg-primary/90 dark:border-primary/30 [&_svg]:size-3.5'

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
        root: document.querySelector('[data-profile-scroll-container="true"]') ?? document.querySelector('[data-page-scroll-container]'),
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
    <div className="mb-3 flex items-center gap-1 overflow-x-auto rounded-lg border border-border/60 bg-card p-1.5 shadow-none no-scrollbar dark:border-border/70 dark:bg-card">
      {PROFILE_SECTIONS.map((sec) => (
        <button
          key={sec.id}
          type="button"
          onClick={() => document.getElementById(sec.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
          className={cn(
            'shrink-0 rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors whitespace-nowrap',
            activeId === sec.id
              ? 'bg-info/10 text-info shadow-none'
              : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground dark:text-muted-foreground dark:hover:bg-muted/50 dark:hover:text-foreground',
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
    queryFn: async () => {
      try {
        return await datasetApi.listProfileScanRuns(datasetId!, { skip: 0, limit: 20 })
      } catch {
        return { total: 0, items: [] }
      }
    },
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
    toast.error(formatApiError(firstError, '加载数据画像失败'))
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

  return (
    <AppFrame>
      <PageScaffold
        title="数据画像"
        showHeader={false}
        size="full"
        density="system-dense"
        bodyGutter="dense"
        bodyClassName="h-full overflow-hidden bg-[radial-gradient(circle_at_12%_0%,hsl(var(--info)/0.10),transparent_28%),linear-gradient(180deg,hsl(var(--background))_0%,hsl(var(--surface-2)/0.76)_44%,hsl(var(--background))_100%)] pb-3"
        bodyContainerClassName="h-full min-h-0 overflow-hidden"
        top={
          <div className={profileHeroCard}>
            <div className="relative flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 items-center gap-2.5">
                <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-info/10 text-info shadow-none">
                  <BarChart3 className="size-3.5" />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-[19px] font-semibold leading-6 tracking-[-0.02em] text-foreground dark:text-foreground">
                      数据画像
                    </h1>
                    <Badge variant="soft" className="h-5 border-info/30 bg-info/10 px-2 text-[10px] font-medium leading-none text-info">
                      PROFILE
                    </Badge>
                  </div>
                  <p className="max-w-4xl text-[12px] leading-5 text-muted-foreground">
                    数据集：<span className="font-semibold text-foreground dark:text-foreground">{dataset?.name || datasetId || '未选择'}</span>
                    <span className="mx-2 text-muted-foreground/60">·</span>
                    格式、长度、扫描件、PII、重复与切片指标的质量画像
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] leading-none text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <Database className="size-3.5 text-info" />
                      文档 <strong className="font-mono text-foreground dark:text-foreground">{summary?.total_documents ?? (isLoading ? '…' : 0)}</strong>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Cloud className="size-3.5 text-info" />
                      总大小 <strong className="font-mono text-foreground dark:text-foreground">{totalSizeLabel}</strong>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <FileSearch className="size-3.5 text-warning" />
                      扫描 PDF <strong className="font-mono text-foreground dark:text-foreground">{scannedPdfCount}</strong>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <BarChart3 className="size-3.5 text-destructive" />
                      问题 <strong className="font-mono text-foreground dark:text-foreground">{summary ? totalFindingCount : (isLoading ? '…' : 0)}</strong>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Sparkles className="size-3.5 text-success" />
                      更新时间 <strong className="font-mono text-foreground dark:text-foreground">{generatedAtLabel}</strong>
                    </span>
                  </div>
                </div>
              </div>
              <div className="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg border border-success/30 bg-success/5 px-3 text-[13px] font-medium text-success shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]">
                <span className={cn('size-2 rounded-full', scanRunning ? 'animate-pulse bg-info' : 'bg-success')} />
                {latestRunLabel}
              </div>
            </div>
          </div>
        }
        toolbar={
          <div className="flex w-full flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className={profileToolbarGroupClass}>
              <Button size="sm" variant="ghost" className={profileToolbarButtonClass} onClick={() => router.push('/datasets')}>
                <ArrowLeft className="w-4 h-4" />
                返回
              </Button>
              {datasetId ? (
                <Button size="sm" variant="ghost" className={profileToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/health`)}>
                  <Activity className="w-4 h-4" />
                  健康
                </Button>
              ) : null}
              {datasetId ? (
                <Button size="sm" variant="ghost" className={profileToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                  <Settings2 className="w-4 h-4" />
                  入库策略
                </Button>
              ) : null}
              {datasetId ? (
                <Button size="sm" variant="ghost" className={profileToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/tables`)}>
                  <Table2 className="w-4 h-4" />
                  表格 / TAG
                </Button>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Button
                size="sm"
                variant="outline"
                className={profileToolbarExportButtonClass}
                onClick={() => detachPromise(exportJson())}
                disabled={isExportingJson || !summary}
              >
                {isExportingJson ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
                导出 JSON
              </Button>
              <Button
                size="sm"
                className={profileToolbarPrimaryButtonClass}
                onClick={() => detachPromise(exportHtml())}
                disabled={isExportingHtml || !summary}
              >
                {isExportingHtml ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
                导出 HTML
              </Button>
            </div>
          </div>
        }
      >
        <div data-profile-scroll-container="true" className="h-full min-h-0 overflow-y-auto pr-1 no-scrollbar">
        <ProfileAnchorNav />
        <div className="space-y-3 pb-3">
          <div id="prof-overview">
          <Panel className={profilePanelClass}>
            <StatsGrid dense className="xl:grid-cols-5">
              <StatCard dense icon={FileSearch} label="文档总数" value={summary?.total_documents ?? (isLoading ? '…' : 0)} color="cyan" />
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
})()} color="teal" dense />
              <StatCard dense icon={Sparkles} label="P50 长度" value={summary?.length_percentiles?.p50 ?? (isLoading ? '…' : 0)} subValue="chars" color="blue" />
              <StatCard dense icon={Sparkles} label="P90 长度" value={summary?.length_percentiles?.p90 ?? (isLoading ? '…' : 0)} subValue="chars" color="blue" />
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
})()} color="orange" dense />
            </StatsGrid>
          </Panel>
          </div>

          <div id="prof-distribution" className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Panel className={profilePanelClass}>
              <ProfileCardHeader
                title="格式分布"
                caption="文件类型占比"
                meta={summary?.generated_at ? formatDate(summary.generated_at) : ''}
              />
              <SafeResponsiveChart {...profileChartProps}>
                  <PieChart>
                    <Tooltip />
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

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="状态分布" caption="按文档处理状态聚合" />
              <SafeResponsiveChart {...profileChartProps}>
                  <BarChart data={statusChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </SafeResponsiveChart>
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="长度分布" caption="按字符长度区间统计" />
              <SafeResponsiveChart {...profileChartProps}>
                  <BarChart data={lengthHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </SafeResponsiveChart>
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="PDF 扫描占比" caption="扫描件、文本型与未知类型" />
              <SafeResponsiveChart {...profileChartProps}>
                  <PieChart>
                    <Tooltip />
                    <Pie data={pdfScanData} dataKey="value" nameKey="name" innerRadius={42} outerRadius={72} paddingAngle={2} />
                  </PieChart>
                </SafeResponsiveChart>
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="文件大小分布" caption="用于发现异常大文件或碎片文件" />
              <SafeResponsiveChart {...profileChartProps}>
                  <BarChart data={fileSizeHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="hsl(var(--chart-3))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </SafeResponsiveChart>
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="页数分布" caption="PDF / Office 页数画像" />
              {pageCountHistogramData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={pageCountHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-7))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="切片数量分布" caption="每个文档生成的切片数量" />
              {chunkCountHistogramData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={chunkCountHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-4))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="平均切片长度" caption="按文档聚合的平均切片长度" />
              {avgChunkCharsHistogramData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={avgChunkCharsHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="切片长度分布" caption="按切片粒度统计字符长度" />
              {chunkLengthHistogramData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={chunkLengthHistogramData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-6))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>

            <Panel className={cn(profilePanelClass, 'lg:col-span-2 p-3')}>
              <div className="mb-3 flex items-start justify-between gap-4">
                <div>
                  <div className={profileSectionTitleClass}>切块目标检查</div>
                  <div className={profileSectionCaptionClass}>
                    检查 token 分布、正文覆盖和重叠成本；缺统计只提示补采集，不代表入库失败。
                  </div>
                </div>
                <Badge variant="outline" className="shrink-0 border-border bg-card/70 px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
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
                          <Badge variant={targetBadgeVariant(String(t.status || ''))} className="h-5 shrink-0 px-1.5 text-[10px] font-mono uppercase">
                            {String(t.status || '')}
                          </Badge>
                        </div>
                        {t.message ? (
                          <div className="mt-1 line-clamp-2 pl-2 text-[11px] leading-4 text-muted-foreground/65 text-pretty">
                            {String(t.message)}
                          </div>
                        ) : null}
                      </div>

                      {t.suggestions.length ? (
                        <div className="mt-2 rounded-lg bg-muted/40 px-2.5 py-1.5 text-[11px] leading-4 text-muted-foreground/70 dark:bg-muted/30">
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
                <div className="py-8 text-center text-[11px] text-muted-foreground/60">
                  暂无数据（可运行深度扫描补齐 chunk token/coverage 等指标）
                </div>
              )}
            </Panel>

            <Panel className={profilePanelClass}>
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
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="解析路由" caption="解析后端、耗时和后备路径概览" />

              {parsingBackendChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={parsingBackendChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}

              <div className="mt-2 grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-[10px] text-muted-foreground">覆盖文档</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.docs_with_provenance || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-[10px] text-muted-foreground">后备解析</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.fallback_docs || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-[10px] text-muted-foreground">P50 耗时 ms</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.elapsed_ms_percentiles?.p50 || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-[10px] text-muted-foreground">P90 耗时 ms</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {Number(summary?.parsing_provenance?.elapsed_ms_percentiles?.p90 || 0)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-[10px] text-muted-foreground">平均解析分</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {averageParseQuality == null ? '-' : averageParseQuality.toFixed(3)}
                  </div>
                </div>
                <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                  <div className="text-[10px] text-muted-foreground">后备率</div>
                  <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                    {fallbackRate == null ? '-' : `${(fallbackRate * 100).toFixed(1)}%`}
                  </div>
                </div>
              </div>
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="语言分布" caption="中文、英文、混合和未知语言占比" />
              {languageMixChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <PieChart>
                      <Tooltip />
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

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="目录分布" caption="点击柱子查看对应文件" />
              {directoryChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={directoryChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} interval={0} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
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
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="质量桶分布" caption="点击柱子查看对应文件" />
              {qualityBucketChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={qualityBucketChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} interval={0} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
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

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="PII 命中" caption="手机号、邮箱、身份证等敏感信息次数" />
              {piiChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={piiChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-4))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>

            <Panel className={profilePanelClass}>
              <ProfileCardHeader title="密钥 / Token 命中" caption="疑似密钥、Token 和凭证命中次数" />
              {secretsChartData.length ? (
                <SafeResponsiveChart {...profileChartProps}>
                    <BarChart data={secretsChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-6))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className={profileEmptyChartClass}>暂无数据</div>
              )}
            </Panel>
          </div>

          <div id="prof-findings">
          <Panel className={cn(profilePanelClass, 'p-3')}>
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <div className={profileSectionTitleClass}>问题清单</div>
                <div className={profileSectionCaptionClass}>
                  只突出有命中的可操作项；点击问题行查看文件列表。
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={totalFindingCount > 0 ? 'soft' : 'outline'} className="h-5 px-1.5 text-[10px] font-mono">
                  命中 {totalFindingCount}
                </Badge>
                <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-mono text-muted-foreground">
                  已检查 {clearFindings.length}
                </Badge>
              </div>
            </div>

            {activeFindings.length ? (
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {activeFindings.map((f) => (
                  <button
                    key={f.key}
                    type="button"
                    className={cn(
                      'relative overflow-hidden rounded-xl border bg-card/60 px-2.5 py-2 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] transition-colors hover:bg-card/90 dark:bg-muted/20 md:grid-cols-[minmax(0,1fr)_auto]',
                      String(f.severity || '').toLowerCase() === 'error'
                        ? 'border-destructive/30'
                        : String(f.severity || '').toLowerCase() === 'warning'
                          ? 'border-warning/30'
                          : 'border-border/60 dark:border-border/60',
                      'focus:outline-none focus:ring-2 focus:ring-primary/30'
                    )}
                    onClick={() => detachPromise(openFinding(f))}
                  >
                    <div
                      className={cn(
                        'absolute inset-y-2 left-0 w-1 rounded-r-full',
                        String(f.severity || '').toLowerCase() === 'error'
                          ? 'bg-destructive'
                          : String(f.severity || '').toLowerCase() === 'warning'
                            ? 'bg-warning'
                            : 'bg-info/30',
                      )}
                    />
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-1.5 pl-2">
                        <div className="truncate text-[12px] font-semibold text-foreground/85">{f.label}</div>
                        <Badge variant={findingBadgeVariant(f.severity)} className="h-5 shrink-0 px-1.5 text-[10px] font-mono">
                          ×{f.count}
                        </Badge>
                      </div>
                      {f.description ? (
                        <div className="mt-1 line-clamp-2 pl-2 text-[11px] leading-4 text-muted-foreground/65">{f.description}</div>
                      ) : null}
                    </div>
                    <div className="mt-2 pl-2 text-[11px] font-medium text-info">查看文件</div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-success/20 bg-success/5 px-2 py-1.5 text-[11px] leading-4 text-success">
                当前没有命中的可操作问题，下面仅保留已检查项摘要。
              </div>
            )}

            {clearFindings.length ? (
              <div className="mt-3 rounded-xl border border-border/40 bg-muted/40 px-2 py-1.5 dark:bg-muted/20">
                <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground/55">
                  已检查未命中
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {clearFindings.slice(0, 10).map((f) => (
                    <span
                      key={f.key}
                      className="rounded-full border border-border/45 bg-card/60 px-2 py-0.5 text-[10px] leading-4 text-muted-foreground/65 dark:bg-card/50"
                    >
                      {f.label}
                    </span>
                  ))}
                  {clearFindings.length > 10 ? (
                    <span className="rounded-full px-2 py-0.5 text-[10px] leading-4 text-muted-foreground/45">
                      +{clearFindings.length - 10}
                    </span>
                  ) : null}
                  </div>
              </div>
            ) : null}
          </Panel>
          </div>

          <div id="prof-scan">
          <Panel className={cn(profilePanelClass, 'p-3')}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-[13px] font-semibold text-foreground/85">
                  深度扫描
                  {latestRunStatus ? (
                    <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-mono">
                      {String(latestRunStatus)}
                    </Badge>
                  ) : null}
                </div>
                <div className={profileSectionCaptionClass}>
                  补齐 PDF、文本、切片和哈希指标，供画像、问题清单和对比使用。
                </div>
              </div>

              <Button size="sm" className="gap-2" onClick={() => detachPromise(startDeepScan())} disabled={scanRunning}>
                {scanRunning ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Sparkles className="w-4 h-4" />}
                启动
              </Button>
            </div>

            <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-5">
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/50 bg-card/55 px-2.5 py-2 dark:bg-card/40">
                <Label className="text-xs text-foreground/80">PDF 指标</Label>
                <Switch
                  checked={!!scanConfig.backfill_pdf_quality}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_pdf_quality: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/50 bg-card/55 px-2.5 py-2 dark:bg-card/40">
                <Label className="text-xs text-foreground/80">文本质量</Label>
                <Switch
                  checked={!!scanConfig.backfill_text_quality}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_text_quality: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/50 bg-card/55 px-2.5 py-2 dark:bg-card/40">
                <Label className="text-xs text-foreground/80">切片分布</Label>
                <Switch
                  checked={!!scanConfig.backfill_chunk_stats}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, backfill_chunk_stats: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/50 bg-card/55 px-2.5 py-2 dark:bg-card/40">
                <Label className="text-xs text-foreground/80">文件哈希</Label>
                <Switch
                  checked={!!scanConfig.compute_file_hash}
                  onCheckedChange={(v) => setScanConfig((prev) => ({ ...prev, compute_file_hash: !!v }))}
                />
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/50 bg-card/55 px-2.5 py-2 dark:bg-card/40">
                <Label className="text-xs text-foreground/80">最大文档数</Label>
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
                  className="h-7 w-20 font-mono text-xs"
                />
              </div>
            </div>

            <div className="mt-2 flex items-center justify-between gap-4 rounded-lg bg-muted/40 px-2.5 py-1.5 dark:bg-muted/20">
              <div className="text-[11px] text-muted-foreground/65">
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
          <Panel className={cn(profilePanelClass, 'p-3')}>
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
              <div className="rounded-xl border border-border/45 bg-muted/40 px-2 py-1.5 text-[11px] text-muted-foreground/60 dark:bg-muted/20">
                暂无扫描记录。启动一次深度扫描后，这里会显示快照和可对比版本。
              </div>
            )}

            <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_280px]">
              <div className="rounded-xl border border-border/50 bg-card/45 p-3 dark:bg-card/40">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-[13px] font-semibold text-foreground/85">快照对比</div>
                  <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-mono text-muted-foreground">
                    已完成 {completedRuns.length}
                  </Badge>
                </div>

                {completedRuns.length >= 2 ? (
                  <>
                    <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">基准快照</Label>
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
                        <Label className="text-[11px] text-muted-foreground">对比快照</Label>
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
                        <div className="rounded-lg border border-border/45 bg-muted/40 p-2 dark:bg-muted/20">
                          <div className="text-[10px] text-muted-foreground">文档数 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.docs >= 0 ? `+${compareDelta.docs}` : String(compareDelta.docs)}</div>
                        </div>
                        <div className="rounded-lg border border-border/45 bg-muted/40 p-2 dark:bg-muted/20">
                          <div className="text-[10px] text-muted-foreground">总大小 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">
                            {compareDelta.bytes >= 0 ? '+' : '-'}
                            {formatFileSize(Math.abs(compareDelta.bytes))}
                          </div>
                        </div>
                        <div className="rounded-lg border border-border/45 bg-muted/40 p-2 dark:bg-muted/20">
                          <div className="text-[10px] text-muted-foreground">P90 长度 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.p90 >= 0 ? `+${compareDelta.p90}` : String(compareDelta.p90)}</div>
                        </div>
                        <div className="rounded-lg border border-border/45 bg-muted/40 p-2 dark:bg-muted/20">
                          <div className="text-[10px] text-muted-foreground">扫描 PDF Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.scanned >= 0 ? `+${compareDelta.scanned}` : String(compareDelta.scanned)}</div>
                        </div>
                        <div className="rounded-lg border border-border/45 bg-muted/40 p-2 dark:bg-muted/20">
                          <div className="text-[10px] text-muted-foreground">PII 命中 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.pii >= 0 ? `+${compareDelta.pii}` : String(compareDelta.pii)}</div>
                        </div>
                        <div className="rounded-lg border border-border/45 bg-muted/40 p-2 dark:bg-muted/20">
                          <div className="text-[10px] text-muted-foreground">Secrets 命中 Δ</div>
                          <div className="mt-0.5 font-mono text-xs font-semibold">{compareDelta.secrets >= 0 ? `+${compareDelta.secrets}` : String(compareDelta.secrets)}</div>
                        </div>
                      </div>
                    ) : (
                    <div className="mt-3 rounded-lg bg-muted/40 px-2.5 py-1.5 text-[11px] text-muted-foreground/60 dark:bg-muted/20">
                        请选择两个已完成扫描记录。
                      </div>
                    )}
                  </>
                ) : (
                  <div className="rounded-lg border border-dashed border-border/55 bg-muted/40 px-3 py-2 text-[11px] leading-4 text-muted-foreground/65 dark:bg-muted/20">
                    <div className="font-medium text-foreground/75">暂无可对比快照</div>
                    <div className="mt-0.5">
                      至少需要 2 次已完成深度扫描；当前 {completedRuns.length} 次。完成后这里会出现基准/对比快照下拉。
                    </div>
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-border/50 bg-card/45 p-3 dark:bg-card/40">
                <div className="text-[13px] font-semibold text-foreground/85">离线报告</div>
                <div className="text-[11px] leading-4 text-muted-foreground/65">
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
          </div>
        </div>
        </div>

        <Dialog open={findingOpen} onOpenChange={(open) => {
           setFindingOpen(open)
           if (!open) {
             setSelectedFinding(null)
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
      </PageScaffold>
    </AppFrame>
  )
}
