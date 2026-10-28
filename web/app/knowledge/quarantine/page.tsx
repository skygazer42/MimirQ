'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, Quarantine, RefreshCw } from '@/components/icons'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AppFrame } from '@/components/app-frame'
import { QuarantineTableWorkspace } from '@/components/knowledge/quarantine/quarantine-table-workspace'
import { QuarantineTuneDialog } from '@/components/knowledge/quarantine/quarantine-tune-dialog'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { cn, detachPromise } from '@/lib/utils'
import { documentApi } from '@/lib/api'
import { formatApiError, toApiErrorInfo } from '@/lib/api-errors'
import { captureApiError } from '@/lib/api-error-reporting'
import { useDatasets } from '@/hooks/use-datasets'
import type { Document, DocumentPipelineOptions } from '@/types'
import { useDocumentView } from '@/store/document-view'
import { usePathname, useRouter } from '@/i18n/navigation'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import { QUARANTINE_PAGE_SIZE } from './constants'
import { buildDemoQuarantineDocuments } from './demo-quarantine'
import { createReviewMetadataPatch, downloadTextFile, extractTuningOverrides, getDropReasons, getQuarantineSeverity, getQuarantineSource, isReviewed, reasonLabel } from './quarantine-signals'
import type { ActingState, JsonRecord, QuarantineSeverity } from './types'
import styles from './quarantine.module.css'

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
  const [acting, setActing] = useState<ActingState>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailDocumentId, setDetailDocumentId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<{ id: string; message: string; requestId?: string } | null>(null)

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
  const refreshQueue = useCallback(async ({ notify = false }: { notify?: boolean } = {}) => {
    try {
      const results = await Promise.all([refetch(), refetchFailed()])
      const error = results.find(result => result.error)?.error
      if (error) throw error
      if (notify) toast.success('隔离队列已同步')
      return true
    } catch (error) {
      const info = captureApiError(error, '隔离队列同步失败', {
        level: 'warning',
        tags: { page: 'knowledge-quarantine', action: 'manual-sync' },
      })
      if (notify) toast.error(info.message)
      return false
    }
  }, [refetch, refetchFailed])

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

  useEffect(() => {
    if (selectedId && !paginated.some(doc => doc.id === selectedId)) setSelectedId(null)
  }, [paginated, selectedId])

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
      setActionError(null)
      setActing({ id: doc.id, action: 'retry' })
      try {
        await documentApi.retry(doc.id)
        await markReviewed(doc.id, { quarantine_action: 'retry' })
        toast.success('已触发重新入库')
        await refreshQueue()
      } catch (err: unknown) {
        const { message, requestId } = toApiErrorInfo(err, '重试失败')
        setActionError({ id: doc.id, message, requestId })
        toast.error(message)
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
      setActionError(null)
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
        const { message, requestId } = toApiErrorInfo(err, '放行失败')
        setActionError({ id: doc.id, message, requestId })
        toast.error(message)
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
      setActionError(null)
      setActing({ id: doc.id, action: 'delete' })
      try {
        await documentApi.delete(doc.id)
        toast.success('已删除文档')
        if (selectedId === doc.id) {
          setSelectedId(null)
        }
        await refreshQueue()
      } catch (err: unknown) {
        const { message, requestId } = toApiErrorInfo(err, '删除失败')
        setActionError({ id: doc.id, message, requestId })
        toast.error(message)
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
      setActionError(null)
      setActing({ id: doc.id, action: 'review' })
      try {
        await markReviewed(doc.id, { quarantine_action: 'reviewed' })
        toast.success('已标记为已复核')
        await refreshQueue()
      } catch (err: unknown) {
        const { message, requestId } = toApiErrorInfo(err, '标记失败')
        setActionError({ id: doc.id, message, requestId })
        toast.error(message)
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
      setActionError(null)
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
        const { message, requestId } = toApiErrorInfo(err, '保存失败')
        setActionError({ id: doc.id, message, requestId })
        toast.error(message)
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
      'quarantine-documents.json',
      JSON.stringify(payload, null, 2),
      'application/json;charset=utf-8'
    )
    toast.success('已导出当前筛选记录')
  }, [filtered])

  const handleExitDemoMode = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())
    params.delete('demo')
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname)
  }, [pathname, router, searchParams])

  const countsReady = demoMode || Boolean(data && failedData)
  const initialLoading = !demoMode && !countsReady && queueFetching && !documents.length

  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding>
      <div data-quarantine-page-root="true" className={styles.shell}>
        <header className={styles.header}>
          <div className={styles.heading}><Quarantine appearance="color" data-quarantine-title-mark="true" aria-hidden="true" /><h1>隔离队列</h1></div>
          <div className={styles.headerActions}>
            {demoMode && <Button size="sm" variant="ghost" onClick={handleExitDemoMode}>退出 Demo</Button>}
            <label className={styles.autoRefresh}><span>自动刷新</span><Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} aria-label="自动刷新隔离队列" /></label>
            <Button variant="ghost" className={styles.sync} aria-label="同步隔离队列" disabled={queueFetching} onClick={() => { if (!demoMode) detachPromise(refreshQueue({ notify: true })) }}><RefreshCw className={cn(queueFetching && 'animate-spin motion-reduce:animate-none')} aria-hidden="true" /><span>同步</span></Button>
            <Button variant="outline" className={styles.export} disabled={!filtered.length} onClick={handleExportFiltered}><Download aria-hidden="true" />导出</Button>
          </div>
        </header>
        <QuarantineTableWorkspace
          demoMode={demoMode}
          dateFrom={dateFrom}
          dateTo={dateTo}
          datasetLabelById={datasetLabelById}
          datasetOptions={datasetOptions}
          datasetsLoading={datasetsLoading}
          documentsCount={documents.length}
          filteredCount={filtered.length}
          hasActiveFilters={hasActiveFilters}
          paginated={paginated}
          queueFetching={queueFetching}
          initialLoading={initialLoading}
          queueError={queueErrorMessage}
          countsReady={countsReady}
          reviewCounts={stats}
          severityCounts={severityCounts}
          reviewState={reviewState}
          safePage={safePage}
          search={search}
          selectedDataset={selectedDataset}
          selectedId={selectedId}
          selectedReason={selectedReason}
          selectedSeverity={selectedSeverity}
          selectedSource={selectedSource}
          sortedReasons={sortedReasons}
          sourceOptions={sourceOptions}
          totalPages={totalPages}
          reasonCounts={reasonCounts}
          acting={acting}
          actionError={actionError}
          onDateFromChange={setDateFrom}
          onDateToChange={setDateTo}
          onDatasetChange={handleDatasetScopeChange}
          onOpenDocument={openDocument}
          onOpenReview={docId => setSelectedId(current => current === docId ? null : docId)}
          onPageChange={setPage}
          onReasonChange={setSelectedReason}
          onRefresh={() => detachPromise(refreshQueue({ notify: true }))}
          onResetFilters={resetFilters}
          onReviewStateChange={setReviewState}
          onSearchChange={setSearch}
          onSeverityChange={setSelectedSeverity}
          onSourceChange={setSelectedSource}
          onRelease={handleRelease}
          onRetry={handleRetry}
          onTune={openTuneDialog}
          onMarkReviewed={handleMarkReviewedOnly}
          onDelete={handleDelete}
          onShowDetails={docId => { setDetailDocumentId(docId); setDetailOpen(true) }}
        />
      </div>
      <IngestionDetailDialog open={detailOpen} onOpenChange={setDetailOpen} documentId={detailDocumentId} />
      <QuarantineTuneDialog
        acting={acting}
        open={tuneOpen}
        patch={tunePatch}
        target={tuneTarget}
        onApplyDisableQualityFilters={() => setTunePatch(current => ({ ...current, governance_drop_outline_only: false, governance_drop_low_density: false }))}
        onOpenChange={setTuneOpen}
        onPatchChange={setTunePatch}
        onResetRecommended={() => {
          if (!tuneTarget) return
          setTunePatch({ ...extractTuningOverrides(tuneTarget), ...buildRecommendedPatch(tuneTarget) })
        }}
        onSave={saveTune}
      />
    </AppFrame>
  )
}
