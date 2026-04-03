'use client'

/**
 * 知识库管理页面
 * 优化版：卡片视图、视觉增强、交互优化、深色模式适配
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useVirtualizer } from '@tanstack/react-virtual'
import { motion, useReducedMotion, type Transition } from 'framer-motion'
import { Database, FileText, Settings, Loader2, CheckCircle, XCircle, AlertTriangle, RefreshCw, Layers, HardDrive, FileStack, Eye, LayoutGrid, List as ListIcon, MoreVertical, Zap, Filter } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { AppFrame } from '@/components/app-frame'
import { WorkbenchPanelDialog, WorkbenchScaffold } from '@/components/workbench'

import { IconButton } from '@/components/ui/icon-button'
import { Panel } from '@/components/ui/panel'
import { useDocuments } from '@/hooks/use-documents'
import { formatFileSize, cn, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { toast } from 'sonner'
import { useRouter } from '@/i18n/navigation'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { toSourcePathPrefix } from '@/lib/document-folders'
import type { ConnectorRunOut, Dataset, DocumentStats } from '@/types'
import { datasetApi, documentApi } from '@/lib/api'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { RetrievePreviewPanel } from '@/components/rag/retrieve-preview-panel'
import { KnowledgeDocumentsPanel } from '@/components/knowledge/knowledge-documents-panel'
import { KnowledgeScopePanel } from '@/components/knowledge/knowledge-scope-panel'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
import { KnowledgeWorkbenchActions } from '@/components/knowledge/knowledge-workbench-actions'
import { KnowledgeRetrievalPanel } from '@/components/knowledge/knowledge-retrieval-panel'
import { KnowledgeSettingsPanel } from '@/components/knowledge/knowledge-settings-panel'
import { useKnowledgeScrollContainer } from '@/components/knowledge/use-knowledge-scroll-container'
import { parseKnowledgeQueryState, serializeKnowledgeQueryState } from '@/components/knowledge/use-knowledge-query-state'
import { useConnectorRuns } from '@/hooks/use-connector-runs'


// Tab 类型
type TabType = 'documents' | 'retrieval' | 'settings'
type ViewMode = 'grid' | 'list'
type DocStatusFilter = 'all' | 'completed' | 'processing' | 'failed' | 'quarantined'
type DocLifecycleFilter = 'active' | 'archived' | 'disabled' | 'all'
type DocSortKey = 'created_at' | 'filename' | 'file_size'
type DocSortDir = 'asc' | 'desc'

function docGridColumnsForPaneWidth(width: number): number {
  // Container-width based: the workbench has optional left/right side panes.
  // Using viewport breakpoints here makes grid cards collapse into narrow columns
  // when both panes are open (large viewport, small center pane).
  const paneWidth = Number(width) || 0
  const minCardWidthPx = 264
  const gapPx = 20 // `gap-5` = 1.25rem ~= 20px
  const cols = Math.floor((paneWidth + gapPx) / (minCardWidthPx + gapPx))
  return Math.max(1, Math.min(5, cols || 1))
}

export default function KnowledgePage() {
  const t = useTranslations('KnowledgePage')
  const router = useRouter()
  const searchParams = useSearchParams()
  const reduceMotion = useReducedMotion()
  const lastUrlRef = useRef<string | null>(null)
  const didInitFromUrlRef = useRef(false)
  const layoutTransition: Transition = reduceMotion
    ? { duration: 0 }
    : { type: 'spring', stiffness: 380, damping: 34, mass: 0.42 }

  const { documents, total, isLoading, uploadDocuments, uploadDocumentFromUrl, deleteDocument, loadDocuments } = useDocuments()
  const [activeTab, setActiveTab] = useState<TabType>('documents')
  // Console-first: list is the primary work surface; grid is an explicit opt-in.
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()
  const [docFilter, setDocFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<DocStatusFilter>('all')
  const [lifecycleFilter, setLifecycleFilter] = useState<DocLifecycleFilter>('active')
  const [sortKey, setSortKey] = useState<DocSortKey>('created_at')
  const [sortDir, setSortDir] = useState<DocSortDir>('desc')
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [batchLifecycleWorking, setBatchLifecycleWorking] = useState(false)
  const [batchReingestWorking, setBatchReingestWorking] = useState(false)
  const [scopeOpen, setScopeOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [expandedConnectorRunId, setExpandedConnectorRunId] = useState<string | null>(null)
  const DATASET_ALL = '__all__'
  const DATASET_DEFAULT = '__default__'
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetScope, setDatasetScope] = useState<string>(DATASET_ALL)
  const [folderPath, setFolderPath] = useState<string | null>(null)
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const selectedDatasetId = datasetScope === DATASET_ALL ? undefined : datasetScope
  const datasetLabelById = useMemo(() => {
    const out: Record<string, string> = {}
    for (const ds of datasets) out[ds.id] = ds.name
    return out
  }, [datasets])
  const [docStats, setDocStats] = useState<DocumentStats | null>(null)
  const [docStatsLoading, setDocStatsLoading] = useState(false)
  const docStatsSeqRef = useRef(0)

  // Init UI state from URL so filters are shareable/bookmarkable.
  useEffect(() => {
    if (didInitFromUrlRef.current) return
    didInitFromUrlRef.current = true

    const state = parseKnowledgeQueryState(new URLSearchParams(searchParams?.toString?.() || ''), {
      datasetAllValue: DATASET_ALL,
    })

    setActiveTab(state.activeTab)
    setViewMode(state.viewMode)
    setDocFilter(state.docFilter)
    setStatusFilter(state.statusFilter)
    setLifecycleFilter(state.lifecycleFilter)
    setDatasetScope(state.datasetScope)
    setFolderPath(state.folderPath)
    setSortKey(state.sortKey)
    setSortDir(state.sortDir)
    setExpandedConnectorRunId(state.connectorRunId)
  }, [DATASET_ALL, searchParams])

  // Keep URL in sync (avoid window scroll; AppFrame handles internal scroll only).
  useEffect(() => {
    if (!didInitFromUrlRef.current) return

    const qs = serializeKnowledgeQueryState(
      {
        activeTab,
        viewMode,
        docFilter,
        statusFilter,
        lifecycleFilter,
        datasetScope,
        folderPath,
        sortKey,
        sortDir,
        connectorRunId: expandedConnectorRunId,
      },
      { datasetAllValue: DATASET_ALL }
    )
    const nextUrl = qs ? `/knowledge?${qs}` : '/knowledge'
    if (lastUrlRef.current === nextUrl) return
    lastUrlRef.current = nextUrl
    router.replace(nextUrl, { scroll: false })
  }, [
    DATASET_ALL,
    activeTab,
    viewMode,
    docFilter,
    statusFilter,
    lifecycleFilter,
    datasetScope,
    folderPath,
    sortKey,
    sortDir,
    expandedConnectorRunId,
    router,
  ])

  const { sentinelRef: mainPaneSentinelRef, scrollEl: mainPaneScrollEl } = useKnowledgeScrollContainer()

  // PageBody is an internal scroll container; on tab switches keep the top anchored.
  useEffect(() => {
    const id = globalThis.window.requestAnimationFrame(() => {
      mainPaneScrollEl?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
    })
    return () => globalThis.window.cancelAnimationFrame(id)
  }, [activeTab, mainPaneScrollEl])

  // Load datasets for filtering (best-effort).
  useEffect(() => {
    let alive = true
    setDatasetsLoading(true)
    datasetApi
      .list({ limit: 200 })
      .then((res) => {
        if (!alive) return
        setDatasets(res.items || [])
      })
      .catch((err) => {
        console.error('Failed to load datasets:', err)
      })
      .finally(() => {
        if (!alive) return
        setDatasetsLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  // Server-side filtering for large knowledge bases (debounced).
  useEffect(() => {
    if (activeTab !== 'documents') return
    const t = globalThis.window.setTimeout(() => {
      loadDocuments({
        limit: 200,
        status: statusFilter === 'all' ? undefined : statusFilter,
        lifecycle: lifecycleFilter,
        q: docFilter.trim() || undefined,
        dataset_id: selectedDatasetId,
        source_path_prefix: selectedDatasetId ? toSourcePathPrefix(folderPath) : undefined,
        order_by: sortKey,
        order_dir: sortDir,
      })
    }, 250)
    return () => globalThis.window.clearTimeout(t)
  }, [activeTab, statusFilter, lifecycleFilter, docFilter, selectedDatasetId, folderPath, sortKey, sortDir, loadDocuments])

  // Accurate dashboard stats (server aggregated) - avoids "only 200 items loaded" bias.
  useEffect(() => {
    if (activeTab !== 'documents') return
    const seq = ++docStatsSeqRef.current
    setDocStatsLoading(true)

    const t = globalThis.window.setTimeout(() => {
      documentApi
        .stats({ q: docFilter.trim() || undefined, dataset_id: selectedDatasetId, lifecycle: lifecycleFilter })
        .then((res) => {
          if (seq !== docStatsSeqRef.current) return
          setDocStats(res)
        })
        .catch((err) => {
          if (seq !== docStatsSeqRef.current) return
          console.error('Failed to load document stats:', err)
          setDocStats(null)
        })
        .finally(() => {
          if (seq !== docStatsSeqRef.current) return
          setDocStatsLoading(false)
        })
    }, 250)

    return () => globalThis.window.clearTimeout(t)
  }, [activeTab, docFilter, selectedDatasetId, lifecycleFilter])

  const totalDocs = docStats?.total ?? total ?? documents.length
  const byStatus = docStats?.by_status || {}
  const statsPlaceholder: string = docStatsLoading ? '…' : '—'
  const completedDocsValue: string | number = docStats ? Number(byStatus.completed || 0) : statsPlaceholder
  const processingDocsCount = docStats ? Number(byStatus.pending || 0) + Number(byStatus.processing || 0) : 0
  const failedDocsCount = docStats ? Number(byStatus.failed || 0) : 0
  const quarantinedDocsCount = docStats ? Number(byStatus.quarantined || 0) : 0
  const processingDocsValue: string | number = docStats ? processingDocsCount : statsPlaceholder
  const failedDocsValue: string | number = docStats ? failedDocsCount : statsPlaceholder
  const quarantinedDocsValue: string | number = docStats ? quarantinedDocsCount : statsPlaceholder
  const totalChunksValue: string | number = docStats ? Number(docStats.total_chunks || 0).toLocaleString() : statsPlaceholder
  const totalSizeValue: string | number = docStats ? formatFileSize(Number(docStats.total_size || 0)) : statsPlaceholder
  const attentionDocsCount = failedDocsCount + quarantinedDocsCount
  const showExtraCard = docStats ? (processingDocsCount > 0 || failedDocsCount > 0 || quarantinedDocsCount > 0) : false
  let extraCardIcon = Loader2
  let extraCardLabel = t('stats.processing')
  let extraCardValue: number = processingDocsCount
  let extraCardColor: 'red' | 'amber' | 'sky' = 'sky'

  if (attentionDocsCount > 0) {
    extraCardLabel = t('stats.needsAttention')
    extraCardValue = attentionDocsCount
    if (failedDocsCount > 0) {
      extraCardIcon = XCircle
      extraCardColor = 'red'
    } else {
      extraCardIcon = AlertTriangle
      extraCardColor = 'amber'
    }
  }

  // The backend already applies q/status/dataset filters; keep UI list consistent with server results.
  const filteredDocuments = useMemo(() => documents, [documents])

  const [docGridColumns, setDocGridColumns] = useState(1)

  useEffect(() => {
    const el = mainPaneScrollEl
    if (!el) return

    const update = () => setDocGridColumns(docGridColumnsForPaneWidth(el.clientWidth))
    update()

    if (typeof ResizeObserver === 'undefined') {
      globalThis.window.addEventListener('resize', update)
      return () => globalThis.window.removeEventListener('resize', update)
    }

    const ro = new ResizeObserver(() => update())
    ro.observe(el)
    return () => ro.disconnect()
  }, [mainPaneScrollEl])

  const docGridRowCount = useMemo(() => {
    const cols = Math.max(1, docGridColumns)
    return Math.ceil(filteredDocuments.length / cols)
  }, [filteredDocuments.length, docGridColumns])

  const docsGridVirtualizer = useVirtualizer({
    count: activeTab === 'documents' && viewMode === 'grid' ? docGridRowCount : 0,
    getScrollElement: () => mainPaneScrollEl,
    estimateSize: () => 340,
    overscan: 6,
  })

	  const docsTableVirtualizer = useVirtualizer({
	    count: activeTab === 'documents' && viewMode === 'list' ? filteredDocuments.length : 0,
	    getScrollElement: () => mainPaneScrollEl,
	    estimateSize: () => 60,
	    overscan: 10,
	    getItemKey: (idx) => filteredDocuments[idx]?.id ?? idx,
	  })

  const selectedSet = useMemo(() => new Set(selectedDocIds), [selectedDocIds])
  const allVisibleSelected = filteredDocuments.length > 0 && filteredDocuments.every((d) => selectedSet.has(d.id))
  const tabs = useMemo(
    () =>
      ([
        { key: 'documents' as TabType, icon: FileText },
        { key: 'retrieval' as TabType, icon: Zap },
        { key: 'settings' as TabType, icon: Settings },
      ]).map((tab) => ({
        ...tab,
        label: t(`tabs.${tab.key}.label`),
      })),
    [t]
  )
  const statusSummaryLabel = useMemo(() => {
    switch (statusFilter) {
      case 'completed':
        return t('scopeSummary.status.completed')
      case 'processing':
        return t('scopeSummary.status.processing')
      case 'failed':
        return t('scopeSummary.status.failed')
      case 'quarantined':
        return t('scopeSummary.status.quarantined')
      default:
        return statusFilter
    }
  }, [statusFilter, t])
  const lifecycleSummaryLabel = useMemo(() => {
    switch (lifecycleFilter) {
      case 'archived':
        return t('scopeSummary.lifecycle.archived')
      case 'disabled':
        return t('scopeSummary.lifecycle.disabled')
      case 'all':
        return t('scopeSummary.lifecycle.all')
      default:
        return lifecycleFilter
    }
  }, [lifecycleFilter, t])
  const selectedDatasetLabel = useMemo(() => {
    if (!selectedDatasetId) return undefined
    return datasets.find((d) => d.id === selectedDatasetId)?.name ?? selectedDatasetId
  }, [datasets, selectedDatasetId])
  const handleDatasetScopeChange = useCallback((value: string) => {
    setDatasetScope(value)
    setFolderPath(null)
  }, [])
  const documentScopeSummary = (
    <div className="flex flex-wrap items-center gap-2 lg:hidden">
      <span
        className="inline-flex items-center rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-xs text-muted-foreground"
        title={
          selectedDatasetId
            ? t('scopeSummary.datasetTitleScoped', { datasetId: selectedDatasetId })
            : t('scopeSummary.datasetTitleAll')
        }
      >
        {t('scopeSummary.labels.scope')}:{' '}
        <span className="ml-1 font-medium text-foreground">
          {selectedDatasetId ? selectedDatasetLabel : t('scopeSummary.allDatasets')}
        </span>
      </span>

      {selectedDatasetId && folderPath ? (
        <span
          className="inline-flex max-w-xs items-center rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-xs text-muted-foreground truncate"
          title={folderPath}
        >
          {t('scopeSummary.labels.directory')}:{' '}
          <span className="ml-1 truncate font-medium text-foreground">{folderPath}</span>
        </span>
      ) : null}

      {statusFilter === 'all' ? null : (
        <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-xs text-muted-foreground">
          {t('scopeSummary.labels.status')}:{' '}
          <span className="ml-1 font-medium text-foreground">{statusSummaryLabel}</span>
        </span>
      )}

      {lifecycleFilter === 'active' ? null : (
        <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-xs text-muted-foreground">
          {t('scopeSummary.labels.lifecycle')}:{' '}
          <span className="ml-1 font-medium text-foreground">{lifecycleSummaryLabel}</span>
        </span>
      )}
    </div>
  )

  const toggleDocSelection = useCallback((docId: string) => {
    setSelectedDocIds((prev) => (prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]))
  }, [])

  const toggleSelectAllVisible = useCallback(() => {
    setSelectedDocIds((prev) => {
      if (allVisibleSelected) return []
      const next = new Set(prev)
      for (const doc of filteredDocuments) next.add(doc.id)
      return Array.from(next)
    })
  }, [allVisibleSelected, filteredDocuments])

  // Keep selection in sync when the visible list changes.
  useEffect(() => {
    const valid = new Set(documents.map((d) => d.id))
    setSelectedDocIds((prev) => {
      const next = prev.filter((id) => valid.has(id))
      return next.length === prev.length ? prev : next
    })
  }, [documents])

  useEffect(() => {
    if (activeTab !== 'documents') setSelectedDocIds([])
  }, [activeTab])

  const confirmBatchDelete = useCallback(async () => {
    const ids = [...selectedDocIds]
    if (ids.length === 0) return
    setBatchDeleting(true)
    try {
      const res = await documentApi.batchDelete(ids)
      if (res?.denied?.length || res?.not_found?.length) {
        console.warn('Batch delete partial result:', res)
      }
      setSelectedDocIds([])
      await loadDocuments()
    } catch (err) {
      console.error('Batch delete failed:', err)
      toast.error(formatApiError(err, t('toasts.batchDeleteFailed')))
    } finally {
      setBatchDeleting(false)
      setBatchDeleteOpen(false)
    }
  }, [selectedDocIds, loadDocuments, t])

  const selectedDocs = useMemo(
    () => filteredDocuments.filter((d) => selectedSet.has(d.id)),
    [filteredDocuments, selectedSet]
  )
  const anySelectedDisabled = useMemo(() => selectedDocs.some((d) => Boolean(d.disabled_at)), [selectedDocs])
  const anySelectedEnabled = useMemo(() => selectedDocs.some((d) => !d.disabled_at), [selectedDocs])
  const anySelectedArchived = useMemo(() => selectedDocs.some((d) => Boolean(d.archived_at)), [selectedDocs])
  const anySelectedNotArchived = useMemo(() => selectedDocs.some((d) => !d.archived_at), [selectedDocs])

  const runBatchLifecycle = useCallback(
    async (action: 'disable' | 'enable' | 'archive' | 'unarchive') => {
      const ids = [...selectedDocIds]
      if (ids.length === 0) return
      setBatchLifecycleWorking(true)
      try {
        const fn =
          (() => {
    if (action === 'disable') {
        return documentApi.batchDisable;
    }
    else if (action === 'enable') {
            return documentApi.batchEnable;
        }
        else if (action === 'archive') {
                return documentApi.batchArchive;
            }
            else {
                return documentApi.batchUnarchive;
            }
})()

        const res = await fn(ids)
        if (res?.denied?.length || res?.not_found?.length || res?.conflicts?.length) {
          console.warn('Batch lifecycle partial result:', res)
        }
        toast.success(
          (() => {
            if (action === 'disable') return t('toasts.batchLifecycle.disable', { count: res.updated })
            if (action === 'enable') return t('toasts.batchLifecycle.enable', { count: res.updated })
            if (action === 'archive') return t('toasts.batchLifecycle.archive', { count: res.updated })
            return t('toasts.batchLifecycle.unarchive', { count: res.updated })
          })()
        )
        setSelectedDocIds([])
        await loadDocuments()
      } catch (err) {
        console.error('Batch lifecycle failed:', err)
        toast.error(formatApiError(err, t('toasts.batchLifecycleFailed')))
      } finally {
        setBatchLifecycleWorking(false)
      }
    },
    [selectedDocIds, loadDocuments, t]
  )

  const runBatchReingest = useCallback(async () => {
    const ids = [...selectedDocIds]
    if (ids.length === 0) return

    // Keep this conservative to avoid accidental mass re-embedding.
    if (ids.length > 50) {
      toast.error(t('toasts.reingestLimitExceeded'))
      return
    }

    setBatchReingestWorking(true)
    try {
      const res = await documentApi.batchReingest({
        document_ids: ids,
        patch: pipelineOverridesEnabled ? pipelineOptions : undefined,
        replace: pipelineOverridesEnabled,
        force: true,
        skip_if_unchanged: false,
      })

      if (res?.denied?.length || res?.not_found?.length || res?.conflicts?.length) {
        console.warn('Batch reingest partial result:', res)
      }

      toast.success(t('toasts.reingestQueued', { count: res.queued }))
      setSelectedDocIds([])
      await loadDocuments()
    } catch (err) {
      console.error('Batch reingest failed:', err)
      toast.error(formatApiError(err, t('toasts.reingestFailed')))
    } finally {
      setBatchReingestWorking(false)
    }
  }, [loadDocuments, pipelineOptions, pipelineOverridesEnabled, selectedDocIds, t])

  const {
    connectorRuns,
    connectorRunsLoading,
    connectorRunsUpdatedAt,
    loadConnectorRuns,
    cancelConnectorRun,
    resumeConnectorRun,
    retryFailedConnectorRun,
  } = useConnectorRuns({ selectedDatasetId, loadDocuments })

  useEffect(() => {
    if (activeTab !== 'settings') return
    detachPromise(loadConnectorRuns({ datasetId: selectedDatasetId }))
  }, [activeTab, loadConnectorRuns, selectedDatasetId])

  const handleConnectorRunCreated = useCallback(
    (run: ConnectorRunOut) => {
      const runId = String(run?.id || '').trim()
      if (!runId) return

      const targetDatasetId = String(run?.dataset_id || '').trim()
      if (targetDatasetId && selectedDatasetId && targetDatasetId !== selectedDatasetId) {
        // Ensure the run is visible in the settings panel by switching the scope explicitly.
        setDatasetScope(targetDatasetId)
        setFolderPath(null)
      }

      setActiveTab('settings')
      setExpandedConnectorRunId(runId)
    },
    [selectedDatasetId, setActiveTab, setDatasetScope, setExpandedConnectorRunId, setFolderPath]
  )

  // 处理文件上传
  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    try {
      const res = await uploadDocuments(Array.from(files), { maxRetries: 1, maxConcurrent: 5 })
      if (res.failed_count > 0) {
        toast.warning(
          t('toasts.uploadPartial', {
            successful: res.successful_count,
            total: res.total,
            failed: res.failed_count,
          })
        )
      } else {
        toast.success(t('toasts.uploadSuccess', { count: res.successful_count }))
      }
    } catch (err: any) {
      toast.error(formatApiError(err, t('toasts.uploadFailed')))
    }
    e.target.value = ''
  }, [uploadDocuments, t])

  return (
    <AppFrame>
        <WorkbenchScaffold
          title={t("header.title")}
          icon={Database}
          iconColor="text-primary"
          description={t('header.description')}
          leftPanel={null}
          rightPanel={null}

          actions={
            <KnowledgeWorkbenchActions
              datasets={datasets}
              datasetsLoading={datasetsLoading}
              selectedDatasetId={selectedDatasetId}
              datasetDefaultValue={DATASET_DEFAULT}
              handleFileUpload={handleFileUpload}
              uploadDocumentFromUrl={uploadDocumentFromUrl}
              loadDocuments={loadDocuments}
              loadConnectorRuns={loadConnectorRuns}
              onConnectorRunCreated={handleConnectorRunCreated}
            />
          }
	          top={
	            <StatsGrid className={showExtraCard ? "lg:grid-cols-5" : "lg:grid-cols-4"}>
	              <StatCard
	                icon={FileStack}
	                label={t("stats.totalDocuments")}
	                value={totalDocs}
	                color="sky"
	                className="bg-card border-border/60 shadow-soft"
	              />
	              <StatCard
	                icon={CheckCircle}
	                label={t('stats.ready')}
	                value={completedDocsValue}
	                color="green"
	                className="bg-card border-border/60 shadow-soft"
	              />
	              <StatCard
	                icon={Layers}
	                label={t('stats.totalChunks')}
	                value={totalChunksValue}
	                color="teal"
	                className="bg-card border-border/60 shadow-soft"
	              />
	              <StatCard
	                icon={HardDrive}
	                label={t('stats.storageUsage')}
	                value={totalSizeValue}
	                color="orange"
	                className="bg-card border-border/60 shadow-soft"
	              />
	              {showExtraCard && (
	                <StatCard
	                  icon={extraCardIcon}
	                  label={extraCardLabel}
	                  value={extraCardValue}
	                  color={extraCardColor}
	                  className="bg-card border-border/60 shadow-soft"
	                />
	              )}
	            </StatsGrid>
	          }
	          toolbar={
            <div className="flex items-center justify-between">
              <div className="flex gap-1 -mb-px">
                {tabs.map((tab) => (
	                  <button
	                    key={tab.key}
	                    onClick={() => setActiveTab(tab.key)}
	                    className={cn(
	                      'flex h-10 items-center gap-2 px-4 text-sm font-medium border-b-2 transition-colors focus-ring',
	                      activeTab === tab.key
	                        ? 'text-primary border-primary bg-primary/10'
	                        : 'text-muted-foreground border-transparent hover:text-foreground hover:bg-muted/30'
	                    )}
	                  >
                    <tab.icon
                      className={cn(
                        "w-4 h-4",
                        activeTab === tab.key ? "text-primary" : "text-muted-foreground"
                      )}
                    />
                    {tab.label}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                <div className="lg:hidden">
                  <WorkbenchPanelDialog
                    open={scopeOpen}
                    onOpenChange={setScopeOpen}
                    title={t('dialogs.scope.title')}
                    trigger={
                      <IconButton
                        label={t('actions.scope')}
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                      >
                        <Filter className="w-4 h-4" />
                      </IconButton>
                    }
                  >
                    <KnowledgeScopePanel
                      datasets={datasets}
                      datasetsLoading={datasetsLoading}
                      datasetScope={datasetScope}
                      datasetAllValue={DATASET_ALL}
                      selectedDatasetId={selectedDatasetId}
                      lifecycleFilter={lifecycleFilter}
                      setLifecycleFilter={setLifecycleFilter}
                      folderPath={folderPath}
                      setFolderPath={setFolderPath}
                      statusFilter={statusFilter}
                      setStatusFilter={setStatusFilter}
                      totalDocs={totalDocs}
                      completedDocsValue={completedDocsValue}
                      processingDocsValue={processingDocsValue}
                      failedDocsValue={failedDocsValue}
                      quarantinedDocsValue={quarantinedDocsValue}
                      setDatasetScope={handleDatasetScopeChange}
                    />
                  </WorkbenchPanelDialog>
                </div>

                {selectedDocIds.length > 0 || activeTab === 'retrieval' ? (
                  <div className="xl:hidden">
                    <WorkbenchPanelDialog
                      open={inspectorOpen}
                      onOpenChange={setInspectorOpen}
                      title={t('dialogs.inspector.title')}
                      trigger={
                        <IconButton
                          label={t('dialogs.inspector.title')}
                          variant="ghost"
                          className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        >
                          <MoreVertical className="w-4 h-4" />
                        </IconButton>
                      }
                    >
                      <KnowledgeInspector selectedDocs={selectedDocs} className="flex-1">
                        {activeTab === 'retrieval' ? (
                          <RetrievePreviewPanel selectedDatasetId={selectedDatasetId} />
                        ) : null}
                      </KnowledgeInspector>
                    </WorkbenchPanelDialog>
                  </div>
                ) : null}

                {activeTab === 'documents' ? (
                  <>
                    <IconButton
                      label={t('actions.refresh')}
                      variant="ghost"
                      onClick={() => loadDocuments()}
                      className="h-9 w-9 text-muted-foreground hover:text-foreground"
                    >
                      <RefreshCw className="w-4 h-4" />
                    </IconButton>
                    <IconButton
                      label={t('actions.previewChunks')}
                      variant="ghost"
                      onClick={() => globalThis.window.open('/chunk-preview', '_blank')}
                      className="h-9 w-9 text-muted-foreground hover:text-foreground"
                    >
                      <Eye className="w-4 h-4" />
                    </IconButton>
                    <motion.div
                      layout={!reduceMotion}
                      transition={layoutTransition}
                      className="bg-muted/40 border border-border/60 p-1 rounded-lg flex gap-1"
                    >
                      <button
                        aria-label={t("actions.viewGrid")}
                        onClick={() => setViewMode('grid')}
                        className={cn(
                          "relative p-1.5 rounded-md transition-colors focus-ring",
                          viewMode === 'grid'
                            ? "bg-background shadow-soft text-primary"
                            : "text-muted-foreground hover:text-foreground hover:bg-muted/40"
                        )}
                      >
                        {viewMode === 'grid' ? (
                          <motion.span
                            layoutId="knowledge-view-mode-active-pill"
                            transition={layoutTransition}
                            aria-hidden="true"
                            className="absolute inset-0 rounded-md bg-background shadow-soft"
                          />
                        ) : null}
                        <LayoutGrid className="relative z-10 w-4 h-4" />
                      </button>
                      <button
                        aria-label={t("actions.viewList")}
                        onClick={() => setViewMode('list')}
                        className={cn(
                          "relative p-1.5 rounded-md transition-colors focus-ring",
                          viewMode === 'list'
                            ? "bg-background shadow-soft text-primary"
                            : "text-muted-foreground hover:text-foreground hover:bg-muted/40"
                        )}
                      >
                        {viewMode === 'list' ? (
                          <motion.span
                            layoutId="knowledge-view-mode-active-pill"
                            transition={layoutTransition}
                            aria-hidden="true"
                            className="absolute inset-0 rounded-md bg-background shadow-soft"
                          />
                        ) : null}
                        <ListIcon className="relative z-10 w-4 h-4" />
                      </button>
                    </motion.div>
                  </>
                ) : null}
              </div>
            </div>
          }
          bodyClassName="pt-6 scroll-smooth"
        >
          <div
            ref={mainPaneSentinelRef}
            data-knowledge-main-scroll-sentinel="true"
            aria-hidden="true"
            className="h-0 w-0"
          />
	          {activeTab === 'documents' ? (
              <motion.div
                layout={!reduceMotion}
                layoutId="knowledge-documents-surface"
                transition={layoutTransition}
              >
                <Panel
                  padding="none"
                  className="overflow-hidden rounded-[28px] border-border/70 bg-card/95 shadow-soft"
                >
                  <div className="grid grid-cols-1 lg:grid-cols-[18.5rem_minmax(0,1fr)] xl:grid-cols-[18.5rem_minmax(0,1fr)_20rem]">
                    <aside className="hidden border-r border-border/60 bg-muted/[0.14] lg:block">
                      <KnowledgeScopePanel
                        surface="embedded"
                        datasets={datasets}
                        datasetsLoading={datasetsLoading}
                        datasetScope={datasetScope}
                        datasetAllValue={DATASET_ALL}
                        selectedDatasetId={selectedDatasetId}
                        lifecycleFilter={lifecycleFilter}
                        setLifecycleFilter={setLifecycleFilter}
                        folderPath={folderPath}
                        setFolderPath={setFolderPath}
                        statusFilter={statusFilter}
                        setStatusFilter={setStatusFilter}
                        totalDocs={totalDocs}
                        completedDocsValue={completedDocsValue}
                        processingDocsValue={processingDocsValue}
                        failedDocsValue={failedDocsValue}
                        quarantinedDocsValue={quarantinedDocsValue}
                        setDatasetScope={handleDatasetScopeChange}
                      />
                    </aside>

                    <div className="min-w-0">
                      <KnowledgeDocumentsPanel
                        embedded
                        isLoading={isLoading}
                        documents={documents}
                        filteredDocuments={filteredDocuments}
                        selectedDatasetId={selectedDatasetId}
                        selectedDatasetLabel={selectedDatasetLabel}
                        datasetLabelById={datasetLabelById}
                        hasActiveFilters={Boolean(docFilter.trim()) || statusFilter !== 'all' || lifecycleFilter !== 'active' || Boolean(folderPath)}
                        onSwitchToAllDatasets={() => {
                          setDatasetScope(DATASET_ALL)
                          setFolderPath(null)
                        }}
                        scopeSummary={documentScopeSummary}
                        docFilter={docFilter}
                        setDocFilter={setDocFilter}
                        onClearFilters={() => {
                          setDocFilter('')
                          setStatusFilter('all')
                          setLifecycleFilter('active')
                          setFolderPath(null)
                        }}
                        sortKey={sortKey}
                        sortDir={sortDir}
                        setSortKey={setSortKey}
                        setSortDir={setSortDir}
                        viewMode={viewMode}
                        docGridColumns={docGridColumns}
                        docGridRowCount={docGridRowCount}
                        docsGridVirtualizer={docsGridVirtualizer}
                        docsTableVirtualizer={docsTableVirtualizer}
                        selectedDocIds={selectedDocIds}
                        setSelectedDocIds={setSelectedDocIds}
                        selectedSet={selectedSet}
                        allVisibleSelected={allVisibleSelected}
                        toggleSelectAllVisible={toggleSelectAllVisible}
                        toggleDocSelection={toggleDocSelection}
                        batchDeleteOpen={batchDeleteOpen}
                        setBatchDeleteOpen={setBatchDeleteOpen}
                        batchDeleting={batchDeleting}
                        confirmBatchDelete={confirmBatchDelete}
                        batchLifecycleWorking={batchLifecycleWorking}
                        batchReingestWorking={batchReingestWorking}
                        runBatchReingest={runBatchReingest}
                        runBatchLifecycle={runBatchLifecycle}
                        anySelectedDisabled={anySelectedDisabled}
                        anySelectedEnabled={anySelectedEnabled}
                        anySelectedArchived={anySelectedArchived}
                        anySelectedNotArchived={anySelectedNotArchived}
                        deleteDocument={deleteDocument}
                        handleFileUpload={handleFileUpload}
                      />
                    </div>

                    <aside className="hidden border-l border-border/60 bg-muted/[0.1] xl:block">
                      <KnowledgeInspector embedded selectedDocs={selectedDocs} />
                    </aside>
                  </div>
                </Panel>
              </motion.div>
          ) : null}

          {/* 检索测试 */}
          {activeTab === 'retrieval' && (
            <Panel padding="none" className="overflow-hidden rounded-[28px] border-border/70 bg-card/95 shadow-soft">
              <div className="grid grid-cols-1 lg:grid-cols-[18.5rem_minmax(0,1fr)] xl:grid-cols-[18.5rem_minmax(0,1fr)_20rem]">
                <aside className="hidden border-r border-border/60 bg-muted/[0.14] lg:block">
                  <KnowledgeScopePanel
                    surface="embedded"
                    datasets={datasets}
                    datasetsLoading={datasetsLoading}
                    datasetScope={datasetScope}
                    datasetAllValue={DATASET_ALL}
                    selectedDatasetId={selectedDatasetId}
                    lifecycleFilter={lifecycleFilter}
                    setLifecycleFilter={setLifecycleFilter}
                    folderPath={folderPath}
                    setFolderPath={setFolderPath}
                    statusFilter={statusFilter}
                    setStatusFilter={setStatusFilter}
                    totalDocs={totalDocs}
                    completedDocsValue={completedDocsValue}
                    processingDocsValue={processingDocsValue}
                    failedDocsValue={failedDocsValue}
                    quarantinedDocsValue={quarantinedDocsValue}
                    setDatasetScope={handleDatasetScopeChange}
                  />
                </aside>

                <div className="min-w-0 px-4 py-5 md:px-5">
                  <KnowledgeRetrievalPanel selectedDatasetId={selectedDatasetId} />
                </div>

                <aside className="hidden border-l border-border/60 bg-muted/[0.1] xl:block">
                  <KnowledgeInspector embedded selectedDocs={selectedDocs}>
                    <RetrievePreviewPanel selectedDatasetId={selectedDatasetId} />
                  </KnowledgeInspector>
                </aside>
              </div>
            </Panel>
          )}

          {/* 设置 */}
          {activeTab === 'settings' && (
            <Panel padding="none" className="overflow-hidden rounded-[28px] border-border/70 bg-card/95 shadow-soft">
              <div className="grid grid-cols-1 lg:grid-cols-[18.5rem_minmax(0,1fr)]">
                <aside className="hidden border-r border-border/60 bg-muted/[0.14] lg:block">
                  <KnowledgeScopePanel
                    surface="embedded"
                    datasets={datasets}
                    datasetsLoading={datasetsLoading}
                    datasetScope={datasetScope}
                    datasetAllValue={DATASET_ALL}
                    selectedDatasetId={selectedDatasetId}
                    lifecycleFilter={lifecycleFilter}
                    setLifecycleFilter={setLifecycleFilter}
                    folderPath={folderPath}
                    setFolderPath={setFolderPath}
                    statusFilter={statusFilter}
                    setStatusFilter={setStatusFilter}
                    totalDocs={totalDocs}
                    completedDocsValue={completedDocsValue}
                    processingDocsValue={processingDocsValue}
                    failedDocsValue={failedDocsValue}
                    quarantinedDocsValue={quarantinedDocsValue}
                    setDatasetScope={handleDatasetScopeChange}
                  />
                </aside>

                <div className="min-w-0 px-4 py-5 md:px-5">
                  <KnowledgeSettingsPanel
                    selectedDatasetId={selectedDatasetId}
                    connectorRuns={connectorRuns}
                    connectorRunsLoading={connectorRunsLoading}
                    connectorRunsUpdatedAt={connectorRunsUpdatedAt}
                    onLoadConnectorRuns={loadConnectorRuns}
                    expandedConnectorRunId={expandedConnectorRunId}
                    onToggleExpandedConnectorRun={(runId) =>
                      setExpandedConnectorRunId((prev) => (prev === runId ? null : runId))
                    }
                    onCancelConnectorRun={cancelConnectorRun}
                    onResumeConnectorRun={resumeConnectorRun}
                    onRetryFailedConnectorRun={retryFailedConnectorRun}
                  />
                </div>
              </div>
            </Panel>
          )}

        </WorkbenchScaffold>
    </AppFrame>
  )
}
