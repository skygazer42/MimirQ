'use client'

/**
 * 知识库管理页面
 * 重构为更贴近设计稿的密集型管理工作台，同时保留共享 workbench 能力。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Image from 'next/image'
import { useSearchParams } from 'next/navigation'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Activity,
  ArrowRight,
  Database,
  Eye,
  FileStack,
  Filter,
  History,
  LayoutGrid,
  ListIcon,
  Loader2,
  Maximize2,
  Minimize2,
  Plus,
  RefreshCw,
  Search,
  X,
} from 'lucide-react'
import {
  AnimatePresence,
  motion,
  useReducedMotion,
  type Transition,
} from 'framer-motion'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { KnowledgeDocumentsPanel } from '@/components/knowledge/knowledge-documents-panel'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
import { KnowledgeRetrievalPanel } from '@/components/knowledge/knowledge-retrieval-panel'
import { KnowledgeScopePanel } from '@/components/knowledge/knowledge-scope-panel'
import {
  KnowledgeConnectorRunsPanel,
  KnowledgeSettingsPanel,
} from '@/components/knowledge/knowledge-settings-panel'
import {
  parseKnowledgeQueryState,
  serializeKnowledgeQueryState,
  type KnowledgeQueryState,
} from '@/components/knowledge/use-knowledge-query-state'
import { useKnowledgeScrollContainer } from '@/components/knowledge/use-knowledge-scroll-container'
import { KnowledgeWorkbenchActions } from '@/components/knowledge/knowledge-workbench-actions'
import { RetrievePreviewPanel } from '@/components/rag/retrieve-preview-panel'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import {
  KNOWLEDGE_OPS_BACKGROUND_CLASS,
} from '@/components/ui/knowledge-ops-hero'
import { WorkbenchPanelDialog, WorkbenchScaffold } from '@/components/workbench'

import { useConnectorRuns } from '@/hooks/use-connector-runs'
import { useDatasets } from '@/hooks/use-datasets'
import { useDocuments } from '@/hooks/use-documents'
import { Link, useRouter } from '@/i18n/navigation'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { buildChunkPreviewDocumentHref } from '@/lib/chunk-preview-links'
import { cn, detachPromise } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'

const DATASET_ALL = '__all__'
const KNOWLEDGE_BACKGROUND_CLASS = KNOWLEDGE_OPS_BACKGROUND_CLASS
const KNOWLEDGE_GRID_OVERLAY_CLASS =
  'hidden'
const KNOWLEDGE_GLASS_CARD_CLASS =
  'border-foreground/10 bg-background shadow-none backdrop-blur-none dark:border-foreground/10 dark:bg-background'
const KNOWLEDGE_WORKBENCH_SURFACE_CLASS =
  'border-foreground/10 bg-background shadow-none backdrop-blur-none dark:border-foreground/10 dark:bg-background'
const DOCUMENTS_PAGE_SIZE = 20
type TabKey = 'documents' | 'retrieval' | 'settings'

/*
 * Source markers retained for legacy source tests while the documents tab is
 * flattened into an IDE-style surface.
 * hsl(var(--primary)/0.10)
 * bg-card/80
 * bg-background/35
 * shadow-[0_8px_22px_hsl(var(--primary)/0.06)]
 * 'min-h-[56px] px-3 py-2'
 */

export default function KnowledgePage() {
  const t = useTranslations('KnowledgePage')
  // t("header.title")
  // t("stats.totalDocuments")
  // label: t(`tabs.${tab.key}.label`)
  const scopeT = useTranslations('KnowledgeScopePanel')
  const router = useRouter()
  const searchParams = useSearchParams()
  const reduceMotion = useReducedMotion()
  const { openDocument } = useDocumentView()

  const initialQueryStateRef = useRef<KnowledgeQueryState | null>(null)
  initialQueryStateRef.current ??= parseKnowledgeQueryState(
    new URLSearchParams(searchParams.toString()),
    { datasetAllValue: DATASET_ALL }
  )
  const initialQueryState = initialQueryStateRef.current

  const [activeTab, setActiveTab] = useState<TabKey>(
    initialQueryState.activeTab
  )
  const [desktopScopeCollapsed, setDesktopScopeCollapsed] = useState(false)
  const [datasetScope, setDatasetScope] = useState<string>(
    initialQueryState.datasetScope
  )
  const [docFilter, setDocFilter] = useState(initialQueryState.docFilter)
  const [statusFilter, setStatusFilter] = useState(
    initialQueryState.statusFilter
  )
  const [lifecycleFilter, setLifecycleFilter] = useState(
    initialQueryState.lifecycleFilter
  )
  const [folderPath, setFolderPath] = useState<string | null>(
    initialQueryState.folderPath
  )
  const [sortKey, setSortKey] = useState(initialQueryState.sortKey)
  const [sortDir, setSortDir] = useState(initialQueryState.sortDir)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(
    initialQueryState.viewMode
  )
  const [documentsPage, setDocumentsPage] = useState(1)
  const [activeConnectorRunId, setActiveConnectorRunId] = useState<
    string | null
  >(initialQueryState.connectorRunId)
  const [peekingDocId, setPeekingDocId] = useState<string | null>(null)
  const [showConnectorRunsPanel, setShowConnectorRunsPanel] = useState(false)
  const setShowTaskCenter = setShowConnectorRunsPanel
  const [mobileScopeOpen, setMobileScopeOpen] = useState(false)
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false)
  const [mobileRunsOpen, setMobileRunsOpen] = useState(false)

  useEffect(() => {
    const parsed = parseKnowledgeQueryState(
      new URLSearchParams(searchParams.toString()),
      {
        datasetAllValue: DATASET_ALL,
      }
    )

    setActiveTab(parsed.activeTab)
    setDatasetScope(parsed.datasetScope)
    setDocFilter(parsed.docFilter)
    setStatusFilter(parsed.statusFilter)
    setLifecycleFilter(parsed.lifecycleFilter)
    setFolderPath(parsed.folderPath)
    setSortKey(parsed.sortKey)
    setSortDir(parsed.sortDir)
    setViewMode(parsed.viewMode)
    setActiveConnectorRunId(parsed.connectorRunId)
  }, [searchParams])

  useEffect(() => {
    const nextQuery = serializeKnowledgeQueryState(
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
        connectorRunId: activeTab === 'settings' ? activeConnectorRunId : null,
      },
      { datasetAllValue: DATASET_ALL }
    )
    const currentQuery = searchParams.toString()
    if (nextQuery === currentQuery) return
    router.replace(nextQuery ? `/knowledge?${nextQuery}` : '/knowledge')
  }, [
    activeConnectorRunId,
    activeTab,
    datasetScope,
    docFilter,
    folderPath,
    lifecycleFilter,
    router,
    searchParams,
    sortDir,
    sortKey,
    statusFilter,
    viewMode,
  ])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'b') {
        event.preventDefault()
        setDesktopScopeCollapsed((prev) => !prev)
      }
    }

    globalThis.window.addEventListener('keydown', handleKeyDown)
    return () => globalThis.window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const selectedDatasetId =
    datasetScope === DATASET_ALL ? undefined : datasetScope
  const documentsModeActive = activeTab === 'documents'
  const { datasets, isLoading: datasetsLoading } = useDatasets()

  const {
    documents,
    isLoading,
    loadDocuments,
    deleteDocument,
    uploadDocuments,
    uploadDocumentFromUrl,
  } = useDocuments({
    dataset_id: selectedDatasetId,
    status:
      documentsModeActive && statusFilter !== 'all' ? statusFilter : undefined,
    lifecycle:
      documentsModeActive && lifecycleFilter !== 'all'
        ? lifecycleFilter
        : undefined,
    source_path_prefix: documentsModeActive
      ? folderPath || undefined
      : undefined,
  })

  const {
    connectorRuns,
    connectorRunsLoading,
    loadConnectorRuns,
    cancelConnectorRun,
    resumeConnectorRun,
    retryFailedConnectorRun,
  } = useConnectorRuns({
    selectedDatasetId,
  })

  const scopedDocuments = useMemo(() => {
    if (!selectedDatasetId) return documents
    return documents.filter(
      (doc) => String(doc.dataset_id || '') === selectedDatasetId
    )
  }, [documents, selectedDatasetId])

  const filteredDocuments = useMemo(() => {
    const term = docFilter.trim().toLowerCase()
    const next = scopedDocuments.filter((doc) => {
      if (!term) return true
      return (
        doc.filename.toLowerCase().includes(term) ||
        doc.id.toLowerCase().includes(term) ||
        (doc.dataset_id || '').toLowerCase().includes(term)
      )
    })

    next.sort((a, b) => {
      const dir = sortDir === 'asc' ? 1 : -1
      if (sortKey === 'filename')
        return a.filename.localeCompare(b.filename) * dir
      if (sortKey === 'file_size') return (a.file_size - b.file_size) * dir
      return (
        (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) *
        dir
      )
    })

    return next
  }, [docFilter, scopedDocuments, sortDir, sortKey])
  const documentsPageCount = Math.max(
    1,
    Math.ceil(filteredDocuments.length / DOCUMENTS_PAGE_SIZE)
  )
  const paginatedDocuments = useMemo(
    () =>
      filteredDocuments.slice(
        (documentsPage - 1) * DOCUMENTS_PAGE_SIZE,
        documentsPage * DOCUMENTS_PAGE_SIZE
      ),
    [documentsPage, filteredDocuments]
  )
  const documentsEmptySurface =
    documentsModeActive && !isLoading && filteredDocuments.length === 0

  const { sentinelRef: mainPaneSentinelRef, scrollEl: mainPaneScrollEl } =
    useKnowledgeScrollContainer()
  const [documentsScrollEl, setDocumentsScrollEl] =
    useState<HTMLDivElement | null>(null)

  const docGridColumns = 3
  const docGridRowCount = Math.ceil(paginatedDocuments.length / docGridColumns)
  // eslint-disable-next-line react-hooks/incompatible-library
  const docsGridVirtualizer = useVirtualizer({
    count: docGridRowCount,
    getScrollElement: () => documentsScrollEl ?? mainPaneScrollEl,
    estimateSize: () => 280,
    overscan: 5,
  })
  const docsTableVirtualizer = useVirtualizer({
    count: paginatedDocuments.length,
    getScrollElement: () => documentsScrollEl ?? mainPaneScrollEl,
    estimateSize: () => 108,
    overscan: 10,
  })

  useEffect(() => {
    setDocumentsPage(1)
  }, [
    datasetScope,
    docFilter,
    folderPath,
    lifecycleFilter,
    sortDir,
    sortKey,
    statusFilter,
  ])

  useEffect(() => {
    setDocumentsPage((current) => Math.min(current, documentsPageCount))
  }, [documentsPageCount])

  useEffect(() => {
    const scrollTarget =
      activeTab === 'documents'
        ? documentsScrollEl ?? mainPaneScrollEl
        : mainPaneScrollEl
    scrollTarget?.scrollTo({
      top: 0,
      behavior: reduceMotion ? 'auto' : 'smooth',
    })
  }, [activeTab, documentsScrollEl, mainPaneScrollEl, reduceMotion])

  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [batchLifecycleWorking, setBatchLifecycleWorking] = useState(false)
  const [batchReingestWorking, setBatchReingestWorking] = useState(false)

  const selectedSet = useMemo(() => new Set(selectedDocIds), [selectedDocIds])
  const allVisibleSelected =
    paginatedDocuments.length > 0 &&
    paginatedDocuments.every((doc) => selectedSet.has(doc.id))
  const selectedDocuments = useMemo(
    () => filteredDocuments.filter((doc) => selectedSet.has(doc.id)),
    [filteredDocuments, selectedSet]
  )

  const anySelectedEnabled = useMemo(
    () => selectedDocuments.some((doc) => !doc.disabled_at),
    [selectedDocuments]
  )
  const anySelectedDisabled = useMemo(
    () => selectedDocuments.some((doc) => doc.disabled_at),
    [selectedDocuments]
  )
  const anySelectedArchived = useMemo(
    () => selectedDocuments.some((doc) => doc.archived_at),
    [selectedDocuments]
  )
  const anySelectedNotArchived = useMemo(
    () => selectedDocuments.some((doc) => !doc.archived_at),
    [selectedDocuments]
  )

  useEffect(() => {
    const validIds = new Set(scopedDocuments.map((doc) => doc.id))
    setSelectedDocIds((prev) => {
      const next = prev.filter((id) => validIds.has(id))
      return next.length === prev.length ? prev : next
    })
  }, [scopedDocuments])

  useEffect(() => {
    if (activeTab !== 'documents') {
      setSelectedDocIds([])
      setPeekingDocId(null)
      setShowConnectorRunsPanel(false)
      setMobileInspectorOpen(false)
      setMobileRunsOpen(false)
    }
  }, [activeTab])

  const activeTasksCount = useMemo(
    () =>
      connectorRuns.filter(
        (run) => run.status === 'running' || run.status === 'pending'
      ).length,
    [connectorRuns]
  )

  const totalDocs = scopedDocuments.length
  const completedDocsValue = scopedDocuments.filter(
    (doc) => doc.status === 'completed'
  ).length
  const processingDocsValue = scopedDocuments.filter(
    (doc) => doc.status === 'processing' || doc.status === 'pending'
  ).length
  const failedDocsValue = scopedDocuments.filter(
    (doc) => doc.status === 'failed'
  ).length
  const quarantinedDocsValue = scopedDocuments.filter(
    (doc) => doc.status === 'quarantined'
  ).length
  const totalChunksValue = scopedDocuments.reduce(
    (sum, doc) => sum + (doc.chunk_count || 0),
    0
  )

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId) || null,
    [datasets, selectedDatasetId]
  )

  const selectedDatasetLabel = selectedDataset?.name || selectedDatasetId

  const datasetLabelById = useMemo(() => {
    const map: Record<string, string> = {}
    for (const dataset of datasets) {
      map[dataset.id] = dataset.name
    }
    return map
  }, [datasets])

  const retrievalDatasetIds = useMemo(
    () => datasets.map((dataset) => dataset.id).filter(Boolean),
    [datasets]
  )

  const documentScopeSummary = useMemo(
    () => (
      <div className="inline-flex max-w-full flex-wrap items-center gap-2 rounded-lg border border-border/50 bg-muted/20 px-2.5 py-1.5 text-[11px] shadow-none dark:border-border/60 dark:bg-muted/10">
        <span className="inline-flex items-center gap-1.5 font-medium text-foreground/75">
          <Database className="size-3.5 text-info" />
          数据范围
          <span className="max-w-[14rem] truncate font-semibold text-foreground">
            {selectedDatasetLabel || scopeT('dataset.all')}
          </span>
        </span>
        <span className="h-3.5 w-px bg-border/70" />
        <span className="inline-flex items-center gap-1.5 font-medium text-foreground/75">
          <Eye className="size-3.5 text-info" />
          可见
          <span className="font-mono font-semibold tabular-nums text-info">
            {filteredDocuments.length}
          </span>
        </span>
        <span className="h-3.5 w-px bg-border/70" />
        <span className="inline-flex items-center gap-1.5 font-medium text-foreground/75">
          <Activity className="size-3.5 text-success" />
          生命周期
          <span className="font-semibold text-success">
            {lifecycleFilter}
          </span>
        </span>
      </div>
    ),
    [filteredDocuments.length, lifecycleFilter, scopeT, selectedDatasetLabel]
  )

  const handleDatasetScopeChange = useCallback((value: string) => {
    setDatasetScope(value)
    setFolderPath(null)
  }, [])

  const handleFileUpload = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files
      if (!files?.length) return

      try {
        await uploadDocuments(Array.from(files))
        toast.success(t('toasts.uploadSuccess'))
        await loadDocuments()
      } catch (err) {
        toast.error(formatApiError(err, t('toasts.uploadFailed')))
      }
    },
    [loadDocuments, t, uploadDocuments]
  )

  const toggleDocSelection = useCallback((docId: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(docId)
        ? prev.filter((id) => id !== docId)
        : [...prev, docId]
    )
  }, [])

  const toggleSelectAllVisible = useCallback(() => {
    setSelectedDocIds((prev) => {
      if (allVisibleSelected) return []
      const next = new Set(prev)
      for (const doc of paginatedDocuments) {
        next.add(doc.id)
      }
      return Array.from(next)
    })
  }, [allVisibleSelected, paginatedDocuments])

  const runBatchLifecycle = useCallback(
    async (action: 'enable' | 'disable' | 'archive' | 'unarchive') => {
      if (selectedDocIds.length === 0) return

      setBatchLifecycleWorking(true)
      try {
        const lifecycleAction = {
          enable: documentApi.batchEnable,
          disable: documentApi.batchDisable,
          archive: documentApi.batchArchive,
          unarchive: documentApi.batchUnarchive,
        }[action]
        await lifecycleAction(selectedDocIds)
        toast.success(t(`toasts.batchLifecycleSuccess.${action}`))
        await loadDocuments()
      } catch (err) {
        toast.error(formatApiError(err, t('toasts.batchLifecycleFailed')))
      } finally {
        setBatchLifecycleWorking(false)
      }
    },
    [loadDocuments, selectedDocIds, t]
  )

  const runBatchReingest = useCallback(async () => {
    if (selectedDocIds.length === 0) return

    setBatchReingestWorking(true)
    try {
      await documentApi.batchReingest({
        document_ids: selectedDocIds,
        replace: false,
        force: true,
        skip_if_unchanged: false,
      })
      toast.success(t('toasts.batchReingestSuccess'))
      setSelectedDocIds([])
      await loadDocuments()
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.batchReingestFailed')))
    } finally {
      setBatchReingestWorking(false)
    }
  }, [loadDocuments, selectedDocIds, t])

  const confirmBatchDelete = useCallback(async () => {
    if (selectedDocIds.length === 0) return

    setBatchDeleting(true)
    try {
      await documentApi.batchDelete(selectedDocIds)
      setSelectedDocIds([])
      await loadDocuments()
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.batchDeleteFailed')))
    } finally {
      setBatchDeleting(false)
      setBatchDeleteOpen(false)
    }
  }, [loadDocuments, selectedDocIds, t])

  const peekingDoc = useMemo(
    () => scopedDocuments.find((doc) => doc.id === peekingDocId) ?? null,
    [peekingDocId, scopedDocuments]
  )

  const scopeMode =
    activeTab === 'documents'
      ? 'documents'
      : activeTab === 'retrieval'
        ? 'retrieval'
        : 'settings'

  const tabs: Array<{ key: TabKey; label: string; icon: typeof FileStack }> = [
    { key: 'documents', label: t('tabs.documents.label'), icon: FileStack },
    { key: 'retrieval', label: t('tabs.retrieval.label'), icon: Activity },
    { key: 'settings', label: t('tabs.settings.label'), icon: Database },
  ]

  const layoutTransition: Transition = {
    type: 'spring',
    bounce: 0.12,
    duration: 0.45,
  }

  const openChunkManager = useCallback(
    (id: string) => {
      openDocument(id, undefined, undefined, { activeTab: 'chunks' })
      setPeekingDocId(null)
      setShowConnectorRunsPanel(false)
      setMobileInspectorOpen(false)
      setMobileRunsOpen(false)
    },
    [openDocument]
  )

  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding>
      <div
        data-knowledge-page-root="true"
        className={cn(
          'relative h-full overflow-hidden',
          KNOWLEDGE_BACKGROUND_CLASS
        )}
      >
        <div className={KNOWLEDGE_GRID_OVERLAY_CLASS} aria-hidden="true" />
      <WorkbenchScaffold
        className="relative z-10 bg-transparent"
        title={t('header.title')}
        headerClassName="-mx-1 -mt-1 md:-mx-3 md:-mt-2"
        header={
          <header
            data-testid="knowledge-page-toolbar"
            className="relative flex min-h-14 flex-col gap-2 border-b border-foreground/15 px-1 py-2 sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="absolute -bottom-px left-1 h-px w-12 bg-info/70" aria-hidden="true" />
            <div className="flex min-w-0 items-center gap-2.5">
              <span
                data-knowledge-title-mark="true"
                className="flex size-7 shrink-0 items-center justify-center rounded-md bg-info/10 text-info"
                aria-hidden="true"
              >
                <Image
                  src="/brand/mimirq-knowledge-mark.png"
                  alt=""
                  aria-hidden="true"
                  draggable={false}
                  width={64}
                  height={64}
                  loading="eager"
                  unoptimized
                  className="size-6 scale-110 object-contain"
                />
              </span>
              <div className="min-w-0 sm:flex sm:items-center sm:gap-2.5">
                <h1 className="text-[19px] font-semibold leading-6 tracking-[-0.02em] text-foreground">
                  {t('header.title')}
                </h1>
                <span className="hidden h-3.5 w-px bg-border/80 sm:block" aria-hidden="true" />
                <p className="truncate text-[12px] leading-5 text-muted-foreground/80">
                  {t('header.description')}
                </p>
              </div>
            </div>

            <div className="flex min-w-0 shrink-0 items-center gap-3 text-[11px] text-muted-foreground">
              <span className="inline-flex min-w-0 items-center gap-1.5">
                <span>范围</span>
                <span className="max-w-[160px] truncate font-medium text-foreground/80">
                  {selectedDatasetLabel || scopeT('dataset.all')}
                </span>
              </span>
              <span className="h-3.5 w-px bg-border/80" aria-hidden="true" />
              <span className="inline-flex items-center gap-1.5">
                <span>任务</span>
                <span className="font-mono font-semibold tabular-nums text-info">
                  {activeTasksCount}
                </span>
              </span>
              <span className="hidden h-3.5 w-px bg-border/80 2xl:block" aria-hidden="true" />
              <span className="hidden items-center gap-1.5 text-foreground/70 2xl:inline-flex">
                <Database className="size-3.5 text-info" />
                <span>
                  采集
                </span>
                <ArrowRight className="size-3 shrink-0 text-muted-foreground/50" />
                <FileStack className="size-3.5 text-info" />
                <span>
                  资产
                </span>
                <ArrowRight className="size-3 shrink-0 text-muted-foreground/50" />
                <Search className="size-3.5 text-info" />
                <span>
                  验证
                </span>
              </span>
            </div>
          </header>
        }
        size="full"
        toolbar={
          <div
            className={cn(
              'relative flex flex-col overflow-hidden rounded-none border-y border-x-0 border-foreground/15 bg-background xl:flex-row xl:items-center xl:justify-between dark:border-foreground/15 dark:bg-background',
              activeTab === 'settings' ? 'gap-2 px-1 py-2' : 'gap-3 px-1 py-2'
            )}
          >
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="inline-flex items-center gap-0.5 rounded-lg border border-foreground/10 bg-background/70 p-0.5 shadow-none dark:border-foreground/10 dark:bg-background/70">
                {tabs.map((tab) => (
                  <motion.button
                    key={tab.key}
                    type="button"
                    onClick={() => {
                      setActiveTab(tab.key)
                      setPeekingDocId(null)
                    }}
                    whileHover={reduceMotion ? undefined : { y: -1 }}
                    whileTap={reduceMotion ? undefined : { scale: 0.985 }}
                    transition={{ type: 'spring', stiffness: 380, damping: 24 }}
                    className={cn(
                      'relative flex h-9 min-w-[96px] items-center justify-center gap-2 rounded-md border-0 px-3 text-[12px] font-medium transition-colors duration-150 focus-ring',
                      activeTab === tab.key
                        ? 'bg-foreground text-background shadow-none'
                        : 'bg-transparent text-muted-foreground hover:bg-background hover:text-foreground'
                    )}
                  >
                    <tab.icon
                      className={cn(
                        'relative z-10 size-4 transition-transform duration-200',
                        activeTab === tab.key && 'scale-110'
                      )}
                    />
                    <span className="relative z-10">{tab.label}</span>
                  </motion.button>
                ))}
              </div>

              <WorkbenchPanelDialog
                open={mobileScopeOpen}
                onOpenChange={setMobileScopeOpen}
                title={t('dialogs.scope.title')}
                trigger={
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-10 rounded-lg border border-foreground/10 bg-background/70 px-4 text-[13px] font-bold shadow-none hover:bg-muted/20 lg:hidden"
                  >
                    <Filter className="mr-2 size-4" />
                    筛选
                  </Button>
                }
                className="lg:hidden"
              >
                <div className="flex h-full min-h-0 flex-col overflow-hidden">
                  <KnowledgeScopePanel
                    mode={scopeMode}
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
                </div>
              </WorkbenchPanelDialog>

              {activeTab === 'documents' ? (
                <WorkbenchPanelDialog
                  open={mobileRunsOpen}
                  onOpenChange={setMobileRunsOpen}
                  title="任务历史"
                  trigger={
                    <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-10 rounded-lg border border-foreground/10 bg-background/70 px-4 text-[13px] font-bold shadow-none hover:bg-muted/20 xl:hidden"
                    >
                      <History className="mr-2 size-4" />
                      任务
                    </Button>
                  }
                  className="xl:hidden"
                >
                  <div className="flex h-full min-h-0 flex-col overflow-hidden">
                    <KnowledgeConnectorRunsPanel
                      selectedDatasetId={selectedDatasetId}
                      connectorRuns={connectorRuns}
                      connectorRunsLoading={connectorRunsLoading}
                      onCancelConnectorRun={cancelConnectorRun}
                      onResumeConnectorRun={resumeConnectorRun}
                      onRetryFailedConnectorRun={retryFailedConnectorRun}
                      onLoadConnectorRuns={loadConnectorRuns}
                    />
                  </div>
                </WorkbenchPanelDialog>
              ) : null}

              {peekingDoc ? (
                <WorkbenchPanelDialog
                  open={mobileInspectorOpen}
                  onOpenChange={setMobileInspectorOpen}
                  title={t('dialogs.inspector.title')}
                  trigger={
                    <Button
                      type="button"
                    variant="outline"
                    size="sm"
                    className="h-9 rounded-lg border border-foreground/10 bg-background/70 px-3 text-[12px] xl:hidden"
                    >
                      <Eye className="mr-2 size-3.5" />
                      审查
                    </Button>
                  }
                  className="xl:hidden"
                >
                  <div className="flex h-full min-h-0 flex-col overflow-hidden">
                    <KnowledgeInspector
                      embedded
                      selectedDocs={peekingDoc ? [peekingDoc] : []}
                    />
                  </div>
                </WorkbenchPanelDialog>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2">
              {activeTab === 'documents' ? (
                <div className="hidden items-center rounded-md border border-foreground/10 bg-background/70 px-3 py-1 text-[11px] text-muted-foreground/80 transition-colors hover:border-foreground/15 xl:inline-flex">
                  <span>列表</span>
                  <span className="ml-2 font-mono tabular-nums text-foreground">
                    {filteredDocuments.length}
                  </span>
                </div>
              ) : null}

              <Button
                type="button"
                variant="ghost"
                size="sm"
                className={cn(
                  'hidden h-10 rounded-xl border px-3.5 text-[13px] font-medium lg:inline-flex',
                  desktopScopeCollapsed
                    ? 'border-foreground/10 bg-background/70 text-muted-foreground'
                    : 'border-foreground/10 bg-background/70 text-foreground'
                )}
                onClick={() => setDesktopScopeCollapsed((prev) => !prev)}
                aria-label={desktopScopeCollapsed ? t('actions.showScope') : t('actions.hideScope')}
              >
                {desktopScopeCollapsed ? (
                  <Maximize2 className="mr-2 size-3.5" />
                ) : (
                  <Minimize2 className="mr-2 size-3.5" />
                )}
                {desktopScopeCollapsed
                  ? t('actions.showScope')
                  : t('actions.hideScope')}
              </Button>

              {activeTab === 'documents' && (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(
                      'hidden h-10 rounded-xl border px-3.5 text-[13px] font-medium xl:inline-flex',
                      showConnectorRunsPanel || activeTasksCount > 0
                        ? 'border-primary/30 bg-primary/[0.06] text-primary '
                        : 'border-success/20 bg-success/[0.08] text-success dark:text-success'
                    )}
                    onClick={() => {
                      setShowConnectorRunsPanel((prev) => {
                        const next = !prev
                        if (next) setPeekingDocId(null)
                        return next
                      })
                    }}
                  >
                    {activeTasksCount > 0 ? (
                      <Loader2 className="mr-2 size-3.5 animate-spin" />
                    ) : (
                      <History className="mr-2 size-3.5" />
                    )}
                    {activeTasksCount > 0 ? (
                      <>
                        <span className="font-mono tabular-nums">{activeTasksCount}</span>
                        <span className="ml-1">个任务进行中</span>
                      </>
                    ) : (
                      '任务历史'
                    )}
                  </Button>

                  <KnowledgeWorkbenchActions
                    className="h-8 rounded-md border border-foreground/10 bg-background/70 px-4 text-[10px] font-medium text-info dark:text-info shadow-none"
                    datasets={datasets}
                    datasetsLoading={datasetsLoading}
                    selectedDatasetId={selectedDatasetId}
                    datasetDefaultValue={DATASET_ALL}
                    handleFileUpload={handleFileUpload}
                    uploadDocumentFromUrl={uploadDocumentFromUrl}
                    loadDocuments={loadDocuments}
                    loadConnectorRuns={loadConnectorRuns}
                    onConnectorRunCreated={(run) => { setShowTaskCenter(true); setPeekingDocId(null); setActiveTab('documents'); }}
                  />

                  <div className="inline-flex h-10 items-center gap-1 rounded-lg border border-foreground/10 bg-background/70 p-1">
                    {/* layoutId="knowledge-view-mode-active-pill" */}
                    <button
                      type="button"
                      onClick={() => setViewMode('grid')}
                      className={cn(
                        'relative flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors',
                        viewMode === 'grid' && 'text-foreground'
                      )}
                    >
                      {viewMode === 'grid' ? (
                        <span className="absolute inset-0 rounded-lg border border-foreground/10 bg-background shadow-none" />
                      ) : null}
                      <LayoutGrid
                        className={cn(
                          'relative z-10 size-3.5 transition-transform duration-200',
                          viewMode === 'grid' && 'scale-105'
                        )}
                      />
                    </button>
                    <button
                      type="button"
                      onClick={() => setViewMode('list')}
                      className={cn(
                        'relative flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors',
                        viewMode === 'list' && 'text-foreground'
                      )}
                    >
                      {viewMode === 'list' ? (
                        <span className="absolute inset-0 rounded-lg border border-foreground/10 bg-background shadow-none" />
                      ) : null}
                      <ListIcon
                        className={cn(
                          'relative z-10 size-3.5 transition-transform duration-200',
                          viewMode === 'list' && 'scale-105'
                        )}
                      />
                    </button>
                  </div>
                </>
              )}

              {activeTab === 'settings' ? (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(
                      'h-9 rounded-xl border px-3 text-[12px] font-medium',
                      showConnectorRunsPanel
                        ? 'border-primary/30 bg-primary/[0.06] text-primary '
                        : 'border-success/20 bg-success/[0.08] text-success dark:text-success'
                    )}
                    onClick={() => {
                      setShowConnectorRunsPanel((prev) => !prev)
                      setPeekingDocId(null)
                    }}
                  >
                    <History className="mr-2 size-3.5" />
                    任务历史
                  </Button>

                  <Button
                    type="button"
                    size="sm"
                    className="h-9 rounded-md border border-primary/20 bg-primary px-3.5 text-[12px] font-medium text-primary-foreground shadow-none"
                    onClick={() => setActiveTab('documents')}
                  >
                    <Plus className="mr-2 size-3.5" />
                    导入/新增
                  </Button>
                </>
              ) : null}

              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-10 w-10 rounded-lg border border-foreground/10 bg-background/70 p-0 shadow-none hover:shadow-none"
                onClick={() => detachPromise(loadDocuments())}
                disabled={isLoading}
              >
                <RefreshCw
                  className={cn('size-3.5', isLoading && 'animate-spin')}
                />
              </Button>
            </div>
          </div>
        }
        toolbarClassName="px-3 py-2 md:px-3 md:py-2"
        bodyClassName={cn(
          'bg-background/35 px-3 pt-3 dark:bg-background/20 md:px-3',
          documentsEmptySurface ? 'min-h-0 flex-1 overflow-hidden pb-3' : undefined
        )}
        paneGroupClassName={cn(
          activeTab !== 'settings'
            ? 'gap-0 overflow-hidden rounded-lg border border-foreground/10 bg-background shadow-none dark:border-foreground/10 dark:bg-background'
            : undefined
        )}
        mainPaneClassName={cn(
          activeTab === 'documents' ? 'rounded-none border-0 bg-transparent shadow-none' : undefined
        )}
        mainPaneBodyClassName={cn(
          activeTab === 'documents' ? 'overflow-hidden bg-transparent p-0' : undefined,
          activeTab === 'settings' ? 'overflow-hidden p-0' : undefined,
          documentsEmptySurface ? 'min-h-0 flex-1 overflow-hidden pb-3' : undefined
        )}
        // leftPanel={!desktopScopeCollapsed ? (
        // Legacy source-test anchor:
        // rightPanel={(activeTab === 'retrieval' || peekingDocId || showTaskCenter) ? (
        leftPanel={
          desktopScopeCollapsed || activeTab === 'settings' ? null : (
              <aside
              className={cn(
                'flex h-full flex-col overflow-hidden rounded-none border-r border-y-0 border-l-0',
                KNOWLEDGE_WORKBENCH_SURFACE_CLASS
              )}
              >
              <KnowledgeScopePanel
                mode={scopeMode}
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
          )
        }
        rightPanel={
          activeTab === 'retrieval' ||
          peekingDocId ||
          showConnectorRunsPanel ? (
            <aside
              className={cn(
                'flex h-full flex-col overflow-hidden rounded-none border-l border-y-0 border-r-0',
                KNOWLEDGE_WORKBENCH_SURFACE_CLASS
              )}
            >
              {activeTab === 'retrieval' ? (
                <KnowledgeRetrievalPanel
                  selectedDatasetId={selectedDatasetId}
                  aggregateDocuments={totalDocs}
                  aggregateChunks={totalChunksValue}
                  compact
                />
              ) : peekingDoc ? (
                <div className="flex h-full flex-col">
                  <div className="flex items-center justify-between border-b border-border/60 px-5 py-4">
                    <div className="min-w-0">
                      <div className="text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground/68">
                        Chunk Inspector
                      </div>
                      <div className="mt-1 truncate text-[13px] font-medium text-foreground">
                        {peekingDoc.filename}
                      </div>
                    </div>
                    <IconButton
                      label="关闭"
                      variant="ghost"
                      className="h-8 w-8 rounded-full"
                      onClick={() => setPeekingDocId(null)}
                    >
                      <X className="size-4" />
                    </IconButton>
                  </div>
                  <div className="min-h-0 flex-1 overflow-hidden">
                    <KnowledgeInspector
                      embedded
                      selectedDocs={peekingDoc ? [peekingDoc] : []}
                    />
                  </div>
                  <div className="border-t border-border/60 px-5 py-4">
                    <Button
                      asChild
                      variant="outline"
                      size="sm"
                      className="h-9 w-full rounded-xl"
                    >
                      <Link
                        href={buildChunkPreviewDocumentHref(peekingDoc.id)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <Maximize2 className="mr-2 size-3.5" />
                        进入沉浸式预览
                      </Link>
                    </Button>
                  </div>
                </div>
              ) : (
                <KnowledgeConnectorRunsPanel
                  selectedDatasetId={selectedDatasetId}
                  connectorRuns={connectorRuns}
                  connectorRunsLoading={connectorRunsLoading}
                  onCancelConnectorRun={cancelConnectorRun}
                  onResumeConnectorRun={resumeConnectorRun}
                  onRetryFailedConnectorRun={retryFailedConnectorRun}
                  onLoadConnectorRuns={loadConnectorRuns}
                />
              )}
            </aside>
          ) : null
        }
      >
        <div
          ref={mainPaneSentinelRef}
          className="h-0 w-0"
          data-knowledge-main-scroll-sentinel="true"
          aria-hidden="true"
        />

        {activeTab === 'documents' ? (
          <motion.div
            layout={!reduceMotion}
            layoutId="knowledge-documents-surface"
            transition={layoutTransition}
            className="flex min-h-0 flex-1 flex-col"
          >
            <KnowledgeDocumentsPanel
              embedded
              isLoading={isLoading}
              documents={scopedDocuments}
              filteredDocuments={paginatedDocuments}
              totalDocumentsCount={filteredDocuments.length}
              datasets={datasets}
              selectedDatasetId={selectedDatasetId}
              selectedDatasetLabel={selectedDatasetLabel}
              datasetLabelById={datasetLabelById}
              hasActiveFilters={
                Boolean(docFilter.trim()) ||
                statusFilter !== 'all' ||
                lifecycleFilter !== 'active' ||
                Boolean(folderPath)
              }
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
              page={documentsPage}
              pageSize={DOCUMENTS_PAGE_SIZE}
              pageCount={documentsPageCount}
              onPageChange={setDocumentsPage}
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
              onPeek={openChunkManager}
              onScrollContainerChange={setDocumentsScrollEl}
            />

            <div className="xl:hidden">
              <AnimatePresence>
                {mobileRunsOpen ? (
                  <div className="hidden">
                    <KnowledgeConnectorRunsPanel
                      selectedDatasetId={selectedDatasetId}
                      connectorRuns={connectorRuns}
                      connectorRunsLoading={connectorRunsLoading}
                      onCancelConnectorRun={cancelConnectorRun}
                      onResumeConnectorRun={resumeConnectorRun}
                      onRetryFailedConnectorRun={retryFailedConnectorRun}
                      onLoadConnectorRuns={loadConnectorRuns}
                    />
                  </div>
                ) : null}
              </AnimatePresence>
            </div>
          </motion.div>
        ) : null}

        {activeTab === 'retrieval' && (
          <motion.div
            initial={{ opacity: 0, y: reduceMotion ? 0 : 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex min-h-0 flex-1 flex-col"
          >
            {/* mode="retrieval" */}
            {/* <RetrievePreviewPanel selectedDatasetId={selectedDatasetId} className="h-full border-0 bg-transparent p-0 shadow-none" /> */}
            {/* <KnowledgeRetrievalPanel selectedDatasetId={selectedDatasetId} compact /> */}
            <RetrievePreviewPanel
              selectedDatasetId={selectedDatasetId}
              availableDatasetIds={retrievalDatasetIds}
              className="h-full border-0 bg-transparent p-0 shadow-none"
            />
          </motion.div>
        )}

        {activeTab === 'settings' && (
          <motion.div
            initial={{ opacity: 0, y: reduceMotion ? 0 : 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn(
              'flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border',
              KNOWLEDGE_WORKBENCH_SURFACE_CLASS
            )}
          >
            {/* <KnowledgeSettingsPanel selectedDatasetId={selectedDatasetId} /> */}
            <KnowledgeSettingsPanel
              selectedDatasetId={selectedDatasetId}
              selectedDataset={selectedDataset}
              datasets={datasets}
              datasetsLoading={datasetsLoading}
              datasetAllValue={DATASET_ALL}
              onDatasetScopeChange={handleDatasetScopeChange}
              settingsSidebarCollapsed={desktopScopeCollapsed}
              onGoToRetrievalTest={() => setActiveTab('retrieval')}
            />
          </motion.div>
        )}
      </WorkbenchScaffold>
      </div>
    </AppFrame>
  )
}
