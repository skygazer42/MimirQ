'use client'

import type { Document } from '@/types'

import { Activity, AlertTriangle, Database, Eye, Filter, Loader2, MoreVertical, Trash2, Upload } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { EmptyState } from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { SearchInput } from '@/components/ui/search-input'
import { Panel } from '@/components/ui/panel'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import { DocumentTags } from '@/components/documents/document-tags'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Link } from '@/i18n/navigation'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatDate, formatFileSize, detachPromise } from '@/lib/utils'
import { getParserLabel } from '@/lib/parser-options'
import { getUserTagsFromDocument } from '@/lib/document-user-tags'
import { getFileTypeMeta } from '@/components/knowledge/file-type'

type ViewMode = 'grid' | 'list'
type DocSortKey = 'created_at' | 'filename' | 'file_size'
type DocSortDir = 'asc' | 'desc'

type KnowledgeDocumentsPanelProps = {
  isLoading: boolean
  documents: Document[]
  filteredDocuments: Document[]

  selectedDatasetId?: string
  selectedDatasetLabel?: string
  datasetLabelById?: Record<string, string>
  hasActiveFilters?: boolean
  onSwitchToAllDatasets?: () => void

  scopeSummary?: React.ReactNode

  docFilter: string
  setDocFilter: (value: string) => void
  onClearFilters: () => void

  sortKey: DocSortKey
  sortDir: DocSortDir
  setSortKey: (value: DocSortKey) => void
  setSortDir: (value: DocSortDir) => void

  viewMode: ViewMode
  docGridColumns: number
  docGridRowCount: number
  docsGridVirtualizer: any
  docsTableVirtualizer: any

  selectedDocIds: string[]
  setSelectedDocIds: (value: string[]) => void
  selectedSet: Set<string>
  allVisibleSelected: boolean
  toggleSelectAllVisible: () => void
  toggleDocSelection: (docId: string) => void

  batchDeleteOpen: boolean
  setBatchDeleteOpen: (open: boolean) => void
  batchDeleting: boolean
  confirmBatchDelete: () => void | Promise<void>

  batchLifecycleWorking: boolean
  batchReingestWorking: boolean
  runBatchReingest: () => void | Promise<void>
  runBatchLifecycle: (action: 'disable' | 'enable' | 'archive' | 'unarchive') => void | Promise<void>

  anySelectedDisabled: boolean
  anySelectedEnabled: boolean
  anySelectedArchived: boolean
  anySelectedNotArchived: boolean

  deleteDocument: (id: string) => void | Promise<void>
  handleFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void
}

function getStatusBadge(status: string): { status: StatusBadgeStatus; label: string } {
  switch (status) {
    case 'completed':
      return { status: 'completed', label: '已就绪' }
    case 'failed':
      return { status: 'failed', label: '失败' }
    case 'quarantined':
      return { status: 'quarantined', label: '已隔离' }
    case 'processing':
      return { status: 'processing', label: '处理中' }
    case 'pending':
      return { status: 'pending', label: '等待' }
    default:
      return { status: 'pending', label: '等待' }
  }
}

function statusBarClassName(status: StatusBadgeStatus) {
  if (status === 'completed') return 'bg-success'
  if (status === 'failed') return 'bg-destructive'
  if (status === 'quarantined') return 'bg-warning'
  if (status === 'processing') return 'bg-info'
  if (status === 'pending') return 'bg-muted-foreground/40'
  return 'bg-muted-foreground/40'
}

const contextualRevealClassName = [
  'opacity-100',
  '[@media(hover:hover)_and_(pointer:fine)]:opacity-0',
  '[@media(hover:hover)_and_(pointer:fine)]:group-hover:opacity-100',
  '[@media(hover:hover)_and_(pointer:fine)]:group-focus-within:opacity-100',
].join(' ')

export function KnowledgeDocumentsPanel({
  isLoading,
  documents,
  filteredDocuments,
  selectedDatasetId,
  selectedDatasetLabel,
  datasetLabelById,
  hasActiveFilters = false,
  onSwitchToAllDatasets,
  scopeSummary,
  docFilter,
  setDocFilter,
  onClearFilters,
  sortKey,
  sortDir,
  setSortKey,
  setSortDir,
  viewMode,
  docGridColumns,
  docGridRowCount,
  docsGridVirtualizer,
  docsTableVirtualizer,
  selectedDocIds,
  setSelectedDocIds,
  selectedSet,
  allVisibleSelected,
  toggleSelectAllVisible,
  toggleDocSelection,
  batchDeleteOpen,
  setBatchDeleteOpen,
  batchDeleting,
  confirmBatchDelete,
  batchLifecycleWorking,
  batchReingestWorking,
  runBatchReingest,
  runBatchLifecycle,
  anySelectedDisabled,
  anySelectedEnabled,
  anySelectedArchived,
  anySelectedNotArchived,
  deleteDocument,
  handleFileUpload,
}: Readonly<KnowledgeDocumentsPanelProps>) {
  const [singleDeleteDoc, setSingleDeleteDoc] = useState<Document | null>(null)
  const [singleDeleteWorking, setSingleDeleteWorking] = useState(false)
  const [singleDeleteError, setSingleDeleteError] = useState<string | null>(null)

  const showDatasetColumn = !selectedDatasetId
  const tableColumnCount = showDatasetColumn ? 9 : 8

  const docsGridVirtualRows = docsGridVirtualizer.getVirtualItems()
  const docsTableVirtualRows = docsTableVirtualizer.getVirtualItems()
  const docsTablePaddingTop = docsTableVirtualRows.length ? docsTableVirtualRows[0].start : 0
  const docsTablePaddingBottom = docsTableVirtualRows.length
    ? docsTableVirtualizer.getTotalSize() - docsTableVirtualRows[docsTableVirtualRows.length - 1].end
    : 0

  const singleDeleteTitle = useMemo(() => {
    if (!singleDeleteDoc) return '确认删除'
    return `删除文档？`
  }, [singleDeleteDoc])

  const singleDeleteDescription = useMemo(() => {
    if (!singleDeleteDoc) return null
    return (
      <div className="space-y-2">
        <div>
          将删除文档 <span className="font-mono tabular-nums">{singleDeleteDoc.filename}</span>，此操作不可撤销。
        </div>
        <div className="text-xs text-muted-foreground font-mono break-all">{singleDeleteDoc.id}</div>
      </div>
    )
  }, [singleDeleteDoc])

  const confirmSingleDelete = useCallback(async () => {
    const doc = singleDeleteDoc
    if (!doc) return
    if (singleDeleteWorking) return

    setSingleDeleteWorking(true)
    setSingleDeleteError(null)
    try {
      await deleteDocument(doc.id)
      toast.success('已删除文档')
      setSingleDeleteDoc(null)
    } catch (err: any) {
      console.error('Delete document failed:', err)
      setSingleDeleteError(formatApiError(err, '删除失败'))
    } finally {
      setSingleDeleteWorking(false)
    }
  }, [deleteDocument, singleDeleteDoc, singleDeleteWorking])

  const requestSingleDelete = useCallback((doc: Document) => {
    setSingleDeleteError(null)
    setSingleDeleteDoc(doc)
  }, [])

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

  const buildCopyHandler = useCallback(
    (text: string, okMsg: string) => () => detachPromise(copyText(text, okMsg)),
    [copyText],
  )

  const buildToggleDocSelectionHandler = useCallback(
    (docId: string) => () => toggleDocSelection(docId),
    [toggleDocSelection],
  )

  const buildRequestSingleDeleteHandler = useCallback(
    (doc: Document) => () => requestSingleDelete(doc),
    [requestSingleDelete],
  )

  const renderGridDocCard = (doc: Document) => {
    const badge = getStatusBadge(doc.status)
    return (
      <div key={doc.id}>
        <DocumentCard
          doc={doc}
          statusBadge={badge}
          statusBarClassName={statusBarClassName(badge.status)}
          onRequestDelete={requestSingleDelete}
          copyText={copyText}
          selected={selectedSet.has(doc.id)}
          onToggleSelect={buildToggleDocSelectionHandler(doc.id)}
        />
      </div>
    )
  }

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-300 motion-reduce:animate-none motion-reduce:transition-none">
      <AlertDialog
        open={Boolean(singleDeleteDoc)}
        onOpenChange={(open) => {
          if (open) return
          setSingleDeleteDoc(null)
          setSingleDeleteWorking(false)
          setSingleDeleteError(null)
        }}
      >
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>{singleDeleteTitle}</AlertDialogTitle>
            <AlertDialogDescription>
              {singleDeleteDescription}
              {singleDeleteError ? (
                <div className="mt-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive text-pretty">
                  {singleDeleteError}
                </div>
              ) : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setSingleDeleteDoc(null)}
              disabled={singleDeleteWorking}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => detachPromise(confirmSingleDelete())}
              disabled={singleDeleteWorking || !singleDeleteDoc}
            >
              {singleDeleteWorking ? '删除中…' : '确认删除'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {(() => {
    if (isLoading && documents.length === 0) {
        return (<div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
          <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none mb-3"/>
          <p className="text-sm">正在加载文档库...</p>
        </div>);
    }
    else if (documents.length === 0 && hasActiveFilters) {
            return (<div className="py-10">
          <EmptyState icon={Filter} title="未找到匹配的文档" description={<span className="text-muted-foreground">尝试清空筛选条件，重新查看范围内的全部文档。</span>} className="bg-transparent shadow-none">
            <Button type="button" variant="outline" className="rounded-xl" onClick={onClearFilters}>
              清空筛选
            </Button>
          </EmptyState>
        </div>);
        }
        else if (documents.length === 0 && selectedDatasetId && onSwitchToAllDatasets) {
                return (<div className="py-10">
          <EmptyState icon={Database} title="该数据集暂无文档" description={<span className="text-muted-foreground">
                {`当前范围为 ${selectedDatasetLabel || selectedDatasetId}。可切换到全部数据集查看其他文档，或通过顶部“导入/新增”上传/导入。`}
              </span>} className="bg-transparent shadow-none">
            <Button type="button" variant="outline" className="rounded-xl" onClick={onSwitchToAllDatasets}>
              切换到全部数据集
            </Button>
          </EmptyState>
        </div>);
            }
            else if (documents.length === 0) {
                    return (<div className="py-10">
          <EmptyState icon={Upload} title="知识库空空如也" description={<span className="text-muted-foreground">
                上传您的第一份文档，MimirQ 将自动解析并构建专属知识索引。
                <br />
                支持 PDF, TXT, Markdown, Excel, Word 等常见格式。
              </span>} className="bg-transparent shadow-none">
            <div>
              <Button size="lg" className="gap-2 rounded-xl shadow-sm" asChild>
                <span>
                  <Upload className="w-5 h-5"/>
                  立即上传文档
                </span>
              </Button>
              <input type="file" multiple accept={UPLOAD_ACCEPT} className="hidden" onChange={handleFileUpload}/>
            </div>
          </EmptyState>
        </div>);
                }
                else {
                    return (<>
          <div className="mb-4 flex flex-col lg:flex-row lg:items-center gap-3">
            <div className="flex w-full lg:max-w-2xl flex-col sm:flex-row gap-3">
              <SearchInput value={docFilter} onValueChange={setDocFilter} placeholder="搜索文档名称…" containerClassName="w-full" inputClassName="h-9 rounded-lg border-border/60 bg-background placeholder:text-muted-foreground/60 focus:border-primary/40"/>

              <Select value={`${sortKey}:${sortDir}`} onValueChange={(value) => {
                            const [k, d] = String(value || '').split(':');
                            if (k === 'created_at' || k === 'filename' || k === 'file_size')
                                setSortKey(k);
                            if (d === 'asc' || d === 'desc')
                                setSortDir(d);
                        }}>
                <SelectTrigger className="h-9 w-full sm:w-[200px] rounded-lg border-border/60 bg-background" aria-label="排序">
                  <SelectValue placeholder="排序"/>
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

            {scopeSummary ? <div className="text-xs">{scopeSummary}</div> : null}
          </div>

          {selectedDocIds.length > 0 ? (<div className="mb-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
              <div className="text-sm text-foreground">
                已选 <span className="font-mono tabular-nums">{selectedDocIds.length}</span> 项
              </div>
              <div className="flex flex-wrap items-center gap-2 justify-end">
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={toggleSelectAllVisible}>
                  {allVisibleSelected ? '取消全选' : '全选当前列表'}
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => setSelectedDocIds([])}>
                  清除选择
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchReingest())} disabled={batchDeleting || batchLifecycleWorking || batchReingestWorking}>
                  {batchReingestWorking ? '重新入库中…' : '重新入库'}
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchLifecycle('disable'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedEnabled}>
                  禁用
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchLifecycle('enable'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedDisabled}>
                  启用
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchLifecycle('archive'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedNotArchived}>
                  归档
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchLifecycle('unarchive'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedArchived}>
                  取消归档
                </Button>
                <Button type="button" variant="destructive" size="sm" className="rounded-xl" onClick={() => setBatchDeleteOpen(true)} disabled={batchDeleting || batchLifecycleWorking}>
                  批量删除
                </Button>
              </div>
            </div>) : null}

          <AlertDialog open={batchDeleteOpen} onOpenChange={setBatchDeleteOpen}>
            <AlertDialogContent className="max-w-md">
              <AlertDialogHeader>
                <AlertDialogTitle>确认删除</AlertDialogTitle>
                <AlertDialogDescription>
                  将删除已选中的 <span className="font-mono tabular-nums">{selectedDocIds.length}</span> 份文档，此操作不可撤销。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <Button type="button" variant="outline" onClick={() => setBatchDeleteOpen(false)} disabled={batchDeleting}>
                  取消
                </Button>
                <Button type="button" variant="destructive" onClick={() => detachPromise(confirmBatchDelete())} disabled={batchDeleting || selectedDocIds.length === 0}>
                  {batchDeleting ? '删除中…' : '确认删除'}
                </Button>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>

          {(() => {
                            if (filteredDocuments.length === 0) {
                                return (<div className="py-10">
              <EmptyState icon={Filter} title="未找到匹配的文档" description={<span className="text-muted-foreground">尝试调整筛选条件，或清空筛选后重新查看全部文档。</span>} className="bg-transparent shadow-none">
                <Button type="button" variant="outline" className="rounded-xl" onClick={onClearFilters}>
                  清空筛选
                </Button>
              </EmptyState>
            </div>);
                            }
	                            else if (viewMode === 'grid') {
	                                    return (<div aria-label="文档列表" style={{
	                                            height: `${docsGridVirtualizer.getTotalSize()}px`,
	                                            width: '100%',
	                                            position: 'relative',
	                                        }}>
	              {docsGridVirtualRows.map((virtualRow: any) => {
                                            const cols = Math.max(1, docGridColumns);
                                            const startIndex = virtualRow.index * cols;
                                            const rowDocs = filteredDocuments.slice(startIndex, startIndex + cols);
                                            const isLastRow = virtualRow.index === docGridRowCount - 1;
	                                            return (<div key={virtualRow.key} data-index={virtualRow.index} ref={docsGridVirtualizer.measureElement} style={{
	                                                    position: 'absolute',
	                                                    top: 0,
	                                                    left: 0,
	                                                    width: '100%',
	                                                    transform: `translateY(${virtualRow.start}px)`,
	                                                }} className={isLastRow ? undefined : 'pb-5'}>
	                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-5">
	                      {rowDocs.map(renderGridDocCard)}
	                    </div>
	                  </div>);
	                                        })}
            </div>);
                                }
                                else {
                                    return (<Panel padding="none" className="rounded-xl overflow-hidden">
	              <table aria-label="知识库文档列表" className="w-full text-sm text-left">
	                <thead className="text-xs text-muted-foreground uppercase border-b border-border/60">
	                  <tr>
	                    <th className="sticky top-0 z-10 bg-card px-3 py-3 font-medium w-10">
	                      <input type="checkbox" className="h-4 w-4 rounded border-border/60 text-primary focus-ring" checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label="全选当前列表"/>
	                    </th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">文档名称</th>
	                    {showDatasetColumn ? (<th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">数据集</th>) : null}
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">标签</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">状态</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium text-right">分块</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium text-right">大小</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">上传时间</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium text-right">操作</th>
	                  </tr>
	                </thead>
	                <tbody className="divide-y divide-border/60">
		                  {docsTablePaddingTop > 0 ? (<tr>
		                      <td colSpan={tableColumnCount} className="p-0" style={{ height: `${docsTablePaddingTop}px` }}/>
		                    </tr>) : null}

	                  {docsTableVirtualRows.map((virtualRow: any) => {
	                                            const doc = filteredDocuments[virtualRow.index];
	                                            if (!doc)
	                                                return null;
	                                            const badge = getStatusBadge(doc.status);
                                            const fileType = getFileTypeMeta(doc);
                                            const TypeIcon = fileType.icon;
                                            const userTags = getUserTagsFromDocument(doc);
	                                            const sourcePath = String((doc.metadata as any)?.source_path || '').trim();
	                                            const parseScoreRaw = (doc.metadata as any)?.parse_quality?.score;
	                                            const parseScore = typeof parseScoreRaw === 'number' && Number.isFinite(parseScoreRaw) ? parseScoreRaw : null;
	                                            const parseLow = parseScore !== null && parseScore < 0.35;
	                                            return (<tr key={virtualRow.key} data-index={virtualRow.index} ref={docsTableVirtualizer.measureElement} className="group hover:bg-muted/20 transition-colors">
		                        <td className="px-3 py-3 align-middle">
		                          <input type="checkbox" className="h-4 w-4 rounded border-border/60 text-primary focus-ring" checked={selectedSet.has(doc.id)} onChange={buildToggleDocSelectionHandler(doc.id)} aria-label={`选择文档 ${doc.filename}`}/>
		                        </td>
	                        <td className="px-4 py-3 font-medium text-foreground">
	                          <div className="flex items-start gap-3">
                            <div className={cn('mt-0.5 p-1.5 rounded-md border', fileType.bg, fileType.border, fileType.color)}>
                              <TypeIcon className="w-4 h-4"/>
                            </div>
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="truncate max-w-[260px]" title={doc.filename}>
                                  {doc.filename}
                                </span>
	                                <span className={cn('inline-flex items-center rounded-full border px-1.5 py-0 text-[10px] font-semibold uppercase ', fileType.bg, fileType.border, fileType.color)} title={fileType.label}>
	                                  {fileType.label}
	                                </span>
	                                {parseLow ? (
	                                  <span
	                                    className="inline-flex items-center rounded-full border border-amber-500/20 bg-amber-500/10 px-1.5 py-0 text-[10px] font-semibold text-amber-700 dark:text-amber-300"
	                                    title={`解析质量偏低 (score=${parseScore?.toFixed?.(3) ?? '—'})`}
	                                  >
	                                    <AlertTriangle className="h-3.5 w-3.5" />
	                                  </span>
	                                ) : null}
	                              </div>
	                              {sourcePath ? (<button type="button" className={cn('mt-0.5 block max-w-[420px] truncate text-[11px] font-mono tabular-nums text-muted-foreground hover:text-foreground underline underline-offset-4 transition-opacity', contextualRevealClassName)} onClick={buildCopyHandler(sourcePath, '已复制 Source Path')} title="点击复制 Source Path">
	                                  {sourcePath}
	                                </button>) : null}
	                            </div>
	                          </div>
	                        </td>
	                        {showDatasetColumn ? (<td className="px-4 py-3 align-middle">
	                            {doc.dataset_id ? (<span className="text-xs text-muted-foreground truncate block max-w-[180px]" title={doc.dataset_id}>
	                                {datasetLabelById?.[doc.dataset_id] ?? doc.dataset_id}
	                              </span>) : (<span className="text-xs text-muted-foreground">—</span>)}
	                          </td>) : null}
	                        <td className="px-4 py-3 align-middle">
	                          {userTags.length ? (<DocumentTags tags={userTags} max={3} dense/>) : (<span className="text-xs text-muted-foreground">—</span>)}
	                        </td>
	                        <td className="px-4 py-3 align-middle">
	                          <StatusBadge status={badge.status} label={badge.label} dense/>
	                        </td>
	                        <td className="px-4 py-3 align-middle text-right text-muted-foreground font-mono tabular-nums text-xs">
	                          {doc.chunk_count ?? '-'}
	                        </td>
	                        <td className="px-4 py-3 align-middle text-right text-muted-foreground font-mono tabular-nums text-xs">
	                          {formatFileSize(doc.file_size)}
	                        </td>
	                        <td className="px-4 py-3 align-middle text-muted-foreground font-mono tabular-nums text-xs">
	                          {formatDate(doc.created_at)}
	                        </td>
	                        <td className="px-4 py-3 align-middle text-right flex items-center justify-end gap-1">
	                          <DocumentDetailDialog document={doc} trigger={<IconButton label="预览内容" variant="ghost" className={cn('h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted transition-opacity', contextualRevealClassName)}>
	                                <Eye className="h-4 w-4"/>
	                              </IconButton>}/>

                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
	                              <IconButton label="更多操作" variant="ghost" className={cn('h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted transition-opacity', contextualRevealClassName)}>
	                                <MoreVertical className="h-4 w-4"/>
	                              </IconButton>
	                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-56">
                              <DropdownMenuItem onSelect={buildCopyHandler(doc.id, '已复制文档 ID')}>
                                复制文档 ID
                              </DropdownMenuItem>
                              <DropdownMenuItem onSelect={buildCopyHandler(doc.filename, '已复制文件名')}>
                                复制文件名
                              </DropdownMenuItem>
                              {sourcePath ? (<DropdownMenuItem onSelect={buildCopyHandler(sourcePath, '已复制 Source Path')}>
                                  复制 Source Path
                                </DropdownMenuItem>) : null}
                              <DropdownMenuItem asChild>
                                <Link href={`/knowledge/${doc.id}/health`} className="flex items-center">
                                  <Activity className="mr-2 h-4 w-4" />
                                  健康卡片
                                </Link>
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={buildRequestSingleDeleteHandler(doc)}>
                                <Trash2 className="mr-2 h-4 w-4"/>
                                删除文档
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </td>
                      </tr>);
                                        })}

		                  {docsTablePaddingBottom > 0 ? (<tr>
		                      <td colSpan={tableColumnCount} className="p-0" style={{ height: `${docsTablePaddingBottom}px` }}/>
		                    </tr>) : null}
	                </tbody>
	              </table>
	            </Panel>);
                                }
                        })()}
        </>);
                }
})()}
    </div>
  )
}

function DocumentCard({
  doc,
  statusBadge,
  statusBarClassName,
  onRequestDelete,
  copyText,
  selected,
  onToggleSelect,
}: Readonly<{
  doc: Document
  statusBadge: { status: StatusBadgeStatus; label: string }
  statusBarClassName: string
  onRequestDelete: (doc: Document) => void
  copyText: (text: string, okMsg: string) => void | Promise<void>
  selected: boolean
  onToggleSelect: () => void
}>) {
  const parserLabel = doc.metadata?.parser_backend ? getParserLabel(doc.metadata.parser_backend as string) : null
  const userTags = getUserTagsFromDocument(doc)
  const fileType = getFileTypeMeta(doc)
  const TypeIcon = fileType.icon
  const parseScoreRaw = (doc.metadata as any)?.parse_quality?.score
  const parseScore = typeof parseScoreRaw === 'number' && Number.isFinite(parseScoreRaw) ? parseScoreRaw : null
  const parseLow = parseScore !== null && parseScore < 0.35

  return (
    <Panel
      padding="none"
      className="group relative rounded-2xl overflow-hidden hover:shadow-strong/20 hover:border-primary/30 transition-colors transition-shadow duration-200 motion-reduce:transition-none"
    >
      <div className={cn('h-1.5 w-full', statusBarClassName)} />

      <div
        className={cn(
          'absolute top-3 left-3 z-10 rounded-lg border border-border/60 bg-background/70 backdrop-blur-sm p-1 transition-opacity',
          selected ? 'opacity-100' : contextualRevealClassName
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
          <div className={cn('w-12 h-12 rounded-xl flex items-center justify-center border', fileType.bg, fileType.border, fileType.color)}>
            <TypeIcon className="w-6 h-6" />
          </div>
          <div className="flex items-center gap-2">
            <div className={cn('px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border', fileType.bg, fileType.color, fileType.border)}>
              {fileType.label}
            </div>
            {parseLow ? (
              <div
                className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                title={`解析质量偏低 (score=${parseScore?.toFixed?.(3) ?? '—'})`}
              >
                <AlertTriangle className="h-3.5 w-3.5" />
              </div>
            ) : null}
            {doc.disabled_at ? (
              <div className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border border-border/60 bg-muted/60 text-muted-foreground">
                Disabled
              </div>
            ) : null}
            {!doc.disabled_at && doc.archived_at ? (
              <div className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border border-border/60 bg-muted/60 text-muted-foreground">
                Archived
              </div>
            ) : null}
            <StatusBadge status={statusBadge.status} label={statusBadge.label} dense />
          </div>
        </div>

        <h3 className="font-semibold text-foreground line-clamp-2 mb-2 min-h-[2.5rem]" title={doc.filename}>
          {doc.filename}
        </h3>

        {userTags.length ? <DocumentTags tags={userTags} max={3} dense className="mb-3" /> : null}

        <div className="space-y-2 mt-auto">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>大小</span>
            <span className="font-mono">{formatFileSize(doc.file_size)}</span>
          </div>
	          <div className="flex items-center justify-between text-xs text-muted-foreground">
	            <span>分块</span>
	            <span className="font-mono tabular-nums">{doc.chunk_count ?? '-'}</span>
	          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>时间</span>
            <span>{formatDate(doc.created_at)}</span>
          </div>
        </div>
      </div>

      <div className={cn('px-5 py-3 border-t border-border/60 bg-muted/20 flex items-center justify-between transition-opacity', contextualRevealClassName)}>
        <span className="text-[10px] text-muted-foreground font-medium truncate max-w-[80px]">{parserLabel || 'Auto'}</span>
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

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton
                label="更多操作"
                variant="ghost"
                className="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreVertical className="w-4 h-4" />
              </IconButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.id, '已复制文档 ID'))}>
                复制文档 ID
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.filename, '已复制文件名'))}>
                复制文件名
              </DropdownMenuItem>
              {String((doc.metadata as any)?.source_path || '').trim() ? (
                <DropdownMenuItem
                  onSelect={() =>
                    detachPromise(copyText(String((doc.metadata as any)?.source_path || ''), '已复制 Source Path'))
                  }
                >
                  复制 Source Path
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem asChild>
                <Link href={`/knowledge/${doc.id}/health`} className="flex items-center">
                  <Activity className="mr-2 h-4 w-4" />
                  健康卡片
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={() => onRequestDelete(doc)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                删除文档
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {statusBadge.status === 'processing' ? (
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-muted">
          <div
            className="h-full bg-primary/70 animate-pulse motion-reduce:animate-none"
            style={{ width: `${doc.processing_progress || 60}%` }}
          />
        </div>
      ) : null}
    </Panel>
  )
}
