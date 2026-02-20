'use client'

/**
 * 知识库管理页面
 * 优化版：卡片视图、视觉增强、交互优化、深色模式适配
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Database,
  FileText,
  FileType,
  FileSpreadsheet,
  FileCode,
  Presentation,
  Settings,
  Upload,
  Sliders,
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  Play,
  RotateCcw,
  Trash2,
  RefreshCw,
  BarChart3,
  Layers,
  HardDrive,
  FileStack,
  Eye,
  LayoutGrid,
  List as ListIcon,
  MoreVertical,
  File as FileIcon,
  Send,
  Zap,
  Globe,
  Filter,
  Folder,
  X,
  ChevronDown,
  ChevronRight,
  Copy,
} from 'lucide-react'
import { AppFrame } from '@/components/app-frame'
import { WorkbenchPanelDialog, WorkbenchScaffold } from '@/components/workbench'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { useDocuments } from '@/hooks/use-documents'
import { formatFileSize, formatDate, cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { toast } from 'sonner'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { getParserLabel } from '@/lib/parser-options'
import { toSourcePathPrefix } from '@/lib/document-folders'
import type { ConnectorRunOut, Dataset, Document, DocumentAccessMode, DocumentStats, IndexAuditResponse } from '@/types'
import { connectorApi, datasetApi, documentApi, observabilityApi } from '@/lib/api-client'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { RetrievePreviewPanel } from '@/components/rag/retrieve-preview-panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { KnowledgeDocumentsPanel } from '@/components/knowledge/knowledge-documents-panel'
import { KnowledgeScopePanel } from '@/components/knowledge/knowledge-scope-panel'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
import { KnowledgeRetrievalPanel } from '@/components/knowledge/knowledge-retrieval-panel'
import { KnowledgeSettingsPanel } from '@/components/knowledge/knowledge-settings-panel'
import { useKnowledgeScrollContainer } from '@/components/knowledge/use-knowledge-scroll-container'
import { parseKnowledgeQueryState, serializeKnowledgeQueryState } from '@/components/knowledge/use-knowledge-query-state'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'

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
  const lastUrlRef = useRef<string | null>(null)
  const didInitFromUrlRef = useRef(false)

  const { documents, total, isLoading, uploadDocuments, uploadDocumentFromUrl, deleteDocument, loadDocuments } = useDocuments()
  const [activeTab, setActiveTab] = useState<TabType>('documents')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
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
  const DATASET_ALL = '__all__'
  const DATASET_DEFAULT = '__default__'
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetScope, setDatasetScope] = useState<string>(DATASET_ALL)
  const [folderPath, setFolderPath] = useState<string | null>(null)
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const selectedDatasetId = datasetScope === DATASET_ALL ? undefined : datasetScope
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
	  }, [searchParams])

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
	      },
	      { datasetAllValue: DATASET_ALL }
	    )
	    const nextUrl = qs ? `/knowledge?${qs}` : '/knowledge'
	    if (lastUrlRef.current === nextUrl) return
	    lastUrlRef.current = nextUrl
	    router.replace(nextUrl, { scroll: false })
  }, [activeTab, viewMode, docFilter, statusFilter, lifecycleFilter, datasetScope, folderPath, sortKey, sortDir, router])

  const { sentinelRef: mainPaneSentinelRef, scrollEl: mainPaneScrollEl } = useKnowledgeScrollContainer()

  // PageBody is an internal scroll container; on tab switches keep the top anchored.
  useEffect(() => {
    const id = window.requestAnimationFrame(() => {
      mainPaneScrollEl?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
    })
    return () => window.cancelAnimationFrame(id)
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
    const t = window.setTimeout(() => {
      loadDocuments({
        limit: 200,
        status: statusFilter !== 'all' ? statusFilter : undefined,
        lifecycle: lifecycleFilter,
        q: docFilter.trim() || undefined,
        dataset_id: selectedDatasetId,
        source_path_prefix: selectedDatasetId ? toSourcePathPrefix(folderPath) : undefined,
        order_by: sortKey,
        order_dir: sortDir,
      })
    }, 250)
    return () => window.clearTimeout(t)
  }, [activeTab, statusFilter, lifecycleFilter, docFilter, selectedDatasetId, folderPath, sortKey, sortDir, loadDocuments])

  // Accurate dashboard stats (server aggregated) - avoids "only 200 items loaded" bias.
  useEffect(() => {
    if (activeTab !== 'documents') return
    const seq = ++docStatsSeqRef.current
    setDocStatsLoading(true)

    const t = window.setTimeout(() => {
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

    return () => window.clearTimeout(t)
  }, [activeTab, docFilter, selectedDatasetId, lifecycleFilter])

  // 检索相关（Index Audit）
  const [indexAudit, setIndexAudit] = useState<IndexAuditResponse | null>(null)
  const [indexAuditLoading, setIndexAuditLoading] = useState(false)
  const [indexAuditError, setIndexAuditError] = useState<string | null>(null)

  const totalDocs = docStats?.total ?? total ?? documents.length
  const byStatus = docStats?.by_status || {}
  const completedDocsValue: string | number = docStats ? Number(byStatus.completed || 0) : (docStatsLoading ? '…' : '—')
  const processingDocsCount = docStats ? Number(byStatus.pending || 0) + Number(byStatus.processing || 0) : 0
  const failedDocsCount = docStats ? Number(byStatus.failed || 0) : 0
  const quarantinedDocsCount = docStats ? Number(byStatus.quarantined || 0) : 0
  const processingDocsValue: string | number = docStats ? processingDocsCount : (docStatsLoading ? '…' : '—')
  const failedDocsValue: string | number = docStats ? failedDocsCount : (docStatsLoading ? '…' : '—')
  const quarantinedDocsValue: string | number = docStats ? quarantinedDocsCount : (docStatsLoading ? '…' : '—')
  const totalChunksValue: string | number = docStats ? Number(docStats.total_chunks || 0).toLocaleString() : (docStatsLoading ? '…' : '—')
  const totalSizeValue: string | number = docStats ? formatFileSize(Number(docStats.total_size || 0)) : (docStatsLoading ? '…' : '—')
  const showExtraCard = docStats ? (processingDocsCount > 0 || failedDocsCount > 0 || quarantinedDocsCount > 0) : false

  // The backend already applies q/status/dataset filters; keep UI list consistent with server results.
  const filteredDocuments = useMemo(() => documents, [documents])

  const [docGridColumns, setDocGridColumns] = useState(() => {
    if (typeof window === 'undefined') return 1
    return docGridColumnsForViewportWidth(window.innerWidth)
  })

  useEffect(() => {
    const onResize = () => setDocGridColumns(docGridColumnsForViewportWidth(window.innerWidth))
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
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
    estimateSize: () => 72,
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
          action === 'disable'
            ? documentApi.batchDisable
            : action === 'enable'
              ? documentApi.batchEnable
              : action === 'archive'
                ? documentApi.batchArchive
                : documentApi.batchUnarchive

        const res = await fn(ids)
        if (res?.denied?.length || res?.not_found?.length || res?.conflicts?.length) {
          console.warn('Batch lifecycle partial result:', res)
        }
        toast.success(
          action === 'disable'
            ? `已禁用 ${res.updated} 份文档`
            : action === 'enable'
              ? `已启用 ${res.updated} 份文档`
              : action === 'archive'
                ? `已归档 ${res.updated} 份文档`
                : `已取消归档 ${res.updated} 份文档`
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
        ...(pipelineOverridesEnabled ? { patch: pipelineOptions, replace: true } : {}),
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

  const [urlImportOpen, setUrlImportOpen] = useState(false)
  const [urlImportUrl, setUrlImportUrl] = useState('')
  const [urlImportFilename, setUrlImportFilename] = useState('')
  const [urlImportDatasetId, setUrlImportDatasetId] = useState<string>(DATASET_DEFAULT)
  const [urlImportSubmitting, setUrlImportSubmitting] = useState(false)

  const [urlBatchOpen, setUrlBatchOpen] = useState(false)
  const [urlBatchUrls, setUrlBatchUrls] = useState('')
  const [urlBatchFilename, setUrlBatchFilename] = useState('')
  const [urlBatchDatasetId, setUrlBatchDatasetId] = useState<string>(DATASET_DEFAULT)
  const [urlBatchAccessMode, setUrlBatchAccessMode] = useState<DocumentAccessMode>('inherit')
  const [urlBatchAccessMembers, setUrlBatchAccessMembers] = useState('')
  const [urlBatchSubmitting, setUrlBatchSubmitting] = useState(false)

  const [webCrawlOpen, setWebCrawlOpen] = useState(false)
  const [webCrawlStartUrls, setWebCrawlStartUrls] = useState('')
  const [webCrawlFilename, setWebCrawlFilename] = useState('')
  const [webCrawlDatasetId, setWebCrawlDatasetId] = useState<string>(DATASET_DEFAULT)
  const [webCrawlMaxPages, setWebCrawlMaxPages] = useState(50)
  const [webCrawlMaxDepth, setWebCrawlMaxDepth] = useState(3)
  const [webCrawlSameHostOnly, setWebCrawlSameHostOnly] = useState(true)
  const [webCrawlIncludePatterns, setWebCrawlIncludePatterns] = useState('')
  const [webCrawlExcludePatterns, setWebCrawlExcludePatterns] = useState('')
  const [webCrawlUseSitemaps, setWebCrawlUseSitemaps] = useState(false)
  const [webCrawlSitemapUrls, setWebCrawlSitemapUrls] = useState('')
  const [webCrawlRespectRobots, setWebCrawlRespectRobots] = useState(false)
  const [webCrawlDedupCanonical, setWebCrawlDedupCanonical] = useState(true)
  const [webCrawlUserAgent, setWebCrawlUserAgent] = useState('')
  const [webCrawlAuthType, setWebCrawlAuthType] = useState<'none' | 'cookie' | 'bearer' | 'basic'>('none')
  const [webCrawlAuthCookie, setWebCrawlAuthCookie] = useState('')
  const [webCrawlAuthToken, setWebCrawlAuthToken] = useState('')
  const [webCrawlAuthUsername, setWebCrawlAuthUsername] = useState('')
  const [webCrawlAuthPassword, setWebCrawlAuthPassword] = useState('')
  const [webCrawlAccessMode, setWebCrawlAccessMode] = useState<DocumentAccessMode>('inherit')
  const [webCrawlAccessMembers, setWebCrawlAccessMembers] = useState('')
  const [webCrawlSubmitting, setWebCrawlSubmitting] = useState(false)
  const [connectorRuns, setConnectorRuns] = useState<ConnectorRunOut[]>([])
  const [connectorRunsLoading, setConnectorRunsLoading] = useState(false)
  const [expandedConnectorRunId, setExpandedConnectorRunId] = useState<string | null>(null)

  const copyText = useCallback(async (text: string, okMsg: string) => {
    try {
      if (!navigator.clipboard?.writeText) {
        toast.error('复制失败：浏览器不支持 Clipboard API')
        return
      }
      await navigator.clipboard.writeText(text)
      toast.success(okMsg)
    } catch {
      toast.error('复制失败')
    }
  }, [])

  const parseUrlBatchUrls = useCallback((raw: string): string[] => {
    const parts = (raw || '')
      .split(/[\n,;]+/g)
      .map((s) => s.trim())
      .filter(Boolean)
    const out: string[] = []
    const seen = new Set<string>()
    for (const p of parts) {
      if (!/^https?:\/\//i.test(p)) continue
      if (seen.has(p)) continue
      seen.add(p)
      out.push(p)
      if (out.length >= 50) break
    }
    return out
  }, [])

  const parseWebCrawlStartUrls = useCallback((raw: string): string[] => {
    const parts = (raw || '')
      .split(/[\n,;]+/g)
      .map((s) => s.trim())
      .filter(Boolean)
    const out: string[] = []
    const seen = new Set<string>()
    for (const p of parts) {
      if (!/^https?:\/\//i.test(p)) continue
      if (seen.has(p)) continue
      seen.add(p)
      out.push(p)
      if (out.length >= 5) break
    }
    return out
  }, [])

  const parseWebCrawlSitemapUrls = useCallback((raw: string): string[] => {
    const parts = (raw || '')
      .split(/[\n,;]+/g)
      .map((s) => s.trim())
      .filter(Boolean)
    const out: string[] = []
    const seen = new Set<string>()
    for (const p of parts) {
      if (!/^https?:\/\//i.test(p)) continue
      if (seen.has(p)) continue
      seen.add(p)
      out.push(p)
      if (out.length >= 10) break
    }
    return out
  }, [])

  const parsePatterns = useCallback((raw: string, max: number): string[] => {
    const parts = (raw || '')
      .split(/\n+/g)
      .map((s) => s.trim())
      .filter(Boolean)
    const out: string[] = []
    const seen = new Set<string>()
    for (const p of parts) {
      if (seen.has(p)) continue
      seen.add(p)
      out.push(p)
      if (out.length >= max) break
    }
    return out
  }, [])

  const parseAccessMembers = useCallback((raw: string): string[] => {
    const parts = (raw || '')
      .split(/[\n,;]+/g)
      .map((s) => s.trim())
      .filter(Boolean)
    const out: string[] = []
    const seen = new Set<string>()
    for (const p of parts) {
      if (seen.has(p)) continue
      seen.add(p)
      out.push(p)
      if (out.length >= 200) break
    }
    return out
  }, [])

  const loadConnectorRuns = useCallback(
    async (params?: { datasetId?: string }) => {
      setConnectorRunsLoading(true)
      try {
        const res = await connectorApi.listRuns({
          limit: 20,
          dataset_id: params?.datasetId,
        })
        setConnectorRuns(res.items || [])
      } catch (err) {
        console.warn('Load connector runs failed:', err)
      } finally {
        setConnectorRunsLoading(false)
      }
    },
    []
  )

  useEffect(() => {
    if (activeTab !== 'settings') return
    void loadConnectorRuns({ datasetId: selectedDatasetId })
  }, [activeTab, loadConnectorRuns, selectedDatasetId])

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

  const handleUrlImport = useCallback(async () => {
    const url = urlImportUrl.trim()
    if (!url) {
      toast.error('请输入 URL')
      return
    }
    setUrlImportSubmitting(true)
    try {
      await uploadDocumentFromUrl({
        url,
        filename: urlImportFilename.trim() ? urlImportFilename.trim() : undefined,
        dataset_id: urlImportDatasetId === DATASET_DEFAULT ? undefined : urlImportDatasetId,
      })
      toast.success('已提交 URL 导入任务（后台拉取并入库）')
      setUrlImportOpen(false)
      setUrlImportUrl('')
      setUrlImportFilename('')
    } catch (err: any) {
      toast.error(formatApiError(err, 'URL 导入失败'))
    } finally {
      setUrlImportSubmitting(false)
    }
  }, [DATASET_DEFAULT, uploadDocumentFromUrl, urlImportDatasetId, urlImportFilename, urlImportUrl])

  const handleUrlBatchImport = useCallback(async () => {
    const urls = parseUrlBatchUrls(urlBatchUrls)
    if (!urls.length) {
      toast.error('请输入至少 1 个 http(s) URL（每行一个）')
      return
    }

    setUrlBatchSubmitting(true)
    try {
      const access =
        urlBatchAccessMode === 'inherit'
          ? null
          : {
              mode: urlBatchAccessMode,
              partial_member_list: urlBatchAccessMode === 'partial_members' ? parseAccessMembers(urlBatchAccessMembers) : null,
            }

      const run = await connectorApi.createRun({
        connector_id: 'url_batch',
        dataset_id: urlBatchDatasetId === DATASET_DEFAULT ? undefined : urlBatchDatasetId,
        config: {
          urls,
          filename: urlBatchFilename.trim() ? urlBatchFilename.trim() : undefined,
          parser_backend: parserBackend,
          chunk_strategy: chunkStrategy,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
          access,
        },
      })

      toast.success(`已创建批量导入任务：${run.id.slice(0, 8)}`)
      setUrlBatchOpen(false)
      setUrlBatchUrls('')
      setUrlBatchFilename('')
      setUrlBatchAccessMode('inherit')
      setUrlBatchAccessMembers('')
      void loadConnectorRuns({ datasetId: selectedDatasetId })
      void loadDocuments()
    } catch (err: any) {
      toast.error(formatApiError(err, '创建 URL 批量导入失败'))
    } finally {
      setUrlBatchSubmitting(false)
    }
  }, [
    DATASET_DEFAULT,
    chunkStrategy,
    loadConnectorRuns,
    loadDocuments,
    parseAccessMembers,
    parseUrlBatchUrls,
    parserBackend,
    pipelineOptions,
    pipelineOverridesEnabled,
    selectedDatasetId,
    urlBatchAccessMembers,
    urlBatchAccessMode,
    urlBatchDatasetId,
    urlBatchFilename,
    urlBatchUrls,
  ])

  const handleWebCrawlImport = useCallback(async () => {
    const startUrls = parseWebCrawlStartUrls(webCrawlStartUrls)
    if (!startUrls.length) {
      toast.error('请输入至少 1 个 http(s) 种子 URL（每行一个）')
      return
    }

    let auth: any = null
    const authType = webCrawlAuthType
    if (authType === 'cookie') {
      const cookie = webCrawlAuthCookie.trim()
      if (!cookie) {
        toast.error('请输入 Cookie')
        return
      }
      auth = { type: 'cookie', cookie }
    } else if (authType === 'bearer') {
      const token = webCrawlAuthToken.trim()
      if (!token) {
        toast.error('请输入 Bearer token')
        return
      }
      auth = { type: 'bearer', token }
    } else if (authType === 'basic') {
      const username = webCrawlAuthUsername.trim()
      const password = webCrawlAuthPassword.trim()
      if (!username || !password) {
        toast.error('请输入 Basic 用户名/密码')
        return
      }
      auth = { type: 'basic', username, password }
    }

    const maxPages = Number.isFinite(webCrawlMaxPages) ? Math.trunc(webCrawlMaxPages) : 50
    const maxDepth = Number.isFinite(webCrawlMaxDepth) ? Math.trunc(webCrawlMaxDepth) : 3

    setWebCrawlSubmitting(true)
    try {
      const access =
        webCrawlAccessMode === 'inherit'
          ? null
          : {
              mode: webCrawlAccessMode,
              partial_member_list:
                webCrawlAccessMode === 'partial_members' ? parseAccessMembers(webCrawlAccessMembers) : null,
            }

      const run = await connectorApi.createRun({
        connector_id: 'web_crawl',
        dataset_id: webCrawlDatasetId === DATASET_DEFAULT ? undefined : webCrawlDatasetId,
        config: {
          start_urls: startUrls,
          max_pages: maxPages,
          max_depth: maxDepth,
          same_host_only: Boolean(webCrawlSameHostOnly),
          include_patterns: parsePatterns(webCrawlIncludePatterns, 30),
          exclude_patterns: parsePatterns(webCrawlExcludePatterns, 60),
          use_sitemaps: Boolean(webCrawlUseSitemaps),
          sitemap_urls: parseWebCrawlSitemapUrls(webCrawlSitemapUrls),
          respect_robots: Boolean(webCrawlRespectRobots),
          dedup_canonical: Boolean(webCrawlDedupCanonical),
          user_agent: webCrawlUserAgent.trim() ? webCrawlUserAgent.trim() : undefined,
          auth,
          filename: webCrawlFilename.trim() ? webCrawlFilename.trim() : undefined,
          parser_backend: parserBackend,
          chunk_strategy: chunkStrategy,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
          access,
        },
      })

      toast.success(`Web crawl run created: ${run.id.slice(0, 8)}`)
      setWebCrawlOpen(false)
      setWebCrawlStartUrls('')
      setWebCrawlFilename('')
      setWebCrawlMaxPages(50)
      setWebCrawlMaxDepth(3)
      setWebCrawlSameHostOnly(true)
      setWebCrawlIncludePatterns('')
      setWebCrawlExcludePatterns('')
      setWebCrawlUseSitemaps(false)
      setWebCrawlSitemapUrls('')
      setWebCrawlRespectRobots(false)
      setWebCrawlDedupCanonical(true)
      setWebCrawlUserAgent('')
      setWebCrawlAuthType('none')
      setWebCrawlAuthCookie('')
      setWebCrawlAuthToken('')
      setWebCrawlAuthUsername('')
      setWebCrawlAuthPassword('')
      setWebCrawlAccessMode('inherit')
      setWebCrawlAccessMembers('')
      void loadConnectorRuns({ datasetId: selectedDatasetId })
      void loadDocuments()
    } catch (err: any) {
      toast.error(formatApiError(err, '创建网页爬取任务失败'))
    } finally {
      setWebCrawlSubmitting(false)
    }
  }, [
    DATASET_DEFAULT,
    chunkStrategy,
    loadConnectorRuns,
    loadDocuments,
    parseAccessMembers,
    parsePatterns,
    parseWebCrawlStartUrls,
    parseWebCrawlSitemapUrls,
    parserBackend,
    pipelineOptions,
    pipelineOverridesEnabled,
    selectedDatasetId,
    webCrawlAccessMembers,
    webCrawlAccessMode,
    webCrawlAuthCookie,
    webCrawlAuthPassword,
    webCrawlAuthToken,
    webCrawlAuthType,
    webCrawlAuthUsername,
    webCrawlDatasetId,
    webCrawlDedupCanonical,
    webCrawlExcludePatterns,
    webCrawlFilename,
    webCrawlIncludePatterns,
    webCrawlMaxDepth,
    webCrawlMaxPages,
    webCrawlRespectRobots,
    webCrawlSameHostOnly,
    webCrawlSitemapUrls,
    webCrawlStartUrls,
    webCrawlUseSitemaps,
    webCrawlUserAgent,
  ])

  const handleCancelConnectorRun = useCallback(
    async (runId: string) => {
      if (!runId) return
      try {
        await connectorApi.cancelRun(runId)
        toast.success('已取消导入任务')
        void loadConnectorRuns({ datasetId: selectedDatasetId })
      } catch (err: any) {
        toast.error(formatApiError(err, '取消导入任务失败'))
      }
    },
    [loadConnectorRuns, selectedDatasetId]
  )

  const handleRetryFailedConnectorRun = useCallback(
    async (runId: string) => {
      if (!runId) return
      try {
        const next = await connectorApi.retryFailed(runId)
        toast.success(`已创建重试任务：${String(next.id || '').slice(0, 8)}`)
        void loadConnectorRuns({ datasetId: selectedDatasetId })
        void loadDocuments()
      } catch (err: any) {
        toast.error(formatApiError(err, '重试失败项失败'))
      }
    },
    [loadConnectorRuns, loadDocuments, selectedDatasetId]
  )

  const handleResumeConnectorRun = useCallback(
    async (runId: string) => {
      if (!runId) return
      try {
        const next = await connectorApi.resumeRun(runId)
        toast.success(`已创建续跑任务：${String(next.id || '').slice(0, 8)}`)
        void loadConnectorRuns({ datasetId: selectedDatasetId })
        void loadDocuments()
      } catch (err: any) {
        toast.error(formatApiError(err, '续跑失败'))
      }
    },
    [loadConnectorRuns, loadDocuments, selectedDatasetId]
  )

  const handleRunIndexAudit = useCallback(async () => {
    if (!selectedDatasetId) {
      toast.error('请先选择数据集再运行 Index Audit')
      return
    }
    setIndexAuditLoading(true)
    setIndexAuditError(null)
    try {
      const res = await observabilityApi.getIndexAudit({ dataset_id: selectedDatasetId })
      setIndexAudit(res)
      toast.success('Index Audit 完成')
    } catch (err: any) {
      console.error('Index audit failed:', err)
      setIndexAuditError(formatApiError(err, 'Index Audit 失败'))
    } finally {
      setIndexAuditLoading(false)
    }
  }, [selectedDatasetId])

  const getConnectorRunBadge = (status: string): { status: StatusBadgeStatus; label: string } => {
    switch (String(status || '').toLowerCase()) {
      case 'pending':
        return { status: 'pending', label: '等待' }
      case 'running':
        return { status: 'processing', label: '运行中' }
      case 'completed':
        return { status: 'completed', label: '已完成' }
      case 'failed':
        return { status: 'failed', label: '失败' }
      case 'cancelled':
        return { status: 'cancelled', label: '已取消' }
      default:
        return { status: 'pending', label: String(status || '等待') }
    }
  }

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
            <>
              <Dialog>
                <DialogTrigger asChild>
                  <Button
                    variant="outline"
                    className="gap-2 border-border bg-background/60 hover:bg-background text-muted-foreground"
                  >
                    <Sliders className="w-4 h-4" />
                    管线配置
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-2xl">
                  <DialogHeader>
                    <DialogTitle>入库管线配置</DialogTitle>
                    <DialogDescription>仅影响新上传文档，可随时调整</DialogDescription>
                  </DialogHeader>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">解析方式</div>
                      <ParserDropdown value={parserBackend} onChange={setParserBackend} />
                    </div>
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">切块策略</div>
                      <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
                    </div>
                  </div>
                  <PipelineOptionsPanel />
                </DialogContent>
              </Dialog>
              <Dialog
                open={urlImportOpen}
                onOpenChange={(open) => {
                  setUrlImportOpen(open)
                  if (open) {
                    setUrlImportDatasetId(selectedDatasetId || DATASET_DEFAULT)
                  }
                }}
              >
                <DialogTrigger asChild>
                  <Button
                    variant="outline"
                    className="gap-2 border-border bg-background/60 hover:bg-background text-muted-foreground"
                  >
                    <Send className="w-4 h-4" />
                    URL 导入
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-2xl">
                  <DialogHeader>
                    <DialogTitle>通过 URL 导入文档</DialogTitle>
                    <DialogDescription>
                      后端拉取 URL 内容并按当前管线配置入库（需要后端开启 URL_INGEST_ENABLED）。
                    </DialogDescription>
                  </DialogHeader>

                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">URL</div>
                        <Input
                          value={urlImportUrl}
                          onChange={(e) => setUrlImportUrl(e.target.value)}
                          placeholder="https://example.com/doc.pdf / https://example.com/page.html"
                          className="font-mono"
                        />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">文件名（可选）</div>
                        <Input
                          value={urlImportFilename}
                          onChange={(e) => setUrlImportFilename(e.target.value)}
                          placeholder="例如：产品手册.pdf"
                        />
                      </div>
                    </div>

                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">目标数据集</div>
                      <Select value={urlImportDatasetId} onValueChange={setUrlImportDatasetId}>
                        <SelectTrigger className="h-10 bg-background">
                          <SelectValue placeholder="选择数据集" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={DATASET_DEFAULT}>默认（自动选择可写数据集）</SelectItem>
                          {datasets.map((ds) => (
                            <SelectItem key={ds.id} value={ds.id}>
                              {ds.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {datasetsLoading ? (
                        <div className="text-xs text-muted-foreground">正在加载数据集...</div>
                      ) : null}
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">解析方式</div>
                        <ParserDropdown value={parserBackend} onChange={setParserBackend} />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">切块策略</div>
                        <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
                      </div>
                    </div>

                    <PipelineOptionsPanel />

                    <div className="flex items-center justify-end gap-2 pt-2">
                      <Button
                        variant="outline"
                        onClick={() => setUrlImportOpen(false)}
                        disabled={urlImportSubmitting}
                      >
                        取消
                      </Button>
                      <Button
                        onClick={handleUrlImport}
                        disabled={urlImportSubmitting || !urlImportUrl.trim()}
                        className="gap-2"
                      >
                        {urlImportSubmitting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
                        开始导入
                      </Button>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>
              <Dialog
                open={urlBatchOpen}
                onOpenChange={(open) => {
                  setUrlBatchOpen(open)
                  if (open) {
                    setUrlBatchDatasetId(selectedDatasetId || DATASET_DEFAULT)
                  }
                }}
              >
                <DialogTrigger asChild>
                  <Button
                    variant="outline"
                    className="gap-2 border-border bg-background/60 hover:bg-background text-muted-foreground"
                  >
                    <Zap className="w-4 h-4" />
                    URL 批量导入
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-2xl">
                  <DialogHeader>
                    <DialogTitle>URL 批量导入（Connector）</DialogTitle>
                    <DialogDescription>
                      一次导入多个 URL，并生成导入运行记录（需要后端开启 URL_INGEST_ENABLED）。
                    </DialogDescription>
                  </DialogHeader>

                  <div className="space-y-4">
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">URLs（每行一个，最多 50）</div>
                      <Textarea
                        value={urlBatchUrls}
                        onChange={(e) => setUrlBatchUrls(e.target.value)}
                        placeholder={'https://example.com/doc1.pdf\nhttps://example.com/doc2.html'}
                        className="font-mono min-h-[140px]"
                      />
                      <div className="text-xs text-muted-foreground">
                        已识别 {parseUrlBatchUrls(urlBatchUrls).length} 个 URL（仅统计 http/https）。
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">文件名（可选）</div>
                        <Input
                          value={urlBatchFilename}
                          onChange={(e) => setUrlBatchFilename(e.target.value)}
                          placeholder="例如：产品手册.pdf"
                        />
                        <div className="text-xs text-muted-foreground">
                          用于显示名/扩展名推断（对所有 URL 生效）。
                        </div>
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">目标数据集</div>
                        <Select value={urlBatchDatasetId} onValueChange={setUrlBatchDatasetId}>
                          <SelectTrigger className="h-10 bg-background">
                            <SelectValue placeholder="选择数据集" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={DATASET_DEFAULT}>默认（自动选择可写数据集）</SelectItem>
                            {datasets.map((ds) => (
                              <SelectItem key={ds.id} value={ds.id}>
                                {ds.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        {datasetsLoading ? (
                          <div className="text-xs text-muted-foreground">正在加载数据集...</div>
                        ) : null}
                      </div>
                    </div>

                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">文档访问控制（可选）</div>
                      <Select value={urlBatchAccessMode} onValueChange={(v) => setUrlBatchAccessMode(v as DocumentAccessMode)}>
                        <SelectTrigger className="h-10 bg-background">
                          <SelectValue placeholder="选择访问模式" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="inherit">继承数据集</SelectItem>
                          <SelectItem value="only_me">仅我可见</SelectItem>
                          <SelectItem value="partial_members">指定成员</SelectItem>
                          <SelectItem value="all_team_members">团队成员</SelectItem>
                        </SelectContent>
                      </Select>
                      {urlBatchAccessMode === 'partial_members' ? (
                        <div className="space-y-2 pt-2">
                          <div className="text-sm font-medium text-foreground/80">允许成员（每行一个 user_id）</div>
                          <Textarea
                            value={urlBatchAccessMembers}
                            onChange={(e) => setUrlBatchAccessMembers(e.target.value)}
                            placeholder={'alice\nbob\ncharlie'}
                            className="font-mono min-h-[110px]"
                          />
                          <div className="text-xs text-muted-foreground">最多 200 个；仅支持当前租户已存在的成员。</div>
                        </div>
                      ) : null}
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">解析方式</div>
                        <ParserDropdown value={parserBackend} onChange={setParserBackend} />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">切块策略</div>
                        <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
                      </div>
                    </div>

                    <PipelineOptionsPanel />

                    <div className="flex items-center justify-end gap-2 pt-2">
                      <Button variant="outline" onClick={() => setUrlBatchOpen(false)} disabled={urlBatchSubmitting}>
                        取消
                      </Button>
                      <Button onClick={handleUrlBatchImport} disabled={urlBatchSubmitting} className="gap-2">
                        {urlBatchSubmitting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
                        开始导入
                      </Button>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>
              <Dialog
                open={webCrawlOpen}
                onOpenChange={(open) => {
                  setWebCrawlOpen(open)
                  if (open) {
                    setWebCrawlDatasetId(selectedDatasetId || DATASET_DEFAULT)
                  }
                }}
              >
                <DialogTrigger asChild>
                  <Button
                    variant="outline"
                    className="gap-2 border-border bg-background/60 hover:bg-background text-muted-foreground"
                  >
                    <Globe className="w-4 h-4" />
                    Website Crawl
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-3xl">
                  <DialogHeader>
                    <DialogTitle>Website Crawl (Connector)</DialogTitle>
                    <DialogDescription>
                      Crawl from one or more seed URLs, discover links, then ingest each page via URL ingestion.
                      Requires backend `URL_INGEST_ENABLED=true`.
                    </DialogDescription>
                  </DialogHeader>

                  <div className="space-y-4">
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">Seed URLs (one per line, max 5)</div>
                      <Textarea
                        value={webCrawlStartUrls}
                        onChange={(e) => setWebCrawlStartUrls(e.target.value)}
                        placeholder={'https://example.com/docs\nhttps://example.com/help'}
                        className="font-mono min-h-[120px]"
                      />
                      <div className="text-xs text-muted-foreground">
                        Parsed: {parseWebCrawlStartUrls(webCrawlStartUrls).length} urls
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Max pages</div>
                        <Input
                          type="number"
                          value={webCrawlMaxPages}
                          onChange={(e) => setWebCrawlMaxPages(Number(e.target.value || 0))}
                          min={1}
                          max={500}
                        />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Max depth</div>
                        <Input
                          type="number"
                          value={webCrawlMaxDepth}
                          onChange={(e) => setWebCrawlMaxDepth(Number(e.target.value || 0))}
                          min={0}
                          max={10}
                        />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Scope</div>
                        <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={webCrawlSameHostOnly}
                            onChange={(e) => setWebCrawlSameHostOnly(e.target.checked)}
                            className="accent-primary h-4 w-4"
                          />
                          Same host only
                        </label>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Include patterns (regex, one per line)</div>
                        <Textarea
                          value={webCrawlIncludePatterns}
                          onChange={(e) => setWebCrawlIncludePatterns(e.target.value)}
                          placeholder={'/docs/\n/help/'}
                          className="font-mono min-h-[110px]"
                        />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Exclude patterns (regex, one per line)</div>
                        <Textarea
                          value={webCrawlExcludePatterns}
                          onChange={(e) => setWebCrawlExcludePatterns(e.target.value)}
                          placeholder={'/logout\n\\?print=1'}
                          className="font-mono min-h-[110px]"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Discovery (optional)</div>
                        <div className="space-y-2 rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
                          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
                            <input
                              type="checkbox"
                              checked={webCrawlUseSitemaps}
                              onChange={(e) => setWebCrawlUseSitemaps(e.target.checked)}
                              className="accent-primary h-4 w-4"
                            />
                            Use sitemap.xml / robots Sitemap hints (faster)
                          </label>
                          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
                            <input
                              type="checkbox"
                              checked={webCrawlRespectRobots}
                              onChange={(e) => setWebCrawlRespectRobots(e.target.checked)}
                              className="accent-primary h-4 w-4"
                            />
                            Respect robots.txt (best-effort)
                          </label>
                          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
                            <input
                              type="checkbox"
                              checked={webCrawlDedupCanonical}
                              onChange={(e) => setWebCrawlDedupCanonical(e.target.checked)}
                              className="accent-primary h-4 w-4"
                            />
                            Dedup by canonical link (best-effort)
                          </label>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Tip: sitemap mode avoids fetching every page just to discover links; the connector still ingests each URL.
                        </div>
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Sitemap URLs (optional, max 10)</div>
                        <Textarea
                          value={webCrawlSitemapUrls}
                          onChange={(e) => setWebCrawlSitemapUrls(e.target.value)}
                          placeholder={'https://example.com/sitemap.xml\nhttps://example.com/sitemap_index.xml'}
                          className="font-mono min-h-[110px]"
                          disabled={!webCrawlUseSitemaps}
                        />
                        <div className="text-xs text-muted-foreground">
                          {webCrawlUseSitemaps
                            ? `Parsed: ${parseWebCrawlSitemapUrls(webCrawlSitemapUrls).length} urls`
                            : 'Enable “Use sitemap” to edit; otherwise the crawler will just follow links from seeds.'}
                        </div>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">User-Agent (optional)</div>
                        <Input
                          value={webCrawlUserAgent}
                          onChange={(e) => setWebCrawlUserAgent(e.target.value)}
                          placeholder="MimirQ/1.0 (+web-crawl)"
                        />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Auth</div>
                        <Select value={webCrawlAuthType} onValueChange={(v) => setWebCrawlAuthType(v as any)}>
                          <SelectTrigger className="h-10 bg-background">
                            <SelectValue placeholder="Select auth" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">None</SelectItem>
                            <SelectItem value="cookie">Cookie</SelectItem>
                            <SelectItem value="bearer">Bearer</SelectItem>
                            <SelectItem value="basic">Basic</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    {webCrawlAuthType === 'cookie' ? (
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Cookie header value</div>
                        <Textarea
                          value={webCrawlAuthCookie}
                          onChange={(e) => setWebCrawlAuthCookie(e.target.value)}
                          placeholder="session=...; other=..."
                          className="font-mono min-h-[90px]"
                        />
                      </div>
                    ) : null}
                    {webCrawlAuthType === 'bearer' ? (
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Bearer token</div>
                        <Textarea
                          value={webCrawlAuthToken}
                          onChange={(e) => setWebCrawlAuthToken(e.target.value)}
                          placeholder="eyJhbGciOi..."
                          className="font-mono min-h-[90px]"
                        />
                      </div>
                    ) : null}
                    {webCrawlAuthType === 'basic' ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <div className="text-sm font-medium text-foreground/80">Username</div>
                          <Input value={webCrawlAuthUsername} onChange={(e) => setWebCrawlAuthUsername(e.target.value)} />
                        </div>
                        <div className="space-y-2">
                          <div className="text-sm font-medium text-foreground/80">Password</div>
                          <Input
                            type="password"
                            value={webCrawlAuthPassword}
                            onChange={(e) => setWebCrawlAuthPassword(e.target.value)}
                          />
                        </div>
                      </div>
                    ) : null}

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Filename override (optional)</div>
                        <Input
                          value={webCrawlFilename}
                          onChange={(e) => setWebCrawlFilename(e.target.value)}
                          placeholder="e.g. website.html"
                        />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Target dataset</div>
                        <Select value={webCrawlDatasetId} onValueChange={setWebCrawlDatasetId}>
                          <SelectTrigger className="h-10 bg-background">
                            <SelectValue placeholder="Select dataset" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={DATASET_DEFAULT}>Default (auto)</SelectItem>
                            {datasets.map((ds) => (
                              <SelectItem key={ds.id} value={ds.id}>
                                {ds.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        {datasetsLoading ? (
                          <div className="text-xs text-muted-foreground">Loading datasets...</div>
                        ) : null}
                      </div>
                    </div>

                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">Document access (optional)</div>
                      <Select value={webCrawlAccessMode} onValueChange={(v) => setWebCrawlAccessMode(v as DocumentAccessMode)}>
                        <SelectTrigger className="h-10 bg-background">
                          <SelectValue placeholder="Select access mode" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="inherit">Inherit dataset</SelectItem>
                          <SelectItem value="only_me">Only me</SelectItem>
                          <SelectItem value="partial_members">Partial members</SelectItem>
                          <SelectItem value="all_team_members">All team members</SelectItem>
                        </SelectContent>
                      </Select>
                      {webCrawlAccessMode === 'partial_members' ? (
                        <div className="space-y-2 pt-2">
                          <div className="text-sm font-medium text-foreground/80">Allowed members (one user_id per line)</div>
                          <Textarea
                            value={webCrawlAccessMembers}
                            onChange={(e) => setWebCrawlAccessMembers(e.target.value)}
                            placeholder={'alice\nbob\ncharlie'}
                            className="font-mono min-h-[110px]"
                          />
                        </div>
                      ) : null}
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Parser</div>
                        <ParserDropdown value={parserBackend} onChange={setParserBackend} />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Chunk strategy</div>
                        <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
                      </div>
                    </div>

                    <PipelineOptionsPanel />

                    <div className="flex items-center justify-end gap-2 pt-2">
                      <Button variant="outline" onClick={() => setWebCrawlOpen(false)} disabled={webCrawlSubmitting}>
                        Cancel
                      </Button>
                      <Button onClick={handleWebCrawlImport} disabled={webCrawlSubmitting} className="gap-2">
                        {webCrawlSubmitting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
                        Start
                      </Button>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>
              <label>
                <Button
                  className="gap-2 rounded-xl shadow-sm border border-primary/20"
                  size="lg"
                  asChild
                >
                  <span>
                    <Upload className="w-4 h-4" />
                    上传文档
                  </span>
                </Button>
                <input
                  type="file"
                  multiple
                  accept={UPLOAD_ACCEPT}
                  className="hidden"
                  onChange={handleFileUpload}
                />
              </label>
            </>
          }
          top={
            <StatsGrid className={showExtraCard ? "lg:grid-cols-5" : "lg:grid-cols-4"}>
              <StatCard
                icon={FileStack}
                label="文档总数"
                value={totalDocs}
                color="sky"
                className="bg-card/60 backdrop-blur-md border-border/60 shadow-soft"
              />
              <StatCard
                icon={CheckCircle}
                label="已就绪"
                value={completedDocsValue}
                color="green"
                className="bg-card/60 backdrop-blur-md border-border/60 shadow-soft"
              />
              <StatCard
                icon={Layers}
                label="知识分块"
                value={totalChunksValue}
                color="teal"
                className="bg-card/60 backdrop-blur-md border-border/60 shadow-soft"
              />
              <StatCard
                icon={HardDrive}
                label="存储占用"
                value={totalSizeValue}
                color="orange"
                className="bg-card/60 backdrop-blur-md border-border/60 shadow-soft"
              />
              {showExtraCard && (
                <StatCard
                  icon={(failedDocsCount + quarantinedDocsCount) > 0 ? (failedDocsCount > 0 ? XCircle : AlertTriangle) : Loader2}
                  label={(failedDocsCount + quarantinedDocsCount) > 0 ? '需关注' : '处理中'}
                  value={(failedDocsCount + quarantinedDocsCount) > 0 ? (failedDocsCount + quarantinedDocsCount) : processingDocsCount}
                  color={(failedDocsCount + quarantinedDocsCount) > 0 ? (failedDocsCount > 0 ? 'red' : 'amber') : 'sky'}
                  className="bg-card/60 backdrop-blur-md border-border/60 shadow-soft"
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
                      'flex items-center gap-2 px-5 py-4 text-sm font-medium border-b-2 transition-colors focus-ring',
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
                      onClick={() => window.open('/chunk-preview', '_blank')}
                      className="h-9 w-9 text-muted-foreground hover:text-foreground"
                    >
                      <Eye className="w-4 h-4" />
                    </IconButton>
                    <div className="bg-muted/40 border border-border/60 p-1 rounded-lg flex gap-1">
                      <button
                        aria-label="网格视图"
                        onClick={() => setViewMode('grid')}
                        className={cn(
                          "p-1.5 rounded-md transition-colors focus-ring",
                          viewMode === 'grid'
                            ? "bg-background shadow-soft text-primary"
                            : "text-muted-foreground hover:text-foreground hover:bg-muted/40"
                        )}
                      >
                        <LayoutGrid className="w-4 h-4" />
                      </button>
                      <button
                        aria-label="列表视图"
                        onClick={() => setViewMode('list')}
                        className={cn(
                          "p-1.5 rounded-md transition-colors focus-ring",
                          viewMode === 'list'
                            ? "bg-background shadow-soft text-primary"
                            : "text-muted-foreground hover:text-foreground hover:bg-muted/40"
                        )}
                      >
                        <ListIcon className="w-4 h-4" />
                      </button>
                    </div>
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
            <KnowledgeDocumentsPanel
              isLoading={isLoading}
              documents={documents}
              filteredDocuments={filteredDocuments}

              docFilter={docFilter}
              setDocFilter={setDocFilter}
              onClearFilters={() => {
                setDocFilter('')
                setStatusFilter('all')
                setLifecycleFilter('active')
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
          ) : null}

          {/* 检索测试 */}
			          {activeTab === 'retrieval' && (
			            <KnowledgeRetrievalPanel
			              selectedDatasetId={selectedDatasetId}
			              indexAudit={indexAudit}
			              indexAuditLoading={indexAuditLoading}
			              indexAuditError={indexAuditError}
			              onRunIndexAudit={handleRunIndexAudit}
			            />
			          )}

	          {/* 设置 */}
	          {activeTab === 'settings' && (
	            <KnowledgeSettingsPanel
	              selectedDatasetId={selectedDatasetId}
	              connectorRuns={connectorRuns}
	              connectorRunsLoading={connectorRunsLoading}
	              onLoadConnectorRuns={loadConnectorRuns}
	              expandedConnectorRunId={expandedConnectorRunId}
	              onToggleExpandedConnectorRun={(runId) =>
	                setExpandedConnectorRunId((prev) => (prev === runId ? null : runId))
	              }
	              onCancelConnectorRun={handleCancelConnectorRun}
	              onResumeConnectorRun={handleResumeConnectorRun}
	              onRetryFailedConnectorRun={handleRetryFailedConnectorRun}
	            />
	          )}

        </WorkbenchScaffold>
    </AppFrame>
  )
}
