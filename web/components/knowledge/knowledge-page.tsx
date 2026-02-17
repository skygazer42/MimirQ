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
import { WorkbenchScaffold } from '@/components/workbench'
import { EmptyState } from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { SearchInput } from '@/components/ui/search-input'
import { Panel } from '@/components/ui/panel'
import { Textarea } from '@/components/ui/textarea'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import { DocumentTags } from '@/components/documents/document-tags'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
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
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { getParserLabel } from '@/lib/parser-options'
import { toSourcePathPrefix } from '@/lib/document-folders'
import type { ConnectorRunOut, Dataset, Document, DocumentAccessMode, DocumentStats, IndexAuditResponse } from '@/types'
import { connectorApi, datasetApi, documentApi, observabilityApi } from '@/lib/api-client'
import { getUserTagsFromDocument } from '@/lib/document-user-tags'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { DatasetFolderTree } from '@/components/document-library/dataset-folder-tree'
import { RetrievePreviewPanel } from '@/components/rag/retrieve-preview-panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { KnowledgeSidebar } from '@/components/knowledge/knowledge-sidebar'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
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
  const DATASET_ALL = '__all__'
  const DATASET_DEFAULT = '__default__'
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetScope, setDatasetScope] = useState<string>(DATASET_ALL)
  const [folderPath, setFolderPath] = useState<string | null>(null)
  const [folderPickerOpen, setFolderPickerOpen] = useState(false)
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const selectedDatasetId = datasetScope === DATASET_ALL ? undefined : datasetScope
  const [docStats, setDocStats] = useState<DocumentStats | null>(null)
  const [docStatsLoading, setDocStatsLoading] = useState(false)
  const docStatsSeqRef = useRef(0)

  // Init UI state from URL so filters are shareable/bookmarkable.
  useEffect(() => {
    if (didInitFromUrlRef.current) return
    didInitFromUrlRef.current = true

    const params = new URLSearchParams(searchParams?.toString?.() || '')

    const tab = params.get('tab')
    if (tab === 'documents' || tab === 'retrieval' || tab === 'settings') setActiveTab(tab)

    const view = params.get('view')
    if (view === 'grid' || view === 'list') setViewMode(view)

    const q = params.get('q')
    if (typeof q === 'string' && q.trim()) setDocFilter(q)

    const status = params.get('status')
    if (status === 'all' || status === 'completed' || status === 'processing' || status === 'failed' || status === 'quarantined') {
      setStatusFilter(status)
    }

    const lifecycle = params.get('lifecycle')
    if (lifecycle === 'active' || lifecycle === 'archived' || lifecycle === 'disabled' || lifecycle === 'all') {
      setLifecycleFilter(lifecycle)
    }

    const dataset = params.get('dataset')
    if (dataset && dataset.trim()) setDatasetScope(dataset)

    const folder = params.get('folder')
    if (folder && folder.trim() && dataset && dataset.trim() && dataset !== DATASET_ALL) setFolderPath(folder.trim())

    const orderBy = params.get('order_by')
    if (orderBy === 'created_at' || orderBy === 'filename' || orderBy === 'file_size') setSortKey(orderBy)

    const orderDir = params.get('order_dir')
    if (orderDir === 'asc' || orderDir === 'desc') setSortDir(orderDir)
  }, [searchParams])

  // Keep URL in sync (avoid window scroll; AppFrame handles internal scroll only).
  useEffect(() => {
    if (!didInitFromUrlRef.current) return
    const params = new URLSearchParams()
    if (activeTab !== 'documents') params.set('tab', activeTab)
    if (viewMode !== 'grid') params.set('view', viewMode)
    if (docFilter.trim()) params.set('q', docFilter.trim())
    if (statusFilter !== 'all') params.set('status', statusFilter)
    if (lifecycleFilter !== 'active') params.set('lifecycle', lifecycleFilter)
    if (datasetScope !== DATASET_ALL) params.set('dataset', datasetScope)
    if (datasetScope !== DATASET_ALL && folderPath) params.set('folder', folderPath)
    if (sortKey !== 'created_at') params.set('order_by', sortKey)
    if (sortDir !== 'desc') params.set('order_dir', sortDir)
    const qs = params.toString()
    const nextUrl = qs ? `/knowledge?${qs}` : '/knowledge'
    if (lastUrlRef.current === nextUrl) return
    lastUrlRef.current = nextUrl
    router.replace(nextUrl, { scroll: false })
  }, [activeTab, viewMode, docFilter, statusFilter, lifecycleFilter, datasetScope, folderPath, sortKey, sortDir, router])

  // PageBody is an internal scroll container; on tab switches keep the top anchored.
  useEffect(() => {
    const id = window.requestAnimationFrame(() => {
      const el = document.querySelector<HTMLElement>('[data-page-scroll-container="true"]')
      el?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
    })
    return () => window.cancelAnimationFrame(id)
  }, [activeTab])

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

  const [pageScrollEl, setPageScrollEl] = useState<HTMLElement | null>(null)

  useEffect(() => {
    setPageScrollEl(document.querySelector<HTMLElement>('[data-page-scroll-container="true"]'))
  }, [])

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
    getScrollElement: () => pageScrollEl,
    estimateSize: () => 340,
    overscan: 6,
  })

  const docsTableVirtualizer = useVirtualizer({
    count: activeTab === 'documents' && viewMode === 'list' ? filteredDocuments.length : 0,
    getScrollElement: () => pageScrollEl,
    estimateSize: () => 72,
    overscan: 10,
    getItemKey: (idx) => filteredDocuments[idx]?.id ?? idx,
  })

  const docsGridVirtualRows = docsGridVirtualizer.getVirtualItems()
  const docsTableVirtualRows = docsTableVirtualizer.getVirtualItems()
  const docsTablePaddingTop = docsTableVirtualRows.length ? docsTableVirtualRows[0].start : 0
  const docsTablePaddingBottom = docsTableVirtualRows.length
    ? docsTableVirtualizer.getTotalSize() - docsTableVirtualRows[docsTableVirtualRows.length - 1].end
    : 0

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

  const getStatusBadge = (status: string): { status: StatusBadgeStatus; label: string } => {
    switch (status) {
      case "completed":
        return { status: "completed", label: "已就绪" }
      case "failed":
        return { status: "failed", label: "失败" }
      case "quarantined":
        return { status: "quarantined", label: "已隔离" }
      case "processing":
        return { status: "processing", label: "处理中" }
      case "pending":
        return { status: "pending", label: "等待" }
      default:
        return { status: "pending", label: "等待" }
    }
  }

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

  const statusBarClassName = (status: StatusBadgeStatus) => {
    if (status === "completed") return "bg-success"
    if (status === "failed") return "bg-destructive"
    if (status === "quarantined") return "bg-warning"
    if (status === "processing") return "bg-info"
    if (status === "pending") return "bg-muted-foreground/40"
    return "bg-muted-foreground/40"
  }

  return (
    <AppFrame>
        <WorkbenchScaffold
          title="知识库管理"
          icon={Database}
          iconColor="text-primary"
          description="管理您的文档资产，构建专属知识大脑"
          leftPanel={<KnowledgeSidebar />}
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

              {activeTab === 'documents' && (
                <div className="flex items-center gap-2">
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
                </div>
              )}
            </div>
          }
          bodyClassName="pt-6 scroll-smooth"
        >
	          {/* 文档列表 */}
	          {activeTab === 'documents' && (
	            <div className="animate-in fade-in slide-in-from-bottom-4 duration-300 motion-reduce:animate-none motion-reduce:transition-none">
              {isLoading && documents.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
                  <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none mb-3" />
                  <p className="text-sm">正在加载文档库...</p>
                </div>
              ) : documents.length === 0 ? (
                <div className="py-10">
                  <EmptyState
                    icon={Upload}
                    title="知识库空空如也"
                    description={
                      <span className="text-muted-foreground">
                        上传您的第一份文档，MimirQ 将自动解析并构建专属知识索引。
                        <br />
                        支持 PDF, TXT, Markdown, Excel, Word 等常见格式。
                      </span>
                    }
                    className="bg-transparent shadow-none"
                  >
                    <label>
                      <Button size="lg" className="gap-2 rounded-xl shadow-sm" asChild>
                        <span>
                          <Upload className="w-5 h-5" />
                          立即上传文档
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
                  </EmptyState>
                </div>
              ) : (
                <>
                  {/* Filters */}
                  <div className="mb-5 flex flex-col lg:flex-row lg:items-center gap-3 justify-between">
                    <div className="flex w-full lg:max-w-2xl flex-col sm:flex-row gap-3">
	                      <SearchInput
	                        value={docFilter}
	                        onValueChange={setDocFilter}
	                        placeholder="搜索文档名称…"
	                        containerClassName="w-full"
	                        inputClassName="h-10 rounded-xl border-border/60 bg-background/60 backdrop-blur-sm placeholder:text-muted-foreground/60 focus:bg-background focus:border-primary/40"
	                      />

                      <Select
                        value={datasetScope}
                        onValueChange={(v) => {
                          setDatasetScope(v)
                          setFolderPath(null)
                          setFolderPickerOpen(false)
                        }}
                      >
                        <SelectTrigger
                          className="h-10 w-full sm:w-[220px] rounded-xl border-border/60 bg-background/60 backdrop-blur-sm"
                          disabled={datasetsLoading}
                          aria-label="筛选数据集"
                        >
                          <SelectValue placeholder={datasetsLoading ? '加载数据集…' : '全部数据集'} />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={DATASET_ALL}>全部数据集</SelectItem>
                          {datasets.map((ds) => (
                            <SelectItem key={ds.id} value={ds.id}>
                              {ds.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>

                      {datasetScope !== DATASET_ALL ? (
                        <Popover open={folderPickerOpen} onOpenChange={setFolderPickerOpen}>
                          <PopoverTrigger asChild>
                            <Button
                              type="button"
                              variant="outline"
                              className="h-10 w-full sm:w-[220px] rounded-xl border-border/60 bg-background/60 backdrop-blur-sm justify-between"
                              aria-label="按目录筛选"
                            >
                              <span className="min-w-0 flex items-center gap-2">
                                <Folder className="h-4 w-4 text-muted-foreground" />
                                <span className="truncate" title={folderPath || '全部目录'}>
                                  {folderPath ? folderPath.split('/').slice(-1)[0] : '全部目录'}
                                </span>
                              </span>
                              <ChevronDown className="h-4 w-4 text-muted-foreground" />
                            </Button>
                          </PopoverTrigger>
                          <PopoverContent align="start" className="w-[380px] p-3">
                            {selectedDatasetId ? (
                              <DatasetFolderTree
                                datasetId={selectedDatasetId}
                                lifecycle={lifecycleFilter}
                                selectedPath={folderPath}
                                onSelect={(path) => {
                                  setFolderPath(path)
                                  setFolderPickerOpen(false)
                                }}
                              />
                            ) : (
                              <div className="text-xs text-muted-foreground">请选择数据集</div>
                            )}
                          </PopoverContent>
                        </Popover>
                      ) : null}

                      <Select value={lifecycleFilter} onValueChange={(v) => setLifecycleFilter(v as DocLifecycleFilter)}>
                        <SelectTrigger
                          className="h-10 w-full sm:w-[180px] rounded-xl border-border/60 bg-background/60 backdrop-blur-sm"
                          aria-label="筛选生命周期"
                        >
                          <SelectValue placeholder="生命周期" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="active">启用中</SelectItem>
                          <SelectItem value="disabled">已禁用</SelectItem>
                          <SelectItem value="archived">已归档</SelectItem>
                          <SelectItem value="all">全部</SelectItem>
                        </SelectContent>
                      </Select>

                      <Select
                        value={`${sortKey}:${sortDir}`}
                        onValueChange={(value) => {
                          const [k, d] = String(value || '').split(':')
                          if (k === 'created_at' || k === 'filename' || k === 'file_size') setSortKey(k)
                          if (d === 'asc' || d === 'desc') setSortDir(d)
                        }}
                      >
                        <SelectTrigger
                          className="h-10 w-full sm:w-[200px] rounded-xl border-border/60 bg-background/60 backdrop-blur-sm"
                          aria-label="排序"
                        >
                          <SelectValue placeholder="排序" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="created_at:desc">最新上传</SelectItem>
                          <SelectItem value="created_at:asc">最早上传</SelectItem>
                          <SelectItem value="filename:asc">文件名 A-Z</SelectItem>
                          <SelectItem value="filename:desc">文件名 Z-A</SelectItem>
                          <SelectItem value="file_size:desc">大小 从大到小</SelectItem>
                          <SelectItem value="file_size:asc">大小 从小到大</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      {(
                        [
                          { key: 'all', label: '全部', count: totalDocs },
                          { key: 'completed', label: '已就绪', count: completedDocsValue },
                          { key: 'processing', label: '处理中', count: processingDocsValue },
                          { key: 'failed', label: '失败', count: failedDocsValue },
                          { key: 'quarantined', label: '隔离', count: quarantinedDocsValue },
                        ] as const
                      ).map((item) => (
                        <button
                          key={item.key}
                          type="button"
                          onClick={() => setStatusFilter(item.key)}
                          className={cn(
                            "h-9 px-3 rounded-full border text-xs font-semibold  transition-colors focus-ring",
                            statusFilter === item.key
                              ? "bg-primary/10 border-primary/40 text-primary"
                              : "bg-background/60 border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/30"
                          )}
                          aria-pressed={statusFilter === item.key}
                        >
                          {item.label}
                          <span className="ml-1 tabular-nums text-[11px] opacity-80">{item.count}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Bulk actions */}
                  {selectedDocIds.length > 0 ? (
                    <div className="mb-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3 rounded-xl border border-border/60 bg-background/60 backdrop-blur-sm px-4 py-3">
                      <div className="text-sm text-foreground">
                        已选 <span className="font-mono tabular-nums">{selectedDocIds.length}</span> 项
                      </div>
                      <div className="flex flex-wrap items-center gap-2 justify-end">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          onClick={toggleSelectAllVisible}
                        >
                          {allVisibleSelected ? '取消全选' : '全选当前列表'}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          onClick={() => setSelectedDocIds([])}
                        >
                          清除选择
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          onClick={() => void runBatchReingest()}
                          disabled={batchDeleting || batchLifecycleWorking || batchReingestWorking}
                        >
                          {batchReingestWorking ? '重新入库中…' : '重新入库'}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          onClick={() => void runBatchLifecycle('disable')}
                          disabled={batchDeleting || batchLifecycleWorking || !anySelectedEnabled}
                        >
                          禁用
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          onClick={() => void runBatchLifecycle('enable')}
                          disabled={batchDeleting || batchLifecycleWorking || !anySelectedDisabled}
                        >
                          启用
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          onClick={() => void runBatchLifecycle('archive')}
                          disabled={batchDeleting || batchLifecycleWorking || !anySelectedNotArchived}
                        >
                          归档
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          onClick={() => void runBatchLifecycle('unarchive')}
                          disabled={batchDeleting || batchLifecycleWorking || !anySelectedArchived}
                        >
                          取消归档
                        </Button>
                        <Button
                          type="button"
                          variant="destructive"
                          size="sm"
                          className="rounded-xl"
                          onClick={() => setBatchDeleteOpen(true)}
                          disabled={batchDeleting || batchLifecycleWorking}
                        >
                          批量删除
                        </Button>
                      </div>
                    </div>
                  ) : null}

                  <Dialog open={batchDeleteOpen} onOpenChange={setBatchDeleteOpen}>
                    <DialogContent className="max-w-md">
                      <DialogHeader>
                        <DialogTitle>确认删除</DialogTitle>
                        <DialogDescription>
                          将删除已选中的 <span className="font-mono tabular-nums">{selectedDocIds.length}</span> 份文档，此操作不可撤销。
                        </DialogDescription>
                      </DialogHeader>
                      <div className="flex items-center justify-end gap-2">
                        <Button type="button" variant="outline" onClick={() => setBatchDeleteOpen(false)} disabled={batchDeleting}>
                          取消
                        </Button>
                        <Button type="button" variant="destructive" onClick={confirmBatchDelete} disabled={batchDeleting || selectedDocIds.length === 0}>
                          {batchDeleting ? '删除中…' : '确认删除'}
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>

                  {filteredDocuments.length === 0 ? (
                    <div className="py-10">
                      <EmptyState
                        icon={Filter}
                        title="未找到匹配的文档"
                        description={
                          <span className="text-muted-foreground">
                            尝试调整筛选条件，或清空筛选后重新查看全部文档。
                          </span>
                        }
                        className="bg-transparent shadow-none"
                      >
                        <Button
                          type="button"
                          variant="outline"
                          className="rounded-xl"
                          onClick={() => {
                            setDocFilter('')
                            setStatusFilter('all')
                            setLifecycleFilter('active')
                          }}
                        >
                          清空筛选
                        </Button>
                      </EmptyState>
                    </div>
	                  ) : viewMode === 'grid' ? (
	                    <div
	                      role="list"
	                      aria-label="文档列表"
	                      style={{
	                        height: `${docsGridVirtualizer.getTotalSize()}px`,
	                        width: '100%',
	                        position: 'relative',
	                      }}
	                    >
	                      {docsGridVirtualRows.map((virtualRow) => {
	                        const cols = Math.max(1, docGridColumns)
	                        const startIndex = virtualRow.index * cols
	                        const rowDocs = filteredDocuments.slice(startIndex, startIndex + cols)
	                        const isLastRow = virtualRow.index === docGridRowCount - 1
	
	                        return (
	                          <div
	                            key={virtualRow.key}
	                            data-index={virtualRow.index}
	                            ref={docsGridVirtualizer.measureElement}
	                            role="presentation"
	                            style={{
	                              position: 'absolute',
	                              top: 0,
	                              left: 0,
	                              width: '100%',
	                              transform: `translateY(${virtualRow.start}px)`,
	                            }}
	                            className={isLastRow ? undefined : 'pb-5'}
	                          >
	                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-5">
	                              {rowDocs.map((doc) => {
	                                const badge = getStatusBadge(doc.status)
	                                return (
	                                  <div key={doc.id} role="listitem">
	                                    <DocumentCard
	                                      doc={doc}
	                                      statusBadge={badge}
	                                      statusBarClassName={statusBarClassName(badge.status)}
	                                      onDelete={deleteDocument}
	                                      selected={selectedSet.has(doc.id)}
	                                      onToggleSelect={() => toggleDocSelection(doc.id)}
	                                    />
	                                  </div>
	                                )
	                              })}
	                            </div>
	                          </div>
	                        )
	                      })}
	                    </div>
	                  ) : (
	                    <Panel padding="none" className="rounded-xl overflow-hidden">
	                      <table className="w-full text-sm text-left">
                        <thead className="text-xs text-muted-foreground uppercase bg-muted/30 border-b border-border/60">
                          <tr>
                            <th className="px-4 py-4 font-medium w-10">
                              <input
                                type="checkbox"
                                className="h-4 w-4 rounded border-border/60 text-primary focus-ring"
                                checked={allVisibleSelected}
                                onChange={toggleSelectAllVisible}
                                aria-label="全选当前列表"
                              />
                            </th>
                            <th className="px-6 py-4 font-medium">文档名称</th>
                            <th className="px-6 py-4 font-medium">标签</th>
                            <th className="px-6 py-4 font-medium">状态</th>
                            <th className="px-6 py-4 font-medium">分块</th>
                            <th className="px-6 py-4 font-medium">大小</th>
                            <th className="px-6 py-4 font-medium">上传时间</th>
                            <th className="px-6 py-4 font-medium text-right">操作</th>
                          </tr>
	                        </thead>
	                        <tbody className="divide-y divide-border/60">
	                          {docsTablePaddingTop > 0 ? (
	                            <tr aria-hidden="true">
	                              <td colSpan={8} className="p-0" style={{ height: `${docsTablePaddingTop}px` }} />
	                            </tr>
	                          ) : null}

	                          {docsTableVirtualRows.map((virtualRow) => {
	                            const doc = filteredDocuments[virtualRow.index]
	                            if (!doc) return null
	                            const badge = getStatusBadge(doc.status)
	                            const fileType = getFileTypeMeta(doc)
	                            const TypeIcon = fileType.icon
	                            const userTags = getUserTagsFromDocument(doc)
	                            return (
	                              <tr
	                                key={virtualRow.key}
	                                data-index={virtualRow.index}
	                                ref={docsTableVirtualizer.measureElement}
	                                className="hover:bg-muted/20 transition-colors group"
	                              >
	                                <td className="px-4 py-4 align-top">
	                                  <input
	                                    type="checkbox"
	                                    className="h-4 w-4 rounded border-border/60 text-primary focus-ring"
	                                    checked={selectedSet.has(doc.id)}
	                                    onChange={() => toggleDocSelection(doc.id)}
	                                    aria-label={`选择文档 ${doc.filename}`}
	                                  />
	                                </td>
	                                <td className="px-6 py-4 font-medium text-foreground flex items-center gap-3">
	                                  <div className={cn("p-2 rounded-lg border", fileType.bg, fileType.border, fileType.color)}>
	                                    <TypeIcon className="w-4 h-4" />
	                                  </div>
	                                  <div className="min-w-0 flex items-center gap-2">
	                                    <span className="truncate max-w-[200px]" title={doc.filename}>{doc.filename}</span>
	                                    <span
	                                      className={cn(
	                                        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ",
	                                        fileType.bg,
	                                        fileType.border,
	                                        fileType.color
	                                      )}
	                                      title={fileType.label}
	                                    >
	                                      {fileType.label}
	                                    </span>
	                                  </div>
	                                </td>
	                                <td className="px-6 py-4 align-top">
	                                  {userTags.length ? (
	                                    <DocumentTags tags={userTags} max={3} dense />
	                                  ) : (
	                                    <span className="text-xs text-muted-foreground">—</span>
	                                  )}
	                                </td>
	                                <td className="px-6 py-4">
	                                  <StatusBadge status={badge.status} label={badge.label} />
	                                </td>
	                                <td className="px-6 py-4 text-muted-foreground">{doc.chunk_count || '-'}</td>
	                                <td className="px-6 py-4 text-muted-foreground font-mono text-xs">{formatFileSize(doc.file_size)}</td>
	                                <td className="px-6 py-4 text-muted-foreground">{formatDate(doc.created_at)}</td>
	                                <td className="px-6 py-4 text-right flex items-center justify-end gap-2">
	                                  <DocumentDetailDialog 
	                                    document={doc} 
	                                    trigger={
	                                      <IconButton
	                                        label="预览内容"
	                                        variant="ghost"
	                                        className="h-9 w-9 text-muted-foreground hover:text-primary hover:bg-muted opacity-0 group-hover:opacity-100"
	                                      >
	                                        <Eye className="w-4 h-4" />
	                                      </IconButton>
	                                    }
	                                  />
	                                  <IconButton
	                                    label="删除文档"
	                                    variant="ghost"
	                                    className="h-9 w-9 text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100"
	                                    onClick={() => deleteDocument(doc.id)}
	                                  >
	                                    <Trash2 className="w-4 h-4" />
	                                  </IconButton>
	                                </td>
	                              </tr>
	                            )
	                          })}

	                          {docsTablePaddingBottom > 0 ? (
	                            <tr aria-hidden="true">
	                              <td colSpan={8} className="p-0" style={{ height: `${docsTablePaddingBottom}px` }} />
	                            </tr>
	                          ) : null}
	                        </tbody>
	                      </table>
	                    </Panel>
                  )}
                </>
              )}
            </div>
          )}

		          {/* 检索测试 */}
		          {activeTab === 'retrieval' && (
		            <div className="max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-2 duration-300 motion-reduce:animate-none motion-reduce:transition-none space-y-4">
                <div className="xl:hidden">
                  <RetrievePreviewPanel selectedDatasetId={selectedDatasetId} />
                </div>

              <Panel padding="none" className="rounded-2xl p-6 text-left bg-background/60 border border-border/60">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <BarChart3 className="h-4 w-4 text-primary" />
                      <h4 className="text-sm font-semibold text-foreground">Index Audit</h4>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      数据集级索引一致性检查（Postgres ↔ 向量库；仅 owner/admin）
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      当前数据集：<span className="font-mono">{selectedDatasetId || '未选择'}</span>
                    </p>
                  </div>

                  <Button
                    type="button"
                    variant="outline"
                    className="h-9 rounded-xl border-border/60 bg-background/60 text-muted-foreground hover:bg-background gap-2"
                    onClick={handleRunIndexAudit}
                    disabled={!selectedDatasetId || indexAuditLoading}
                  >
                    {indexAuditLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <RefreshCw className="h-4 w-4" />
                    )}
                    运行
                  </Button>
                </div>

                {indexAuditError && (
                  <div className="mt-4 rounded-xl border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive">
                    {indexAuditError}
                  </div>
                )}

                {indexAudit && (
                  <div className="mt-4 space-y-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                        <div className="text-xs text-muted-foreground">Vector Backend</div>
                        <div className="mt-1 text-xs font-mono text-foreground/90">{indexAudit.vector_backend || '-'}</div>
                      </div>
                      <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                        <div className="text-xs text-muted-foreground">Active Docs</div>
                        <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.active_documents}</div>
                      </div>
                      <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                        <div className="text-xs text-muted-foreground">Active Chunks</div>
                        <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.active_chunks}</div>
                      </div>
                      <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                        <div className="text-xs text-muted-foreground">DB Missing vector_id</div>
                        <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.vector_id_missing}</div>
                      </div>
                      <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                        <div className="text-xs text-muted-foreground">Checked IDs</div>
                        <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.vector_ids_checked}</div>
                      </div>
                      <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                        <div className="text-xs text-muted-foreground">Missing In Backend</div>
                        <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.vector_ids_missing_in_backend}</div>
                      </div>
                      <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                        <div className="text-xs text-muted-foreground">Milvus Sampled</div>
                        <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.milvus_ids_sampled}</div>
                      </div>
                      <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                        <div className="text-xs text-muted-foreground">Orphan Sample</div>
                        <div className="mt-1 text-lg font-semibold text-foreground">
                          {(indexAudit.milvus_orphan_ids_sample || []).length}
                        </div>
                      </div>
                    </div>

                    {(indexAudit.vector_ids_missing_in_backend_sample || []).length > 0 ? (
                      <div>
                        <div className="text-xs font-medium text-foreground/80">Missing in Vector Backend (sample)</div>
                        <pre className="mt-2 max-h-48 overflow-auto rounded-xl border border-border/60 bg-muted/20 p-3 text-xs font-mono text-muted-foreground">
                          {(indexAudit.vector_ids_missing_in_backend_sample || []).join('\n')}
                        </pre>
                      </div>
                    ) : null}

                    {(indexAudit.milvus_orphan_ids_sample || []).length > 0 ? (
                      <div>
                        <div className="text-xs font-medium text-foreground/80">Orphan Vector IDs (sample)</div>
                        <pre className="mt-2 max-h-48 overflow-auto rounded-xl border border-border/60 bg-muted/20 p-3 text-xs font-mono text-muted-foreground">
                          {(indexAudit.milvus_orphan_ids_sample || []).join('\n')}
                        </pre>
                      </div>
                    ) : null}
                  </div>
                )}
              </Panel>
            </div>
          )}

	          {/* 设置 */}
	          {activeTab === 'settings' && (
	            <div className="max-w-3xl mx-auto animate-in fade-in slide-in-from-bottom-2 duration-300 motion-reduce:animate-none motion-reduce:transition-none">
              <Panel padding="none" className="rounded-xl overflow-hidden">
                <div className="p-6 border-b border-border/60 bg-muted/20">
                  <h3 className="text-lg font-bold text-foreground">知识库参数配置</h3>
                  <p className="text-sm text-muted-foreground mt-1">
                    调整 Embedding 模型、检索策略及相似度阈值
                  </p>
                </div>

                <div className="p-8 space-y-8">
                  {/* Embedding 模型 */}
                  <div className="space-y-3">
                    <label className="text-sm font-semibold text-foreground">
                      Embedding 模型
                    </label>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      {['text-embedding-v3', 'text-embedding-3-small', 'bge-large-zh'].map((model) => (
                        <div key={model} className="relative">
                          <input type="radio" name="model" id={model} className="peer sr-only" defaultChecked={model === 'text-embedding-v3'} />
                          <label
                            htmlFor={model}
                            className="flex flex-col p-4 border-2 border-border/60 rounded-xl cursor-pointer transition-colors hover:border-border peer-checked:border-primary peer-checked:bg-primary/10"
                          >
                            <span className="font-medium text-sm text-foreground">{model}</span>
                            <span className="text-xs text-muted-foreground mt-1">768 维 / 中英支持</span>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="h-px bg-border/60" />

                  {/* 检索模式 */}
                  <div className="space-y-3">
                    <label className="text-sm font-semibold text-foreground">
                      检索模式
                    </label>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {[
                        { value: 'vector', label: '向量检索', desc: '基于语义相似度，适合模糊匹配', icon: Zap },
                        { value: 'fulltext', label: '全文检索', desc: '基于关键词匹配，适合专有名词', icon: FileText },
                        { value: 'hybrid', label: '混合检索', desc: '向量 + 全文加权，效果最佳', icon: Layers },
                      ].map((mode) => (
                        <div key={mode.value} className="relative">
                          <input type="radio" name="retrieval_mode" id={mode.value} className="peer sr-only" defaultChecked={mode.value === 'hybrid'} />
                          <label
                            htmlFor={mode.value}
                            className="flex flex-col p-4 border-2 border-border/60 rounded-xl cursor-pointer transition-colors hover:border-border peer-checked:border-primary peer-checked:bg-primary/10 h-full"
                          >
                            <div className="flex items-center gap-2 mb-2">
                              <mode.icon className="w-4 h-4 text-primary" />
                              <span className="font-medium text-sm text-foreground">{mode.label}</span>
                            </div>
                            <span className="text-xs text-muted-foreground leading-relaxed">
                              {mode.desc}
                            </span>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="h-px bg-border/60" />

                  {/* 阈值参数 */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div className="space-y-3">
                      <div className="flex justify-between">
                         <label className="text-sm font-semibold text-foreground">召回数量 (Top K)</label>
                         <span className="text-sm font-mono text-primary">5</span>
                      </div>
                      <input type="range" min="1" max="20" defaultValue="5" className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary" />
                      <p className="text-xs text-muted-foreground">
                        单次检索返回的最大片段数，建议 3-8 之间
                      </p>
                    </div>

                    <div className="space-y-3">
                      <div className="flex justify-between">
                         <label className="text-sm font-semibold text-foreground">相似度阈值</label>
                         <span className="text-sm font-mono text-primary">0.7</span>
                      </div>
                      <input type="range" min="0" max="1" step="0.1" defaultValue="0.7" className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary" />
                      <p className="text-xs text-muted-foreground">
                        过滤低相关度的结果，值越大匹配越精准
                      </p>
                    </div>
                  </div>

                  <div className="h-px bg-border/60" />

                  {/* Connectors */}
                  <div className="space-y-3">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <label className="text-sm font-semibold text-foreground">Connectors 导入任务</label>
                        <p className="text-xs text-muted-foreground mt-1">
                          用于批量 URL 导入/同步；仅展示你有写权限的数据集的运行记录。
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          className="gap-2"
                          onClick={() => void loadConnectorRuns({ datasetId: selectedDatasetId })}
                          disabled={connectorRunsLoading}
                        >
                          <RefreshCw className={cn('w-4 h-4', connectorRunsLoading && 'animate-spin motion-reduce:animate-none')} />
                          刷新
                        </Button>
                      </div>
                    </div>

                    {connectorRunsLoading ? (
                      <div className="rounded-xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
                        正在加载导入任务...
                      </div>
                    ) : connectorRuns.length === 0 ? (
                      <div className="rounded-xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
                        暂无导入任务。可通过顶部“URL 批量导入”创建。
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {connectorRuns.map((run) => {
                          const badge = getConnectorRunBadge(run.status)
                          const stats = (run.stats || {}) as any
                          const created = Number(stats.created || 0)
                          const failed = Number(stats.failed || 0)
                          const totalUrls = Number(stats.total_urls || stats.discovered || 0)
                          const processedUrls = Number(stats.processed_urls || stats.cursor || 0)
                          const progressPct =
                            totalUrls > 0
                              ? Math.max(0, Math.min(100, Math.round((processedUrls / totalUrls) * 100)))
                              : 0
                          const errors: any[] = Array.isArray(stats.errors) ? stats.errors : []
                          const errorGroups: any[] = Array.isArray(stats.error_groups) ? stats.error_groups : []
                          const isActive = run.status === 'pending' || run.status === 'running'
                          const canRetryFailed = !isActive && failed > 0
                          const canResume =
                            !isActive &&
                            String(run.connector_id || '').toLowerCase() === 'url_batch' &&
                            String(run.status || '').toLowerCase() === 'cancelled' &&
                            totalUrls > processedUrls
                          return (
                            <div
                              key={run.id}
                              className="rounded-xl border border-border/60 bg-background/60 p-4"
                            >
                              <div className="flex items-start justify-between gap-4">
                                <div className="min-w-0">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <StatusBadge status={badge.status} label={badge.label} dense />
                                    <span className="text-xs font-mono text-muted-foreground truncate">{run.id}</span>
                                  </div>
                                  <div className="mt-1 text-xs text-muted-foreground">
                                    {formatDate(run.created_at)} · {run.connector_id} · dataset {run.dataset_id || '-'}
                                  </div>
                                  <div className="mt-2 text-xs text-foreground/80">
                                    created <span className="font-mono">{created}</span> · failed{' '}
                                    <span className={cn('font-mono', failed > 0 && 'text-destructive')}>{failed}</span>
                                  </div>
                                  {totalUrls > 0 ? (
                                    <div className="mt-2">
                                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                                        <span>progress</span>
                                        <span className="font-mono">
                                          {processedUrls}/{totalUrls} ({progressPct}%)
                                        </span>
                                      </div>
	                                      <div className="mt-1 h-2 w-full rounded-full bg-muted/60 overflow-hidden">
	                                        <div
	                                          className={cn(
	                                            'h-2 w-full rounded-full origin-left transition-transform duration-200 ease-out motion-reduce:transition-none',
	                                            failed > 0 ? 'bg-destructive/70' : 'bg-primary/70'
	                                          )}
	                                          style={{ transform: `scaleX(${progressPct / 100})` }}
	                                        />
	                                      </div>
                                    </div>
                                  ) : null}
                                  {run.error_message ? (
                                    <div className="mt-2 text-xs text-destructive">{run.error_message}</div>
                                  ) : null}
                                  {errorGroups.length > 0 ? (
                                    <div className="mt-2 text-xs text-muted-foreground">
                                      <div className="font-medium text-foreground/80">错误聚类：</div>
                                      <div className="mt-1 space-y-1">
                                        {errorGroups.slice(0, 3).map((g, idx) => (
                                          <div key={idx} className="font-mono truncate">
                                            [{String(g?.code || 'error')}] x{Number(g?.count || 0)} —{' '}
                                            {String(g?.error || '').slice(0, 140)}
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  ) : null}
                                  {errors.length > 0 ? (
                                    <div className="mt-2 text-xs text-muted-foreground">
                                      <div className="font-medium text-foreground/80">错误示例：</div>
                                      <div className="mt-1 space-y-1">
                                        {errors.slice(0, 3).map((e, idx) => (
                                          <div key={idx} className="font-mono truncate">
                                            {String(e?.url || '').slice(0, 80)} —{' '}
                                            {e?.code ? `[${String(e.code)}] ` : ''}
                                            {String(e?.error || '').slice(0, 120)}
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  ) : null}

                                  {Array.isArray((run as any).documents) && (run as any).documents.length > 0 ? (
                                    <div className="mt-3">
                                      <button
                                        type="button"
                                        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground/80"
                                        onClick={() =>
                                          setExpandedConnectorRunId((prev) => (prev === run.id ? null : run.id))
          }
        >
                                        {expandedConnectorRunId === run.id ? (
                                          <ChevronDown className="h-4 w-4" />
                                        ) : (
                                          <ChevronRight className="h-4 w-4" />
                                        )}
                                        产物列表（{(run as any).documents.length}）
                                      </button>

                                      {expandedConnectorRunId === run.id ? (
                                        <div className="mt-2 rounded-lg border border-border/60 bg-background/40 p-3">
                                          <div className="flex items-center justify-between gap-2">
                                            <div className="text-xs font-medium text-foreground/80">Documents</div>
                                            <Button
                                              type="button"
                                              variant="outline"
                                              size="sm"
                                              className="h-7 px-2 gap-1.5"
                                              onClick={() => {
                                                const ids = (run as any).documents
                                                  .map((d: any) => String(d?.document_id || '').trim())
                                                  .filter(Boolean)
                                                void copyText(ids.join('\n'), '已复制文档 ID 列表')
                                              }}
                                            >
                                              <Copy className="h-3.5 w-3.5" />
                                              复制 IDs
                                            </Button>
                                          </div>
                                          <div className="mt-2 space-y-1">
                                            {(run as any).documents.slice(0, 15).map((d: any) => (
                                              <div key={String(d?.document_id)} className="flex items-start justify-between gap-3">
                                                <div className="min-w-0">
                                                  <div className="text-[11px] font-mono text-foreground/90 truncate">
                                                    {String(d?.document_id || '')}
                                                  </div>
                                                  {d?.source_ref ? (
                                                    <div className="mt-0.5 text-[10px] text-muted-foreground font-mono truncate">
                                                      {String(d.source_ref)}
                                                    </div>
                                                  ) : null}
                                                </div>
                                                <div className="shrink-0 text-[10px] font-mono rounded-full border border-border/60 bg-background px-2 py-0.5">
                                                  {String(d?.status || 'created')}
                                                </div>
                                              </div>
                                            ))}
                                            {(run as any).documents.length > 15 ? (
                                              <div className="text-[10px] text-muted-foreground">
                                                …(+{(run as any).documents.length - 15})
                                              </div>
                                            ) : null}
                                          </div>
                                        </div>
                                      ) : null}
                                    </div>
                                  ) : null}
                                </div>

                                <div className="flex flex-col items-end gap-2">
                                  {isActive ? (
                                    <AlertDialog>
                                      <AlertDialogTrigger asChild>
                                        <Button variant="outline" className="gap-2">
                                          <X className="w-4 h-4" />
                                          取消
                                        </Button>
                                      </AlertDialogTrigger>
                                      <AlertDialogContent>
                                        <AlertDialogHeader>
                                          <AlertDialogTitle>取消导入任务？</AlertDialogTitle>
                                          <AlertDialogDescription>
                                            将以 best-effort 方式取消该导入任务（run_id：<span className="font-mono">{run.id.slice(0, 8)}</span>）。此操作可能导致部分文件处于未完成状态。
                                          </AlertDialogDescription>
                                        </AlertDialogHeader>
                                        <AlertDialogFooter>
                                          <AlertDialogCancel>返回</AlertDialogCancel>
                                          <AlertDialogAction onClick={() => void handleCancelConnectorRun(run.id)}>取消任务</AlertDialogAction>
                                        </AlertDialogFooter>
                                      </AlertDialogContent>
                                    </AlertDialog>
                                  ) : null}
                                  {canResume ? (
                                    <AlertDialog>
                                      <AlertDialogTrigger asChild>
                                        <Button variant="outline" className="gap-2">
                                          <Play className="w-4 h-4" />
                                          续跑
                                        </Button>
                                      </AlertDialogTrigger>
                                      <AlertDialogContent>
                                        <AlertDialogHeader>
                                          <AlertDialogTitle>续跑导入任务？</AlertDialogTitle>
                                          <AlertDialogDescription>
                                            将从上次 cursor 位置创建一个新的导入任务（best-effort）。run_id：<span className="font-mono">{run.id.slice(0, 8)}</span>
                                          </AlertDialogDescription>
                                        </AlertDialogHeader>
                                        <AlertDialogFooter>
                                          <AlertDialogCancel>返回</AlertDialogCancel>
                                          <AlertDialogAction onClick={() => void handleResumeConnectorRun(run.id)}>续跑</AlertDialogAction>
                                        </AlertDialogFooter>
                                      </AlertDialogContent>
                                    </AlertDialog>
                                  ) : null}
                                  {canRetryFailed ? (
                                    <AlertDialog>
                                      <AlertDialogTrigger asChild>
                                        <Button variant="outline" className="gap-2">
                                          <RotateCcw className="w-4 h-4" />
                                          只重试失败
                                        </Button>
                                      </AlertDialogTrigger>
                                      <AlertDialogContent>
                                        <AlertDialogHeader>
                                          <AlertDialogTitle>只重试失败项？</AlertDialogTitle>
                                          <AlertDialogDescription>
                                            将创建一个新的导入任务（best-effort），仅处理失败项。run_id：<span className="font-mono">{run.id.slice(0, 8)}</span>
                                          </AlertDialogDescription>
                                        </AlertDialogHeader>
                                        <AlertDialogFooter>
                                          <AlertDialogCancel>返回</AlertDialogCancel>
                                          <AlertDialogAction onClick={() => void handleRetryFailedConnectorRun(run.id)}>创建重试任务</AlertDialogAction>
                                        </AlertDialogFooter>
                                      </AlertDialogContent>
                                    </AlertDialog>
                                  ) : null}
                                </div>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </div>

                <div className="p-6 bg-muted/20 border-t border-border/60 flex justify-end">
                   <Button className="gap-2">
                      <Settings className="w-4 h-4" />
                      保存所有更改
                    </Button>
                </div>
              </Panel>
            </div>
          )}
        </WorkbenchScaffold>
    </AppFrame>
  )
}

// 文档卡片组件
function DocumentCard({
  doc,
  statusBadge,
  statusBarClassName,
  onDelete,
  selected,
  onToggleSelect,
}: {
  doc: Document
  statusBadge: { status: StatusBadgeStatus; label: string }
  statusBarClassName: string
  onDelete: (id: string) => void
  selected: boolean
  onToggleSelect: () => void
}) {
  const parserLabel = doc.metadata?.parser_backend ? getParserLabel(doc.metadata.parser_backend as string) : null
  const userTags = getUserTagsFromDocument(doc)
  const fileType = getFileTypeMeta(doc)
  const TypeIcon = fileType.icon

	  return (
	    <Panel
	      padding="none"
	      className="group relative rounded-2xl overflow-hidden hover:shadow-strong/20 hover:border-primary/30 transition-colors transition-shadow duration-200 motion-reduce:transition-none"
	    >
      {/* 顶部装饰条 */}
      <div className={cn("h-1.5 w-full", statusBarClassName)} />

      {/* Bulk select checkbox */}
      <div
        className={cn(
          "absolute top-3 left-3 z-10 rounded-lg border border-border/60 bg-background/70 backdrop-blur-sm p-1 transition-opacity",
          selected ? "opacity-100" : "opacity-100 lg:opacity-0 lg:group-hover:opacity-100"
        )}
      >
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-border/60 text-primary focus-ring"
          checked={selected}
          onChange={onToggleSelect}
          aria-label={`选择文档 ${doc.filename}`}
        />
      </div>
      
      <div className="p-5 flex-1 flex flex-col">
        <div className="flex items-start justify-between mb-4">
          <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center border", fileType.bg, fileType.border, fileType.color)}>
            <TypeIcon className="w-6 h-6" />
          </div>
          <div className="flex items-center gap-2">
            <div className={cn("px-2.5 py-1 rounded-full text-[10px] font-bold uppercase  border", fileType.bg, fileType.color, fileType.border)}>
              {fileType.label}
            </div>
            {doc.disabled_at ? (
              <div className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase  border border-border/60 bg-muted/60 text-muted-foreground">
                Disabled
              </div>
            ) : null}
            {!doc.disabled_at && doc.archived_at ? (
              <div className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase  border border-border/60 bg-muted/60 text-muted-foreground">
                Archived
              </div>
            ) : null}
            <StatusBadge status={statusBadge.status} label={statusBadge.label} dense />
          </div>
        </div>

        <h3 className="font-semibold text-foreground line-clamp-2 mb-2 min-h-[2.5rem]" title={doc.filename}>
          {doc.filename}
        </h3>

        {userTags.length ? (
          <DocumentTags tags={userTags} max={3} dense className="mb-3" />
        ) : null}

        <div className="space-y-2 mt-auto">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>大小</span>
            <span className="font-mono">{formatFileSize(doc.file_size)}</span>
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>分块</span>
            <span className="font-mono">{doc.chunk_count || '-'}</span>
          </div>
           <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>时间</span>
            <span>{formatDate(doc.created_at)}</span>
          </div>
        </div>
      </div>
      
      {/* 底部操作栏 - Hover 显示 */}
      <div className="px-5 py-3 border-t border-border/60 bg-muted/20 flex items-center justify-between opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity">
         <span className="text-[10px] text-muted-foreground font-medium truncate max-w-[80px]">
           {parserLabel || 'Auto'}
         </span>
         <div className="flex items-center gap-1">
           <DocumentDetailDialog 
             document={doc}
             trigger={
               <IconButton
                 label="预览内容"
                 variant="ghost"
                 className="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted"
                 onClick={(e) => e.stopPropagation()}
               >
                 <Eye className="w-4 h-4" />
               </IconButton>
             }
           />
           <IconButton
             label="删除文档"
             variant="ghost"
             className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
             onClick={(e) => {
               e.stopPropagation()
               onDelete(doc.id)
             }}
           >
             <Trash2 className="w-4 h-4" />
           </IconButton>
         </div>
      </div>

       {/* 进度条 (处理中) */}
       {statusBadge.status === 'processing' && (
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-muted">
            <div 
              className="h-full bg-primary/70 animate-pulse motion-reduce:animate-none" 
              style={{ width: `${doc.processing_progress || 60}%` }} 
            />
          </div>
        )}
    </Panel>
  )
}
