'use client'

/**
 * 知识库管理页面
 * 优化版：极致空间回收、一体化工作台、UI Pro Max 交互、三位一体右侧抽屉
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
  Grid2X2,
  HardDrive,
  Layers,
  LayoutGrid,
  ListIcon,
  Maximize2,
  Minimize2,
  MoreVertical,
  RefreshCw,
  X,
  History,
  Loader2,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { StatCard } from '@/components/ui/stats-card'
import { WorkbenchScaffold } from '@/components/workbench'
import { KnowledgeDocumentsPanel } from '@/components/knowledge/knowledge-documents-panel'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
import { KnowledgeScopePanel } from '@/components/knowledge/knowledge-scope-panel'
import { KnowledgeSettingsPanel, KnowledgeConnectorRunsPanel } from '@/components/knowledge/knowledge-settings-panel'
import { KnowledgeRetrievalPanel } from '@/components/knowledge/knowledge-retrieval-panel'
import { KnowledgeWorkbenchActions } from '@/components/knowledge/knowledge-workbench-actions'
import { RetrievePreviewPanel } from '@/components/rag/retrieve-preview-panel'

import { Link, useRouter } from '@/i18n/navigation'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise, formatFileSize } from '@/lib/utils'
import { cn } from '@/lib/utils'
import { useDatasets } from '@/hooks/use-datasets'
import { useDocuments } from '@/hooks/use-documents'
import { useConnectorRuns } from '@/hooks/use-connector-runs'

const DATASET_ALL = '__all__'
type TabKey = 'documents' | 'retrieval' | 'settings'

export default function KnowledgePage() {
  const t = useTranslations('KnowledgePage')
  const scopeT = useTranslations('KnowledgeScopePanel')
  const router = useRouter()
  const searchParams = useSearchParams()
  const reduceMotion = useReducedMotion()

  // --- 状态管理 ---
  const [activeTab, setActiveTab] = useState<TabKey>((searchParams.get('tab') as TabKey) || 'documents')
  const [desktopScopeCollapsed, setDesktopScopeCollapsed] = useState(false)
  const [peekingDocId, setPeekingDocId] = useState<string | null>(null)
  const [showTaskCenter, setShowTaskCenter] = useState(false)

  // 快捷键支持：Cmd+B 折叠侧边栏
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault()
        setDesktopScopeCollapsed((prev) => !prev)
      }
    }
    globalThis.window.addEventListener('keydown', handleKeyDown)
    return () => globalThis.window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const { datasets, isLoading: datasetsLoading } = useDatasets()
  const [datasetScope, setDatasetScope] = useState<string>(searchParams.get('datasetId') || DATASET_ALL)
  const selectedDatasetId = datasetScope === DATASET_ALL ? undefined : datasetScope

  const [docFilter, setDocFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'completed' | 'processing' | 'failed' | 'quarantined'>('all')
  const [lifecycleFilter, setLifecycleFilter] = useState<'active' | 'archived' | 'disabled' | 'all'>('active')
  const [folderPath, setFolderPath] = useState<string | null>(null)

  const [sortKey, setSortKey] = useState<'created_at' | 'filename' | 'file_size'>('created_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')

  const {
    documents,
    isLoading,
    loadDocuments,
    deleteDocument,
    uploadDocuments,
    uploadDocumentFromUrl,
  } = useDocuments({
    dataset_id: selectedDatasetId,
    status: statusFilter === 'all' ? undefined : statusFilter,
    lifecycle: lifecycleFilter === 'all' ? undefined : lifecycleFilter,
    source_path_prefix: folderPath || undefined,
  })

  const {
    connectorRuns,
    connectorRunsLoading,
    loadConnectorRuns,
    cancelConnectorRun,
    resumeConnectorRun,
    retryFailedConnectorRun,
  } = useConnectorRuns({
    selectedDatasetId: selectedDatasetId,
  })

  const activeTasksCount = useMemo(() => 
    connectorRuns.filter(r => r.status === 'running' || r.status === 'pending').length,
  [connectorRuns])

  // --- 逻辑与过滤 ---
  const filteredDocuments = useMemo(() => {
    let list = [...documents]
    const term = docFilter.trim().toLowerCase()
    if (term) list = list.filter(d => d.filename.toLowerCase().includes(term))
    list.sort((a, b) => {
      const dir = sortDir === 'asc' ? 1 : -1
      if (sortKey === 'filename') return a.filename.localeCompare(b.filename) * dir
      if (sortKey === 'file_size') return (a.file_size - b.file_size) * dir
      return (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) * dir
    })
    return list
  }, [documents, docFilter, sortKey, sortDir])

  const mainPaneRef = useRef<HTMLDivElement>(null)
  const mainPaneSentinelRef = useRef<HTMLDivElement>(null)
  const docGridColumns = 3
  const docGridRowCount = Math.ceil(filteredDocuments.length / docGridColumns)
  const docsGridVirtualizer = useVirtualizer({ count: docGridRowCount, getScrollElement: () => mainPaneRef.current, estimateSize: () => 280, overscan: 5 })
  const docsTableVirtualizer = useVirtualizer({ count: filteredDocuments.length, getScrollElement: () => mainPaneRef.current, estimateSize: () => 52, overscan: 10 })

  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)
  const selectedSet = useMemo(() => new Set(selectedDocIds), [selectedDocIds])
  const allVisibleSelected = filteredDocuments.length > 0 && filteredDocuments.every((d) => selectedSet.has(d.id))
  const selectedDocuments = useMemo(() => filteredDocuments.filter((d) => selectedSet.has(d.id)), [filteredDocuments, selectedSet])

  const anySelectedEnabled = useMemo(() => selectedDocuments.some((d) => !d.disabled_at), [selectedDocuments])
  const anySelectedDisabled = useMemo(() => selectedDocuments.some((d) => d.disabled_at), [selectedDocuments])
  const anySelectedArchived = useMemo(() => selectedDocuments.some((d) => d.archived_at), [selectedDocuments])
  const anySelectedNotArchived = useMemo(() => selectedDocuments.some((d) => !d.archived_at), [selectedDocuments])

  const [batchLifecycleWorking, setBatchLifecycleWorking] = useState(false)
  const [batchReingestWorking, setBatchReingestWorking] = useState(false)

  const runBatchLifecycle = useCallback(async (action: 'enable' | 'disable' | 'archive' | 'unarchive') => {
    if (selectedDocIds.length === 0) return
    setBatchLifecycleWorking(true)
    try {
      await documentApi.batchLifecycle(selectedDocIds, action)
      toast.success(t(`toasts.batchLifecycleSuccess.${action}`))
      await loadDocuments()
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.batchLifecycleFailed')))
    } finally { setBatchLifecycleWorking(false) }
  }, [selectedDocIds, loadDocuments, t])

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
    } finally { setBatchReingestWorking(false) }
  }, [selectedDocIds, loadDocuments, t])

  const totalDocs = documents.length
  const completedDocsValue = documents.filter((d) => d.status === 'completed').length
  const processingDocsValue = documents.filter((d) => d.status === 'processing' || d.status === 'pending').length
  const failedDocsValue = documents.filter((d) => d.status === 'failed').length
  const quarantinedDocsValue = documents.filter((d) => d.status === 'quarantined').length
  
  const totalChunksValue = documents.reduce((acc, d) => acc + (d.chunk_count || 0), 0)
  const totalSizeValue = formatFileSize(documents.reduce((acc, d) => acc + d.file_size, 0))

  const selectedDatasetLabel = useMemo(() => datasets.find(d => d.id === selectedDatasetId)?.name || selectedDatasetId, [datasets, selectedDatasetId])
  const datasetLabelById = useMemo(() => {
    const map: Record<string, string> = {}
    datasets.forEach((d) => (map[d.id] = d.name))
    return map
  }, [datasets])

  const handleDatasetScopeChange = useCallback((id: string) => {
    setDatasetScope(id); setFolderPath(null)
    const params = new URLSearchParams(globalThis.window.location.search)
    if (id === DATASET_ALL) params.delete('datasetId'); else params.set('datasetId', id)
    router.replace(`/knowledge?${params.toString()}`)
  }, [router])

  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files?.length) return
    try {
      await uploadDocuments(Array.from(files), selectedDatasetId)
      toast.success(t('toasts.uploadSuccess')); await loadDocuments()
    } catch (err) { toast.error(formatApiError(err, t('toasts.uploadFailed'))) }
  }, [uploadDocuments, selectedDatasetId, loadDocuments, t])

  const tabs: { key: TabKey; label: string; icon: any }[] = [
    { key: 'documents', label: t('tabs.documents.label'), icon: FileStack },
    { key: 'retrieval', label: t('tabs.retrieval.label'), icon: RefreshCw },
    { key: 'settings', label: t('tabs.settings.label'), icon: Database },
  ]

  const layoutTransition = { type: 'spring', bounce: 0.2, duration: 0.6 }
  const documentScopeSummary = useMemo(() => (
    <div className="flex flex-wrap items-center gap-2">
      <span className="inline-flex max-w-xs items-center rounded-full border border-sky-500/20 bg-sky-500/8 px-2.5 py-1 text-xs text-sky-700 dark:text-sky-300 truncate shadow-[0_10px_24px_-20px_rgba(14,165,233,0.45)]">
        {t('scopeSummary.labels.scope')}: <span className="ml-1 truncate font-medium text-foreground">{selectedDatasetLabel || scopeT('dataset.all')}</span>
      </span>
    </div>
  ), [scopeT, selectedDatasetLabel, t])

  const toggleDocSelection = useCallback((docId: string) => setSelectedDocIds((prev) => (prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId])), [])
  const toggleSelectAllVisible = useCallback(() => setSelectedDocIds((prev) => { if (allVisibleSelected) return []; const next = new Set(prev); for (const doc of filteredDocuments) next.add(doc.id); return Array.from(next); }), [allVisibleSelected, filteredDocuments])

  useEffect(() => { const valid = new Set(documents.map((d) => d.id)); setSelectedDocIds((prev) => { const next = prev.filter((id) => valid.has(id)); return next.length === prev.length ? prev : next; }); }, [documents])
  useEffect(() => { if (activeTab !== 'documents') setSelectedDocIds([]) }, [activeTab])

  const confirmBatchDelete = useCallback(async () => {
    const ids = [...selectedDocIds]
    if (ids.length === 0) return
    setBatchDeleting(true)
    try {
      await documentApi.batchDelete(ids)
      setSelectedDocIds([]); await loadDocuments()
    } catch (err) { toast.error(formatApiError(err, t('toasts.batchDeleteFailed'))) } finally { setBatchDeleting(false); setBatchDeleteOpen(false) }
  }, [selectedDocIds, loadDocuments, t])

  const peekingDoc = useMemo(() => documents.find(d => d.id === peekingDocId), [documents, peekingDocId])
  const scopeMode = activeTab === 'documents' ? 'documents' : activeTab === 'retrieval' ? 'retrieval' : 'settings'

  return (
    <AppFrame>
        <WorkbenchScaffold
          title={
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between w-full">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-[radial-gradient(circle_at_35%_35%,rgba(56,189,248,0.22),transparent_58%),linear-gradient(135deg,rgba(14,165,233,0.12),rgba(16,185,129,0.08))] shadow-inner-soft">
                  <Database className="size-5 text-primary" />
                </div>
                <div>
                  <h1 className="text-lg font-bold tracking-tight text-foreground leading-none">{t("header.title")}</h1>
                  <p className="text-[10px] font-medium text-muted-foreground/55 mt-1">{t('header.description')}</p>
                </div>
              </div>

              {activeTab === 'documents' && (
                <div className="flex flex-wrap items-center rounded-2xl border border-border/40 bg-[linear-gradient(90deg,rgba(14,165,233,0.08),rgba(255,255,255,0.55),rgba(16,185,129,0.08))] p-1 gap-1 shadow-inner-soft dark:bg-[linear-gradient(90deg,rgba(14,165,233,0.12),rgba(17,24,39,0.7),rgba(16,185,129,0.12))]">
                  <StatCard variant="minimal" icon={FileStack} label={t("stats.totalDocuments")} value={totalDocs} color="sky" />
                  <div className="w-px h-6 bg-border/40 mx-0.5" />
                  <StatCard variant="minimal" icon={CheckCircle} label={t('stats.ready')} value={completedDocsValue} color="green" />
                  <div className="w-px h-6 bg-border/40 mx-0.5" />
                  <StatCard variant="minimal" icon={Layers} label={t('stats.totalChunks')} value={totalChunksValue} color="teal" />
                  <div className="w-px h-6 bg-border/40 mx-0.5" />
                  <StatCard variant="minimal" icon={HardDrive} label={t('stats.storageUsage')} value={totalSizeValue} color="orange" />
                </div>
              )}
            </div>
          }
          icon={undefined}
          description={null}
          size="full"
          leftPanel={!desktopScopeCollapsed ? (
            <aside className="h-full flex flex-col rounded-[2.5rem] overflow-hidden border border-sky-500/12 bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.08),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.78),rgba(255,255,255,0.48))] shadow-soft backdrop-blur-md dark:border-sky-500/15 dark:bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.12),transparent_34%),linear-gradient(180deg,rgba(17,24,39,0.68),rgba(15,23,42,0.52))]">
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
          ) : null}
          rightPanel={(activeTab === 'retrieval' || peekingDocId || showTaskCenter) ? (
            <aside className="h-full flex flex-col rounded-[2.5rem] overflow-hidden border border-emerald-500/12 bg-[radial-gradient(circle_at_top_right,rgba(16,185,129,0.08),transparent_34%),linear-gradient(180deg,rgba(255,255,255,0.78),rgba(255,255,255,0.48))] shadow-soft backdrop-blur-md dark:border-emerald-500/15 dark:bg-[radial-gradient(circle_at_top_right,rgba(16,185,129,0.12),transparent_32%),linear-gradient(180deg,rgba(17,24,39,0.68),rgba(15,23,42,0.52))]">
              {peekingDocId && activeTab === 'documents' ? (
                <div className="flex flex-col h-full">
                  <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/40 bg-background/20 backdrop-blur-sm">
                    <div className="flex flex-col">
                      <span className="text-[10px] font-bold uppercase tracking-widest text-primary/60">窥探分块 Peek Chunks</span>
                      <span className="text-xs font-bold text-foreground truncate max-w-[200px]">{peekingDoc?.filename}</span>
                    </div>
                    <IconButton label="关闭" variant="ghost" size="sm" onClick={() => setPeekingDocId(null)}><X className="size-4" /></IconButton>
                  </div>
                  <div className="flex-1 min-h-0 overflow-y-auto">
                    <KnowledgeInspector embedded selectedDocs={peekingDoc ? [peekingDoc] : []} />
                  </div>
                  <div className="p-4 border-t border-border/40 bg-muted/20">
                    <Button asChild variant="outline" size="sm" className="w-full rounded-xl"><Link href={`/chunk-preview?docId=${peekingDocId}`} target="_blank"><Maximize2 className="mr-2 size-3.5" />进入沉浸式预览</Link></Button>
                  </div>
                </div>
              ) : showTaskCenter ? (
                <div className="flex flex-col h-full bg-background/95 backdrop-blur-xl">
                  <div className="flex items-center justify-between px-5 py-3 border-b border-border/40">
                    <div className="flex items-center gap-2.5">
                      <div className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <Activity className={cn("size-4", activeTasksCount > 0 && "animate-pulse")} />
                      </div>
                      <span className="text-sm font-black tracking-tight text-foreground/90 uppercase">Monitoring</span>
                    </div>
                    <IconButton label="关闭" variant="ghost" size="sm" className="size-8 rounded-lg" onClick={() => setShowTaskCenter(false)}>
                      <X className="size-4" />
                    </IconButton>
                  </div>
                  <div className="flex-1 min-h-0 overflow-y-auto">
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
                </div>
              ) : (
                <KnowledgeRetrievalPanel selectedDatasetId={selectedDatasetId} compact />
              )}
            </aside>
          ) : null}
          top={null}
          toolbar={
            <div className="flex items-center justify-between">
              <div className="flex p-1 gap-1 rounded-xl border border-border/40 bg-[linear-gradient(90deg,rgba(56,189,248,0.08),rgba(255,255,255,0.45),rgba(16,185,129,0.08))] dark:bg-[linear-gradient(90deg,rgba(56,189,248,0.12),rgba(17,24,39,0.72),rgba(16,185,129,0.12))]">
                {tabs.map((tab) => (
                  <button key={tab.key} onClick={() => { setActiveTab(tab.key); setPeekingDocId(null); setShowTaskCenter(false); }} className={cn('relative flex h-8 items-center gap-2 px-4 text-xs font-bold rounded-lg transition-all duration-300 focus-ring', activeTab === tab.key ? 'text-primary' : 'text-muted-foreground hover:text-foreground hover:bg-muted/40')}>
                    {activeTab === tab.key && <motion.div layoutId="active-knowledge-tab" className="absolute inset-0 rounded-lg bg-background shadow-soft border border-border/50" transition={layoutTransition} />}
                    <tab.icon className={cn("relative z-10 w-3.5 h-3.5 transition-transform duration-300", activeTab === tab.key ? "text-primary scale-110" : "text-muted-foreground")} />
                    <span className="relative z-10">{tab.label}</span>
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                <Button type="button" variant="ghost" size="sm" className="h-8 rounded-xl border border-border/40 bg-background/50 px-3 text-[10px] font-bold text-muted-foreground hover:text-foreground hover:bg-muted" onClick={() => setDesktopScopeCollapsed((prev) => !prev)}>
                  {desktopScopeCollapsed ? <Maximize2 className="mr-2 size-3" /> : <Minimize2 className="mr-2 size-3" />}
                  {desktopScopeCollapsed ? t('actions.showScope') : t('actions.hideScope')}
                </Button>
                <div className="h-4 w-px bg-border/60 mx-1" />
                
                {/* 动态任务指示器 */}
                <Button 
                  type="button" 
                  variant="ghost" 
                  size="sm" 
                  className={cn(
                    "h-8 rounded-xl border px-3 text-[10px] font-bold transition-all duration-300",
                    activeTasksCount > 0 || showTaskCenter
                      ? "border-primary/40 bg-primary/8 text-primary shadow-[0_0_12px_-5px_rgba(var(--primary),0.4)]" 
                      : "border-emerald-500/20 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300 hover:border-emerald-500/35 hover:bg-emerald-500/12"
                  )}
                  onClick={() => { setShowTaskCenter(true); setPeekingDocId(null); }}
                >
                  {activeTasksCount > 0 ? <Loader2 className="mr-2 size-3 animate-spin" /> : <History className="mr-2 size-3" />}
                  {activeTasksCount > 0 ? (
                    <>
                      <span className="font-mono tabular-nums mr-1">{activeTasksCount}</span>
                      <span>个任务进行中</span>
                    </>
                  ) : "任务历史"}
                </Button>

                <KnowledgeWorkbenchActions className="h-8 rounded-xl border border-sky-500/20 bg-sky-500/8 px-4 text-[10px] font-bold text-sky-700 dark:text-sky-300 shadow-soft" datasets={datasets} datasetsLoading={datasetsLoading} selectedDatasetId={selectedDatasetId} datasetDefaultValue={DATASET_ALL} handleFileUpload={handleFileUpload} uploadDocumentFromUrl={uploadDocumentFromUrl} loadDocuments={loadDocuments} loadConnectorRuns={loadConnectorRuns} onConnectorRunCreated={(run) => { setShowTaskCenter(true); setPeekingDocId(null); setActiveTab('documents'); }} />
                <Button type="button" variant="outline" size="sm" className="h-8 w-8 rounded-xl border-border/40 bg-background/50 p-0 text-muted-foreground hover:text-foreground hover:bg-muted" onClick={() => detachPromise(loadDocuments())} disabled={isLoading}><RefreshCw className={cn('size-3.5', isLoading && 'animate-spin')} /></Button>
                {activeTab === 'documents' && (
                  <>
                    {(docFilter.trim() || statusFilter !== 'all' || lifecycleFilter !== 'active' || folderPath) && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-8 rounded-xl border border-primary/20 bg-primary/5 px-3 text-[10px] font-bold text-primary hover:bg-primary/10"
                        onClick={() => {
                          setDocFilter('')
                          setStatusFilter('all')
                          setLifecycleFilter('active')
                          setFolderPath(null)
                        }}
                      >
                        <X className="mr-1.5 size-3" />
                        清空筛选
                      </Button>
                    )}
                    <div className="h-4 w-px bg-border/60 mx-1" />
                    <div className="flex p-0.5 gap-0.5 bg-muted/30 rounded-lg border border-border/40">
                      <button type="button" onClick={() => setViewMode('grid')} className={cn('relative h-6 w-7 flex items-center justify-center rounded-md transition-colors', viewMode === 'grid' ? 'text-primary' : 'text-muted-foreground hover:text-foreground')}>{viewMode === 'grid' && <motion.span layoutId="knowledge-view-mode-pill" transition={layoutTransition} className="absolute inset-0 rounded-md bg-background shadow-soft border border-border/50" />}<LayoutGrid className="relative z-10 w-3.5 h-3.5" /></button>
                      <button type="button" onClick={() => setViewMode('list')} className={cn('relative h-6 w-7 flex items-center justify-center rounded-md transition-colors', viewMode === 'list' ? 'text-primary' : 'text-muted-foreground hover:text-foreground')}>{viewMode === 'list' && <motion.span layoutId="knowledge-view-mode-pill" transition={layoutTransition} className="absolute inset-0 rounded-md bg-background shadow-soft border border-border/50" />}<ListIcon className="relative z-10 w-3.5 h-3.5" /></button>
                    </div>
                  </>
                )}
              </div>
            </div>
          }
          bodyClassName="pt-4 scroll-smooth"
        >
          <div ref={mainPaneSentinelRef} className="h-0 w-0" aria-hidden="true" />
          <div className="h-full min-h-0 flex flex-col" ref={mainPaneRef}>
            {activeTab === 'documents' ? (
              <motion.div layout={!reduceMotion} layoutId="knowledge-documents-surface" transition={layoutTransition} className="flex-1 min-h-0">
                <KnowledgeDocumentsPanel embedded isLoading={isLoading} documents={documents} filteredDocuments={filteredDocuments} selectedDatasetId={selectedDatasetId} selectedDatasetLabel={selectedDatasetLabel} datasetLabelById={datasetLabelById} hasActiveFilters={Boolean(docFilter.trim()) || statusFilter !== 'all' || lifecycleFilter !== 'active' || Boolean(folderPath)} onSwitchToAllDatasets={() => { setDatasetScope(DATASET_ALL); setFolderPath(null); }} scopeSummary={documentScopeSummary} docFilter={docFilter} setDocFilter={setDocFilter} onClearFilters={() => { setDocFilter(''); setStatusFilter('all'); setLifecycleFilter('active'); setFolderPath(null); }} sortKey={sortKey} sortDir={sortDir} setSortKey={setSortKey} setSortDir={setSortDir} viewMode={viewMode} docGridColumns={docGridColumns} docGridRowCount={docGridRowCount} docsGridVirtualizer={docsGridVirtualizer} docsTableVirtualizer={docsTableVirtualizer} selectedDocIds={selectedDocIds} setSelectedDocIds={setSelectedDocIds} selectedSet={selectedSet} allVisibleSelected={allVisibleSelected} toggleSelectAllVisible={toggleSelectAllVisible} toggleDocSelection={toggleDocSelection} batchDeleteOpen={batchDeleteOpen} setBatchDeleteOpen={setBatchDeleteOpen} batchDeleting={batchDeleting} confirmBatchDelete={confirmBatchDelete} batchLifecycleWorking={batchLifecycleWorking} batchReingestWorking={batchReingestWorking} runBatchReingest={runBatchReingest} runBatchLifecycle={runBatchLifecycle} anySelectedDisabled={anySelectedDisabled} anySelectedEnabled={anySelectedEnabled} anySelectedArchived={anySelectedArchived} anySelectedNotArchived={anySelectedNotArchived} deleteDocument={deleteDocument} handleFileUpload={handleFileUpload} onPeek={(id) => { setPeekingDocId(id); setShowTaskCenter(false); }} />
              </motion.div>
            ) : null}
            {activeTab === 'retrieval' && (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex-1 min-h-0">
                <RetrievePreviewPanel selectedDatasetId={selectedDatasetId} className="h-full border-0 bg-transparent p-0 shadow-none" />
              </motion.div>
            )}
            {activeTab === 'settings' && (
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex-1 min-h-0 bg-card/30 backdrop-blur-md border border-border/40 rounded-[2.5rem] overflow-hidden">
                <KnowledgeSettingsPanel selectedDatasetId={selectedDatasetId} />
              </motion.div>
            )}
          </div>
        </WorkbenchScaffold>
    </AppFrame>
  )
}
