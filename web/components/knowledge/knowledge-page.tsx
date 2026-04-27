'use client'

/**
 * 知识库管理页面
 * 重构为更贴近设计稿的密集型管理工作台，同时保留共享 workbench 能力。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Activity,
  CheckCircle,
  Database,
  Eye,
  FileStack,
  Filter,
  HardDrive,
  History,
  Layers,
  LayoutGrid,
  ListIcon,
  Loader2,
  Maximize2,
  Minimize2,
  Plus,
  RefreshCw,
  Star,
  X,
} from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { KnowledgeDocumentsPanel } from '@/components/knowledge/knowledge-documents-panel'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
import { KnowledgeRetrievalPanel } from '@/components/knowledge/knowledge-retrieval-panel'
import { KnowledgeScopePanel } from '@/components/knowledge/knowledge-scope-panel'
import { KnowledgeConnectorRunsPanel, KnowledgeSettingsPanel } from '@/components/knowledge/knowledge-settings-panel'
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
import { WorkbenchPanelDialog, WorkbenchScaffold } from '@/components/workbench'

import { useConnectorRuns } from '@/hooks/use-connector-runs'
import { useDatasets } from '@/hooks/use-datasets'
import { useDocuments } from '@/hooks/use-documents'
import { Link, useRouter } from '@/i18n/navigation'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise, formatFileSize } from '@/lib/utils'

const DATASET_ALL = '__all__'
type TabKey = 'documents' | 'retrieval' | 'settings'

export default function KnowledgePage() {
  const t = useTranslations('KnowledgePage')
  // t("header.title")
  // t("stats.totalDocuments")
  // label: t(`tabs.${tab.key}.label`)
  const scopeT = useTranslations('KnowledgeScopePanel')
  const router = useRouter()
  const searchParams = useSearchParams()
  const reduceMotion = useReducedMotion()

  const initialQueryStateRef = useRef<KnowledgeQueryState | null>(null)
  if (!initialQueryStateRef.current) {
    initialQueryStateRef.current = parseKnowledgeQueryState(
      new URLSearchParams(searchParams.toString()),
      { datasetAllValue: DATASET_ALL }
    )
  }
  const initialQueryState = initialQueryStateRef.current

  const [activeTab, setActiveTab] = useState<TabKey>(initialQueryState.activeTab)
  const [desktopScopeCollapsed, setDesktopScopeCollapsed] = useState(false)
  const [datasetScope, setDatasetScope] = useState<string>(initialQueryState.datasetScope)
  const [docFilter, setDocFilter] = useState(initialQueryState.docFilter)
  const [statusFilter, setStatusFilter] = useState(initialQueryState.statusFilter)
  const [lifecycleFilter, setLifecycleFilter] = useState(initialQueryState.lifecycleFilter)
  const [folderPath, setFolderPath] = useState<string | null>(initialQueryState.folderPath)
  const [sortKey, setSortKey] = useState(initialQueryState.sortKey)
  const [sortDir, setSortDir] = useState(initialQueryState.sortDir)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(initialQueryState.viewMode)
  const [activeConnectorRunId, setActiveConnectorRunId] = useState<string | null>(initialQueryState.connectorRunId)
  const [peekingDocId, setPeekingDocId] = useState<string | null>(null)
  const [showConnectorRunsPanel, setShowConnectorRunsPanel] = useState(false)
  const [mobileScopeOpen, setMobileScopeOpen] = useState(false)
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false)
  const [mobileRunsOpen, setMobileRunsOpen] = useState(false)

  useEffect(() => {
    const parsed = parseKnowledgeQueryState(new URLSearchParams(searchParams.toString()), {
      datasetAllValue: DATASET_ALL,
    })

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

  const selectedDatasetId = datasetScope === DATASET_ALL ? undefined : datasetScope
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
    status: documentsModeActive && statusFilter !== 'all' ? statusFilter : undefined,
    lifecycle: documentsModeActive && lifecycleFilter !== 'all' ? lifecycleFilter : undefined,
    source_path_prefix: documentsModeActive ? folderPath || undefined : undefined,
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

  const filteredDocuments = useMemo(() => {
    const term = docFilter.trim().toLowerCase()
    const next = documents.filter((doc) => {
      if (!term) return true
      return (
        doc.filename.toLowerCase().includes(term) ||
        doc.id.toLowerCase().includes(term) ||
        (doc.dataset_id || '').toLowerCase().includes(term)
      )
    })

    next.sort((a, b) => {
      const dir = sortDir === 'asc' ? 1 : -1
      if (sortKey === 'filename') return a.filename.localeCompare(b.filename) * dir
      if (sortKey === 'file_size') return (a.file_size - b.file_size) * dir
      return (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) * dir
    })

    return next
  }, [docFilter, documents, sortDir, sortKey])

  const { sentinelRef: mainPaneSentinelRef, scrollEl: mainPaneScrollEl } = useKnowledgeScrollContainer()

  const docGridColumns = 3
  const docGridRowCount = Math.ceil(filteredDocuments.length / docGridColumns)
  const docsGridVirtualizer = useVirtualizer({
    count: docGridRowCount,
    getScrollElement: () => mainPaneScrollEl,
    estimateSize: () => 280,
    overscan: 5,
  })
  const docsTableVirtualizer = useVirtualizer({
    count: filteredDocuments.length,
    getScrollElement: () => mainPaneScrollEl,
    estimateSize: () => 52,
    overscan: 10,
  })

  useEffect(() => {
    mainPaneScrollEl?.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' })
  }, [activeTab, mainPaneScrollEl, reduceMotion])

  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)
  const [batchLifecycleWorking, setBatchLifecycleWorking] = useState(false)
  const [batchReingestWorking, setBatchReingestWorking] = useState(false)

  const selectedSet = useMemo(() => new Set(selectedDocIds), [selectedDocIds])
  const allVisibleSelected =
    filteredDocuments.length > 0 && filteredDocuments.every((doc) => selectedSet.has(doc.id))
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
    const validIds = new Set(documents.map((doc) => doc.id))
    setSelectedDocIds((prev) => {
      const next = prev.filter((id) => validIds.has(id))
      return next.length === prev.length ? prev : next
    })
  }, [documents])

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
    () => connectorRuns.filter((run) => run.status === 'running' || run.status === 'pending').length,
    [connectorRuns]
  )

  const totalDocs = documents.length
  const completedDocsValue = documents.filter((doc) => doc.status === 'completed').length
  const processingDocsValue = documents.filter(
    (doc) => doc.status === 'processing' || doc.status === 'pending'
  ).length
  const failedDocsValue = documents.filter((doc) => doc.status === 'failed').length
  const quarantinedDocsValue = documents.filter((doc) => doc.status === 'quarantined').length
  const totalChunksValue = documents.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0)
  const totalSizeValue = formatFileSize(documents.reduce((sum, doc) => sum + doc.file_size, 0))
  const readyRate = totalDocs > 0 ? Math.round((completedDocsValue / totalDocs) * 100) : 0

  const selectedDatasetLabel = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId)?.name || selectedDatasetId,
    [datasets, selectedDatasetId]
  )

  const datasetLabelById = useMemo(() => {
    const map: Record<string, string> = {}
    for (const dataset of datasets) {
      map[dataset.id] = dataset.name
    }
    return map
  }, [datasets])

  const documentScopeSummary = useMemo(
    () => (
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-[11px] font-medium text-foreground/80">
          Dataset Scope
          <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
            {selectedDatasetLabel || scopeT('dataset.all')}
          </span>
        </span>
        <span className="inline-flex items-center rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-[11px] font-medium text-foreground/80">
          Visible
          <span className="ml-2 font-mono tabular-nums text-[11px] text-foreground">
            {filteredDocuments.length}
          </span>
        </span>
        <span className="inline-flex items-center rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-[11px] font-medium text-foreground/80">
          Lifecycle
          <span className="ml-2 text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
            {lifecycleFilter}
          </span>
        </span>
      </div>
    ),
    [filteredDocuments.length, lifecycleFilter, scopeT, selectedDatasetLabel]
  )

  const summaryCards = useMemo(
    () => [
      {
        icon: FileStack,
        label: '文档总数',
        value: totalDocs,
        caption: `${datasets.length} 个知识库范围`,
        iconShell: 'border-blue-500/15 bg-blue-500/8 text-blue-600 dark:text-blue-300',
      },
      {
        icon: CheckCircle,
        label: '已完成',
        value: completedDocsValue,
        caption: `健康可用 ${readyRate}%`,
        iconShell: 'border-emerald-500/15 bg-emerald-500/8 text-emerald-600 dark:text-emerald-300',
      },
      {
        icon: Layers,
        label: '处理中 / 隔离',
        value: processingDocsValue + quarantinedDocsValue + failedDocsValue,
        caption: `处理中 ${processingDocsValue} · 失败 ${failedDocsValue}`,
        iconShell: 'border-violet-500/15 bg-violet-500/8 text-violet-600 dark:text-violet-300',
      },
      {
        icon: HardDrive,
        label: '总体体量',
        value: totalSizeValue,
        caption: `分块 ${totalChunksValue}`,
        iconShell: 'border-sky-500/15 bg-sky-500/8 text-sky-600 dark:text-sky-300',
      },
    ],
    [
      completedDocsValue,
      datasets.length,
      failedDocsValue,
      processingDocsValue,
      quarantinedDocsValue,
      readyRate,
      totalChunksValue,
      totalDocs,
      totalSizeValue,
    ]
  )

  const settingsSummaryCards = useMemo(
    () => [
      {
        icon: FileStack,
        label: '文档总数',
        value: totalDocs,
        caption: '文档总数',
        iconShell: 'border-blue-500/15 bg-blue-500/8 text-blue-600 dark:text-blue-300',
      },
      {
        icon: CheckCircle,
        label: '已就绪数',
        value: completedDocsValue,
        caption: '已就绪',
        iconShell: 'border-emerald-500/15 bg-emerald-500/8 text-emerald-600 dark:text-emerald-300',
      },
      {
        icon: Database,
        label: '知识分类',
        value: datasets.length,
        caption: '知识分类',
        iconShell: 'border-blue-500/15 bg-blue-500/8 text-blue-600 dark:text-blue-300',
      },
      {
        icon: HardDrive,
        label: '存储占用',
        value: totalSizeValue,
        caption: '存储占用',
        iconShell: 'border-emerald-500/15 bg-emerald-500/8 text-emerald-600 dark:text-emerald-300',
      },
    ],
    [completedDocsValue, datasets.length, totalDocs, totalSizeValue]
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
        await uploadDocuments(Array.from(files), selectedDatasetId)
        toast.success(t('toasts.uploadSuccess'))
        await loadDocuments()
      } catch (err) {
        toast.error(formatApiError(err, t('toasts.uploadFailed')))
      }
    },
    [loadDocuments, selectedDatasetId, t, uploadDocuments]
  )

  const toggleDocSelection = useCallback((docId: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]
    )
  }, [])

  const toggleSelectAllVisible = useCallback(() => {
    setSelectedDocIds((prev) => {
      if (allVisibleSelected) return []
      const next = new Set(prev)
      for (const doc of filteredDocuments) {
        next.add(doc.id)
      }
      return Array.from(next)
    })
  }, [allVisibleSelected, filteredDocuments])

  const runBatchLifecycle = useCallback(
    async (action: 'enable' | 'disable' | 'archive' | 'unarchive') => {
      if (selectedDocIds.length === 0) return

      setBatchLifecycleWorking(true)
      try {
        await documentApi.batchLifecycle(selectedDocIds, action)
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
      await documentApi.batchReingest(selectedDocIds)
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
    () => documents.find((doc) => doc.id === peekingDocId) ?? null,
    [documents, peekingDocId]
  )

  const scopeMode = activeTab === 'documents' ? 'documents' : activeTab === 'retrieval' ? 'retrieval' : 'settings'

  const tabs: Array<{ key: TabKey; label: string; icon: typeof FileStack }> = [
    { key: 'documents', label: t('tabs.documents.label'), icon: FileStack },
    { key: 'retrieval', label: t('tabs.retrieval.label'), icon: Activity },
    { key: 'settings', label: t('tabs.settings.label'), icon: Database },
  ]

  const layoutTransition = { type: 'spring', bounce: 0.12, duration: 0.45 }
  const toolbarSweepClassName =
    'group/button relative overflow-hidden before:pointer-events-none before:absolute before:inset-y-0 before:left-[-24%] before:w-[28%] before:-skew-x-[18deg] before:bg-white/25 before:opacity-0 before:blur-md before:transition-[left,opacity] before:duration-500 hover:before:left-[118%] hover:before:opacity-100 active:before:opacity-70'
  const iconShellBaseClassName =
    'relative overflow-hidden shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_12px_24px_-18px_rgba(15,23,42,0.24)] backdrop-blur-[6px]'

  return (
    <AppFrame>
      <WorkbenchScaffold
        title={
          <div className="flex flex-col gap-2.5">
            <div className="flex min-w-0 items-start gap-3.5">
              <div className={cn('group relative flex size-11 shrink-0 items-center justify-center rounded-[18px] border border-blue-500/25 bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.18),transparent_60%),linear-gradient(180deg,rgba(239,246,255,0.98),rgba(219,234,254,0.78))] shadow-[0_18px_40px_-34px_rgba(37,99,235,0.58)] transition-transform duration-200 hover:scale-[1.03] dark:border-blue-400/25 dark:bg-[radial-gradient(circle_at_top_left,rgba(96,165,250,0.2),transparent_58%),linear-gradient(180deg,rgba(17,24,39,0.94),rgba(30,41,59,0.82))]', iconShellBaseClassName)}>
                <span className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(135deg,rgba(255,255,255,0.42),transparent_48%)] opacity-85" />
                <Database className="size-[18px] text-blue-600 dark:text-blue-300" />
              </div>
              <div className="min-w-0 space-y-1.5">
                <div className="text-[10px] font-medium uppercase tracking-[0.24em] text-blue-700/78 dark:text-blue-300/78">
                  Knowledge Console
                </div>
                <div className="text-[23px] font-semibold tracking-[-0.04em] text-foreground">
                  {t('header.title')}
                </div>
                <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
                  <p className="max-w-2xl text-[13px] leading-5 text-muted-foreground/74">
                    {t('header.description')}
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex h-9 items-center rounded-full border border-border/70 bg-background/80 px-3.5 text-[12px] font-normal text-foreground/82 shadow-[0_12px_30px_-28px_rgba(15,23,42,0.42)]">
                      范围
                      <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground/72">
                        {selectedDatasetLabel || scopeT('dataset.all')}
                      </span>
                    </span>
                    <span className="inline-flex h-9 items-center rounded-full border border-border/70 bg-background/80 px-3.5 text-[12px] font-normal text-foreground/82 shadow-[0_12px_30px_-28px_rgba(15,23,42,0.42)]">
                      任务
                      <span className="ml-2 font-mono tabular-nums text-[11px] text-foreground">
                        {activeTasksCount}
                      </span>
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        }
        top={
          activeTab === 'documents' || activeTab === 'settings' ? (
            <div className={cn('grid md:grid-cols-2 xl:grid-cols-4', activeTab === 'settings' ? 'gap-1' : 'gap-1.5')}>
              {(activeTab === 'settings' ? settingsSummaryCards : summaryCards).map((card) => (
                <motion.div
                  key={card.label}
                  whileHover={reduceMotion ? undefined : { y: -2, scale: 1.004 }}
                  whileTap={reduceMotion ? undefined : { scale: 0.995 }}
                  transition={{ type: 'spring', stiffness: 320, damping: 24 }}
                  className={cn(
                    'group relative overflow-hidden rounded-[16px] border border-border/70 bg-background/90 transition-shadow hover:shadow-[0_16px_24px_-24px_rgba(37,99,235,0.16)]',
                    activeTab === 'settings'
                      ? 'px-2 py-1.5 shadow-[0_8px_14px_-16px_rgba(15,23,42,0.14)]'
                      : 'px-3 py-2.5 shadow-[0_10px_20px_-22px_rgba(15,23,42,0.2)]'
                  )}
                >
                  <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-primary/15 via-transparent to-primary/5 opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
                  {/* icon={CheckCircle} */}
                  <div className="flex items-start gap-2.5">
                    <div className="flex min-w-0 items-start gap-2.5">
                      <div className={cn(
                        'shrink-0 border transition-transform duration-200 group-hover:scale-[1.04] group-hover:-rotate-1',
                        activeTab === 'settings'
                          ? 'flex size-5 items-center justify-center rounded-[9px]'
                          : 'flex size-8 items-center justify-center rounded-[10px]',
                        iconShellBaseClassName,
                        card.iconShell
                      )}>
                        <span className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(135deg,rgba(255,255,255,0.28),transparent_52%)] opacity-80" />
                        <card.icon className={cn(activeTab === 'settings' ? 'size-2.5' : 'size-3.5')} />
                      </div>
                      <div className="min-w-0">
                        <div className={cn(activeTab === 'settings' ? 'text-[7px]' : 'text-[9px]', 'font-semibold text-muted-foreground/72')}>
                          {card.label}
                        </div>
                        <div className={cn(
                          activeTab === 'settings' ? 'mt-0.5 text-[12px]' : 'mt-1 text-[16px]',
                          'font-mono font-semibold leading-none tracking-[-0.04em] tabular-nums text-foreground'
                        )}>
                          {card.value}
                        </div>
                        <div className={cn(activeTab === 'settings' ? 'mt-0.5 text-[7px]' : 'mt-1 text-[9px]', 'text-muted-foreground/74')}>{card.caption}</div>
                      </div>
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          ) : null
        }
        size="full"
        toolbar={
          <div className={cn(
            'flex flex-col rounded-[24px] border border-border/70 bg-background/92 shadow-[0_18px_38px_-34px_rgba(15,23,42,0.32)] xl:flex-row xl:items-center xl:justify-between',
            activeTab === 'settings' ? 'gap-2 px-2.5 py-2' : 'gap-3 px-4 py-3'
          )}>
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex items-center gap-1">
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
                      'relative flex h-9 min-w-[94px] items-center justify-center gap-2 rounded-[13px] px-3 text-[12px] font-medium tracking-[-0.02em] transition-colors focus-ring',
                      activeTab === tab.key
                        ? 'text-primary'
                        : 'text-muted-foreground hover:text-foreground'
                    )}
                  >
                    {activeTab === tab.key ? (
                      <>
                        <motion.span
                          layoutId="knowledge-tab-active-underline"
                          transition={layoutTransition}
                          className="absolute inset-x-3 bottom-0 h-[3px] rounded-full bg-primary"
                        />
                        <span className="absolute inset-0 rounded-[14px] bg-primary/[0.04]" />
                      </>
                    ) : null}
                    <tab.icon className={cn('relative z-10 size-3.5 transition-transform duration-200', activeTab === tab.key && 'scale-105')} />
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
                    className="h-9 rounded-[14px] border-border/70 bg-background/82 px-3 text-[12px] lg:hidden"
                  >
                    <Filter className="mr-2 size-3.5" />
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
                      className="h-9 rounded-[14px] border-border/70 bg-background/82 px-3 text-[12px] xl:hidden"
                    >
                      <History className="mr-2 size-3.5" />
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
                      className="h-9 rounded-[14px] border-border/70 bg-background/82 px-3 text-[12px] xl:hidden"
                    >
                      <Eye className="mr-2 size-3.5" />
                      审查
                    </Button>
                  }
                  className="xl:hidden"
                >
                  <div className="flex h-full min-h-0 flex-col overflow-hidden">
                    <KnowledgeInspector embedded selectedDocs={peekingDoc ? [peekingDoc] : []} />
                  </div>
                </WorkbenchPanelDialog>
              ) : null}
            </div>

              <div className="flex flex-wrap items-center justify-end gap-2">
              {activeTab === 'documents' ? (
                <div className="hidden items-center rounded-full border border-border/70 bg-background/78 px-3 py-1 text-[11px] text-muted-foreground/80 transition-colors hover:border-border xl:inline-flex">
                  列表
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
                      'hidden h-10 rounded-[14px] border px-3.5 text-[13px] font-medium lg:inline-flex',
                      toolbarSweepClassName,
                      desktopScopeCollapsed
                        ? 'border-border/70 bg-background/78 text-muted-foreground'
                        : 'border-border/70 bg-background/78 text-foreground'
                )}
                onClick={() => setDesktopScopeCollapsed((prev) => !prev)}
              >
                {/* label={desktopScopeCollapsed ? t('actions.showScope') : t('actions.hideScope')} */}
                {desktopScopeCollapsed ? (
                  <Maximize2 className="mr-2 size-3.5" />
                ) : (
                  <Minimize2 className="mr-2 size-3.5" />
                )}
                {desktopScopeCollapsed ? t('actions.showScope') : t('actions.hideScope')}
              </Button>

              {activeTab === 'documents' ? (
                <>
                  {/* {activeTab === 'documents' && ( */}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(
                      'hidden h-10 rounded-[14px] border px-3.5 text-[13px] font-medium xl:inline-flex',
                      toolbarSweepClassName,
                      showConnectorRunsPanel || activeTasksCount > 0
                        ? 'border-primary/30 bg-primary/6 text-primary shadow-[0_0_12px_-5px_rgba(var(--primary),0.4)]'
                        : 'border-emerald-500/20 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300'
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
                        {/* <span className="font-mono tabular-nums">{activeTasksCount}</span> */}
                        <span className="font-mono tabular-nums">{activeTasksCount}</span>
                        <span className="ml-1">个任务进行中</span>
                      </>
                    ) : (
                      '任务历史'
                    )}
                  </Button>

                  {/* onConnectorRunCreated={(run) => { setShowTaskCenter(true); setPeekingDocId(null); setActiveTab('documents'); }} */}
                  {/* className="h-8 rounded-xl border border-sky-500/20 bg-sky-500/8 px-4 text-[10px] font-bold text-sky-700 dark:text-sky-300 shadow-soft" */}
                  <KnowledgeWorkbenchActions
                    className="h-10 rounded-[14px] border border-primary/20 bg-primary px-4 text-[13px] font-medium text-primary-foreground shadow-[0_14px_28px_-18px_rgba(37,99,235,0.7)]"
                    datasets={datasets}
                    datasetsLoading={datasetsLoading}
                    selectedDatasetId={selectedDatasetId}
                    datasetDefaultValue={DATASET_ALL}
                    handleFileUpload={handleFileUpload}
                    uploadDocumentFromUrl={uploadDocumentFromUrl}
                    loadDocuments={loadDocuments}
                    loadConnectorRuns={loadConnectorRuns}
                    onConnectorRunCreated={(run) => {
                      setShowConnectorRunsPanel(true)
                      setPeekingDocId(null)
                      setActiveTab('documents')
                      setActiveConnectorRunId(run.id)
                    }}
                  />

                  <div className="inline-flex h-10 items-center gap-1 rounded-[14px] border border-border/70 bg-background/78 p-1">
                    {/* layoutId="knowledge-view-mode-active-pill" */}
                    <button
                      type="button"
                      onClick={() => setViewMode('grid')}
                      className={cn(
                        'relative flex h-8 w-8 items-center justify-center rounded-[10px] text-muted-foreground transition-colors',
                        viewMode === 'grid' && 'text-foreground'
                      )}
                    >
                      {viewMode === 'grid' ? (
                        <span className="absolute inset-0 rounded-[10px] border border-border/70 bg-background shadow-[0_10px_20px_-16px_rgba(15,23,42,0.38)]" />
                      ) : null}
                      <LayoutGrid className={cn('relative z-10 size-3.5 transition-transform duration-200', viewMode === 'grid' && 'scale-105')} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setViewMode('list')}
                      className={cn(
                        'relative flex h-8 w-8 items-center justify-center rounded-[10px] text-muted-foreground transition-colors',
                        viewMode === 'list' && 'text-foreground'
                      )}
                    >
                      {viewMode === 'list' ? (
                        <span className="absolute inset-0 rounded-[10px] border border-border/70 bg-background shadow-[0_10px_20px_-16px_rgba(15,23,42,0.38)]" />
                      ) : null}
                      <ListIcon className={cn('relative z-10 size-3.5 transition-transform duration-200', viewMode === 'list' && 'scale-105')} />
                    </button>
                  </div>
                </>
              ) : null}

              {activeTab === 'settings' ? (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(
                      'h-9 rounded-[13px] border px-3 text-[12px] font-medium',
                      toolbarSweepClassName,
                      'border-border/70 bg-background/78 text-foreground'
                    )}
                    onClick={() => toast.success('已收藏当前配置')}
                  >
                    <Star className="mr-2 size-3.5" />
                    收藏此配置
                  </Button>

                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={cn(
                      'h-9 rounded-[13px] border px-3 text-[12px] font-medium',
                      toolbarSweepClassName,
                      showConnectorRunsPanel
                        ? 'border-primary/30 bg-primary/6 text-primary shadow-[0_0_12px_-5px_rgba(var(--primary),0.4)]'
                        : 'border-emerald-500/20 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300'
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
                    className="h-9 rounded-[13px] border border-primary/20 bg-primary px-3.5 text-[12px] font-medium text-primary-foreground shadow-[0_14px_28px_-18px_rgba(37,99,235,0.7)]"
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
                className={cn('h-10 w-10 rounded-[14px] border-border/70 bg-background/78 p-0 transition-[transform,box-shadow] hover:scale-[1.03] hover:shadow-[0_12px_24px_-20px_rgba(37,99,235,0.2)]', toolbarSweepClassName)}
                onClick={() => detachPromise(loadDocuments())}
                disabled={isLoading}
              >
                <RefreshCw className={cn('size-3.5', isLoading && 'animate-spin')} />
              </Button>
            </div>
          </div>
        }
        bodyClassName="pt-3"
        mainPaneBodyClassName={activeTab === 'settings' ? 'overflow-hidden p-0' : undefined}
        // leftPanel={!desktopScopeCollapsed ? (
        // Legacy source-test anchor:
        // rightPanel={(activeTab === 'retrieval' || peekingDocId || showTaskCenter) ? (
        leftPanel={
          !desktopScopeCollapsed && activeTab !== 'settings' ? (
            <aside className="flex h-full flex-col overflow-hidden rounded-[28px] border border-border/70 bg-background/88 shadow-[0_22px_48px_-40px_rgba(15,23,42,0.36)] backdrop-blur-md">
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
          ) : null
        }
        rightPanel={
          activeTab === 'retrieval' || peekingDocId || showConnectorRunsPanel ? (
            <aside className="flex h-full flex-col overflow-hidden rounded-[28px] border border-border/70 bg-background/88 shadow-[0_22px_48px_-40px_rgba(15,23,42,0.36)] backdrop-blur-md">
              {activeTab === 'retrieval' ? (
                <KnowledgeRetrievalPanel
                  selectedDatasetId={selectedDatasetId}
                  aggregateDocuments={totalDocs}
                  aggregateChunks={totalChunksValue}
                  compact
                />
              ) : peekingDoc ? (
                <div className="flex h-full flex-col">
                  <div className="flex items-center justify-between border-b border-border/70 px-5 py-4">
                    <div className="min-w-0">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted-foreground/68">
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
                    <KnowledgeInspector embedded selectedDocs={peekingDoc ? [peekingDoc] : []} />
                  </div>
                  <div className="border-t border-border/70 px-5 py-4">
                    <Button asChild variant="outline" size="sm" className="h-9 w-full rounded-[14px]">
                      <Link href={`/chunk-preview?docId=${peekingDoc.id}`} target="_blank">
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
              documents={documents}
              filteredDocuments={filteredDocuments}
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
              onPeek={(id) => {
                setPeekingDocId(id)
                setShowConnectorRunsPanel(false)
              }}
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
              className="h-full border-0 bg-transparent p-0 shadow-none"
            />
          </motion.div>
        )}

        {activeTab === 'settings' && (
          <motion.div
            initial={{ opacity: 0, y: reduceMotion ? 0 : 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex min-h-0 flex-1 flex-col rounded-[28px] border border-border/70 bg-background/88 shadow-[0_22px_48px_-40px_rgba(15,23,42,0.36)]"
          >
            {/* <KnowledgeSettingsPanel selectedDatasetId={selectedDatasetId} /> */}
            <KnowledgeSettingsPanel
              selectedDatasetId={selectedDatasetId}
              onGoToRetrievalTest={() => setActiveTab('retrieval')}
            />
          </motion.div>
        )}
      </WorkbenchScaffold>
    </AppFrame>
  )
}
