'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Dataset as DatasetIcon, Filter, History, KnowledgeBase, Loader2, MoreHorizontal, RefreshCw } from '@/components/icons'
import { AppFrame } from '@/components/app-frame'
import { DatasetFolderTree } from '@/components/document-library/dataset-folder-tree'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { KnowledgeDocumentsPanel } from '@/components/knowledge/knowledge-documents-panel'
import { KnowledgeConnectorRunsPanel } from '@/components/knowledge/knowledge-connector-runs-panel'
import { KnowledgeWorkbenchActions, type KnowledgeWorkbenchActionsHandle } from '@/components/knowledge/knowledge-workbench-actions'
import {
  parseKnowledgeQueryState,
  serializeKnowledgeQueryState,
  type KnowledgeQueryState,
  type KnowledgeStatusFilter,
} from '@/components/knowledge/use-knowledge-query-state'
import { RetrievePreviewPanel } from '@/components/rag/retrieve-preview-panel'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useConnectorRuns } from '@/hooks/use-connector-runs'
import { useDatasets } from '@/hooks/use-datasets'
import { useDocuments } from '@/hooks/use-documents'
import { useIsMobile } from '@/hooks/use-media-query'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'

import styles from './knowledge-page.module.css'

const DATASET_ALL = '__all__'
const DEFAULT_PAGE_SIZE = 20
const TABS = ['documents', 'retrieval'] as const
const STATUS_FILTERS: KnowledgeStatusFilter[] = ['all', 'completed', 'processing', 'failed', 'quarantined']
const SORT_OPTIONS = [
  { value: 'created_at:desc', label: '最新上传' },
  { value: 'created_at:asc', label: '最早上传' },
  { value: 'filename:asc', label: '文件名 A–Z' },
  { value: 'filename:desc', label: '文件名 Z–A' },
  { value: 'file_size:desc', label: '大小从大到小' },
  { value: 'file_size:asc', label: '大小从小到大' },
]

export default function KnowledgePage() {
  const t = useTranslations('KnowledgePage')
  const scopeT = useTranslations('KnowledgeScopePanel')
  const searchParams = useSearchParams()
  const router = useRouter()
  const isMobile = useIsMobile()
  const queryClient = useQueryClient()
  const importActionsRef = useRef<KnowledgeWorkbenchActionsHandle>(null)
  const { openDocument } = useDocumentView()
  const queryString = searchParams.toString()
  const [query, setQuery] = useState(() => parseKnowledgeQueryState(
    new URLSearchParams(queryString), { datasetAllValue: DATASET_ALL }
  ))
  const queryRef = useRef(query)
  const writtenQueryRef = useRef(queryString)
  const [documentsPage, setDocumentsPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [scopeOpen, setScopeOpen] = useState(false)
  const [tasksOpen, setTasksOpen] = useState(false)
  const [operationsOpen, setOperationsOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false)
  const [batchDeleteError, setBatchDeleteError] = useState<string | null>(null)
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [batchLifecycleWorking, setBatchLifecycleWorking] = useState(false)
  const [batchReingestWorking, setBatchReingestWorking] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams(queryString)
    if (params.get('tab') === 'settings' && !params.get('run') && params.get('tasks') !== '1') {
      router.replace('/settings#sec-models')
    }
  }, [queryString, router])

  // Only external navigation reads state back. Our own URL writes preserve the
  // exact input string, including a trailing space while a name is being typed.
  useEffect(() => {
    if (queryString === writtenQueryRef.current) return
    writtenQueryRef.current = queryString
    const next = parseKnowledgeQueryState(new URLSearchParams(queryString), { datasetAllValue: DATASET_ALL })
    queryRef.current = next
    setQuery(next)
    setDocumentsPage(1)
    setSelectedDocIds([])
  }, [queryString])

  const updateQuery = useCallback((patch: Partial<KnowledgeQueryState>) => {
    const next = { ...queryRef.current, ...patch, viewMode: 'list' as const }
    queryRef.current = next
    setQuery(next)
    setDocumentsPage(1)
    setSelectedDocIds([])
    const nextQuery = serializeKnowledgeQueryState(next, { datasetAllValue: DATASET_ALL })
    writtenQueryRef.current = nextQuery
    globalThis.window.history.replaceState(
      globalThis.window.history.state,
      '',
      nextQuery ? '/knowledge?' + nextQuery : '/knowledge'
    )
  }, [])

  const { activeTab, datasetScope, docFilter, statusFilter, lifecycleFilter, folderPath, sortKey, sortDir } = query
  const selectedDatasetId = datasetScope === DATASET_ALL ? undefined : datasetScope
  const { datasets, isLoading: datasetsLoading } = useDatasets()
  const selectedDataset = datasets.find(dataset => dataset.id === selectedDatasetId) ?? null
  const selectedDatasetLabel = selectedDataset?.name || selectedDatasetId
  const datasetLabelById = useMemo(
    () => Object.fromEntries(datasets.map(dataset => [dataset.id, dataset.name])),
    [datasets]
  )
  const retrievalDatasetIds = useMemo(() => datasets.map(dataset => dataset.id).filter(Boolean), [datasets])

  const { documents, total, isLoading, error, loadDocuments, deleteDocument, uploadDocuments, uploadDocumentFromUrl } = useDocuments({
    dataset_id: selectedDatasetId,
    status: activeTab === 'documents' && statusFilter !== 'all' ? statusFilter : undefined,
    lifecycle: activeTab === 'documents' ? lifecycleFilter : 'active',
    source_path_prefix: activeTab === 'documents' ? folderPath || undefined : undefined,
    q: activeTab === 'documents' ? docFilter.trim() || undefined : undefined,
    order_by: sortKey,
    order_dir: sortDir,
    skip: activeTab === 'documents' ? (documentsPage - 1) * pageSize : 0,
    limit: pageSize,
  })

  const statsParams = {
    dataset_id: selectedDatasetId,
    lifecycle: activeTab === 'documents' ? lifecycleFilter : 'active' as const,
    q: activeTab === 'documents' ? docFilter.trim() || undefined : undefined,
  }
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['documents', 'stats', statsParams],
    queryFn: () => documentApi.stats(statsParams),
    enabled: !folderPath || activeTab !== 'documents',
  })
  const statusCounts = !folderPath && stats ? {
    all: stats.total,
    completed: stats.by_status?.completed ?? 0,
    processing: (stats.by_status?.processing ?? 0) + (stats.by_status?.pending ?? 0),
    failed: stats.by_status?.failed ?? 0,
    quarantined: stats.by_status?.quarantined ?? 0,
  } : undefined
  const totalChunks = !folderPath && statusFilter === 'all' ? stats?.total_chunks : undefined
  const documentCount = folderPath && activeTab === 'documents' ? total : stats?.total
  const pageCount = Math.max(1, Math.ceil(total / pageSize))

  useEffect(() => {
    if (isLoading) return
    setDocumentsPage(current => Math.min(current, pageCount))
  }, [isLoading, pageCount])

  const {
    connectorRuns, connectorRunsLoading, loadConnectorRuns,
    cancelConnectorRun, resumeConnectorRun, retryFailedConnectorRun,
  } = useConnectorRuns({ selectedDatasetId })
  const activeTasksCount = connectorRuns.filter(run => run.status === 'running' || run.status === 'pending').length

  useEffect(() => {
    if (tasksOpen) detachPromise(loadConnectorRuns({ datasetId: selectedDatasetId }))
  }, [loadConnectorRuns, selectedDatasetId, tasksOpen])

  useEffect(() => {
    if (query.connectorRunId || query.tasksOpen) setTasksOpen(true)
  }, [query.connectorRunId, query.tasksOpen])

  const refreshDocuments = useCallback(async () => {
    await Promise.all([
      loadDocuments(),
      queryClient.invalidateQueries({ queryKey: queryKeys.documents.all }),
    ])
  }, [loadDocuments, queryClient])

  const handleDatasetScopeChange = useCallback((value: string) => {
    updateQuery({ datasetScope: value, folderPath: null })
  }, [updateQuery])

  const handleFileUpload = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const input = event.target
    const files = Array.from(input.files || [])
    if (!files.length) return
    try {
      await uploadDocuments(files)
      toast.success(t('toasts.uploadSuccess', { count: files.length }))
      await refreshDocuments()
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.uploadFailed')))
    } finally {
      input.value = ''
    }
  }, [refreshDocuments, t, uploadDocuments])

  const selectedSet = useMemo(() => new Set(selectedDocIds), [selectedDocIds])
  const selectedDocuments = documents.filter(doc => selectedSet.has(doc.id))
  const allVisibleSelected = documents.length > 0 && documents.every(doc => selectedSet.has(doc.id))
  const toggleDocSelection = useCallback((docId: string) => {
    setSelectedDocIds(previous => previous.includes(docId) ? previous.filter(id => id !== docId) : [...previous, docId])
  }, [])
  const toggleSelectAllVisible = () => {
    setSelectedDocIds(allVisibleSelected ? [] : documents.map(doc => doc.id))
  }
  const batchWorking = batchDeleting || batchLifecycleWorking || batchReingestWorking

  useEffect(() => {
    if (isLoading) return
    const validIds = new Set(documents.map(doc => doc.id))
    setSelectedDocIds(previous => {
      const next = previous.filter(id => validIds.has(id))
      return next.length === previous.length ? previous : next
    })
  }, [documents, isLoading])

  const runBatchLifecycle = async (action: 'enable' | 'disable' | 'archive' | 'unarchive') => {
    if (!selectedDocIds.length || batchWorking) return
    setBatchLifecycleWorking(true)
    try {
      const lifecycleAction = {
        enable: documentApi.batchEnable, disable: documentApi.batchDisable,
        archive: documentApi.batchArchive, unarchive: documentApi.batchUnarchive,
      }[action]
      const result = await lifecycleAction(selectedDocIds)
      const remaining = [...(result.denied ?? []), ...(result.conflicts ?? [])]
      if (result.updated) toast.success(t('toasts.batchLifecycle.' + action, { count: result.updated }))
      if (remaining.length) toast.error(remaining.length + ' 份文档未完成操作，请检查权限或处理状态。')
      setSelectedDocIds(remaining)
      await refreshDocuments()
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.batchLifecycleFailed')))
    } finally {
      setBatchLifecycleWorking(false)
    }
  }
  const runBatchReingest = async () => {
    if (!selectedDocIds.length || batchWorking) return
    setBatchReingestWorking(true)
    try {
      const result = await documentApi.batchReingest({
        document_ids: selectedDocIds, replace: false, force: true, skip_if_unchanged: false,
      })
      const remaining = [...(result.denied ?? []), ...(result.conflicts ?? [])]
      if (result.queued) toast.success(t('toasts.reingestQueued', { count: result.queued }))
      if (remaining.length) toast.error(remaining.length + ' 份文档未能重新入库，请检查权限或处理状态。')
      setSelectedDocIds(remaining)
      await refreshDocuments()
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.reingestFailed')))
    } finally {
      setBatchReingestWorking(false)
    }
  }
  const confirmBatchDelete = async () => {
    if (!selectedDocIds.length || batchWorking) return
    setBatchDeleting(true)
    setBatchDeleteError(null)
    try {
      const result = await documentApi.batchDelete(selectedDocIds)
      const remaining = result.denied ?? []
      setSelectedDocIds(remaining)
      if (remaining.length) {
        setBatchDeleteError('已删除 ' + result.deleted + ' 份文档；其余 ' + remaining.length + ' 份没有删除权限。')
      } else {
        setBatchDeleteOpen(false)
      }
      await refreshDocuments()
    } catch (err) {
      setBatchDeleteError(formatApiError(err, t('toasts.batchDeleteFailed')))
    } finally {
      setBatchDeleting(false)
    }
  }

  const handleTabsKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const current = TABS.indexOf(activeTab)
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1
      : (current + (event.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length
    updateQuery({ activeTab: TABS[index] })
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[index]?.focus()
  }
  const hasAdvancedFilters = lifecycleFilter !== 'active' || Boolean(folderPath)
  const hasActiveFilters = hasAdvancedFilters || statusFilter !== 'all' || Boolean(docFilter.trim())
  const showImportIntro = activeTab === 'documents' && !isLoading && !error && total === 0 && !hasActiveFilters
  const clearFilters = () => updateQuery({ docFilter: '', statusFilter: 'all', lifecycleFilter: 'active', folderPath: null })

  const datasetSelect = (
    <Select value={datasetScope} onValueChange={handleDatasetScopeChange} disabled={datasetsLoading || batchWorking}>
      <SelectTrigger className={styles.datasetTrigger} aria-label={scopeT('dataset.ariaLabel')}>
        <DatasetIcon aria-hidden="true" />
        <SelectValue placeholder={scopeT('dataset.all')} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={DATASET_ALL}>{scopeT('dataset.all')}</SelectItem>
        {selectedDatasetId && !selectedDataset ? <SelectItem value={selectedDatasetId}>{selectedDatasetId}</SelectItem> : null}
        {datasets.map(dataset => <SelectItem key={dataset.id} value={dataset.id}>{dataset.name}</SelectItem>)}
      </SelectContent>
    </Select>
  )

  return (
    <AppFrame navigationVariant={activeTab === 'retrieval' && !isMobile ? 'rail' : 'default'} rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding={activeTab !== 'retrieval'}>
      <div data-knowledge-page-root="true" data-knowledge-table-shell="true" className={styles.shell}>
        <header className={styles.pageHeader} data-testid="knowledge-page-toolbar">
          <div className={styles.pageHeading} data-knowledge-title-mark="true">
            <KnowledgeBase appearance="color" className="size-6" aria-hidden="true" />
            <h1>{t('header.title')}</h1>
          </div>
          <div className={styles.tabs} role="tablist" aria-label="知识库视图" onKeyDown={handleTabsKeyDown}>
            {TABS.map(tab => (
              <button
                key={tab} id={'knowledge-tab-' + tab} type="button" role="tab"
                aria-selected={activeTab === tab} aria-controls={'knowledge-panel-' + tab}
                tabIndex={activeTab === tab ? 0 : -1} className={styles.tab}
                onClick={() => updateQuery({ activeTab: tab })}
              >
                {t('tabs.' + tab + '.label')}
                {tab === 'documents' && typeof documentCount === 'number' && !showImportIntro ? <span className={styles.tabCount}>{documentCount}</span> : null}
              </button>
            ))}
          </div>
          <div className={styles.headerActions}>
            <Button variant="ghost" className={styles.taskButton} onClick={() => setTasksOpen(true)} aria-label="任务历史" title="任务历史">
              {activeTasksCount ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <History className="size-4" />}
              {activeTasksCount ? <span>{activeTasksCount}</span> : <span className={styles.taskLabel}>任务</span>}
            </Button>
            <KnowledgeWorkbenchActions
              actionsRef={importActionsRef}
              className={styles.importButton} open={importOpen} onOpenChange={setImportOpen}
              datasets={datasets} datasetsLoading={datasetsLoading} selectedDatasetId={selectedDatasetId}
              datasetDefaultValue={DATASET_ALL} handleFileUpload={handleFileUpload}
              uploadDocumentFromUrl={uploadDocumentFromUrl} loadDocuments={refreshDocuments}
              loadConnectorRuns={loadConnectorRuns}
              onConnectorRunCreated={() => { setTasksOpen(true); updateQuery({ activeTab: 'documents' }) }}
            />
          </div>
        </header>

        <div className={cn(styles.toolbar, (showImportIntro || activeTab === 'retrieval') && styles.introToolbar)} aria-label="文档筛选与排序">
          {datasetSelect}
          {activeTab === 'retrieval' && stats ? <p className={styles.scopeSummary}>{stats.total} 份文档<span>·</span>{stats.total_chunks ?? 0} 个分片</p> : null}
          {activeTab === 'documents' && !showImportIntro ? (
            <div className={styles.filters} aria-label="处理状态">
              {STATUS_FILTERS.map(status => (
                <Button
                  key={status} variant="ghost" className={styles.filter} disabled={batchWorking}
                  aria-pressed={statusFilter === status}
                  onClick={() => updateQuery({ statusFilter: status })}
                >
                  {scopeT('status.' + status + '.label')}
                  {statusCounts ? <span className={styles.filterCount}>{statusCounts[status]}</span> : null}
                </Button>
              ))}
            </div>
          ) : null}
          <div className={styles.toolbarEnd}>
            {activeTab === 'documents' ? (
              <>
                {!showImportIntro ? <>
                <SearchInput
                  aria-label="搜索文档名称" placeholder="搜索文档名称"
                  value={docFilter} onValueChange={value => updateQuery({ docFilter: value })}
                  disabled={batchWorking} containerClassName={styles.search} inputClassName={styles.searchInput}
                />
                <Select value={sortKey + ':' + sortDir} onValueChange={value => {
                  const [key, direction] = value.split(':')
                  updateQuery({ sortKey: key as KnowledgeQueryState['sortKey'], sortDir: direction as KnowledgeQueryState['sortDir'] })
                }} disabled={batchWorking}>
                  <SelectTrigger aria-label="文档排序" className={styles.sort}><SelectValue /></SelectTrigger>
                  <SelectContent>{SORT_OPTIONS.map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
                </Select>
                </> : null}
                <IconButton
                  label="更多筛选" title="更多筛选" variant="ghost"
                  className={cn(styles.toolIcon, styles.advancedFilter)} aria-pressed={hasAdvancedFilters}
                  onClick={() => setScopeOpen(true)} disabled={batchWorking}
                ><Filter className="size-4" /></IconButton>
                <IconButton
                  label="文档工具" title="文档工具" variant="ghost" className={cn(styles.toolIcon, styles.refresh)}
                  onClick={() => setOperationsOpen(true)}
                ><MoreHorizontal className="size-4" /></IconButton>
              </>
            ) : null}
            <IconButton
              label="刷新文档" title="刷新文档" variant="ghost" className={cn(styles.toolIcon, styles.refresh)}
              disabled={isLoading || batchWorking} onClick={() => detachPromise(refreshDocuments())}
            ><RefreshCw className={cn('size-4', isLoading && 'animate-spin motion-reduce:animate-none')} /></IconButton>
          </div>
        </div>

        {activeTab === 'documents' && hasAdvancedFilters ? (
          <div className={styles.filterSummary}>
            {lifecycleFilter !== 'active' ? <span>{scopeT('lifecycle.label')}：{scopeT('lifecycle.' + lifecycleFilter)}</span> : null}
            {folderPath ? <span title={folderPath}>文件夹：{folderPath}</span> : null}
            <Button variant="ghost" onClick={clearFilters}>清空筛选</Button>
          </div>
        ) : null}

        <div className={styles.content} id={'knowledge-panel-' + activeTab} role="tabpanel" aria-labelledby={'knowledge-tab-' + activeTab}>
          {activeTab === 'documents' ? (
            <KnowledgeDocumentsPanel
              isLoading={isLoading} error={error} documents={documents} totalDocumentsCount={total}
              totalChunks={totalChunks} datasets={datasets} selectedDatasetId={selectedDatasetId}
              selectedDatasetLabel={selectedDatasetLabel} datasetLabelById={datasetLabelById}
              hasActiveFilters={hasActiveFilters}
              showImportIntro={showImportIntro}
              onImportSource={source => importActionsRef.current?.openImport(source)}
              onClearFilters={clearFilters} onSwitchToAllDatasets={() => handleDatasetScopeChange(DATASET_ALL)}
              onImport={() => setImportOpen(true)} onRefresh={refreshDocuments}
              page={documentsPage} pageSize={pageSize} pageCount={pageCount}
              onPageChange={page => { setDocumentsPage(page); setSelectedDocIds([]) }}
              onPageSizeChange={size => { setPageSize(size); setDocumentsPage(1); setSelectedDocIds([]) }}
              selectedDocIds={selectedDocIds} setSelectedDocIds={setSelectedDocIds}
              selectedSet={selectedSet} allVisibleSelected={allVisibleSelected}
              toggleSelectAllVisible={toggleSelectAllVisible} toggleDocSelection={toggleDocSelection}
              batchDeleteOpen={batchDeleteOpen} setBatchDeleteOpen={open => { setBatchDeleteOpen(open); setBatchDeleteError(null) }}
              batchDeleteError={batchDeleteError} batchDeleting={batchDeleting} confirmBatchDelete={confirmBatchDelete}
              batchLifecycleWorking={batchLifecycleWorking} batchReingestWorking={batchReingestWorking}
              runBatchReingest={runBatchReingest} runBatchLifecycle={runBatchLifecycle}
              anySelectedDisabled={selectedDocuments.some(doc => doc.disabled_at)}
              anySelectedEnabled={selectedDocuments.some(doc => !doc.disabled_at)}
              anySelectedArchived={selectedDocuments.some(doc => doc.archived_at)}
              anySelectedNotArchived={selectedDocuments.some(doc => !doc.archived_at)}
              deleteDocument={deleteDocument}
              onOpenDocument={id => openDocument(id)}
              onPeek={id => openDocument(id, undefined, undefined, { activeTab: 'chunks' })}
              operationsOpen={operationsOpen} setOperationsOpen={setOperationsOpen}
            />
          ) : null}
          {activeTab === 'retrieval' ? (
            <RetrievePreviewPanel
              selectedDatasetId={selectedDatasetId} availableDatasetIds={retrievalDatasetIds}
              scopeLabel={selectedDatasetLabel || scopeT('dataset.all')}
              aggregateDocuments={stats?.total ?? (error ? undefined : total)} aggregateChunks={stats?.total_chunks ?? 0}
              scopeLoading={datasetsLoading || isLoading || statsLoading}
              onGoToDocuments={() => updateQuery({ activeTab: 'documents' })}
            />
          ) : null}
        </div>

        <Sheet open={scopeOpen} onOpenChange={setScopeOpen}>
          <SheetContent className={styles.sheet}>
            <SheetHeader className={styles.sheetHeader}>
              <SheetTitle>更多筛选</SheetTitle>
              <SheetDescription className="sr-only">按文档生命周期与文件夹筛选</SheetDescription>
            </SheetHeader>
            <div className={styles.operationsBody} data-knowledge-scope-content="true">
              <div className="space-y-6">
                <div className="space-y-2"><p className="text-[13px] font-medium">{scopeT('dataset.label')}</p>{datasetSelect}</div>
                <div className="space-y-2">
                  <p className="text-[13px] font-medium">{scopeT('lifecycle.label')}</p>
                  <Select value={lifecycleFilter} onValueChange={value => updateQuery({ lifecycleFilter: value as KnowledgeQueryState['lifecycleFilter'] })}>
                    <SelectTrigger aria-label={scopeT('lifecycle.ariaLabel')}><SelectValue /></SelectTrigger>
                    <SelectContent>{(['active', 'disabled', 'archived', 'all'] as const).map(value => <SelectItem key={value} value={value}>{scopeT('lifecycle.' + value)}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                {selectedDatasetId ? (
                  <DatasetFolderTree datasetId={selectedDatasetId} lifecycle={lifecycleFilter} selectedPath={folderPath} onSelect={path => updateQuery({ folderPath: path })} />
                ) : <p className="text-[13px] leading-6 text-muted-foreground">选择数据集后可按文件夹筛选。</p>}
                {hasActiveFilters ? <Button variant="outline" onClick={clearFilters}>清空筛选</Button> : null}
                <div className={styles.scopeTools}>
                  <Button variant="outline" onClick={() => { setScopeOpen(false); setOperationsOpen(true) }}>文档工具</Button>
                  <Button variant="ghost" disabled={isLoading} onClick={() => detachPromise(refreshDocuments())}><RefreshCw className="size-4" />刷新文档</Button>
                </div>
              </div>
            </div>
          </SheetContent>
        </Sheet>
        <Sheet open={tasksOpen} onOpenChange={open => {
          setTasksOpen(open)
          if (!open && (query.connectorRunId || query.tasksOpen)) updateQuery({ connectorRunId: null, tasksOpen: false })
        }}>
          <SheetContent className={cn(styles.sheet, styles.operationsSheet)}>
            <SheetHeader className={styles.sheetHeader}>
              <SheetTitle>任务历史</SheetTitle>
              <SheetDescription className="sr-only">当前数据集的导入任务与处理记录</SheetDescription>
            </SheetHeader>
            <div className={styles.sheetBody}>
              <KnowledgeConnectorRunsPanel
                selectedDatasetId={selectedDatasetId} connectorRuns={connectorRuns}
                connectorRunsLoading={connectorRunsLoading} onCancelConnectorRun={cancelConnectorRun}
                onResumeConnectorRun={resumeConnectorRun} onRetryFailedConnectorRun={retryFailedConnectorRun}
                onLoadConnectorRuns={loadConnectorRuns}
              />
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </AppFrame>
  )
}
