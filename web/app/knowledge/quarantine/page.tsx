'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowRight,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Download,
  Eye,
  Layers,
  LayoutList,
  MoreHorizontal,
  Play,
  RefreshCw,
  RotateCcw,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import {
  KNOWLEDGE_OPS_HERO_PANEL_CLASS,
  KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS,
} from '@/components/ui/knowledge-ops-hero'
import { Button } from '@/components/ui/button'
import { getDocumentKind } from '@/components/ingestion/monitor-utils'
import { Input } from '@/components/ui/input'
import { SearchInput } from '@/components/ui/search-input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { cn, detachPromise, formatDate, formatFileSize } from '@/lib/utils'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { captureApiError } from '@/lib/api-error-reporting'
import { useDatasets } from '@/hooks/use-datasets'
import type { Document, DocumentPipelineOptions } from '@/types'
import { useDocumentView } from '@/store/document-view'
import { usePathname, useRouter } from '@/i18n/navigation'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import { FileKindGlyph } from './components/file-kind-glyph'
import { QuarantineEmptyState } from './components/quarantine-empty-state'
import { QuarantineReviewDrawer } from './components/quarantine-review-drawer'
import { StatusPill } from './components/status-pill'
import {
  DonutSummaryCard,
  QuickActionCard,
  SummaryStatCard,
} from './components/summary-cards'
import {
  QUARANTINE_BACKGROUND_CLASS,
  QUARANTINE_GRID_OVERLAY_CLASS,
  QUARANTINE_PAGE_SIZE,
} from './constants'
import { buildDemoQuarantineDocuments } from './demo-quarantine'
import {
  createReviewMetadataPatch,
  downloadTextFile,
  extractTuningOverrides,
  getDropReasons,
  getQuarantineSeverity,
  getQuarantineSource,
  getSeverityBarClassName,
  getSeverityClassName,
  isReviewed,
  reasonLabel,
} from './quarantine-signals'
import type {
  ActingState,
  JsonRecord,
  QuarantineSeverity,
  QueueSyncStatus,
  ReviewState,
} from './types'

function finiteNumberOrUndefined(value: string): number | undefined {
  if (value === '') return undefined
  const numericValue = Number(value)
  return Number.isFinite(numericValue) ? numericValue : undefined
}

function getQuarantineFooterMessage({
  hasActiveFilters,
  filteredCount,
  documentCount,
  autoRefresh,
}: {
  hasActiveFilters: boolean
  filteredCount: number
  documentCount: number
  autoRefresh: boolean
}): string {
  if (hasActiveFilters) {
    return `当前筛出 ${filteredCount} / ${documentCount} 条`
  }
  if (autoRefresh) return '自动刷新已开启，每 5 秒轮询一次'
  return '自动刷新已关闭'
}

export default function QuarantineQueuePage() {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const demoMode =
    /(^|\/)demo(\/|$)/.test(pathname) && searchParams.get('demo') === '1'
  const { openDocument } = useDocumentView()
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedReason, setSelectedReason] = useState('all')
  const [selectedDataset, setSelectedDataset] = useState(
    searchParams.get('datasetId') || 'all'
  )
  const [selectedSource, setSelectedSource] = useState('all')
  const [selectedSeverity, setSelectedSeverity] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [reviewState, setReviewState] = useState<
    'all' | 'pending' | 'reviewed'
  >('all')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reviewDrawerOpen, setReviewDrawerOpen] = useState(false)
  const [acting, setActing] = useState<ActingState>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailDocumentId, setDetailDocumentId] = useState<string | null>(null)
  const [lastQueueSync, setLastQueueSync] = useState<QueueSyncStatus | null>(null)

  const [tuneOpen, setTuneOpen] = useState(false)
  const [tuneTarget, setTuneTarget] = useState<Document | null>(null)
  const [tunePatch, setTunePatch] = useState<DocumentPipelineOptions>({})
  const { datasets, isLoading: datasetsLoading } = useDatasets()
  const selectedDatasetId = selectedDataset === 'all' ? null : selectedDataset

  const { data, error: queueError, isFetching, refetch } = useQuery({
    queryKey: ['quarantine-documents', 'quarantined', selectedDatasetId],
    queryFn: ({ signal }) =>
      documentApi.list(
        {
          limit: 200,
          status: 'quarantined',
          dataset_id: selectedDatasetId ?? undefined,
        },
        { signal }
      ),
    staleTime: 3_000,
    enabled: !demoMode,
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  const {
    data: failedData,
    error: failedQueueError,
    isFetching: isFetchingFailed,
    refetch: refetchFailed,
  } = useQuery({
    queryKey: ['quarantine-documents', 'failed', selectedDatasetId],
    queryFn: ({ signal }) =>
      documentApi.list(
        {
          limit: 200,
          status: 'failed',
          dataset_id: selectedDatasetId ?? undefined,
        },
        { signal }
      ),
    staleTime: 3_000,
    enabled: !demoMode,
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  const documents = useMemo(
    () =>
      demoMode
        ? buildDemoQuarantineDocuments()
        : [...(data?.items || []), ...(failedData?.items || [])],
    [data, demoMode, failedData]
  )
  const queueFetching = isFetching || isFetchingFailed
  const queueErrorMessage = useMemo(() => {
    const err = queueError || failedQueueError
    return err ? formatApiError(err, '隔离队列同步失败') : null
  }, [failedQueueError, queueError])
  const refreshQueue = useCallback(
    async ({ notify = false }: { notify?: boolean } = {}) => {
      try {
        const [quarantineResult, failedResult] = await Promise.all([
          refetch(),
          refetchFailed(),
        ])
        const err = quarantineResult.error || failedResult.error
        if (err) {
          const info = captureApiError(err, '隔离队列同步失败', {
            level: 'warning',
            tags: { page: 'knowledge-quarantine', action: 'manual-sync' },
          })
          setLastQueueSync({
            type: 'error',
            message: info.message,
            at: new Date().toISOString(),
          })
          if (notify) toast.error(info.message)
          return false
        }

        const quarantinedTotal = quarantineResult.data?.total ?? data?.total ?? 0
        const failedTotal = failedResult.data?.total ?? failedData?.total ?? 0
        const message =
          quarantinedTotal + failedTotal > 0
            ? `同步完成：待审核 ${quarantinedTotal} 条，失败 ${failedTotal} 条`
            : '同步完成：当前没有隔离或失败记录'
        setLastQueueSync({
          type: 'success',
          message,
          at: new Date().toISOString(),
        })
        if (notify) toast.success(message)
        return true
      } catch (err) {
        const info = captureApiError(err, '隔离队列同步失败', {
          level: 'warning',
          tags: { page: 'knowledge-quarantine', action: 'manual-sync' },
        })
        setLastQueueSync({
          type: 'error',
          message: info.message,
          at: new Date().toISOString(),
        })
        if (notify) toast.error(info.message)
        return false
      }
    },
    [data?.total, failedData?.total, refetch, refetchFailed]
  )

  useEffect(() => {
    setSelectedDataset(searchParams.get('datasetId') || 'all')
  }, [searchParams])

  const handleDatasetScopeChange = useCallback(
    (value: string) => {
      setSelectedDataset(value)
      const params = new URLSearchParams(searchParams.toString())
      if (value === 'all') {
        params.delete('datasetId')
      } else {
        params.set('datasetId', value)
      }
      const query = params.toString()
      router.replace(query ? `${pathname}?${query}` : pathname)
    },
    [pathname, router, searchParams]
  )

  const reasonCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const doc of documents) {
      const keys = getDropReasons(doc)
      for (const key of keys) {
        counts[key] = (counts[key] || 0) + 1
      }
    }
    return counts
  }, [documents])

  const sortedReasons = useMemo(() => {
    return Object.entries(reasonCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([reason]) => reason)
  }, [reasonCounts])

  const datasetLabelById = useMemo(() => {
    const map: Record<string, string> = {}
    for (const dataset of datasets) {
      map[dataset.id] = dataset.name
    }
    return map
  }, [datasets])

  const datasetOptions = useMemo(() => {
    const seen = new Set<string>()
    const options = datasets.map((dataset) => {
      seen.add(dataset.id)
      return { id: dataset.id, label: dataset.name }
    })
    for (const doc of documents) {
      if (!doc.dataset_id || seen.has(doc.dataset_id)) continue
      seen.add(doc.dataset_id)
      options.push({ id: doc.dataset_id, label: doc.dataset_id })
    }
    return options.sort((a, b) => a.label.localeCompare(b.label))
  }, [datasets, documents])

  const sourceOptions = useMemo(
    () =>
      Array.from(
        new Set(documents.map((doc) => getQuarantineSource(doc)))
      ).sort((a, b) => a.localeCompare(b)),
    [documents]
  )

  const severityCounts = useMemo(() => {
    return documents.reduce<Record<QuarantineSeverity, number>>(
      (acc, doc) => {
        const severity = getQuarantineSeverity(doc)
        acc[severity] += 1
        return acc
      },
      { 高: 0, 中: 0, 低: 0 }
    )
  }, [documents])

  const sourceCounts = useMemo(() => {
    return documents.reduce<Record<string, number>>((acc, doc) => {
      const source = getQuarantineSource(doc)
      acc[source] = (acc[source] || 0) + 1
      return acc
    }, {})
  }, [documents])

  const stats = useMemo(() => {
    const total = documents.length
    const reviewed = documents.filter(isReviewed).length
    const highRisk = documents.filter(
      (doc) => getQuarantineSeverity(doc) === '高'
    ).length
    return {
      total,
      reviewed,
      unreviewed: Math.max(0, total - reviewed),
      highRisk,
    }
  }, [documents])

  const reasonTopItems = useMemo(
    () =>
      Object.entries(reasonCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([reason, count]) => ({
          label: `R${Math.max(1, sortedReasons.indexOf(reason) + 1)} ${reasonLabel(reason)}`,
          value: count,
          hint: documents.length
            ? `(${((count / documents.length) * 100).toFixed(1)}%)`
            : '(0%)',
        })),
    [documents.length, reasonCounts, sortedReasons]
  )

  const severityItems = useMemo(
    () => [
      { label: '高', value: severityCounts['高'] },
      { label: '中', value: severityCounts['中'] },
      { label: '低', value: severityCounts['低'] },
    ],
    [severityCounts]
  )

  const sourceItems = useMemo(
    () =>
      Object.entries(sourceCounts)
        .sort((a, b) => b[1] - a[1])
        .map(([label, value]) => ({ label, value })),
    [sourceCounts]
  )

  const filtered = useMemo(() => {
    let out = documents
    if (reviewState === 'pending') out = out.filter((d) => !isReviewed(d))
    if (reviewState === 'reviewed') out = out.filter((d) => isReviewed(d))
    if (selectedReason !== 'all')
      out = out.filter((d) => getDropReasons(d).includes(selectedReason))
    if (selectedDataset !== 'all')
      out = out.filter((d) => d.dataset_id === selectedDataset)
    if (selectedSource !== 'all')
      out = out.filter((d) => getQuarantineSource(d) === selectedSource)
    if (selectedSeverity !== 'all')
      out = out.filter((d) => getQuarantineSeverity(d) === selectedSeverity)
    if (dateFrom)
      out = out.filter(
        (d) =>
          new Date(String(d.updated_at || d.created_at || '')).getTime() >=
          new Date(`${dateFrom}T00:00:00`).getTime()
      )
    if (dateTo)
      out = out.filter(
        (d) =>
          new Date(String(d.updated_at || d.created_at || '')).getTime() <=
          new Date(`${dateTo}T23:59:59`).getTime()
      )

    const q = search.trim().toLowerCase()
    if (q) {
      out = out.filter((d) => {
        const filename = (d.filename || '').toLowerCase()
        const id = d.id.toLowerCase()
        const dataset = (d.dataset_id || '').toLowerCase()
        const source = getQuarantineSource(d).toLowerCase()
        const severity = getQuarantineSeverity(d).toLowerCase()
        const reasons = getDropReasons(d)
          .flatMap((reason) => [reason, reasonLabel(reason)])
          .join(' ')
          .toLowerCase()

        return (
          filename.includes(q) ||
          id.includes(q) ||
          dataset.includes(q) ||
          reasons.includes(q) ||
          source.includes(q) ||
          severity.includes(q)
        )
      })
    }

    return out
  }, [
    dateFrom,
    dateTo,
    documents,
    reviewState,
    search,
    selectedDataset,
    selectedReason,
    selectedSeverity,
    selectedSource,
  ])

  const listSummary = useMemo(() => {
    if (!documents.length) return null

    const hasSearch = search.trim().length > 0
    const hasReasonFilter = selectedReason !== 'all'
    const hasDatasetFilter = selectedDataset !== 'all'
    const hasSourceFilter = selectedSource !== 'all'
    const hasSeverityFilter = selectedSeverity !== 'all'
    const hasReviewFilter = reviewState !== 'all'
    const hasDateFilter = Boolean(dateFrom || dateTo)

    if (
      hasSearch ||
      hasReasonFilter ||
      hasDatasetFilter ||
      hasSourceFilter ||
      hasSeverityFilter ||
      hasReviewFilter ||
      hasDateFilter
    ) {
      return `筛出 ${filtered.length} / ${documents.length}`
    }

    return `共 ${filtered.length} 条`
  }, [
    dateFrom,
    dateTo,
    documents.length,
    filtered.length,
    reviewState,
    search,
    selectedDataset,
    selectedReason,
    selectedSeverity,
    selectedSource,
  ])

  const hasActiveFilters =
    Boolean(search.trim()) ||
    selectedReason !== 'all' ||
    selectedDataset !== 'all' ||
    selectedSource !== 'all' ||
    selectedSeverity !== 'all' ||
    reviewState !== 'all' ||
    Boolean(dateFrom || dateTo)

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(filtered.length / QUARANTINE_PAGE_SIZE)),
    [filtered.length]
  )
  // Clamp during render instead of via an effect: when filters shrink the
  // result set, safePage stays in range without an extra render pass.
  const safePage = Math.min(page, totalPages)
  const paginated = useMemo(
    () =>
      filtered.slice(
        (safePage - 1) * QUARANTINE_PAGE_SIZE,
        safePage * QUARANTINE_PAGE_SIZE
      ),
    [filtered, safePage]
  )

  const selected = useMemo(() => {
    if (!selectedId) return null
    return documents.find((d) => d.id === selectedId) || null
  }, [documents, selectedId])

  useEffect(() => {
    if (!selectedId) return
    if (documents.some((doc) => doc.id === selectedId)) return
    setSelectedId(null)
    setReviewDrawerOpen(false)
  }, [documents, selectedId])

  useEffect(() => {
    if (!filtered.length && reviewDrawerOpen) {
      setSelectedId(null)
      setReviewDrawerOpen(false)
    }
  }, [filtered, reviewDrawerOpen])

  useEffect(() => {
    setPage(1)
  }, [
    search,
    selectedReason,
    selectedDataset,
    selectedSource,
    selectedSeverity,
    dateFrom,
    dateTo,
    reviewState,
  ])

  const resetFilters = useCallback(() => {
    setSearch('')
    setSelectedReason('all')
    handleDatasetScopeChange('all')
    setSelectedSource('all')
    setSelectedSeverity('all')
    setDateFrom('')
    setDateTo('')
    setReviewState('all')
  }, [handleDatasetScopeChange])

  const markReviewed = useCallback(
    async (docId: string, extra?: JsonRecord) => {
      const patch = createReviewMetadataPatch(extra)
      await documentApi.patchUserMetadata(docId, { patch, replace: false })
    },
    []
  )

  const buildRecommendedPatch = useCallback(
    (doc: Document): DocumentPipelineOptions => {
      const reasons = new Set(getDropReasons(doc))
      const patch: DocumentPipelineOptions = {}
      if (reasons.has('outline_only'))
        patch.governance_drop_outline_only = false
      if (reasons.has('low_density')) patch.governance_drop_low_density = false
      return patch
    },
    []
  )

  const handleRetry = useCallback(
    async (doc: Document) => {
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不执行真实重试')
        return
      }
      setActing({ id: doc.id, action: 'retry' })
      try {
        await documentApi.retry(doc.id)
        await markReviewed(doc.id, { quarantine_action: 'retry' })
        toast.success('已触发重新入库')
        await refreshQueue()
      } catch (err: unknown) {
        toast.error(formatApiError(err, '重试失败'))
      } finally {
        setActing(null)
      }
    },
    [demoMode, markReviewed, refreshQueue]
  )

  const handleRelease = useCallback(
    async (doc: Document) => {
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不执行真实放行')
        return
      }
      setActing({ id: doc.id, action: 'release' })
      try {
        const patch = buildRecommendedPatch(doc)
        if (Object.keys(patch).length) {
          await documentApi.patchPipeline(doc.id, { patch, replace: false })
        }
        await documentApi.retry(doc.id)
        await markReviewed(doc.id, {
          quarantine_action: 'release_retry',
          quarantine_reason: getDropReasons(doc).join(','),
        })
        toast.success('已放行并重试')
        await refreshQueue()
      } catch (err: unknown) {
        toast.error(formatApiError(err, '放行失败'))
      } finally {
        setActing(null)
      }
    },
    [buildRecommendedPatch, demoMode, markReviewed, refreshQueue]
  )

  const handleDelete = useCallback(
    async (doc: Document) => {
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不执行真实删除')
        return
      }
      setActing({ id: doc.id, action: 'delete' })
      try {
        await documentApi.delete(doc.id)
        toast.success('已删除文档')
        if (selectedId === doc.id) {
          setSelectedId(null)
          setReviewDrawerOpen(false)
        }
        await refreshQueue()
      } catch (err: unknown) {
        toast.error(formatApiError(err, '删除失败'))
      } finally {
        setActing(null)
      }
    },
    [demoMode, refreshQueue, selectedId]
  )

  const handleMarkReviewedOnly = useCallback(
    async (doc: Document) => {
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不写入真实审核状态')
        return
      }
      setActing({ id: doc.id, action: 'review' })
      try {
        await markReviewed(doc.id, { quarantine_action: 'reviewed' })
        toast.success('已标记为已处理')
        await refreshQueue()
      } catch (err: unknown) {
        toast.error(formatApiError(err, '标记失败'))
      } finally {
        setActing(null)
      }
    },
    [demoMode, markReviewed, refreshQueue]
  )

  const openTuneDialog = useCallback(
    (doc: Document) => {
      const current = extractTuningOverrides(doc)
      const recommended = buildRecommendedPatch(doc)
      setTuneTarget(doc)
      setTunePatch({ ...current, ...recommended })
      setTuneOpen(true)
    },
    [buildRecommendedPatch]
  )

  const saveTune = useCallback(
    async (opts: { retryAfterSave: boolean }) => {
      if (!tuneTarget) return
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不写入真实规则配置')
        setTuneOpen(false)
        return
      }
      const doc = tuneTarget
      setActing({ id: doc.id, action: 'tune' })
      try {
        await documentApi.patchPipeline(doc.id, {
          patch: tunePatch,
          replace: false,
        })
        if (opts.retryAfterSave) {
          await documentApi.retry(doc.id)
          await markReviewed(doc.id, { quarantine_action: 'tune_retry' })
          toast.success('已保存配置并重试')
        } else {
          toast.success('已保存配置')
        }
        setTuneOpen(false)
        await refreshQueue()
      } catch (err: unknown) {
        toast.error(formatApiError(err, '保存失败'))
      } finally {
        setActing(null)
      }
    },
    [demoMode, markReviewed, refreshQueue, tunePatch, tuneTarget]
  )

  const handleExportFiltered = useCallback(() => {
    const payload = filtered.map((doc) => ({
      id: doc.id,
      filename: doc.filename,
      dataset_id: doc.dataset_id,
      status: doc.status,
      source: getQuarantineSource(doc),
      severity: getQuarantineSeverity(doc),
      reasons: getDropReasons(doc),
      updated_at: doc.updated_at,
    }))
    downloadTextFile(
      'quarantine-review-samples.json',
      JSON.stringify(payload, null, 2),
      'application/json;charset=utf-8'
    )
    toast.success('已导出隔离样本')
  }, [filtered])

  const handleOpenFirstForReview = useCallback(() => {
    if (!filtered.length) {
      toast.error('当前没有可审核的隔离记录')
      return
    }
    setSelectedId(filtered[0].id)
    setReviewDrawerOpen(true)
  }, [filtered])

  const handleOpenRuleManager = useCallback(() => {
    const target = filtered[0] || documents[0]
    if (!target) {
      toast.error('当前没有可调参的隔离记录')
      return
    }
    openTuneDialog(target)
  }, [documents, filtered, openTuneDialog])

  const handleOpenReplayLog = useCallback(() => {
    const target = filtered[0] || documents[0]
    if (!target) {
      toast.error('当前没有可查看的回放记录')
      return
    }
    setDetailDocumentId(target.id)
    setDetailOpen(true)
  }, [documents, filtered])

  const handleExitDemoMode = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())
    params.delete('demo')
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname)
  }, [pathname, router, searchParams])

  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding>
      <div
        data-quarantine-page-root="true"
        className={cn(
          'relative h-full overflow-hidden',
          QUARANTINE_BACKGROUND_CLASS
        )}
      >
        <div className={QUARANTINE_GRID_OVERLAY_CLASS} aria-hidden="true" />
        <PageScaffold
          title="隔离审核中心"
          icon={ShieldAlert}
          showHeader={false}
          size="full"
          // max-w-[1520px]
          topClassName="relative z-10 w-full max-w-none px-4 pt-4 pb-2.5 md:px-5 lg:px-6"
          top={
          <div className="space-y-2.5">
            <div
              className={cn(
                'flex min-h-[95px] min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between',
                KNOWLEDGE_OPS_HERO_PANEL_CLASS
              )}
            >
              <div className="pointer-events-none absolute -right-10 -top-14 size-44 rounded-full bg-info/10 blur-3xl dark:bg-info/[0.08]" aria-hidden="true" />
              <div className="pointer-events-none absolute bottom-0 left-8 right-8 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--info)/0.28),transparent)]" aria-hidden="true" />
              <div className="relative flex min-w-0 items-center gap-3">
                <div className="relative flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-info/20 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.12))] text-info shadow-[inset_0_1px_0_hsl(var(--background)),0_18px_36px_-24px_hsl(var(--info)/0.9)]">
                  <span
                    className="absolute inset-x-2 top-1 h-px bg-card/70"
                    aria-hidden="true"
                  />
                  <PageTitleIcon name="quarantine-queue" className="size-9" />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-info/30 bg-info/5 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-info">
                      <Sparkles className="size-3" />
                      Quarantine Ops
                    </span>
                    <span className="inline-flex items-center rounded-full border border-warning/30 bg-warning/5 px-2.5 py-1 text-[10px] font-medium text-warning">
                      <ShieldCheck className="mr-1.5 size-3" />
                      样本复核与规则回放
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <h1 className="text-[26px] font-black tracking-[-0.025em] text-foreground">
                      <span className="bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent">
                        隔离审核中心
                      </span>
                    </h1>
                    <p className="text-[13px] leading-5 text-muted-foreground/85">
                      集中复核隔离样本，支持原文预览、规则调参与回放。
                    </p>
                  </div>
                </div>
              </div>
              <div className="relative flex min-w-0 flex-col gap-1.5 lg:min-w-[500px]">
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className={cn(KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS, 'py-1.5')}>
                    <span className="inline-flex items-center gap-1.5">
                      <span
                        className="size-1 rounded-full bg-info/70"
                        aria-hidden
                      />
                      队列
                    </span>
                    <span className="min-w-0 truncate font-medium text-foreground">
                      {stats.total} 条样本
                    </span>
                    <span className="h-3.5 w-px bg-border/70" />
                    <span>待审核</span>
                    <span className="font-mono tabular-nums text-foreground">
                      {stats.unreviewed}
                    </span>
                  </div>
                  <div className={cn(KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS, 'justify-between py-1.5')}>
                    <span className="inline-flex items-center gap-1.5">
                      <LayoutList className="size-3 text-info" />
                      发现
                    </span>
                    <ArrowRight className="size-3 shrink-0 text-muted-foreground/45" />
                    <span className="inline-flex items-center gap-1.5">
                      <Eye className="size-3 text-info" />
                      复核
                    </span>
                    <ArrowRight className="size-3 shrink-0 text-muted-foreground/45" />
                    <span className="inline-flex items-center gap-1.5">
                      <RotateCcw className="size-3 text-info" />
                      回放
                    </span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {demoMode ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 gap-2 rounded-xl border-primary/35 bg-background px-4 text-[12px] font-medium text-primary shadow-[0_16px_30px_-26px_hsl(var(--primary)/0.55)] hover:bg-primary/10"
                      onClick={handleExitDemoMode}
                    >
                      <Play className="size-4 fill-current" />
                      退出 Demo
                    </Button>
                  ) : null}
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-2 rounded-xl border-info/25 bg-info/[0.06] px-3.5 text-[12px] font-medium text-info shadow-[0_12px_24px_-22px_hsl(var(--info)/0.5)] hover:border-info/40 hover:bg-info/[0.12] hover:text-info"
                    onClick={() => {
                      if (demoMode) {
                        toast.success('Demo 数据已刷新')
                        return
                      }
                      detachPromise(refreshQueue({ notify: true }))
                    }}
                  >
                    <RefreshCw
                      className={cn(
                        'h-4 w-4',
                        queueFetching
                          ? 'animate-spin motion-reduce:animate-none'
                          : ''
                      )}
                    />
                    同步数据
                  </Button>

                  <div className="flex h-8 items-center gap-2 rounded-xl border border-transparent bg-background/70 px-2.5">
                    <span className="text-[11px] font-medium text-muted-foreground">
                      自动刷新
                    </span>
                    <Switch
                      checked={autoRefresh}
                      onCheckedChange={setAutoRefresh}
                      className="data-[state=checked]:bg-primary"
                    />
                  </div>
                </div>
              </div>
            </div>

            {queueErrorMessage ? (
              <div className="flex items-start gap-2 rounded-xl border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                <div className="min-w-0">
                  <div className="font-medium">隔离队列同步异常</div>
                  <div className="mt-0.5 break-words text-[11px] opacity-85">
                    {queueErrorMessage}
                  </div>
                </div>
              </div>
            ) : null}

            {lastQueueSync ? (
              <div
                className={cn(
                  'flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2 text-[11px]',
                  lastQueueSync.type === 'success'
                    ? 'border-success/20 bg-success/10 text-success'
                    : 'border-destructive/20 bg-destructive/10 text-destructive'
                )}
              >
                {lastQueueSync.type === 'success' ? (
                  <CheckCircle2 className="size-4 shrink-0" />
                ) : (
                  <AlertCircle className="size-4 shrink-0" />
                )}
                <span className="font-medium">
                  {lastQueueSync.type === 'success' ? '上次同步成功' : '上次同步异常'}
                </span>
                <span className="min-w-0 flex-1 truncate">{lastQueueSync.message}</span>
                <span className="font-mono text-[10px] opacity-70">
                  {formatDate(lastQueueSync.at)}
                </span>
              </div>
            ) : null}

            <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-4">
              <SummaryStatCard
                label="总隔离记录"
                value={stats.total}
                hint="较昨日 0"
                icon={LayoutList}
                tone="neutral"
              />
              <SummaryStatCard
                label="待审核"
                value={stats.unreviewed}
                hint="较昨日 0"
                icon={AlertCircle}
                tone="warning"
              />
              <SummaryStatCard
                label="已解决"
                value={stats.reviewed}
                hint="较昨日 0"
                icon={CheckCircle2}
                tone="success"
              />
              <SummaryStatCard
                label="规则集中率"
                value={stats.highRisk}
                hint={
                  stats.total
                    ? `占比 ${((stats.highRisk / Math.max(stats.total, 1)) * 100).toFixed(1)}%`
                    : '占比 0%'
                }
                icon={BarChart3}
                tone="info"
              />
            </div>
          </div>
        }
          bodyClassName="relative z-10 w-full max-w-none px-2 pb-5 md:px-3 xl:px-4"
        >
        <div className="space-y-4">
          <div
            aria-label="审计主画布"
            className="overflow-hidden rounded-[1.2rem] border border-border/60 bg-background/94 shadow-[0_20px_48px_-40px_rgba(15,23,42,0.18)] backdrop-blur-sm"
          >
            <div className="border-b border-border/60 px-4.5 py-3.5">
              <div className="flex flex-col gap-2.5 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-[0.98rem] font-semibold text-foreground">
                      异常隔离审查表
                    </div>
                    <span className="rounded-full border border-border/60 bg-muted/35 px-2 py-0.5 text-[10px] font-medium text-muted-foreground tabular-nums">
                      {listSummary || '当前空队列'}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
                    治理规则命中统计与待裁决样本分布，支持按条件筛选后快速复核。
                  </p>

                  {hasActiveFilters ? (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {reviewState === 'all' ? null : (
                        <Badge
                          variant="secondary"
                          className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                        >
                          {reviewState === 'pending' ? '仅待审核' : '仅已处理'}
                        </Badge>
                      )}
                      {selectedReason === 'all' ? null : (
                        <Badge
                          variant="secondary"
                          className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                        >
                          原因: {reasonLabel(selectedReason)}
                        </Badge>
                      )}
                      {selectedDataset === 'all' ? null : (
                        <Badge
                          variant="secondary"
                          className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                        >
                          数据集: {datasetLabelById[selectedDataset] || selectedDataset}
                        </Badge>
                      )}
                      {selectedSource === 'all' ? null : (
                        <Badge
                          variant="secondary"
                          className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                        >
                          来源: {selectedSource}
                        </Badge>
                      )}
                      {selectedSeverity === 'all' ? null : (
                        <Badge
                          variant="secondary"
                          className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                        >
                          疑似度: {selectedSeverity}
                        </Badge>
                      )}
                      {search.trim() ? (
                        <Badge
                          variant="secondary"
                          className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                        >
                          搜索: {search.trim()}
                        </Badge>
                      ) : null}
                      {dateFrom ? (
                        <Badge
                          variant="secondary"
                          className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                        >
                          开始: {dateFrom}
                        </Badge>
                      ) : null}
                      {dateTo ? (
                        <Badge
                          variant="secondary"
                          className="rounded-full px-2.5 py-1 text-[11px] font-medium"
                        >
                          结束: {dateTo}
                        </Badge>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                <div className="w-full xl:w-[18rem]">
                  <SearchInput
                    value={search}
                    onValueChange={setSearch}
                    placeholder="搜索文件名 / ID / 规则 / 原因"
                    containerClassName="w-full"
                    inputClassName="h-9 rounded-xl border-border/60 bg-background text-[11px] shadow-none"
                  />
                </div>
              </div>
            </div>

            <div className="border-b border-border/60 px-4.5 py-2">
              <div className="flex flex-col gap-2.5 xl:flex-row xl:items-center xl:justify-between">
                <div className="grid gap-2 md:grid-cols-3 xl:min-w-0 xl:flex-1 xl:grid-cols-7">
                  <div className="min-w-0">
                    <Select
                      value={reviewState}
                      onValueChange={(value) =>
                        setReviewState(value as ReviewState)
                      }
                    >
                      <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                        <SelectValue placeholder="处理状态" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部状态</SelectItem>
                        <SelectItem value="pending">仅待审核</SelectItem>
                        <SelectItem value="reviewed">仅已处理</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <Select
                      value={selectedReason}
                      onValueChange={setSelectedReason}
                    >
                      <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                        <SelectValue placeholder="隔离原因" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">所有原因</SelectItem>
                        {sortedReasons.map((reason) => (
                          <SelectItem key={reason} value={reason}>
                            {reasonLabel(reason)} ({reasonCounts[reason] || 0})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <Select
                      value={selectedSource}
                      onValueChange={setSelectedSource}
                    >
                      <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                        <SelectValue placeholder="来源" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部来源</SelectItem>
                        {sourceOptions.map((source) => (
                          <SelectItem key={source} value={source}>
                            {source}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <Select
                      value={selectedSeverity}
                      onValueChange={setSelectedSeverity}
                    >
                      <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                        <SelectValue placeholder="疑似度" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部疑似度</SelectItem>
                        <SelectItem value="高">高</SelectItem>
                        <SelectItem value="中">中</SelectItem>
                        <SelectItem value="低">低</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <Select
                      value={selectedDataset}
                      onValueChange={handleDatasetScopeChange}
                    >
                      <SelectTrigger className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none">
                        <SelectValue placeholder="数据集" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">
                          {datasetsLoading ? '加载数据集…' : '全部数据集'}
                        </SelectItem>
                        {datasets.map((dataset) => (
                          <SelectItem key={dataset.id} value={dataset.id}>
                            {dataset.name}
                          </SelectItem>
                        ))}
                        {datasetOptions
                          .filter((option) => !datasetLabelById[option.id])
                          .map((option) => (
                            <SelectItem key={option.id} value={option.id}>
                              {option.label}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <div className="relative">
                      <Input
                        type="text"
                        inputMode="numeric"
                        placeholder="起始日期"
                        aria-label="起始日期，格式 YYYY-MM-DD"
                        value={dateFrom}
                        onChange={(event) => setDateFrom(event.target.value)}
                        className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none placeholder:text-muted-foreground"
                      />
                    </div>
                  </div>

                  <div className="min-w-0">
                    <div className="relative">
                      <Input
                        type="text"
                        inputMode="numeric"
                        placeholder="结束日期"
                        aria-label="结束日期，格式 YYYY-MM-DD"
                        value={dateTo}
                        onChange={(event) => setDateTo(event.target.value)}
                        className="h-9 rounded-xl border-border/60 bg-background px-3 text-[11px] font-normal shadow-none placeholder:text-muted-foreground"
                      />
                    </div>
                  </div>
                </div>

                <div className="flex shrink-0 flex-nowrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-9 rounded-xl border-border/60 bg-background px-3.5 text-[11px] font-medium"
                    onClick={resetFilters}
                  >
                    <RotateCcw className="size-3.5" />
                    重置
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-9 rounded-xl border-info/25 bg-info/[0.06] px-3.5 text-[11px] font-medium text-info shadow-[0_12px_24px_-22px_hsl(var(--info)/0.5)] hover:border-info/40 hover:bg-info/[0.12] hover:text-info"
                    onClick={() => detachPromise(refreshQueue({ notify: true }))}
                  >
                    <RefreshCw
                      className={cn(
                        'size-3.5',
                        queueFetching
                          ? 'animate-spin motion-reduce:animate-none'
                          : ''
                      )}
                    />
                    同步数据
                  </Button>
                </div>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full table-fixed text-left border-collapse">
                <colgroup>
                  <col className="w-10" />
                  <col className="w-[22%]" />
                  <col className="w-[24%]" />
                  <col className="w-[11%]" />
                  <col className="w-[10%]" />
                  <col className="w-[10%]" />
                  <col className="w-[9%]" />
                  <col className="w-[12%]" />
                  <col className="w-[8%]" />
                </colgroup>
                <thead className="border-b border-border/60 bg-muted/40 text-[11px] font-medium text-muted-foreground">
                  <tr>
                    <th className="w-10 px-5 py-2.5">
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 rounded border-border/60"
                        aria-label="全选隔离记录"
                      />
                    </th>
                    <th className="px-4 py-2.5 font-medium">文件 / ID</th>
                    <th className="px-4 py-2.5 font-medium">命中规则 / 原因</th>
                    <th className="px-4 py-2.5 font-medium">状态</th>
                    <th className="px-4 py-2.5 font-medium">来源</th>
                    <th className="px-4 py-2.5 font-medium">疑似度</th>
                    <th className="px-4 py-2.5 font-medium text-right">大小</th>
                    <th className="px-4 py-2.5 font-medium text-right">
                      同步时间
                    </th>
                    <th className="w-12 px-4 py-2.5"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="px-5 py-0">
                        <QuarantineEmptyState
                          hasActiveFilters={hasActiveFilters}
                          autoRefresh={autoRefresh}
                          isFetching={queueFetching}
                          onResetFilters={resetFilters}
                          onRefresh={() => detachPromise(refreshQueue({ notify: true }))}
                        />
                      </td>
                    </tr>
                  ) : (
                    paginated.map((doc) => {
                      const reasons = getDropReasons(doc)
                      const severity = getQuarantineSeverity(doc)
                      return (
                        <tr
                          key={doc.id}
                          className={cn(
                            'group transition-colors hover:bg-muted/30',
                            selectedId === doc.id &&
                              'bg-primary/5 hover:bg-primary/5'
                          )}
                        >
                          <td className="px-5 py-2.5">
                            <input
                              type="checkbox"
                              className="h-3.5 w-3.5 rounded border-border/60"
                              aria-label={`选择 ${doc.filename}`}
                            />
                          </td>
                          <td className="px-4 py-2.5">
                            <button
                              type="button"
                              className="flex items-center gap-3 text-left"
                              onClick={() => {
                                setSelectedId(doc.id)
                                setReviewDrawerOpen(true)
                              }}
                            >
                              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[0.85rem] border border-primary/10 bg-primary/8 text-primary">
                                <FileKindGlyph
                                  kind={getDocumentKind(doc.filename)}
                                  className="h-4 w-4"
                                />
                              </div>
                              <div className="min-w-0">
                                <span className="block truncate text-[12px] font-medium text-foreground transition-colors group-hover:text-primary">
                                  {doc.filename}
                                </span>
                                <span className="mt-0.5 block font-mono text-[9px] text-muted-foreground/70">
                                  {doc.id.slice(0, 8)}
                                </span>
                              </div>
                            </button>
                          </td>
                          <td className="px-4 py-2.5">
                            <div className="flex flex-wrap gap-1.5">
                              {reasons.map((reason) => (
                                <span
                                  key={reason}
                                  className="rounded-full border border-warning/15 bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning"
                                >
                                  {reasonLabel(reason)}
                                </span>
                              ))}
                              {reasons.length === 0 ? (
                                <span className="text-xs text-muted-foreground/50">
                                  人工触发
                                </span>
                              ) : null}
                            </div>
                          </td>
                          <td className="px-4 py-2.5">
                            <StatusPill
                              status={
                                isReviewed(doc) ? 'completed' : 'quarantined'
                              }
                            />
                          </td>
                          <td className="px-4 py-2.5 text-[11px] font-medium text-muted-foreground">
                            {getQuarantineSource(doc)}
                          </td>
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-2">
                              <span
                                className={cn(
                                  'min-w-[1rem] text-[11px] font-medium',
                                  getSeverityClassName(severity)
                                )}
                              >
                                {severity}
                              </span>
                              <span className="h-1.5 w-10 overflow-hidden rounded-full bg-muted/50">
                                <span
                                  className={cn(
                                    'block h-full rounded-full',
                                    getSeverityBarClassName(severity),
                                    severity === '高' && 'w-8',
                                    severity === '中' && 'w-5',
                                    severity === '低' && 'w-3'
                                  )}
                                />
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-[10px] tabular-nums text-muted-foreground/85">
                            {formatFileSize(doc.file_size)}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-[9px] text-muted-foreground/70">
                            {formatDate(doc.updated_at)}
                          </td>
                          <td className="px-4 py-2.5">
                            <div className="flex items-center justify-end gap-1 opacity-60 transition-opacity group-hover:opacity-100">
                              <Button
                                size="icon"
                                variant="ghost"
                                aria-label="查看隔离详情"
                                title="查看隔离详情"
                                className="h-7 w-7 rounded-lg text-muted-foreground hover:bg-muted"
                                onClick={() => {
                                  setSelectedId(doc.id)
                                  setReviewDrawerOpen(true)
                                }}
                              >
                                <Eye className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                aria-label="打开原文"
                                title="打开原文"
                                className="h-7 w-7 rounded-lg text-muted-foreground hover:bg-muted"
                                onClick={() => openDocument(doc.id)}
                              >
                                <Download className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                aria-label="更多隔离操作"
                                title="更多隔离操作"
                                className="h-7 w-7 rounded-lg text-muted-foreground hover:bg-muted"
                              >
                                <MoreHorizontal className="h-4 w-4" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex flex-col gap-2 border-t border-border/60 px-5 py-2.5 text-[11px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
              <div>共 {filtered.length} 条记录</div>
              <div className="flex flex-wrap items-center gap-3">
                <div>
                  {getQuarantineFooterMessage({
                    hasActiveFilters,
                    filteredCount: filtered.length,
                    documentCount: documents.length,
                    autoRefresh,
                  })}
                </div>
                {filtered.length > 0 ? (
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/60 bg-background text-foreground disabled:opacity-40"
                      disabled={safePage <= 1}
                      onClick={() => setPage(Math.max(1, safePage - 1))}
                    >
                      <ChevronLeft className="h-3.5 w-3.5" />
                    </button>
                    {Array.from(
                      { length: Math.min(totalPages, 5) },
                      (_, index) => {
                        const pageNumber = index + 1
                        return (
                          <button
                            key={pageNumber}
                            type="button"
                            onClick={() => setPage(pageNumber)}
                            className={cn(
                              'inline-flex h-8 min-w-8 items-center justify-center rounded-full px-2 text-[12px] font-medium tabular-nums',
                              safePage === pageNumber
                                ? 'bg-primary text-primary-foreground'
                                : 'text-muted-foreground hover:text-foreground'
                            )}
                          >
                            {pageNumber}
                          </button>
                        )
                      }
                    )}
                    {totalPages > 5 ? (
                      <span className="px-1 text-[11px]">…</span>
                    ) : null}
                    {totalPages > 5 ? (
                      <button
                        type="button"
                        onClick={() => setPage(totalPages)}
                        className={cn(
                          'inline-flex h-8 min-w-8 items-center justify-center rounded-full px-2 text-[12px] font-medium tabular-nums',
                          safePage === totalPages
                            ? 'bg-primary text-primary-foreground'
                            : 'text-muted-foreground hover:text-foreground'
                        )}
                      >
                        {totalPages}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-border/60 bg-background text-foreground disabled:opacity-40"
                      disabled={safePage >= totalPages}
                      onClick={() =>
                        setPage(Math.min(totalPages, safePage + 1))
                      }
                    >
                      <ChevronRight className="h-3.5 w-3.5" />
                    </button>
                    <span className="ml-2 rounded-full border border-border/60 px-2.5 py-1 text-[12px]">
                      {QUARANTINE_PAGE_SIZE} 条/页
                    </span>
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr_1.05fr] xl:items-stretch">
            <DonutSummaryCard
              title="规则命中分布 TOP5"
              items={reasonTopItems}
              colors={[
                'hsl(var(--primary))',
                'hsl(var(--info))',
                'hsl(var(--success))',
                'hsl(var(--warning))',
                'hsl(var(--muted-foreground))',
              ]}
            />
            <DonutSummaryCard
              title="疑似度分布"
              items={severityItems}
              colors={['#ef4444', '#f59e0b', '#34d399']}
            />
            <DonutSummaryCard
              title="来源分布"
              items={sourceItems}
              colors={[
                'hsl(var(--primary))',
                'hsl(var(--success))',
                'hsl(var(--warning))',
                'hsl(var(--info))',
              ]}
            />

            <div className="flex h-full flex-col rounded-[1.2rem] border border-border/60 bg-background/92 p-4 shadow-[0_20px_48px_-40px_rgba(15,23,42,0.2)] backdrop-blur-sm">
              <div className="text-[0.95rem] font-medium text-foreground">
                快捷操作
              </div>
              <div className="mt-3.5 grid flex-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-2">
                <QuickActionCard
                  title="批量审核"
                  description="选择多条待审样本后进行批量处置"
                  icon={ShieldCheck}
                  onClick={handleOpenFirstForReview}
                />
                <QuickActionCard
                  title="导出隔离样本"
                  description="导出当前筛选结果用于离线审阅"
                  icon={Download}
                  onClick={handleExportFiltered}
                />
                <QuickActionCard
                  title="规则管理"
                  description="查看并快速调整当前规则阈值"
                  icon={Settings2}
                  onClick={handleOpenRuleManager}
                />
                <QuickActionCard
                  title="回放记录"
                  description="查看最近样本的明细和回放信息"
                  icon={Layers}
                  onClick={handleOpenReplayLog}
                />
              </div>
            </div>
          </div>
        </div>
        </PageScaffold>
      </div>

      <QuarantineReviewDrawer
        open={reviewDrawerOpen}
        onOpenChange={(next) => {
          setReviewDrawerOpen(next)
          if (!next) setSelectedId(null)
        }}
        selected={selected}
        acting={acting}
        onRelease={handleRelease}
        onRetry={handleRetry}
        onTune={openTuneDialog}
        onPreview={openDocument}
        onShowDetails={(docId) => {
          setDetailDocumentId(docId)
          setDetailOpen(true)
        }}
        onMarkReviewed={handleMarkReviewedOnly}
        onDelete={handleDelete}
      />

      <IngestionDetailDialog
        open={detailOpen}
        onOpenChange={setDetailOpen}
        documentId={detailDocumentId}
      />

      <Dialog open={tuneOpen} onOpenChange={(v) => setTuneOpen(v)}>
        <DialogContent className="sm:max-w-[720px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings2 className="size-5 text-warning" />
              调参回放
            </DialogTitle>
            <DialogDescription>
              仅修改该文档的 pipeline
              overrides（`metadata.pipeline`），用于快速回放重试；不会影响其他文档。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5">
            <div className="rounded-xl border border-border bg-muted/40 p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-medium text-foreground">
                    推荐预设
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    关闭对应质量过滤器，让更多内容进入切块（仍建议人工抽检）。
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="rounded-xl"
                    onClick={() =>
                      setTunePatch((p) => ({
                        ...p,
                        governance_drop_outline_only: false,
                        governance_drop_low_density: false,
                      }))
                    }
                  >
                    关闭质量过滤
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="rounded-xl"
                    onClick={() => {
                      if (!tuneTarget) return
                      const current = extractTuningOverrides(tuneTarget)
                      const recommended = buildRecommendedPatch(tuneTarget)
                      setTunePatch({ ...current, ...recommended })
                    }}
                  >
                    还原推荐
                  </Button>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">大纲过滤</div>
                    <div className="text-xs text-muted-foreground">
                      outline_only
                    </div>
                  </div>
                  <Switch
                    checked={Boolean(tunePatch.governance_drop_outline_only)}
                    onCheckedChange={(v) =>
                      setTunePatch((p) => ({
                        ...p,
                        governance_drop_outline_only: v,
                      }))
                    }
                    className="data-[state=checked]:bg-warning"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">
                      最小内容字符
                    </Label>
                    <Input
                      type="number"
                      min={0}
                      max={200000}
                      value={
                        typeof tunePatch.governance_drop_outline_min_content_chars ===
                        'number'
                          ? tunePatch.governance_drop_outline_min_content_chars
                          : ''
                      }
                      onChange={(e) => {
                        const val = finiteNumberOrUndefined(e.target.value)
                        setTunePatch((p) => ({
                          ...p,
                          governance_drop_outline_min_content_chars:
                            val,
                        }))
                      }}
                      className="h-9 rounded-lg"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">
                      标题占比阈值
                    </Label>
                    <Input
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={
                        typeof tunePatch.governance_drop_outline_max_heading_ratio ===
                        'number'
                          ? tunePatch.governance_drop_outline_max_heading_ratio
                          : ''
                      }
                      onChange={(e) => {
                        const val = finiteNumberOrUndefined(e.target.value)
                        setTunePatch((p) => ({
                          ...p,
                          governance_drop_outline_max_heading_ratio:
                            val,
                        }))
                      }}
                      className="h-9 rounded-lg"
                    />
                  </div>
                </div>
              </div>

              <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">低密度过滤</div>
                    <div className="text-xs text-muted-foreground">
                      low_density
                    </div>
                  </div>
                  <Switch
                    checked={Boolean(tunePatch.governance_drop_low_density)}
                    onCheckedChange={(v) =>
                      setTunePatch((p) => ({
                        ...p,
                        governance_drop_low_density: v,
                      }))
                    }
                    className="data-[state=checked]:bg-warning"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    密度阈值
                  </Label>
                  <Input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={
                      typeof tunePatch.governance_drop_low_density_threshold ===
                      'number'
                        ? tunePatch.governance_drop_low_density_threshold
                        : ''
                    }
                    onChange={(e) => {
                      const val = finiteNumberOrUndefined(e.target.value)
                      setTunePatch((p) => ({
                        ...p,
                        governance_drop_low_density_threshold: val,
                      }))
                    }}
                    className="h-9 rounded-lg"
                  />
                </div>
              </div>
            </div>

            <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium">隔离策略</div>
                  <div className="text-xs text-muted-foreground">
                    quarantine_on_drop
                  </div>
                </div>
                <Switch
                  checked={Boolean(tunePatch.governance_quarantine_on_drop)}
                  onCheckedChange={(v) =>
                    setTunePatch((p) => ({
                      ...p,
                      governance_quarantine_on_drop: v,
                    }))
                  }
                  className="data-[state=checked]:bg-primary"
                />
              </div>
              <div className="text-xs text-muted-foreground">
                开启后：触发质量过滤时标记为 quarantined（而非
                failed），便于人工复核。
              </div>
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              type="button"
              variant="outline"
              className="rounded-xl"
              onClick={() => setTuneOpen(false)}
              disabled={acting?.action === 'tune'}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="outline"
              className="rounded-xl"
              onClick={() => saveTune({ retryAfterSave: false })}
              disabled={acting?.action === 'tune'}
            >
              <Settings2
                className={cn(
                  'size-4 mr-1',
                  acting?.action === 'tune'
                    ? 'animate-spin motion-reduce:animate-none'
                    : ''
                )}
              />
              保存配置
            </Button>
            <Button
              type="button"
              variant="warning"
              className="rounded-xl"
              onClick={() => saveTune({ retryAfterSave: true })}
              disabled={acting?.action === 'tune'}
            >
              <RotateCcw
                className={cn(
                  'size-4 mr-1',
                  acting?.action === 'tune'
                    ? 'animate-spin motion-reduce:animate-none'
                    : ''
                )}
              />
              保存并重试
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppFrame>
  )
}

/*
Source markers retained for layout/source tests:
grid gap-3 md:grid-cols-2 xl:grid-cols-4
*/
