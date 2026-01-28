'use client'

/**
 * 知识库管理页面
 * 优化版：卡片视图、视觉增强、交互优化、深色模式适配
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  Database,
  FileText,
  FileType,
  FileSpreadsheet,
  FileCode,
  Presentation,
  Search,
  Settings,
  Upload,
  Sliders,
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
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
  Sparkles,
  Send,
  Zap,
  Globe,
  Filter,
  X,
} from 'lucide-react'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { EmptyState } from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
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
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { getParserLabel } from '@/lib/parser-options'
import type { Citation, ConnectorRunOut, Dataset, Document, DocumentAccessMode, DocumentStats } from '@/types'
import { connectorApi, datasetApi, documentApi, ragApi } from '@/lib/api-client'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

// Tab 类型
type TabType = 'documents' | 'retrieval' | 'settings'
type ViewMode = 'grid' | 'list'
type DocStatusFilter = 'all' | 'completed' | 'processing' | 'failed' | 'quarantined'
type DocSortKey = 'created_at' | 'filename' | 'file_size'
type DocSortDir = 'asc' | 'desc'

type FileTypeStyle = {
  icon: typeof FileText
  label: string
  color: string
  bg: string
  border: string
}

function getFileTypeStyle(doc: Pick<Document, 'filename' | 'file_type'>): FileTypeStyle {
  const explicit = String(doc.file_type || '').trim().toLowerCase()
  const fromName = String(doc.filename || '')
    .trim()
    .split('.')
    .pop()
    ?.toLowerCase()
    ?.trim() || ''
  const ext = explicit || fromName

  const base = {
    border: 'border-border/60',
  }

  switch (ext) {
    case 'pdf':
      return {
        icon: FileText,
        label: 'PDF',
        color: 'text-red-600 dark:text-red-400',
        bg: 'bg-red-50 dark:bg-red-900/20',
        border: 'border-red-200/60 dark:border-red-500/30',
      }
    case 'docx':
      return {
        icon: FileType,
        label: 'DOCX',
        color: 'text-blue-600 dark:text-blue-400',
        bg: 'bg-blue-50 dark:bg-blue-900/20',
        border: 'border-blue-200/60 dark:border-blue-500/30',
      }
    case 'doc':
      return {
        icon: FileType,
        label: 'DOC',
        color: 'text-indigo-600 dark:text-indigo-400',
        bg: 'bg-indigo-50 dark:bg-indigo-900/20',
        border: 'border-indigo-200/60 dark:border-indigo-500/30',
      }
    case 'ppt':
    case 'pptx':
      return {
        icon: Presentation,
        label: ext.toUpperCase(),
        color: 'text-rose-700 dark:text-rose-300',
        bg: 'bg-rose-50 dark:bg-rose-900/20',
        border: 'border-rose-200/60 dark:border-rose-500/30',
      }
    case 'xlsx':
    case 'xls':
      return {
        icon: FileSpreadsheet,
        label: ext.toUpperCase(),
        color: 'text-emerald-700 dark:text-emerald-300',
        bg: 'bg-emerald-50 dark:bg-emerald-900/20',
        border: 'border-emerald-200/60 dark:border-emerald-500/30',
      }
    case 'csv':
      return {
        icon: FileSpreadsheet,
        label: 'CSV',
        color: 'text-teal-700 dark:text-teal-300',
        bg: 'bg-teal-50 dark:bg-teal-900/20',
        border: 'border-teal-200/60 dark:border-teal-500/30',
      }
    case 'md':
      return {
        icon: FileCode,
        label: 'MD',
        color: 'text-purple-700 dark:text-purple-300',
        bg: 'bg-purple-50 dark:bg-purple-900/20',
        border: 'border-purple-200/60 dark:border-purple-500/30',
      }
    case 'txt':
      return {
        icon: FileText,
        label: 'TXT',
        color: 'text-muted-foreground',
        bg: 'bg-muted/40',
        border: base.border,
      }
    case 'json':
      return {
        icon: FileCode,
        label: 'JSON',
        color: 'text-amber-700 dark:text-amber-300',
        bg: 'bg-amber-50 dark:bg-amber-900/20',
        border: 'border-amber-200/60 dark:border-amber-500/30',
      }
    case 'html':
    case 'htm':
      return {
        icon: FileCode,
        label: 'HTML',
        color: 'text-orange-700 dark:text-orange-300',
        bg: 'bg-orange-50 dark:bg-orange-900/20',
        border: 'border-orange-200/60 dark:border-orange-500/30',
      }
    default:
      return {
        icon: FileIcon,
        label: ext ? ext.toUpperCase() : 'FILE',
        color: 'text-muted-foreground',
        bg: 'bg-muted/40',
        border: base.border,
      }
  }
}

export default function KnowledgePage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const lastUrlRef = useRef<string | null>(null)
  const didInitFromUrlRef = useRef(false)

  const { documents, total, isLoading, uploadDocument, uploadDocumentFromUrl, deleteDocument, loadDocuments } = useDocuments()
  const [activeTab, setActiveTab] = useState<TabType>('documents')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()
  const [docFilter, setDocFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<DocStatusFilter>('all')
  const [sortKey, setSortKey] = useState<DocSortKey>('created_at')
  const [sortDir, setSortDir] = useState<DocSortDir>('desc')
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)
  const DATASET_ALL = '__all__'
  const DATASET_DEFAULT = '__default__'
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetScope, setDatasetScope] = useState<string>(DATASET_ALL)
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

    const dataset = params.get('dataset')
    if (dataset && dataset.trim()) setDatasetScope(dataset)

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
    if (datasetScope !== DATASET_ALL) params.set('dataset', datasetScope)
    if (sortKey !== 'created_at') params.set('order_by', sortKey)
    if (sortDir !== 'desc') params.set('order_dir', sortDir)
    const qs = params.toString()
    const nextUrl = qs ? `/knowledge?${qs}` : '/knowledge'
    if (lastUrlRef.current === nextUrl) return
    lastUrlRef.current = nextUrl
    router.replace(nextUrl, { scroll: false })
  }, [activeTab, viewMode, docFilter, statusFilter, datasetScope, sortKey, sortDir, router])

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
        q: docFilter.trim() || undefined,
        dataset_id: selectedDatasetId,
        order_by: sortKey,
        order_dir: sortDir,
      })
    }, 250)
    return () => window.clearTimeout(t)
  }, [activeTab, statusFilter, docFilter, selectedDatasetId, sortKey, sortDir, loadDocuments])

  // Accurate dashboard stats (server aggregated) - avoids "only 200 items loaded" bias.
  useEffect(() => {
    if (activeTab !== 'documents') return
    const seq = ++docStatsSeqRef.current
    setDocStatsLoading(true)

    const t = window.setTimeout(() => {
      documentApi
        .stats({ q: docFilter.trim() || undefined, dataset_id: selectedDatasetId })
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
  }, [activeTab, docFilter, selectedDatasetId])

  // 检索测试状态
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Citation[]>([])
  const [searchQueryForRetrieval, setSearchQueryForRetrieval] = useState<string>('')
  const [searchMetrics, setSearchMetrics] = useState<Record<string, any> | null>(null)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [isSearching, setIsSearching] = useState(false)

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

    for (const file of Array.from(files)) {
      try {
        await uploadDocument(file)
      } catch (error) {
        console.error('Upload failed:', error)
      }
    }
    e.target.value = ''
  }, [uploadDocument])

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
      toast.error('Please input at least 1 http(s) seed URL (one per line)')
      return
    }

    let auth: any = null
    const authType = webCrawlAuthType
    if (authType === 'cookie') {
      const cookie = webCrawlAuthCookie.trim()
      if (!cookie) {
        toast.error('Please input Cookie')
        return
      }
      auth = { type: 'cookie', cookie }
    } else if (authType === 'bearer') {
      const token = webCrawlAuthToken.trim()
      if (!token) {
        toast.error('Please input Bearer token')
        return
      }
      auth = { type: 'bearer', token }
    } else if (authType === 'basic') {
      const username = webCrawlAuthUsername.trim()
      const password = webCrawlAuthPassword.trim()
      if (!username || !password) {
        toast.error('Please input Basic username/password')
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
      toast.error(formatApiError(err, 'Failed to create web crawl run'))
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
    webCrawlExcludePatterns,
    webCrawlFilename,
    webCrawlIncludePatterns,
    webCrawlMaxDepth,
    webCrawlMaxPages,
    webCrawlSameHostOnly,
    webCrawlStartUrls,
    webCrawlUserAgent,
  ])

  const handleCancelConnectorRun = useCallback(
    async (runId: string) => {
      if (!runId) return
      if (!confirm('确定要取消该导入任务吗？（best-effort）')) return
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

  // 检索测试
  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return

    setIsSearching(true)
    setSearchError(null)
    setSearchResults([])
    setSearchQueryForRetrieval('')
    setSearchMetrics(null)
    try {
      const res = await ragApi.retrievePreview({
        query: searchQuery.trim(),
        history: [],
        document_ids: [],
      })
      setSearchResults(res.citations || [])
      setSearchQueryForRetrieval(res.query_for_retrieval || '')
      setSearchMetrics(res.metrics || null)
    } catch (error: any) {
      console.error('Search failed:', error)
      setSearchError(formatApiError(error, '检索失败，请检查后端服务状态'))
    } finally {
      setIsSearching(false)
    }
  }, [searchQuery])

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
        {/* 背景装饰 */}
        <div className="absolute top-0 left-0 right-0 h-64 bg-gradient-to-b from-primary/10 to-transparent pointer-events-none" />

        <PageScaffold
          title="知识库管理"
          icon={Database}
          iconColor="text-primary"
          description="管理您的文档资产，构建专属知识大脑"
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
                  className="gap-2 rounded-xl shadow-glow border border-primary/20"
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
	            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 motion-reduce:animate-none motion-reduce:transition-none">
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
                      <Button size="lg" className="gap-2 rounded-xl shadow-glow" asChild>
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
                      <div className="relative w-full">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                        <input
                          value={docFilter}
                          onChange={(e) => setDocFilter(e.target.value)}
                          placeholder="搜索文档名称…"
                          className="w-full h-10 pl-9 pr-10 rounded-xl border border-border/60 bg-background/60 backdrop-blur-sm text-sm outline-none transition-colors placeholder:text-muted-foreground/60 focus:bg-background focus:border-primary/40 focus-ring"
                        />
                        {docFilter.trim() ? (
                          <button
                            type="button"
                            onClick={() => setDocFilter('')}
                            aria-label="清除搜索"
                            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md hover:bg-muted/40 focus-ring"
                          >
                            <X className="h-4 w-4 text-muted-foreground" />
                          </button>
                        ) : null}
                      </div>

                      <Select value={datasetScope} onValueChange={setDatasetScope}>
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
                            "h-9 px-3 rounded-full border text-xs font-semibold tracking-wide transition-colors focus-ring",
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
                          variant="destructive"
                          size="sm"
                          className="rounded-xl"
                          onClick={() => setBatchDeleteOpen(true)}
                          disabled={batchDeleting}
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
                          }}
                        >
                          清空筛选
                        </Button>
                      </EmptyState>
                    </div>
                  ) : viewMode === 'grid' ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-5">
                      {filteredDocuments.map((doc) => {
                        const badge = getStatusBadge(doc.status)
                        return (
                          <DocumentCard
                            key={doc.id}
                            doc={doc}
                            statusBadge={badge}
                            statusBarClassName={statusBarClassName(badge.status)}
                            onDelete={deleteDocument}
                            selected={selectedSet.has(doc.id)}
                            onToggleSelect={() => toggleDocSelection(doc.id)}
                          />
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
                            <th className="px-6 py-4 font-medium">状态</th>
                            <th className="px-6 py-4 font-medium">分块</th>
                            <th className="px-6 py-4 font-medium">大小</th>
                            <th className="px-6 py-4 font-medium">上传时间</th>
                            <th className="px-6 py-4 font-medium text-right">操作</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border/60">
                          {filteredDocuments.map((doc) => {
                            const badge = getStatusBadge(doc.status)
                            const fileType = getFileTypeStyle(doc)
                            const TypeIcon = fileType.icon
                            return (
                              <tr key={doc.id} className="hover:bg-muted/20 transition-colors group">
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
                                        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
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
	            <div className="max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-2 duration-500 motion-reduce:animate-none motion-reduce:transition-none">
              <Panel padding="none" className="rounded-2xl p-8 text-center relative overflow-hidden">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary via-primary/60 to-primary/20" />
                
                <div className="mb-8">
                  <div className="w-16 h-16 bg-primary/10 text-primary rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-soft">
                    <Sparkles className="w-8 h-8" />
                  </div>
                  <h3 className="text-xl font-bold text-foreground">语义检索测试</h3>
                  <p className="text-muted-foreground mt-2">
                    输入您的问题，模拟 RAG 系统的检索召回过程
                  </p>
                </div>

                <div className="max-w-2xl mx-auto relative mb-10">
                  <div className={cn(
                    "flex items-center bg-background/60 border-2 border-border/60 rounded-2xl p-2 shadow-soft transition-all duration-300",
                    "focus-within:border-primary/60 focus-within:ring-4 focus-within:ring-ring/15 focus-within:shadow-strong/10"
                  )}>
                    <Search className="w-5 h-5 text-muted-foreground ml-3" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                      placeholder="例如：MimirQ 支持哪些文档格式？"
                      className="flex-1 px-4 py-3 bg-transparent outline-none text-foreground placeholder:text-muted-foreground/60 text-lg"
                    />
                    <Button
                      onClick={handleSearch}
                      disabled={isSearching || !searchQuery.trim()}
                      className="rounded-xl px-6 h-12 text-base font-medium shadow-glow border border-primary/20"
                    >
                      {isSearching ? <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none" /> : "开始检索"}
                    </Button>
                  </div>
                </div>

                {searchError && (
                  <div className="max-w-2xl mx-auto mb-6 text-left">
                    <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive">
                      {searchError}
                    </div>
                  </div>
                )}

	                {searchResults.length > 0 && (
	                  <div className="text-left space-y-4 animate-in fade-in slide-in-from-bottom-4 motion-reduce:animate-none motion-reduce:transition-none">
                    <div className="flex items-center justify-between px-2">
                      <h4 className="text-sm font-semibold text-foreground">召回结果</h4>
                      <span className="text-xs text-muted-foreground bg-muted/60 border border-border/60 px-2 py-1 rounded-full">
                        Top {searchResults.length}
                      </span>
                    </div>

                    {searchQueryForRetrieval && searchQueryForRetrieval !== searchQuery.trim() && (
                      <div className="px-2 text-xs text-muted-foreground">
                        实际检索 Query：<span className="font-mono">{searchQueryForRetrieval}</span>
                      </div>
                    )}

                    {searchMetrics && (
                      <div className="px-2 text-xs text-muted-foreground">
                        Metrics：<span className="font-mono">{JSON.stringify(searchMetrics)}</span>
                      </div>
                    )}

                    {searchResults.map((result, index) => (
                      <div
                        key={`${result.document_id}-${index}`}
                        className="group p-5 bg-card border border-border/60 rounded-xl hover:border-primary/30 hover:shadow-strong/10 transition-all duration-300 relative overflow-hidden"
                      >
                         <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary/80 opacity-0 group-hover:opacity-100 transition-opacity" />
                        <div className="flex items-start gap-4">
                          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center font-bold text-sm">
                            {index + 1}
                          </div>
                          <div className="flex-1">
                            <p className="text-foreground/90 leading-relaxed text-sm mb-3">
                              {result.chunk_content}
                            </p>
                            <div className="flex items-center gap-3 text-xs">
                              <span className="flex items-center gap-1 text-muted-foreground bg-muted/60 border border-border/60 px-2 py-1 rounded-md">
                                <FileIcon className="w-3 h-3" />
                                {result.document_name}
                              </span>
                              <span className="text-muted-foreground/40">|</span>
                              <span className="font-medium text-primary">
                                相似度 {(result.relevance_score * 100).toFixed(0)}%
                              </span>
                              {typeof result.page_number === 'number' && (
                                <>
                                  <span className="text-muted-foreground/40">|</span>
                                  <span className="text-muted-foreground">P.{result.page_number}</span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Panel>
            </div>
          )}

	          {/* 设置 */}
	          {activeTab === 'settings' && (
	            <div className="max-w-3xl mx-auto animate-in fade-in slide-in-from-bottom-2 duration-500 motion-reduce:animate-none motion-reduce:transition-none">
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
                          const errors: any[] = Array.isArray(stats.errors) ? stats.errors : []
                          const isActive = run.status === 'pending' || run.status === 'running'
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
                                  {run.error_message ? (
                                    <div className="mt-2 text-xs text-destructive">{run.error_message}</div>
                                  ) : null}
                                  {errors.length > 0 ? (
                                    <div className="mt-2 text-xs text-muted-foreground">
                                      <div className="font-medium text-foreground/80">错误示例：</div>
                                      <div className="mt-1 space-y-1">
                                        {errors.slice(0, 3).map((e, idx) => (
                                          <div key={idx} className="font-mono truncate">
                                            {String(e?.url || '').slice(0, 80)} — {String(e?.error || '').slice(0, 120)}
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  ) : null}
                                </div>

                                {isActive ? (
                                  <Button variant="outline" className="gap-2" onClick={() => void handleCancelConnectorRun(run.id)}>
                                    <X className="w-4 h-4" />
                                    取消
                                  </Button>
                                ) : null}
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
        </PageScaffold>
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
  const fileType = getFileTypeStyle(doc)
  const TypeIcon = fileType.icon

  return (
    <Panel
      padding="none"
      className="group relative rounded-2xl overflow-hidden transition-all duration-300 hover:shadow-strong/20 hover:border-primary/30"
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
            <div className={cn("px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border", fileType.bg, fileType.color, fileType.border)}>
              {fileType.label}
            </div>
            <StatusBadge status={statusBadge.status} label={statusBadge.label} dense />
          </div>
        </div>

        <h3 className="font-semibold text-foreground line-clamp-2 mb-2 min-h-[2.5rem]" title={doc.filename}>
          {doc.filename}
        </h3>

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
