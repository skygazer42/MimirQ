'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, Quarantine, RefreshCw } from '@/components/icons'
import { useSearchParams } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AppFrame } from '@/components/app-frame'
import { QuarantineTableWorkspace } from '@/components/knowledge/quarantine/quarantine-table-workspace'
import { QuarantineTuneDialog } from '@/components/knowledge/quarantine/quarantine-tune-dialog'
import { Button } from '@/components/ui/button'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { Switch } from '@/components/ui/switch'
import { cn, detachPromise } from '@/lib/utils'
import { documentApi } from '@/lib/api/documents'
import { formatApiError, toApiErrorInfo } from '@/lib/api-errors'
import { getAuthSessionRevision } from '@/lib/auth-storage'
import { captureApiError } from '@/lib/api-error-reporting'
import { downloadBlob } from '@/lib/download'
import { useDatasets } from '@/hooks/use-datasets'
import type { Document, DocumentPipelineOptions } from '@/types'
import { useDocumentView } from '@/store/document-view'
import { usePathname, useRouter } from '@/i18n/navigation'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import { QUARANTINE_PAGE_SIZE } from './constants'
import { buildDemoQuarantineDocuments } from './demo-quarantine'
import {
  createReviewMetadataPatch,
  extractTuningOverrides,
  getDropReasons,
  getQuarantineSeverity,
  getQuarantineSource,
  isReviewed,
  reasonLabel,
} from './quarantine-signals'
import type { ActingState, JsonRecord, QuarantineSeverity } from './types'
import styles from './quarantine.module.css'

function quarantineQueueKey(status: 'quarantined' | 'failed', datasetId: string | null) {
  return ['quarantine-documents', status, datasetId] as const
}

export default function QuarantineQueuePage() {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const queryClient = useQueryClient()
  const demoMode = /(^|\/)demo(\/|$)/.test(pathname) && searchParams.get('demo') === '1'
  const datasetParam = searchParams.get('datasetId')
  const datasetFromQuery = datasetParam === null || datasetParam === '' ? 'all' : datasetParam
  const { openDocument } = useDocumentView()
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedReason, setSelectedReason] = useState('all')
  const [selectedDataset, setSelectedDataset] = useState(datasetFromQuery)
  const [selectedSource, setSelectedSource] = useState('all')
  const [selectedSeverity, setSelectedSeverity] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [reviewState, setReviewState] = useState<'all' | 'pending' | 'reviewed'>('all')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [actingByDocumentId, setActingByDocumentId] = useState<ReadonlyMap<string, NonNullable<ActingState>>>(new Map())
  const actingRef = useRef(new Map<string, NonNullable<ActingState>>())
  const mountedRef = useRef(false)
  const tuneVisitRef = useRef<object>({})
  const reviewVisitRef = useRef<object>({})
  const queueVisitRef = useRef<object>({})
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailDocumentId, setDetailDocumentId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<{ id: string; message: string; requestId?: string } | null>(null)

  const [tuneOpen, setTuneOpen] = useState(false)
  const [tuneTarget, setTuneTarget] = useState<Document | null>(null)
  const [tunePatch, setTunePatch] = useState<DocumentPipelineOptions>({})
  const {
    datasets,
    isLoading: datasetsLoading,
    isFetching: datasetsFetching,
    error: datasetsError,
    refreshDatasets,
  } = useDatasets()
  const selectedDatasetId = selectedDataset === 'all' ? null : selectedDataset

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const changeTuneOpen = useCallback((open: boolean) => {
    if (!open) tuneVisitRef.current = {}
    setTuneOpen(open)
  }, [])

  useEffect(
    () => () => {
      reviewVisitRef.current = {}
    },
    [selectedId],
  )
  useEffect(
    () => () => {
      queueVisitRef.current = {}
    },
    [demoMode, selectedDatasetId],
  )

  const {
    data,
    error: queueError,
    isFetching,
  } = useQuery({
    queryKey: quarantineQueueKey('quarantined', selectedDatasetId),
    queryFn: ({ signal }) =>
      documentApi.list(
        {
          limit: 200,
          status: 'quarantined',
          dataset_id: selectedDatasetId ?? undefined,
        },
        { signal },
      ),
    staleTime: 3_000,
    enabled: !demoMode,
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  const {
    data: failedData,
    error: failedQueueError,
    isFetching: isFetchingFailed,
  } = useQuery({
    queryKey: quarantineQueueKey('failed', selectedDatasetId),
    queryFn: ({ signal }) =>
      documentApi.list(
        {
          limit: 200,
          status: 'failed',
          dataset_id: selectedDatasetId ?? undefined,
        },
        { signal },
      ),
    staleTime: 3_000,
    enabled: !demoMode,
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  const documents = useMemo(() => {
    if (demoMode) return buildDemoQuarantineDocuments()
    const byId = new Map<string, Document>()
    for (const doc of [...(data?.items ?? []), ...(failedData?.items ?? [])]) {
      const previous = byId.get(doc.id)
      if (previous === undefined || Date.parse(doc.updated_at) >= Date.parse(previous.updated_at)) byId.set(doc.id, doc)
    }
    return Array.from(byId.values())
  }, [data, demoMode, failedData])
  const queueFetching = isFetching || isFetchingFailed
  const queueErrorMessage = useMemo(() => {
    const err = queueError ?? failedQueueError
    return err ? formatApiError(err, '隔离队列同步失败') : null
  }, [failedQueueError, queueError])
  const refreshQueue = useCallback(
    async ({ notify = false }: { notify?: boolean } = {}) => {
      const authRevision = getAuthSessionRevision()
      const visit = queueVisitRef.current
      const queryKeys = [
        quarantineQueueKey('quarantined', selectedDatasetId),
        quarantineQueueKey('failed', selectedDatasetId),
      ]
      const ownsView = () =>
        mountedRef.current && queueVisitRef.current === visit && authRevision === getAuthSessionRevision()
      try {
        await Promise.all(
          queryKeys.map((queryKey) =>
            queryClient.refetchQueries({ queryKey, exact: true, type: 'all' }, { throwOnError: true }),
          ),
        )
        if (!ownsView()) return
        if (queryKeys.some((queryKey) => queryClient.getQueryState(queryKey)?.fetchStatus === 'paused')) {
          if (notify) toast.info('隔离队列同步已暂停，恢复连接后会继续。')
          return
        }
        const [quarantineResult, failedResult] = queryKeys.map((queryKey) =>
          queryClient.getQueryData<Awaited<ReturnType<typeof documentApi.list>>>(queryKey),
        )
        if (quarantineResult === undefined || failedResult === undefined) {
          throw new Error('未取得完整的隔离队列数据')
        }
        const quarantinedTotal = quarantineResult.total
        const failedTotal = failedResult.total
        const message =
          quarantinedTotal + failedTotal > 0
            ? `同步完成：待审核 ${quarantinedTotal} 条，失败 ${failedTotal} 条`
            : '同步完成：当前没有隔离或失败记录'
        if (notify) toast.success(message)
      } catch (err) {
        if (!ownsView()) return
        const info = captureApiError(err, '隔离队列同步失败', {
          level: 'warning',
          tags: { page: 'knowledge-quarantine', action: 'manual-sync' },
        })
        if (notify) toast.error(info.message)
      }
    },
    [queryClient, selectedDatasetId],
  )

  useEffect(() => {
    setSelectedDataset(datasetFromQuery)
  }, [datasetFromQuery])

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
    [pathname, router, searchParams],
  )

  const reasonCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const doc of documents) {
      for (const reason of getDropReasons(doc)) {
        counts.set(reason, (counts.get(reason) ?? 0) + 1)
      }
    }
    return Object.fromEntries(counts)
  }, [documents])

  const sortedReasons = useMemo(() => {
    return Object.entries(reasonCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([reason]) => reason)
  }, [reasonCounts])

  const datasetOptions = useMemo(() => {
    const byId = new Map(datasets.map(({ id, name }) => [id, name === '' ? id : name]))
    for (const doc of documents) {
      const datasetId = doc.dataset_id
      if (datasetId && !byId.has(datasetId)) byId.set(datasetId, datasetId)
    }
    return Array.from(byId, ([id, label]) => ({ id, label })).sort((left, right) =>
      left.label.localeCompare(right.label),
    )
  }, [datasets, documents])
  const datasetLabelById = useMemo(
    () => Object.fromEntries(datasetOptions.map(({ id, label }) => [id, label])),
    [datasetOptions],
  )

  const sourceOptions = useMemo(
    () => Array.from(new Set(documents.map((doc) => getQuarantineSource(doc)))).sort((a, b) => a.localeCompare(b)),
    [documents],
  )

  const severityCounts = useMemo(() => {
    return documents.reduce<Record<QuarantineSeverity, number>>(
      (acc, doc) => {
        const severity = getQuarantineSeverity(doc)
        acc[severity] += 1
        return acc
      },
      { 高: 0, 中: 0, 低: 0 },
    )
  }, [documents])

  const stats = useMemo(() => {
    const total = documents.length
    const reviewed = documents.filter(isReviewed).length
    return {
      total,
      reviewed,
      unreviewed: total - reviewed,
    }
  }, [documents])

  const filtered = useMemo(() => {
    let out = documents
    if (reviewState === 'pending') out = out.filter((d) => !isReviewed(d))
    if (reviewState === 'reviewed') out = out.filter((d) => isReviewed(d))
    if (selectedReason !== 'all') out = out.filter((d) => getDropReasons(d).includes(selectedReason))
    if (selectedDataset !== 'all') out = out.filter((d) => d.dataset_id === selectedDataset)
    if (selectedSource !== 'all') out = out.filter((d) => getQuarantineSource(d) === selectedSource)
    if (selectedSeverity !== 'all') out = out.filter((d) => getQuarantineSeverity(d) === selectedSeverity)
    const rangeStart = dateFrom === '' ? undefined : Date.parse(`${dateFrom}T00:00:00`)
    const rangeEnd = dateTo === '' ? undefined : Date.parse(`${dateTo}T23:59:59.999`)
    if (rangeStart !== undefined || rangeEnd !== undefined) {
      out = out.filter((doc) => {
        const time = Date.parse(doc.updated_at)
        return (rangeStart === undefined || time >= rangeStart) && (rangeEnd === undefined || time <= rangeEnd)
      })
    }

    const q = search.trim().toLowerCase()
    if (q) {
      out = out.filter((d) => {
        const filename = d.filename.toLowerCase()
        const id = d.id.toLowerCase()
        const dataset = d.dataset_id?.toLowerCase()
        const source = getQuarantineSource(d).toLowerCase()
        const severity = getQuarantineSeverity(d).toLowerCase()
        const reasons = getDropReasons(d)
          .flatMap((reason) => [reason, reasonLabel(reason)])
          .join(' ')
          .toLowerCase()

        return (
          filename.includes(q) ||
          id.includes(q) ||
          dataset?.includes(q) ||
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

  const totalPages = useMemo(() => Math.max(1, Math.ceil(filtered.length / QUARANTINE_PAGE_SIZE)), [filtered.length])
  // Clamp during render instead of via an effect: when filters shrink the
  // result set, safePage stays in range without an extra render pass.
  const safePage = Math.min(page, totalPages)
  const paginated = useMemo(
    () => filtered.slice((safePage - 1) * QUARANTINE_PAGE_SIZE, safePage * QUARANTINE_PAGE_SIZE),
    [filtered, safePage],
  )

  useEffect(() => {
    if (selectedId && !paginated.some((doc) => doc.id === selectedId)) setSelectedId(null)
  }, [paginated, selectedId])

  useEffect(() => {
    setPage(1)
  }, [search, selectedReason, selectedDataset, selectedSource, selectedSeverity, dateFrom, dateTo, reviewState])

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

  const markReviewed = useCallback(async (docId: string, extra?: JsonRecord) => {
    const patch = createReviewMetadataPatch(extra)
    await documentApi.patchUserMetadata(docId, { patch, replace: false })
  }, [])

  const recordRetryReview = useCallback(
    async (docId: string, metadata: JsonRecord, authRevision: number) => {
      try {
        await markReviewed(docId, metadata)
        return true
      } catch (error) {
        if (!mountedRef.current || authRevision !== getAuthSessionRevision()) return false
        const info = toApiErrorInfo(error, '复核状态写入失败')
        const message = `重试已触发，复核状态写入失败：${info.message}`
        setActionError({ id: docId, message, requestId: info.requestId })
        toast.error(message)
        return false
      }
    },
    [markReviewed],
  )

  const buildRecommendedPatch = useCallback((doc: Document): DocumentPipelineOptions => {
    const reasons = new Set(getDropReasons(doc))
    const patch: DocumentPipelineOptions = {}
    if (reasons.has('outline_only')) patch.governance_drop_outline_only = false
    if (reasons.has('low_density')) patch.governance_drop_low_density = false
    return patch
  }, [])

  const handleRetry = useCallback(
    async (doc: Document) => {
      if (actingRef.current.has(doc.id)) return
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不执行真实重试')
        return
      }
      setActionError(null)
      const action = { id: doc.id, action: 'retry' } as const
      const authRevision = getAuthSessionRevision()
      actingRef.current.set(doc.id, action)
      setActingByDocumentId(new Map(actingRef.current))
      try {
        await documentApi.retry(doc.id)
        if (authRevision !== getAuthSessionRevision()) return
        const reviewed = await recordRetryReview(doc.id, { quarantine_action: 'retry' }, authRevision)
        if (authRevision !== getAuthSessionRevision()) return
        if (mountedRef.current && reviewed) toast.success('已触发重新入库')
        await refreshQueue()
      } catch (err: unknown) {
        if (!mountedRef.current || authRevision !== getAuthSessionRevision()) return
        const { message, requestId } = toApiErrorInfo(err, '重试失败')
        setActionError({ id: doc.id, message, requestId })
        toast.error(message)
      } finally {
        if (actingRef.current.get(doc.id) === action) {
          actingRef.current.delete(doc.id)
          if (mountedRef.current) setActingByDocumentId(new Map(actingRef.current))
        }
      }
    },
    [demoMode, recordRetryReview, refreshQueue],
  )

  const handleRelease = useCallback(
    async (doc: Document) => {
      if (actingRef.current.has(doc.id)) return
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不执行真实放行')
        return
      }
      setActionError(null)
      const action = { id: doc.id, action: 'release' } as const
      const authRevision = getAuthSessionRevision()
      actingRef.current.set(doc.id, action)
      setActingByDocumentId(new Map(actingRef.current))
      try {
        const patch = buildRecommendedPatch(doc)
        if (Object.keys(patch).length) {
          await documentApi.patchPipeline(doc.id, { patch, replace: false })
          if (authRevision !== getAuthSessionRevision()) return
        }
        await documentApi.retry(doc.id)
        if (authRevision !== getAuthSessionRevision()) return
        const reviewed = await recordRetryReview(
          doc.id,
          { quarantine_action: 'release_retry', quarantine_reason: getDropReasons(doc).join(',') },
          authRevision,
        )
        if (authRevision !== getAuthSessionRevision()) return
        if (mountedRef.current && reviewed) toast.success('已放行并重试')
        await refreshQueue()
      } catch (err: unknown) {
        if (!mountedRef.current || authRevision !== getAuthSessionRevision()) return
        const { message, requestId } = toApiErrorInfo(err, '放行失败')
        setActionError({ id: doc.id, message, requestId })
        toast.error(message)
      } finally {
        if (actingRef.current.get(doc.id) === action) {
          actingRef.current.delete(doc.id)
          if (mountedRef.current) setActingByDocumentId(new Map(actingRef.current))
        }
      }
    },
    [buildRecommendedPatch, demoMode, recordRetryReview, refreshQueue],
  )

  const handleDelete = useCallback(
    async (doc: Document) => {
      if (actingRef.current.has(doc.id)) return
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不执行真实删除')
        return
      }
      setActionError(null)
      const action = { id: doc.id, action: 'delete' } as const
      const authRevision = getAuthSessionRevision()
      const reviewVisit = reviewVisitRef.current
      actingRef.current.set(doc.id, action)
      setActingByDocumentId(new Map(actingRef.current))
      try {
        await documentApi.delete(doc.id)
        if (authRevision !== getAuthSessionRevision()) return
        if (mountedRef.current) toast.success('已删除文档')
        if (mountedRef.current && reviewVisitRef.current === reviewVisit && selectedId === doc.id) {
          setSelectedId(null)
        }
        await refreshQueue()
      } catch (err: unknown) {
        if (!mountedRef.current || authRevision !== getAuthSessionRevision()) return
        const { message, requestId } = toApiErrorInfo(err, '删除失败')
        setActionError({ id: doc.id, message, requestId })
        throw err
      } finally {
        if (actingRef.current.get(doc.id) === action) {
          actingRef.current.delete(doc.id)
          if (mountedRef.current) setActingByDocumentId(new Map(actingRef.current))
        }
      }
    },
    [demoMode, refreshQueue, selectedId],
  )

  const handleMarkReviewedOnly = useCallback(
    async (doc: Document) => {
      if (actingRef.current.has(doc.id)) return
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不写入真实审核状态')
        return
      }
      setActionError(null)
      const action = { id: doc.id, action: 'review' } as const
      const authRevision = getAuthSessionRevision()
      actingRef.current.set(doc.id, action)
      setActingByDocumentId(new Map(actingRef.current))
      try {
        await markReviewed(doc.id, { quarantine_action: 'reviewed' })
        if (authRevision !== getAuthSessionRevision()) return
        if (mountedRef.current) toast.success('已标记为已处理')
        await refreshQueue()
      } catch (err: unknown) {
        if (!mountedRef.current || authRevision !== getAuthSessionRevision()) return
        const { message, requestId } = toApiErrorInfo(err, '标记失败')
        setActionError({ id: doc.id, message, requestId })
        toast.error(message)
      } finally {
        if (actingRef.current.get(doc.id) === action) {
          actingRef.current.delete(doc.id)
          if (mountedRef.current) setActingByDocumentId(new Map(actingRef.current))
        }
      }
    },
    [demoMode, markReviewed, refreshQueue],
  )

  const openTuneDialog = useCallback(
    (doc: Document) => {
      tuneVisitRef.current = {}
      const current = extractTuningOverrides(doc)
      const recommended = buildRecommendedPatch(doc)
      setTuneTarget(doc)
      setTunePatch({ ...current, ...recommended })
      setTuneOpen(true)
    },
    [buildRecommendedPatch],
  )

  const saveTune = useCallback(
    async (opts: { retryAfterSave: boolean }) => {
      if (!tuneTarget || actingRef.current.has(tuneTarget.id)) return
      if (demoMode) {
        toast.success('Demo 模式仅用于预览布局，不写入真实规则配置')
        setTuneOpen(false)
        return
      }
      const doc = tuneTarget
      setActionError(null)
      const action = { id: doc.id, action: 'tune' } as const
      const authRevision = getAuthSessionRevision()
      const tuneVisit = tuneVisitRef.current
      actingRef.current.set(doc.id, action)
      setActingByDocumentId(new Map(actingRef.current))
      try {
        await documentApi.patchPipeline(doc.id, {
          patch: tunePatch,
          replace: false,
        })
        if (authRevision !== getAuthSessionRevision()) return
        let reviewed = true
        if (opts.retryAfterSave) {
          await documentApi.retry(doc.id)
          if (authRevision !== getAuthSessionRevision()) return
          reviewed = await recordRetryReview(doc.id, { quarantine_action: 'tune_retry' }, authRevision)
          if (authRevision !== getAuthSessionRevision()) return
        }
        if (mountedRef.current && tuneVisitRef.current === tuneVisit) {
          if (reviewed) toast.success(opts.retryAfterSave ? '已保存配置并重试' : '已保存配置')
          setTuneOpen(false)
        }
        await refreshQueue()
      } catch (err: unknown) {
        if (!mountedRef.current || tuneVisitRef.current !== tuneVisit || authRevision !== getAuthSessionRevision())
          return
        const { message, requestId } = toApiErrorInfo(err, '保存失败')
        setActionError({ id: doc.id, message, requestId })
        toast.error(message)
      } finally {
        if (actingRef.current.get(doc.id) === action) {
          actingRef.current.delete(doc.id)
          if (mountedRef.current) setActingByDocumentId(new Map(actingRef.current))
        }
      }
    },
    [demoMode, recordRetryReview, refreshQueue, tunePatch, tuneTarget],
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
    downloadBlob(
      'quarantine-documents.json',
      new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }),
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
          <div className={styles.heading}>
            <Quarantine appearance="color" data-quarantine-title-mark="true" aria-hidden="true" />
            <h1>隔离队列</h1>
          </div>
          <div className={styles.headerActions}>
            {demoMode && (
              <Button size="sm" variant="ghost" onClick={handleExitDemoMode}>
                退出 Demo
              </Button>
            )}
            <label className={styles.autoRefresh}>
              <span>自动刷新</span>
              <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} aria-label="自动刷新隔离队列" />
            </label>
            <Button
              variant="ghost"
              className={styles.sync}
              aria-label="同步隔离队列"
              disabled={queueFetching}
              onClick={() => {
                if (!demoMode) detachPromise(refreshQueue({ notify: true }))
              }}
            >
              <RefreshCw
                className={cn(queueFetching && 'animate-spin motion-reduce:animate-none')}
                aria-hidden="true"
              />
              <span>同步</span>
            </Button>
            <Button
              variant="outline"
              className={styles.export}
              disabled={!filtered.length}
              onClick={handleExportFiltered}
            >
              <Download aria-hidden="true" />
              导出
            </Button>
          </div>
        </header>
        {!demoMode && datasetsError !== null ? (
          <WorkspaceNotice
            retry={() => void refreshDatasets()}
            retryLabel="重新读取数据集目录"
            pending={datasetsFetching}
          >
            {formatApiError(datasetsError, '数据集目录读取失败，隔离队列范围已保留')}
          </WorkspaceNotice>
        ) : null}
        {!demoMode && datasetsFetching && !datasetsLoading ? (
          <p role="status" className="text-sm text-muted-foreground">
            正在更新数据集目录，保留当前范围。
          </p>
        ) : null}
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
          actingByDocumentId={actingByDocumentId}
          actionError={actionError}
          onDateFromChange={setDateFrom}
          onDateToChange={setDateTo}
          onDatasetChange={handleDatasetScopeChange}
          onOpenDocument={openDocument}
          onOpenReview={(docId) => setSelectedId((current) => (current === docId ? null : docId))}
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
          onShowDetails={(docId) => {
            setDetailDocumentId(docId)
            setDetailOpen(true)
          }}
        />
      </div>
      <IngestionDetailDialog open={detailOpen} onOpenChange={setDetailOpen} documentId={detailDocumentId} />
      <QuarantineTuneDialog
        acting={tuneTarget ? (actingByDocumentId.get(tuneTarget.id) ?? null) : null}
        open={tuneOpen}
        patch={tunePatch}
        target={tuneTarget}
        onApplyDisableQualityFilters={() =>
          setTunePatch((current) => ({
            ...current,
            governance_drop_outline_only: false,
            governance_drop_low_density: false,
          }))
        }
        onOpenChange={changeTuneOpen}
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
