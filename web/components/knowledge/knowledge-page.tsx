'use client'

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
  type ChangeEvent as ReactChangeEvent,
} from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { isCancelledError, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import {
  Dataset as DatasetIcon,
  Filter,
  History,
  KnowledgeBase,
  Loader2,
  MoreHorizontal,
  RefreshCw,
  X,
} from '@/components/icons'
import { AppFrame } from '@/components/app-frame'
import { DatasetFolderTree } from '@/components/document-library/dataset-folder-tree'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { KnowledgeDocumentsPanel } from '@/components/knowledge/knowledge-documents-panel'
import { KnowledgeConnectorRunsPanel } from '@/components/knowledge/knowledge-connector-runs-panel'
import {
  KnowledgeWorkbenchActions,
  type KnowledgeWorkbenchActionsHandle,
} from '@/components/knowledge/knowledge-workbench-actions'
import {
  DATASET_ALL,
  parseKnowledgeQueryState,
  serializeKnowledgeQueryState,
  STATUS_FILTERS,
  TABS,
  type KnowledgeQueryState,
} from '@/components/knowledge/use-knowledge-query-state'
import { RetrievePreviewPanel } from '@/components/rag/retrieve-preview-panel'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { SearchInput } from '@/components/ui/search-input'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useConnectorRuns } from '@/hooks/use-connector-runs'
import { useDatasets } from '@/hooks/use-datasets'
import { useDocuments } from '@/hooks/use-documents'
import { useIsMobile } from '@/hooks/use-media-query'
import { getUploadReceiptKey } from '@/lib/api/document-helpers'
import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'
import type { DocumentBatchUploadFailure } from '@/types/backend'

import styles from './knowledge-page.module.css'

const DEFAULT_PAGE_SIZE = 20
const SORT_OPTIONS = [
  { value: 'created_at:desc', label: '最新上传' },
  { value: 'created_at:asc', label: '最早上传' },
  { value: 'filename:asc', label: '文件名 A–Z' },
  { value: 'filename:desc', label: '文件名 Z–A' },
  { value: 'file_size:desc', label: '大小从大到小' },
  { value: 'file_size:asc', label: '大小从小到大' },
]

type KnowledgeBatchAction = 'delete' | 'lifecycle' | 'reingest'
type UploadNotice = {
  sessionKey: string
  message: string
  failures: DocumentBatchUploadFailure[]
  interruption?: string
}

export default function KnowledgePage() {
  const t = useTranslations('KnowledgePage')
  const scopeT = useTranslations('KnowledgeScopePanel')
  const documentsT = useTranslations('KnowledgeDocumentsPanel')
  const searchParams = useSearchParams()
  const router = useRouter()
  const isMobile = useIsMobile()
  const queryClient = useQueryClient()
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const [uploadNotice, setUploadNotice] = useState<UploadNotice | null>(null)
  const latestUpload = useRef<symbol | null>(null)
  const importActionsRef = useRef<KnowledgeWorkbenchActionsHandle>(null)
  const { openDocument } = useDocumentView()
  const queryString = searchParams.toString()
  const [query, setQuery] = useState(() => parseKnowledgeQueryState(new URLSearchParams(queryString)))
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
  const [batchAction, setBatchAction] = useState<KnowledgeBatchAction | null>(null)
  const batchActionRef = useRef<KnowledgeBatchAction | null>(null)
  const batchWorking = batchAction !== null
  const batchDeleting = batchAction === 'delete'
  const batchLifecycleWorking = batchAction === 'lifecycle'
  const batchReingestWorking = batchAction === 'reingest'

  useEffect(() => {
    const params = new URLSearchParams(queryString)
    if (params.get('tab') === 'settings' && !parseKnowledgeQueryState(params).tasksOpen) {
      router.replace('/settings#sec-models')
    }
  }, [queryString, router])

  // Only external navigation reads state back. Our own URL writes preserve the
  // exact input string, including a trailing space while a name is being typed.
  useEffect(() => {
    if (queryString === writtenQueryRef.current) return
    writtenQueryRef.current = queryString
    const next = parseKnowledgeQueryState(new URLSearchParams(queryString))
    queryRef.current = next
    setQuery(next)
    setDocumentsPage(1)
    setSelectedDocIds([])
  }, [queryString])

  const updateQuery = useCallback((patch: Partial<KnowledgeQueryState>) => {
    const next = { ...queryRef.current, ...patch }
    queryRef.current = next
    setQuery(next)
    setDocumentsPage(1)
    setSelectedDocIds([])
    const nextQuery = serializeKnowledgeQueryState(next)
    writtenQueryRef.current = nextQuery
    globalThis.window.history.replaceState(
      globalThis.window.history.state,
      '',
      nextQuery ? '/knowledge?' + nextQuery : '/knowledge',
    )
  }, [])

  const { activeTab, datasetScope, docFilter, statusFilter, lifecycleFilter, folderPath, sortKey, sortDir } = query
  const isDocumentsTab = activeTab === 'documents'
  const searchTerm = docFilter.trim()
  const documentQuery = isDocumentsTab && searchTerm !== '' ? searchTerm : undefined
  const documentFolder = isDocumentsTab && folderPath !== null && folderPath !== '' ? folderPath : undefined
  const documentLifecycle = isDocumentsTab ? lifecycleFilter : 'active'
  const selectedDatasetId = datasetScope === DATASET_ALL ? undefined : datasetScope
  const {
    datasets,
    isLoading: datasetsLoading,
    isFetching: datasetsFetching,
    error: datasetsError,
    refreshDatasets,
  } = useDatasets()
  const selectedDataset = datasets.find((dataset) => dataset.id === selectedDatasetId) ?? null
  const selectedDatasetLabel =
    selectedDataset === null
      ? selectedDatasetId
      : selectedDataset.name === ''
        ? selectedDataset.id
        : selectedDataset.name
  const datasetLabelById = useMemo(
    () => Object.fromEntries(datasets.map((dataset) => [dataset.id, dataset.name === '' ? dataset.id : dataset.name])),
    [datasets],
  )
  const retrievalDatasetIds = useMemo(() => datasets.map((dataset) => dataset.id), [datasets])

  const {
    documents,
    total,
    isLoading,
    isPlaceholderData,
    error,
    loadDocuments,
    deleteDocument,
    uploadDocuments,
    uploadDocumentFromUrl,
  } = useDocuments({
    dataset_id: selectedDatasetId,
    status: isDocumentsTab && statusFilter !== 'all' ? statusFilter : undefined,
    lifecycle: documentLifecycle,
    source_path_prefix: documentFolder,
    q: documentQuery,
    order_by: sortKey,
    order_dir: sortDir,
    skip: isDocumentsTab ? (documentsPage - 1) * pageSize : 0,
    limit: pageSize,
  })

  const statsParams = {
    dataset_id: selectedDatasetId,
    lifecycle: documentLifecycle,
    q: documentQuery,
  }
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['documents', 'stats', statsParams],
    queryFn: () => documentApi.stats(statsParams),
    enabled: documentFolder === undefined,
  })
  const statusCounts =
    !folderPath && stats
      ? {
          all: stats.total,
          completed: stats.by_status?.completed ?? 0,
          processing: (stats.by_status?.processing ?? 0) + (stats.by_status?.pending ?? 0),
          failed: stats.by_status?.failed ?? 0,
          quarantined: stats.by_status?.quarantined ?? 0,
        }
      : undefined
  const totalChunks = !folderPath && statusFilter === 'all' ? stats?.total_chunks : undefined
  const documentCount = documentFolder === undefined ? stats?.total : isPlaceholderData ? undefined : total
  const pageCount = Math.max(1, Math.ceil(total / pageSize))

  useEffect(() => {
    if (isLoading || isPlaceholderData || error !== null) return
    setDocumentsPage((current) => Math.min(current, pageCount))
  }, [error, isLoading, isPlaceholderData, pageCount])

  const {
    connectorRuns,
    connectorRunsLoading,
    connectorRunsError,
    loadConnectorRuns,
    cancelConnectorRun,
    resumeConnectorRun,
    retryFailedConnectorRun,
  } = useConnectorRuns({ selectedDatasetId })
  const activeTasksCount = connectorRuns.filter((run) => run.status === 'running' || run.status === 'pending').length

  useEffect(() => {
    if (tasksOpen) detachPromise(loadConnectorRuns({ datasetId: selectedDatasetId }))
  }, [loadConnectorRuns, selectedDatasetId, tasksOpen])

  useEffect(() => {
    if (query.connectorRunId || query.tasksOpen) setTasksOpen(true)
  }, [query.connectorRunId, query.tasksOpen])

  const refreshDocuments = useCallback(async () => {
    await Promise.all([queryClient.invalidateQueries({ queryKey: queryKeys.documents.all }), loadDocuments()])
  }, [loadDocuments, queryClient])

  const handleDatasetScopeChange = useCallback(
    (value: string) => {
      updateQuery({ datasetScope: value, folderPath: null })
    },
    [updateQuery],
  )

  const handleFileUpload = useCallback(
    async (event: ReactChangeEvent<HTMLInputElement>) => {
      const input = event.currentTarget
      if (input.files === null || input.files.length === 0) return
      const files = Array.from(input.files)
      const uploadSessionKey = getAuthSessionKey()
      const upload = Symbol()
      latestUpload.current = upload
      input.value = ''
      setUploadNotice(null)

      try {
        const result = await uploadDocuments(files)
        if (uploadSessionKey !== getAuthSessionKey()) return
        if (result.interruption !== undefined || result.failed_count > 0) {
          const message = t('toasts.uploadPartial', {
            successful: result.successful_count,
            failed: result.failed_count,
          })
          const unconfirmed = result.total - result.successful_count - result.failed_count
          const summary =
            unconfirmed > 0 ? `${message}，${t('toasts.uploadUnconfirmed', { count: unconfirmed })}` : message
          if (latestUpload.current === upload) {
            setUploadNotice({
              sessionKey: uploadSessionKey,
              message: summary,
              failures: result.failed,
              interruption: result.interruption,
            })
          } else {
            toast.warning(summary)
          }
        } else {
          toast.success(t('toasts.uploadSuccess', { count: result.successful_count }))
        }
      } catch (error) {
        if (uploadSessionKey !== getAuthSessionKey() || isCancelledError(error)) return
        toast.error(formatApiError(error, t('toasts.uploadFailed')))
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
    },
    [queryClient, t, uploadDocuments],
  )

  const selectedSet = useMemo(() => new Set(selectedDocIds), [selectedDocIds])
  const selectedDocuments = documents.filter((doc) => selectedSet.has(doc.id))
  const allVisibleSelected = documents.length > 0 && documents.every((doc) => selectedSet.has(doc.id))
  const toggleDocSelection = useCallback((docId: string) => {
    setSelectedDocIds((previous) =>
      previous.includes(docId) ? previous.filter((id) => id !== docId) : [...previous, docId],
    )
  }, [])
  const toggleSelectAllVisible = () => {
    setSelectedDocIds(allVisibleSelected ? [] : documents.map((doc) => doc.id))
  }
  useEffect(() => {
    if (isLoading || isPlaceholderData || error !== null) return
    const validIds = new Set(documents.map((doc) => doc.id))
    setSelectedDocIds((previous) => {
      const next = previous.filter((id) => validIds.has(id))
      return next.length === previous.length ? previous : next
    })
  }, [documents, error, isLoading, isPlaceholderData])

  async function runDocumentBatchAction<Result>(
    action: KnowledgeBatchAction,
    perform: (documentIds: string[]) => Promise<Result>,
    handleResult: (result: Result) => string[],
    onFailure: (error: unknown) => void,
  ) {
    const documentIds = selectedDocIds
    if (documentIds.length === 0 || batchActionRef.current !== null) return

    const ownsSession = () => getAuthSessionKey() === sessionKey
    batchActionRef.current = action
    setBatchAction(action)
    try {
      try {
        const result = await perform(documentIds)
        if (!ownsSession()) return
        const remainingIds = handleResult(result)
        setSelectedDocIds((current) => (current === documentIds ? remainingIds : current))
      } catch (error) {
        if (ownsSession()) onFailure(error)
        return
      }

      try {
        await refreshDocuments()
      } catch (error) {
        if (ownsSession()) toast.error(formatApiError(error, documentsT('toasts.refreshFailed')))
      }
    } finally {
      batchActionRef.current = null
      setBatchAction(null)
    }
  }

  function warnMissingDocuments(documentIds: readonly string[] | undefined) {
    if (documentIds !== undefined && documentIds.length > 0) {
      toast.warning(t('toasts.batchNotFound', { count: documentIds.length }))
    }
  }

  function runBatchLifecycle(action: 'enable' | 'disable' | 'archive' | 'unarchive') {
    const lifecycleAction = {
      enable: documentApi.batchEnable,
      disable: documentApi.batchDisable,
      archive: documentApi.batchArchive,
      unarchive: documentApi.batchUnarchive,
    }[action]
    return runDocumentBatchAction(
      'lifecycle',
      lifecycleAction,
      (result) => {
        const remainingIds = [...(result.denied ?? []), ...(result.conflicts ?? [])]
        if (result.updated > 0) toast.success(t('toasts.batchLifecycle.' + action, { count: result.updated }))
        warnMissingDocuments(result.not_found)
        if (remainingIds.length > 0) toast.error(remainingIds.length + ' 份文档未完成操作，请检查权限或处理状态。')
        return remainingIds
      },
      (error) => toast.error(formatApiError(error, t('toasts.batchLifecycleFailed'))),
    )
  }

  function runBatchReingest() {
    return runDocumentBatchAction(
      'reingest',
      (documentIds) =>
        documentApi.batchReingest({
          document_ids: documentIds,
          replace: false,
          force: true,
          skip_if_unchanged: false,
        }),
      (result) => {
        const remainingIds = [...result.denied, ...result.conflicts]
        if (result.queued > 0) toast.success(t('toasts.reingestQueued', { count: result.queued }))
        warnMissingDocuments(result.not_found)
        if (remainingIds.length > 0) toast.error(remainingIds.length + ' 份文档未能重新入库，请检查权限或处理状态。')
        return remainingIds
      },
      (error) => toast.error(formatApiError(error, t('toasts.reingestFailed'))),
    )
  }

  function confirmBatchDelete() {
    return runDocumentBatchAction(
      'delete',
      (documentIds) => {
        setBatchDeleteError(null)
        return documentApi.batchDelete(documentIds)
      },
      (result) => {
        const remainingIds = result.denied ?? []
        warnMissingDocuments(result.not_found)
        if (remainingIds.length > 0) {
          setBatchDeleteError(t('toasts.batchDeletePartial', { deleted: result.deleted, denied: remainingIds.length }))
        } else {
          setBatchDeleteOpen(false)
          if (result.deleted > 0) toast.success(t('toasts.batchDeleteSuccess', { count: result.deleted }))
        }
        return remainingIds
      },
      (error) => setBatchDeleteError(formatApiError(error, t('toasts.batchDeleteFailed'))),
    )
  }

  const handleTabsKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const current = TABS.indexOf(activeTab)
    const index =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? TABS.length - 1
          : (current + (event.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length
    updateQuery({ activeTab: TABS[index] })
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[index]?.focus()
  }
  const hasAdvancedFilters = lifecycleFilter !== 'active' || Boolean(folderPath)
  const hasActiveFilters = hasAdvancedFilters || statusFilter !== 'all' || searchTerm !== ''
  const showImportIntro = activeTab === 'documents' && !isLoading && !error && total === 0 && !hasActiveFilters
  const clearFilters = () =>
    updateQuery({ docFilter: '', statusFilter: 'all', lifecycleFilter: 'active', folderPath: null })

  const datasetSelect = (
    <Select value={datasetScope} onValueChange={handleDatasetScopeChange} disabled={datasetsLoading || batchWorking}>
      <SelectTrigger className={styles.datasetTrigger} aria-label={scopeT('dataset.ariaLabel')}>
        <DatasetIcon aria-hidden="true" />
        <SelectValue placeholder={scopeT('dataset.all')} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={DATASET_ALL}>{scopeT('dataset.all')}</SelectItem>
        {selectedDatasetId && !selectedDataset ? (
          <SelectItem value={selectedDatasetId}>{selectedDatasetId}</SelectItem>
        ) : null}
        {datasets.map((dataset) => (
          <SelectItem key={dataset.id} value={dataset.id}>
            {dataset.name === '' ? dataset.id : dataset.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )

  return (
    <AppFrame
      navigationVariant={activeTab === 'retrieval' && !isMobile ? 'rail' : 'default'}
      rightPanel={<DocumentViewerPanel />}
      withDocumentViewerPadding={activeTab !== 'retrieval'}
    >
      <div data-knowledge-page-root="true" data-knowledge-table-shell="true" className={styles.shell}>
        <header className={styles.pageHeader} data-testid="knowledge-page-toolbar">
          <div className={styles.pageHeading} data-knowledge-title-mark="true">
            <KnowledgeBase appearance="color" className="size-6" aria-hidden="true" />
            <h1>{t('header.title')}</h1>
          </div>
          <div className={styles.tabs} role="tablist" aria-label="知识库视图" onKeyDown={handleTabsKeyDown}>
            {TABS.map((tab) => (
              <button
                key={tab}
                id={'knowledge-tab-' + tab}
                type="button"
                role="tab"
                aria-selected={activeTab === tab}
                aria-controls={'knowledge-panel-' + tab}
                tabIndex={activeTab === tab ? 0 : -1}
                className={styles.tab}
                onClick={() => updateQuery({ activeTab: tab })}
              >
                {t('tabs.' + tab + '.label')}
                {tab === 'documents' && typeof documentCount === 'number' && !showImportIntro ? (
                  <span className={styles.tabCount}>{documentCount}</span>
                ) : null}
              </button>
            ))}
          </div>
          <div className={styles.headerActions}>
            <Button
              variant="ghost"
              className={styles.taskButton}
              onClick={() => setTasksOpen(true)}
              aria-label="任务历史"
              title="任务历史"
            >
              {activeTasksCount ? (
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
              ) : (
                <History className="size-4" />
              )}
              {activeTasksCount ? <span>{activeTasksCount}</span> : <span className={styles.taskLabel}>任务</span>}
            </Button>
            <KnowledgeWorkbenchActions
              actionsRef={importActionsRef}
              className={styles.importButton}
              open={importOpen}
              onOpenChange={setImportOpen}
              datasets={datasets}
              datasetsLoading={datasetsLoading}
              selectedDatasetId={selectedDatasetId}
              datasetDefaultValue={DATASET_ALL}
              handleFileUpload={handleFileUpload}
              uploadDocumentFromUrl={uploadDocumentFromUrl}
              loadDocuments={refreshDocuments}
              loadConnectorRuns={loadConnectorRuns}
              onConnectorRunCreated={(run) => {
                const runDatasetScope = run.dataset_id ?? DATASET_ALL
                const current = queryRef.current
                setTasksOpen(true)
                updateQuery({
                  activeTab: 'documents',
                  datasetScope: runDatasetScope,
                  folderPath: runDatasetScope === current.datasetScope ? current.folderPath : null,
                  connectorRunId: run.id,
                })
              }}
            />
          </div>
        </header>

        {uploadNotice?.sessionKey === sessionKey && (
          <WorkspaceNotice>
            <div className="flex items-start justify-between gap-3">
              <p>{uploadNotice.message}</p>
              <IconButton label={t('toasts.dismissUploadResult')} variant="ghost" onClick={() => setUploadNotice(null)}>
                <X className="size-4" aria-hidden="true" />
              </IconButton>
            </div>
            {uploadNotice.interruption !== undefined && <p className="wrap-anywhere">{uploadNotice.interruption}</p>}
            {uploadNotice.failures.length > 0 && (
              <details>
                <summary className="cursor-pointer">{t('toasts.uploadFailureDetails')}</summary>
                <ol className="max-h-48 list-decimal overflow-y-auto pl-5">
                  {uploadNotice.failures.map((failure, index) => (
                    <li key={index} className="wrap-anywhere">
                      {getUploadReceiptKey(failure)} · {failure.error}
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </WorkspaceNotice>
        )}
        {datasetsError !== null ? (
          <WorkspaceNotice
            retry={() => void refreshDatasets()}
            retryLabel="重新读取数据集目录"
            pending={datasetsFetching}
          >
            {formatApiError(datasetsError, '数据集目录读取失败，当前选择已保留')}
          </WorkspaceNotice>
        ) : null}
        {datasetsFetching && !datasetsLoading ? (
          <p role="status" className="text-sm text-muted-foreground">
            正在更新数据集目录，保留当前选择。
          </p>
        ) : null}
        <div
          className={cn(styles.toolbar, (showImportIntro || activeTab === 'retrieval') && styles.introToolbar)}
          aria-label="文档筛选与排序"
        >
          {datasetSelect}
          {activeTab === 'retrieval' && stats ? (
            <p className={styles.scopeSummary}>
              {stats.total} 份文档<span>·</span>
              {stats.total_chunks} 个分片
            </p>
          ) : null}
          {activeTab === 'documents' && !showImportIntro ? (
            <div className={styles.filters} aria-label="处理状态">
              {STATUS_FILTERS.map((status) => (
                <Button
                  key={status}
                  variant="ghost"
                  className={styles.filter}
                  disabled={batchWorking}
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
                {!showImportIntro ? (
                  <>
                    <SearchInput
                      aria-label="搜索文档名称"
                      placeholder="搜索文档名称"
                      value={docFilter}
                      onValueChange={(value) => updateQuery({ docFilter: value })}
                      disabled={batchWorking}
                      containerClassName={styles.search}
                      inputClassName={styles.searchInput}
                    />
                    <Select
                      value={sortKey + ':' + sortDir}
                      onValueChange={(value) => {
                        const [key, direction] = value.split(':')
                        updateQuery({
                          sortKey: key as KnowledgeQueryState['sortKey'],
                          sortDir: direction as KnowledgeQueryState['sortDir'],
                        })
                      }}
                      disabled={batchWorking}
                    >
                      <SelectTrigger aria-label="文档排序" className={styles.sort}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SORT_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </>
                ) : null}
                <IconButton
                  label="更多筛选"
                  title="更多筛选"
                  variant="ghost"
                  className={cn(styles.toolIcon, styles.advancedFilter)}
                  aria-pressed={hasAdvancedFilters}
                  onClick={() => setScopeOpen(true)}
                  disabled={batchWorking}
                >
                  <Filter className="size-4" />
                </IconButton>
                <IconButton
                  label="文档工具"
                  title="文档工具"
                  variant="ghost"
                  className={cn(styles.toolIcon, styles.refresh)}
                  onClick={() => setOperationsOpen(true)}
                >
                  <MoreHorizontal className="size-4" />
                </IconButton>
              </>
            ) : null}
            <IconButton
              label="刷新文档"
              title="刷新文档"
              variant="ghost"
              className={cn(styles.toolIcon, styles.refresh)}
              disabled={isLoading || batchWorking}
              onClick={() => detachPromise(refreshDocuments())}
            >
              <RefreshCw className={cn('size-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
            </IconButton>
          </div>
        </div>

        {activeTab === 'documents' && hasAdvancedFilters ? (
          <div className={styles.filterSummary}>
            {lifecycleFilter !== 'active' ? (
              <span>
                {scopeT('lifecycle.label')}：{scopeT('lifecycle.' + lifecycleFilter)}
              </span>
            ) : null}
            {folderPath ? <span title={folderPath}>文件夹：{folderPath}</span> : null}
            <Button variant="ghost" onClick={clearFilters}>
              清空筛选
            </Button>
          </div>
        ) : null}

        <div
          className={styles.content}
          id={'knowledge-panel-' + activeTab}
          role="tabpanel"
          aria-labelledby={'knowledge-tab-' + activeTab}
        >
          {activeTab === 'documents' ? (
            <KnowledgeDocumentsPanel
              isLoading={isLoading}
              isPlaceholderData={isPlaceholderData}
              error={error}
              documents={documents}
              totalDocumentsCount={total}
              totalChunks={totalChunks}
              datasets={datasets}
              selectedDatasetId={selectedDatasetId}
              selectedDatasetLabel={selectedDatasetLabel}
              datasetLabelById={datasetLabelById}
              hasActiveFilters={hasActiveFilters}
              showImportIntro={showImportIntro}
              onImportSource={(source) => importActionsRef.current?.openImport(source)}
              onClearFilters={clearFilters}
              onSwitchToAllDatasets={() => handleDatasetScopeChange(DATASET_ALL)}
              onImport={() => setImportOpen(true)}
              onRefresh={refreshDocuments}
              page={documentsPage}
              pageSize={pageSize}
              pageCount={pageCount}
              onPageChange={(page) => {
                setDocumentsPage(page)
                setSelectedDocIds([])
              }}
              onPageSizeChange={(size) => {
                setPageSize(size)
                setDocumentsPage(1)
                setSelectedDocIds([])
              }}
              selectedDocIds={selectedDocIds}
              setSelectedDocIds={setSelectedDocIds}
              selectedSet={selectedSet}
              allVisibleSelected={allVisibleSelected}
              toggleSelectAllVisible={toggleSelectAllVisible}
              toggleDocSelection={toggleDocSelection}
              batchDeleteOpen={batchDeleteOpen}
              setBatchDeleteOpen={(open) => {
                setBatchDeleteOpen(open)
                setBatchDeleteError(null)
              }}
              batchDeleteError={batchDeleteError}
              batchDeleting={batchDeleting}
              confirmBatchDelete={confirmBatchDelete}
              batchLifecycleWorking={batchLifecycleWorking}
              batchReingestWorking={batchReingestWorking}
              runBatchReingest={runBatchReingest}
              runBatchLifecycle={runBatchLifecycle}
              anySelectedDisabled={selectedDocuments.some((doc) => doc.disabled_at)}
              anySelectedEnabled={selectedDocuments.some((doc) => !doc.disabled_at)}
              anySelectedArchived={selectedDocuments.some((doc) => doc.archived_at)}
              anySelectedNotArchived={selectedDocuments.some((doc) => !doc.archived_at)}
              deleteDocument={deleteDocument}
              onOpenDocument={(id) => openDocument(id)}
              onPeek={(id) => openDocument(id, undefined, undefined, { activeTab: 'chunks' })}
              operationsOpen={operationsOpen}
              setOperationsOpen={setOperationsOpen}
            />
          ) : null}
          {activeTab === 'retrieval' ? (
            <RetrievePreviewPanel
              selectedDatasetId={selectedDatasetId}
              availableDatasetIds={retrievalDatasetIds}
              scopeLabel={selectedDatasetLabel === undefined ? scopeT('dataset.all') : selectedDatasetLabel}
              aggregateDocuments={stats?.total ?? (isLoading || error ? undefined : total)}
              aggregateChunks={stats?.total_chunks}
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
                <div className="space-y-2">
                  <p className="text-[13px] font-medium">{scopeT('dataset.label')}</p>
                  {datasetSelect}
                </div>
                <div className="space-y-2">
                  <p className="text-[13px] font-medium">{scopeT('lifecycle.label')}</p>
                  <Select
                    value={lifecycleFilter}
                    onValueChange={(value) =>
                      updateQuery({ lifecycleFilter: value as KnowledgeQueryState['lifecycleFilter'] })
                    }
                  >
                    <SelectTrigger aria-label={scopeT('lifecycle.ariaLabel')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(['active', 'disabled', 'archived', 'all'] as const).map((value) => (
                        <SelectItem key={value} value={value}>
                          {scopeT('lifecycle.' + value)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {selectedDatasetId ? (
                  <DatasetFolderTree
                    datasetId={selectedDatasetId}
                    lifecycle={lifecycleFilter}
                    selectedPath={folderPath}
                    onSelect={(path) => updateQuery({ folderPath: path })}
                  />
                ) : (
                  <p className="text-[13px] leading-6 text-muted-foreground">选择数据集后可按文件夹筛选。</p>
                )}
                {hasActiveFilters ? (
                  <Button variant="outline" onClick={clearFilters}>
                    清空筛选
                  </Button>
                ) : null}
                <div className={styles.scopeTools}>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setScopeOpen(false)
                      setOperationsOpen(true)
                    }}
                  >
                    文档工具
                  </Button>
                  <Button variant="ghost" disabled={isLoading} onClick={() => detachPromise(refreshDocuments())}>
                    <RefreshCw className="size-4" />
                    刷新文档
                  </Button>
                </div>
              </div>
            </div>
          </SheetContent>
        </Sheet>
        <Sheet
          open={tasksOpen}
          onOpenChange={(open) => {
            setTasksOpen(open)
            if (!open && (query.connectorRunId || query.tasksOpen))
              updateQuery({ connectorRunId: null, tasksOpen: false })
          }}
        >
          <SheetContent className={cn(styles.sheet, styles.operationsSheet)}>
            <SheetHeader className={styles.sheetHeader}>
              <SheetTitle>任务历史</SheetTitle>
              <SheetDescription className="sr-only">当前数据集的导入任务与处理记录</SheetDescription>
            </SheetHeader>
            <div className={styles.sheetBody}>
              <KnowledgeConnectorRunsPanel
                selectedDatasetId={selectedDatasetId}
                connectorRuns={connectorRuns}
                connectorRunsLoading={connectorRunsLoading}
                connectorRunsError={connectorRunsError}
                onCancelConnectorRun={cancelConnectorRun}
                onResumeConnectorRun={resumeConnectorRun}
                onRetryFailedConnectorRun={retryFailedConnectorRun}
                onLoadConnectorRuns={loadConnectorRuns}
              />
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </AppFrame>
  )
}
