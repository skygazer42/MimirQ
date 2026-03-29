'use client'

/**
 * 知识库管理页面
 * 优化版：卡片视图、视觉增强、交互优化、深色模式适配
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useVirtualizer } from '@tanstack/react-virtual'
import { motion, useReducedMotion } from 'framer-motion'
import { Database, FileText, Settings, Loader2, CheckCircle, XCircle, AlertTriangle, RefreshCw, Layers, HardDrive, FileStack, Eye, LayoutGrid, List as ListIcon, MoreVertical, Zap, Filter } from 'lucide-react'
import { AppFrame } from '@/components/app-frame'
import { WorkbenchPanelDialog, WorkbenchScaffold } from '@/components/workbench'

import { IconButton } from '@/components/ui/icon-button'
import { useDocuments } from '@/hooks/use-documents'
import { formatFileSize, cn, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { toast } from 'sonner'
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

function docGridColumnsForViewportWidth(width: number): number {
  // Keep in sync with the Tailwind grid classes used in the documents grid:
  // `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5`.
  const w = Number(width) || 0
  if (w >= 1536) return 5
  if (w >= 1280) return 4
  if (w >= 1024) return 3
  if (w >= 640) return 2
  return 1
}

export default function KnowledgePage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const reduceMotion = useReducedMotion()
  const lastUrlRef = useRef<string | null>(null)
  const didInitFromUrlRef = useRef(false)
  const layoutTransition = reduceMotion
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
  let extraCardLabel = '处理中'
  let extraCardValue: number = processingDocsCount
  let extraCardColor: 'red' | 'amber' | 'sky' = 'sky'

  if (attentionDocsCount > 0) {
    extraCardLabel = '需关注'
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

  const [docGridColumns, setDocGridColumns] = useState(() => {
    if (globalThis.window === undefined) return 1
    return docGridColumnsForViewportWidth(globalThis.window.innerWidth)
  })

  useEffect(() => {
    const onResize = () => setDocGridColumns(docGridColumnsForViewportWidth(globalThis.window.innerWidth))
    onResize()
    globalThis.window.addEventListener('resize', onResize)
    return () => globalThis.window.removeEventListener('resize', onResize)
  }, [])

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
      toast.error(formatApiError(err, '批量删除失败'))
    } finally {
      setBatchDeleting(false)
      setBatchDeleteOpen(false)
    }
  }, [selectedDocIds, loadDocuments])

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
    if (action === 'disable') {
        return `已禁用 ${res.updated} 份文档`;
    }
    else if (action === 'enable') {
            return `已启用 ${res.updated} 份文档`;
        }
        else if (action === 'archive') {
                return `已归档 ${res.updated} 份文档`;
            }
            else {
                return `已取消归档 ${res.updated} 份文档`;
            }
})()
        )
        setSelectedDocIds([])
        await loadDocuments()
      } catch (err) {
        console.error('Batch lifecycle failed:', err)
        toast.error(formatApiError(err, '批量操作失败'))
      } finally {
        setBatchLifecycleWorking(false)
      }
    },
    [selectedDocIds, loadDocuments]
  )

  const runBatchReingest = useCallback(async () => {
    const ids = [...selectedDocIds]
    if (ids.length === 0) return

    // Keep this conservative to avoid accidental mass re-embedding.
    if (ids.length > 50) {
      toast.error('一次最多重新入库 50 份文档')
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

      toast.success(`已触发重新入库 ${res.queued} 份文档`)
      setSelectedDocIds([])
      await loadDocuments()
    } catch (err) {
      console.error('Batch reingest failed:', err)
      toast.error(formatApiError(err, '批量重新入库失败'))
    } finally {
      setBatchReingestWorking(false)
    }
  }, [loadDocuments, pipelineOptions, pipelineOverridesEnabled, selectedDocIds])

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
        toast.warning(`已上传 ${res.successful_count}/${res.total} 个文件，失败 ${res.failed_count} 个（可重试）`)
      } else {
        toast.success(`已上传 ${res.successful_count} 个文件`)
      }
    } catch (err: any) {
      toast.error(formatApiError(err, '上传失败'))
    }
    e.target.value = ''
  }, [uploadDocuments])

  return (
    <AppFrame>
        <WorkbenchScaffold
          title="知识库管理"
          icon={Database}
          iconColor="text-primary"
          description="管理您的文档资产，构建专属知识大脑"
          leftPanel={
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
              setDatasetScope={(v) => {
                setDatasetScope(v)
                setFolderPath(null)
              }}
            />
          }
          rightPanel={
            <KnowledgeInspector selectedDocs={selectedDocs}>
              {activeTab === 'retrieval' ? (
                <RetrievePreviewPanel selectedDatasetId={selectedDatasetId} />
              ) : null}
            </KnowledgeInspector>
          }

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
	                label="文档总数"
	                value={totalDocs}
	                color="sky"
	                className="bg-card border-border/60 shadow-soft"
	              />
	              <StatCard
	                icon={CheckCircle}
	                label="已就绪"
	                value={completedDocsValue}
	                color="green"
	                className="bg-card border-border/60 shadow-soft"
	              />
	              <StatCard
	                icon={Layers}
	                label="知识分块"
	                value={totalChunksValue}
	                color="teal"
	                className="bg-card border-border/60 shadow-soft"
	              />
	              <StatCard
	                icon={HardDrive}
	                label="存储占用"
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
                {[
                  { key: 'documents' as TabType, label: '文档列表', icon: FileText },
                  { key: 'retrieval' as TabType, label: '检索测试', icon: Zap },
                  { key: 'settings' as TabType, label: '配置', icon: Settings },
	                ].map((tab) => (
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
                    title="范围筛选"
                    trigger={
                      <IconButton
                        label="范围筛选"
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
                      setDatasetScope={(v) => {
                        setDatasetScope(v)
                        setFolderPath(null)
                      }}
                    />
                  </WorkbenchPanelDialog>
                </div>

                {selectedDocIds.length > 0 || activeTab === 'retrieval' ? (
                  <div className="xl:hidden">
                    <WorkbenchPanelDialog
                      open={inspectorOpen}
                      onOpenChange={setInspectorOpen}
                      title="Inspector"
                      trigger={
                        <IconButton
                          label="Inspector"
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
                      label="刷新列表"
                      variant="ghost"
                      onClick={() => loadDocuments()}
                      className="h-9 w-9 text-muted-foreground hover:text-foreground"
                    >
                      <RefreshCw className="w-4 h-4" />
                    </IconButton>
                    <IconButton
                      label="预览分块"
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
                        aria-label="网格视图"
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
                        aria-label="列表视图"
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
	            <KnowledgeDocumentsPanel
	              isLoading={isLoading}
	              documents={documents}
	              filteredDocuments={filteredDocuments}
	              selectedDatasetId={selectedDatasetId}
	              selectedDatasetLabel={
	                selectedDatasetId
	                  ? (datasets.find((d) => d.id === selectedDatasetId)?.name ?? selectedDatasetId)
	                  : undefined
	              }
	              datasetLabelById={datasetLabelById}
	              hasActiveFilters={Boolean(docFilter.trim()) || statusFilter !== 'all' || lifecycleFilter !== 'active' || Boolean(folderPath)}
	              onSwitchToAllDatasets={() => {
	                setDatasetScope(DATASET_ALL)
	                setFolderPath(null)
	              }}
	              scopeSummary={
	                <div className="flex flex-wrap items-center gap-2">
		                  <span
		                    className="inline-flex items-center rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-xs text-muted-foreground"
		                    title={selectedDatasetId ? `dataset ${selectedDatasetId}` : 'all datasets'}
		                  >
		                    范围:{' '}
		                    <span className="font-medium text-foreground ml-1">
		                      {selectedDatasetId
		                        ? (datasets.find((d) => d.id === selectedDatasetId)?.name ?? selectedDatasetId)
		                        : '全部数据集'}
		                    </span>
		                  </span>

	                  {selectedDatasetId && folderPath ? (
	                    <span
	                      className="inline-flex items-center rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-xs text-muted-foreground max-w-xs truncate"
	                      title={folderPath}
	                    >
	                      目录: <span className="ml-1 truncate font-medium text-foreground">{folderPath}</span>
	                    </span>
	                  ) : null}

		                  {statusFilter === 'all' ? null : (
		                    <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-xs text-muted-foreground">
		                      状态:{' '}
		                      <span className="ml-1 font-medium text-foreground">
		                        {(() => {
	    if (statusFilter === 'completed') {
	        return '已就绪';
    }
    else if (statusFilter === 'processing') {
            return '处理中';
        }
        else if (statusFilter === 'failed') {
                return '失败';
            }
            else if (statusFilter === 'quarantined') {
                    return '隔离';
                }
                else {
                    return statusFilter;
                }
})()}
                      </span>
                    </span>
	                  )}

		                  {lifecycleFilter === 'active' ? null : (
		                    <span className="inline-flex items-center rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-xs text-muted-foreground">
		                      生命周期:{' '}
		                      <span className="ml-1 font-medium text-foreground">
		                        {(() => {
	    if (lifecycleFilter === 'archived') {
	        return '已归档';
    }
    else if (lifecycleFilter === 'disabled') {
            return '已禁用';
        }
        else if (lifecycleFilter === 'all') {
                return '全部';
            }
            else {
                return lifecycleFilter;
            }
})()}
                      </span>
                    </span>
                  )}
                </div>
              }

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
              </motion.div>
          ) : null}

          {/* 检索测试 */}
			          {activeTab === 'retrieval' && (
			            <KnowledgeRetrievalPanel
			              selectedDatasetId={selectedDatasetId}
			            />
			          )}

	          {/* 设置 */}
	          {activeTab === 'settings' && (
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
	          )}

        </WorkbenchScaffold>
    </AppFrame>
  )
}
