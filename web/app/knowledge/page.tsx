'use client'

/**
 * 知识库管理页面
 * 优化版：卡片视图、视觉增强、交互优化、深色模式适配
 */
import { useCallback, useMemo, useState } from 'react'
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
  Filter
} from 'lucide-react'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { EmptyState } from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Panel } from '@/components/ui/panel'
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
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { getParserLabel } from '@/lib/parser-options'
import type { Citation, Document } from '@/types'
import { ragApi } from '@/lib/api-client'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'

// Tab 类型
type TabType = 'documents' | 'retrieval' | 'settings'
type ViewMode = 'grid' | 'list'

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
  const { documents, isLoading, uploadDocument, deleteDocument, loadDocuments } = useDocuments()
  const [activeTab, setActiveTab] = useState<TabType>('documents')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()

  // 检索测试状态
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Citation[]>([])
  const [searchQueryForRetrieval, setSearchQueryForRetrieval] = useState<string>('')
  const [searchMetrics, setSearchMetrics] = useState<Record<string, any> | null>(null)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [isSearching, setIsSearching] = useState(false)

  const stats = useMemo(() => {
    const totalDocs = documents.length
    let completedDocs = 0
    let processingDocs = 0
    let failedDocs = 0
    let quarantinedDocs = 0
    let totalChunks = 0
    let totalSize = 0

    for (const doc of documents) {
      totalChunks += doc.chunk_count || 0
      totalSize += doc.file_size || 0

      if (doc.status === 'completed') {
        completedDocs += 1
      } else if (doc.status === 'failed') {
        failedDocs += 1
      } else if (doc.status === 'quarantined') {
        quarantinedDocs += 1
      } else if (doc.status === 'processing' || doc.status === 'pending') {
        processingDocs += 1
      }
    }

    return {
      totalDocs,
      completedDocs,
      processingDocs,
      failedDocs,
      quarantinedDocs,
      totalChunks,
      totalSize,
      showExtraCard: processingDocs > 0 || failedDocs > 0 || quarantinedDocs > 0,
    }
  }, [documents])

  const {
    totalDocs,
    completedDocs,
    processingDocs,
    failedDocs,
    quarantinedDocs,
    totalChunks,
    totalSize,
    showExtraCard,
  } = stats

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
        rag_config: {
          top_k: 5,
          score_threshold: 0.7,
          retrieval_mode: 'hybrid',
        },
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
                value={completedDocs}
                color="green"
                className="bg-card/60 backdrop-blur-md border-border/60 shadow-soft"
              />
              <StatCard
                icon={Layers}
                label="知识分块"
                value={totalChunks.toLocaleString()}
                color="teal"
                className="bg-card/60 backdrop-blur-md border-border/60 shadow-soft"
              />
              <StatCard
                icon={HardDrive}
                label="存储占用"
                value={formatFileSize(totalSize)}
                color="orange"
                className="bg-card/60 backdrop-blur-md border-border/60 shadow-soft"
              />
              {showExtraCard && (
                <StatCard
                  icon={(failedDocs + quarantinedDocs) > 0 ? (failedDocs > 0 ? XCircle : AlertTriangle) : Loader2}
                  label={(failedDocs + quarantinedDocs) > 0 ? '需关注' : '处理中'}
                  value={(failedDocs + quarantinedDocs) > 0 ? (failedDocs + quarantinedDocs) : processingDocs}
                  color={(failedDocs + quarantinedDocs) > 0 ? (failedDocs > 0 ? 'red' : 'amber') : 'sky'}
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
                  {viewMode === 'grid' ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-5">
                      {documents.map((doc) => {
                        const badge = getStatusBadge(doc.status)
                        return (
                          <DocumentCard
                            key={doc.id}
                            doc={doc}
                            statusBadge={badge}
                            statusBarClassName={statusBarClassName(badge.status)}
                            onDelete={deleteDocument}
                          />
                        )
                      })}
                    </div>
                  ) : (
                    <Panel padding="none" className="rounded-xl overflow-hidden">
                      <table className="w-full text-sm text-left">
                        <thead className="text-xs text-muted-foreground uppercase bg-muted/30 border-b border-border/60">
                          <tr>
                            <th className="px-6 py-4 font-medium">文档名称</th>
                            <th className="px-6 py-4 font-medium">状态</th>
                            <th className="px-6 py-4 font-medium">分块</th>
                            <th className="px-6 py-4 font-medium">大小</th>
                            <th className="px-6 py-4 font-medium">上传时间</th>
                            <th className="px-6 py-4 font-medium text-right">操作</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border/60">
                          {documents.map((doc) => {
                             const badge = getStatusBadge(doc.status)
                             const fileType = getFileTypeStyle(doc)
                             const TypeIcon = fileType.icon
                             return (
                            <tr key={doc.id} className="hover:bg-muted/20 transition-colors group">
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
                          )})}
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
}: {
  doc: Document
  statusBadge: { status: StatusBadgeStatus; label: string }
  statusBarClassName: string
  onDelete: (id: string) => void
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
