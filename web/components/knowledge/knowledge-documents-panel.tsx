'use client'

import type { Dataset, Document } from '@/types'

import {
  Activity,
  ChevronDown,
  Database,
  Eye,
  Filter,
  Layers,
  Loader2,
  MoreVertical,
  RefreshCw,
  RotateCcw,
  Trash2,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { type Key, type ReactNode, type SyntheticEvent, useCallback, useState } from 'react'
import { toast } from 'sonner'
import { motion, AnimatePresence } from 'framer-motion'

import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { SearchInput } from '@/components/ui/search-input'
import { Panel } from '@/components/ui/panel'
import {
  StatusBadge,
  type StatusBadgeStatus,
} from '@/components/ui/status-badge'
import { DocumentOperationsPanel } from '@/components/documents/document-operations-panel'
import { DocumentTags } from '@/components/documents/document-tags'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Link } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatDate, formatFileSize, detachPromise } from '@/lib/utils'
import { getParserLabel } from '@/lib/parser-options'
import { getUserTagsFromDocument } from '@/lib/document-user-tags'
import { getFileTypeMeta } from '@/components/knowledge/file-type'

type ViewMode = 'grid' | 'list'
type DocSortKey = 'created_at' | 'filename' | 'file_size'
type DocSortDir = 'asc' | 'desc'
type TranslateValue = string | number | Date
type TranslateFn = (key: string, values?: Record<string, TranslateValue>) => string
type VirtualRowLike = {
  key: Key
  index: number
  start: number
  end: number
}
type VirtualizerLike = {
  getVirtualItems: () => VirtualRowLike[]
  getTotalSize: () => number
  measureElement: (node: Element | null) => void
}

type KnowledgeDocumentsPanelProps = {
  isLoading: boolean
  documents: Document[]
  filteredDocuments: Document[]
  totalDocumentsCount: number
  datasets?: Dataset[]
  embedded?: boolean

  selectedDatasetId?: string
  selectedDatasetLabel?: string
  datasetLabelById?: Record<string, string>
  hasActiveFilters?: boolean
  onSwitchToAllDatasets?: () => void

  scopeSummary?: ReactNode

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
  docsGridVirtualizer: VirtualizerLike
  docsTableVirtualizer: VirtualizerLike
  page: number
  pageSize: number
  pageCount: number
  onPageChange: (page: number) => void

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
  runBatchLifecycle: (
    action: 'disable' | 'enable' | 'archive' | 'unarchive'
  ) => void | Promise<void>

  anySelectedDisabled: boolean
  anySelectedEnabled: boolean
  anySelectedArchived: boolean
  anySelectedNotArchived: boolean

  deleteDocument: (id: string) => void | Promise<void>
  handleFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void
  onPeek?: (docId: string) => void
}

function getDocsGridColsClassName(docGridColumns: number): string {
  if (docGridColumns >= 5) return 'grid-cols-5'
  if (docGridColumns === 4) return 'grid-cols-4'
  if (docGridColumns === 3) return 'grid-cols-3'
  if (docGridColumns === 2) return 'grid-cols-2'
  return 'grid-cols-1'
}

function getEmptyTitle(isDatasetEmpty: boolean, docFilter: string): string {
  if (isDatasetEmpty) return '知识货架待入库'
  if (docFilter) return '没有匹配到相关文档'
  return '当前筛选无结果'
}

function getQualityColor(qualityPercent: number | null): string {
  if (qualityPercent === null) return 'text-muted-foreground/20'
  if (qualityPercent > 80) return 'text-success'
  if (qualityPercent > 50) return 'text-warning'
  return 'text-rose'
}

function getStatusBadge(
  status: string,
  t: TranslateFn
): { status: StatusBadgeStatus; label: string } {
  switch (status) {
    case 'completed':
      return { status: 'completed', label: t('status.completed') }
    case 'failed':
      return { status: 'failed', label: t('status.failed') }
    case 'quarantined':
      return { status: 'quarantined', label: t('status.quarantined') }
    case 'processing':
      return { status: 'processing', label: t('status.processing') }
    case 'pending':
      return { status: 'pending', label: t('status.pending') }
    default:
      return { status: 'pending', label: t('status.pending') }
  }
}

function getStatusBarColor(status: string) {
  if (status === 'completed') return 'bg-success'
  if (status === 'failed') return 'bg-destructive'
  if (status === 'quarantined') return 'bg-warning'
  if (status === 'processing' || status === 'pending') return 'bg-info'
  return 'bg-muted-foreground/40'
}

function getDocumentLifecycleLabel(doc: Document) {
  if (doc.archived_at) return '已归档'
  if (doc.disabled_at) return '已停用'
  return '启用中'
}

function getDocumentSourceLabel(doc: Document) {
  const metadata = (doc.metadata || {}) as Record<string, unknown>
  const source =
    typeof metadata.source === 'string' ? metadata.source.toLowerCase() : ''
  const sourcePath =
    typeof metadata.source_path === 'string' ? metadata.source_path : ''
  if (
    source.includes('connector') ||
    source.includes('crawl') ||
    source.includes('jira')
  )
    return '连接器'
  if (source.includes('url')) return 'URL 导入'
  if (sourcePath) return '目录上传'
  return '手动导入'
}

function getDocumentTagSummary(tags: string[]) {
  if (!tags.length) return '-'
  const visible = tags.slice(0, 2).join(' / ')
  return tags.length > 2 ? `${visible} +${tags.length - 2}` : visible
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
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
  totalDocumentsCount,
  datasets = [],
  embedded = false,
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
  page,
  pageSize,
  pageCount,
  onPageChange,
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
  onPeek,
}: Readonly<KnowledgeDocumentsPanelProps>) {
  const t = useTranslations('KnowledgeDocumentsPanel')
  // t("empty.filtered.title")
  // t("actions.clearFilters")
  // t("sort.placeholder")
  // t("empty.emptyDataset.actions.switchToAllDatasets")
  // t("empty.emptyDataset.description", {
  // t("row.parseQualityLow", {
  // t("table.columns.dataset")
  // source_path
  // const controlsClassName = embedded ? 'border-b border-border/60 bg-background/65 px-4 py-3 backdrop-blur-sm' : 'mb-4'
  const [activeDrawerDoc, setActiveDrawerDoc] = useState<Document | null>(null)
  const [singleDeleteDoc, setSingleDeleteDoc] = useState<Document | null>(null)
  const [singleDeleteWorking, setSingleDeleteWorking] = useState(false)
  const [singleDeleteError, setSingleDeleteError] = useState<string | null>(
    null
  )
  const [opsOpen, setOpsOpen] = useState(false)

  const docsGridColsClassName = getDocsGridColsClassName(docGridColumns)

  const showDatasetColumn = !selectedDatasetId
  const tableColumnCount = showDatasetColumn ? 9 : 8
  const documentListGridTemplate = showDatasetColumn
    ? '2.25rem minmax(16rem,1.65fr) minmax(8.5rem,.78fr) minmax(5.5rem,.55fr) minmax(5rem,.5fr) 3.75rem 5rem 5.5rem 8.5rem'
    : '2.25rem minmax(18rem,1.8fr) minmax(5.5rem,.55fr) minmax(5rem,.5fr) 3.75rem 5rem 5.5rem 8.5rem'
  const peekChunksLabel = (() => {
    const resolved = t('actions.peekChunks')
    return resolved === 'KnowledgeDocumentsPanel.actions.peekChunks'
      ? '查看分块'
      : resolved
  })()

  const docsGridVirtualRows = docsGridVirtualizer.getVirtualItems()
  const docsTableVirtualRows = docsTableVirtualizer.getVirtualItems()
  const docsTablePaddingTop = docsTableVirtualRows.length
    ? docsTableVirtualRows[0].start
    : 0
  const docsTablePaddingBottom = docsTableVirtualRows.length
    ? docsTableVirtualizer.getTotalSize() -
      docsTableVirtualRows[docsTableVirtualRows.length - 1].end
    : 0
  const sectionInsetClassName = embedded ? 'px-4 py-4' : ''

  const confirmSingleDelete = useCallback(async () => {
    const doc = singleDeleteDoc
    if (!doc) return
    if (singleDeleteWorking) return

    setSingleDeleteWorking(true)
    setSingleDeleteError(null)
    try {
      await deleteDocument(doc.id)
      toast.success(t('toasts.deleteSuccess'))
      setSingleDeleteDoc(null)
    } catch (err: unknown) {
      console.error('Delete document failed:', err)
      setSingleDeleteError(formatApiError(err, t('singleDelete.errorFallback')))
    } finally {
      setSingleDeleteWorking(false)
    }
  }, [deleteDocument, singleDeleteDoc, singleDeleteWorking, t])

  const requestSingleDelete = useCallback((doc: Document) => {
    setSingleDeleteError(null)
    setSingleDeleteDoc(doc)
  }, [])

  const handleDrawerOpenChange = useCallback((open: boolean) => {
    if (!open) setActiveDrawerDoc(null)
  }, [])

  const buildOpenInspectorHandler = useCallback(
    (doc: Document) => (event?: SyntheticEvent) => {
      event?.stopPropagation()
      setActiveDrawerDoc(doc)
    },
    []
  )

  const copyText = useCallback(
    async (text: string, okMsg: string) => {
      try {
        await globalThis.navigator.clipboard.writeText(text)
        toast.success(okMsg)
      } catch {
        toast.error(t('toasts.copyFailed'))
      }
    },
    [t]
  )

  const renderGridDocCard = (doc: Document) => {
    const badge = getStatusBadge(doc.status, t)
    return (
      <div key={doc.id} className="h-full">
        <DocumentCard
          doc={doc}
          statusBadge={badge}
          statusBarClassName={getStatusBarColor(doc.status)}
          onRequestDelete={requestSingleDelete}
          copyText={copyText}
          t={t}
          selected={selectedSet.has(doc.id)}
          onToggleSelect={() => toggleDocSelection(doc.id)}
          onPeek={onPeek}
        />
      </div>
    )
  }

  const visibleDocumentsCount = totalDocumentsCount
  const pageStart = visibleDocumentsCount
    ? (page - 1) * pageSize + 1
    : 0
  const pageEnd = Math.min(page * pageSize, visibleDocumentsCount)
  const canGoPrevious = page > 1
  const canGoNext = page < pageCount
  const isDatasetEmpty = documents.length === 0
  const showEmptyState = visibleDocumentsCount === 0
  const compactEmptyInventory = embedded && showEmptyState
  const iconShellClassName =
    'relative overflow-hidden shadow-[inset_0_1px_0_hsl(var(--card)/0.72),0_10px_20px_-18px_hsl(var(--foreground)/0.18)] backdrop-blur-[6px]'
  const inventoryStatCardClassName =
    'group relative overflow-hidden rounded-[16px] border border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)/0.94),hsl(var(--surface-2)/0.64))] px-3 py-2 shadow-[0_12px_24px_-24px_hsl(var(--primary)/0.34)] transition-[border-color,box-shadow,transform] hover:border-primary/25 hover:shadow-[0_16px_28px_-24px_hsl(var(--primary)/0.32)] dark:border-border/70 dark:bg-background/60'
  const checkboxCellClassName =
    'flex size-7 items-center justify-center rounded-[10px] border border-border/60 bg-card/76 shadow-[inset_0_1px_0_hsl(var(--card)/0.86),0_8px_16px_-14px_hsl(var(--primary)/0.35)] dark:border-border/70 dark:bg-background/70'
  const checkboxInputClassName =
    'size-4 cursor-pointer rounded-[5px] border-border/70 bg-background text-primary shadow-sm focus-ring dark:border-border/70 dark:bg-background'
  const inventoryToolbar = (
    <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
      <SearchInput
        value={docFilter}
        onValueChange={setDocFilter}
        containerClassName="min-w-0 w-full xl:max-w-[480px]"
        inputClassName="h-9 rounded-[12px] border-border/60 bg-background/86 pr-4 text-[12px] shadow-[inset_0_1px_0_hsl(var(--card)/0.86)] dark:border-border/70 dark:bg-background/72"
        placeholder={
          showDatasetColumn
            ? '搜索文件名 / 文档 ID / 数据集'
            : '搜索文件名 / 文档 ID'
        }
      />

      <div className="flex flex-wrap items-center gap-2 lg:flex-nowrap lg:justify-end">
        <Select
          value={sortKey}
          onValueChange={(value) => setSortKey(value as DocSortKey)}
        >
          <SelectTrigger className="h-9 min-w-[144px] rounded-[12px] border-border/60 bg-background/86 text-[11px] font-medium shadow-[inset_0_1px_0_hsl(var(--card)/0.86)] dark:border-border/70 dark:bg-background/72">
            <SelectValue placeholder={t('table.columns.name')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="created_at">按上传时间</SelectItem>
            <SelectItem value="filename">按文件名</SelectItem>
            <SelectItem value="file_size">按文件大小</SelectItem>
          </SelectContent>
        </Select>

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-9 min-w-[80px] justify-center rounded-[12px] border-border/60 bg-background/86 px-3 text-[11px] font-medium shadow-[inset_0_1px_0_hsl(var(--card)/0.86)] hover:border-primary/25 dark:border-border/70 dark:bg-background/72"
          onClick={() => setSortDir(sortDir === 'asc' ? 'desc' : 'asc')}
        >
          {sortDir === 'asc' ? '升序' : '降序'}
        </Button>

        {hasActiveFilters ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-9 min-w-[96px] justify-center rounded-[12px] border border-border/60 bg-background/78 px-3 text-[11px] font-medium hover:bg-card/90 dark:border-border/70 dark:bg-background/62"
            onClick={onClearFilters}
          >
            <RotateCcw className="mr-2 size-3.5" />
            清空筛选
          </Button>
        ) : null}

        <Button
          type="button"
          variant={opsOpen ? 'default' : 'outline'}
          size="sm"
          className="h-9 min-w-[96px] justify-center rounded-[12px] px-3 text-[11px] font-medium"
          aria-expanded={opsOpen}
          onClick={() => setOpsOpen((open) => !open)}
        >
          <Activity className="mr-2 size-3.5" />
          运维工具
        </Button>
      </div>
    </div>
  )

  return (
    <div
      className={cn(
        'animate-in fade-in slide-in-from-bottom-4 duration-300 motion-reduce:animate-none motion-reduce:transition-none',
        embedded && 'flex h-full min-h-0 flex-col'
      )}
    >
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
            <AlertDialogTitle>
              {singleDeleteDoc
                ? t('singleDelete.title')
                : t('singleDelete.titleDefault')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {singleDeleteDoc && (
                <div className="space-y-2">
                  <div>
                    {t('singleDelete.description', {
                      filename: singleDeleteDoc.filename,
                    })}
                  </div>
                  <div className="text-xs text-muted-foreground font-mono break-all">
                    {singleDeleteDoc.id}
                  </div>
                </div>
              )}
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
              {t('actions.cancel')}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => detachPromise(confirmSingleDelete())}
              disabled={singleDeleteWorking || !singleDeleteDoc}
            >
              {singleDeleteWorking
                ? t('actions.deleting')
                : t('actions.confirmDelete')}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AnimatePresence>
        {selectedDocIds.length > 0 ? (
          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 40, scale: 0.95 }}
            transition={{ type: 'spring', damping: 20, stiffness: 300 }}
            className={cn(
              'fixed bottom-8 left-1/2 z-50 -translate-x-1/2 overflow-hidden rounded-[2.25rem] border border-border/50 bg-background/70 px-4 py-3 shadow-[0_30px_90px_-32px_rgba(15,23,42,0.88),0_18px_36px_-24px_rgba(15,23,42,0.55),inset_0_1px_0_rgba(255,255,255,0.16)] backdrop-blur-2xl supports-[backdrop-filter]:bg-background/58'
            )}
          >
            <div className="pointer-events-none absolute inset-0 bg-background/90" />
            <div className="pointer-events-none absolute inset-x-10 top-0 h-px bg-card/30 dark:bg-card/10" />
            <div className="pointer-events-none absolute -left-8 top-1/2 size-28 -translate-y-1/2 rounded-full bg-primary/10 blur-3xl" />
            <div className="pointer-events-none absolute -right-6 top-2 size-24 rounded-full bg-foreground/5 blur-2xl" />

            <div className="relative flex items-center gap-4">
              <div className="flex items-center gap-3 pr-4 border-r border-border/40">
                <div className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-medium font-mono tabular-nums shadow-[inset_0_1px_0_rgba(255,255,255,0.18)]">
                  {selectedDocIds.length}
                </div>
                <span className="text-[13px] font-medium text-foreground/90 whitespace-nowrap">
                  {t('selection.selectedCount', {
                    count: selectedDocIds.length,
                  })}
                </span>
              </div>

              <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5 pr-0.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-full px-4 text-xs font-medium hover:bg-muted/60"
                  onClick={toggleSelectAllVisible}
                >
                  {allVisibleSelected
                    ? t('selection.clearSelectAll')
                    : t('selection.selectAllVisible')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-full px-4 text-xs font-medium hover:bg-muted/60"
                  onClick={() => setSelectedDocIds([])}
                >
                  {t('actions.clearSelection')}
                </Button>
                <div className="w-px h-4 bg-border/40 mx-1" />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-full px-4 text-xs font-medium hover:bg-muted/60 text-primary"
                  onClick={() => detachPromise(runBatchReingest())}
                  disabled={
                    batchDeleting ||
                    batchLifecycleWorking ||
                    batchReingestWorking
                  }
                >
                  {batchReingestWorking ? (
                    <Loader2 className="size-3 animate-spin mr-1.5" />
                  ) : (
                    <RefreshCw className="size-3 mr-1.5" />
                  )}
                  {batchReingestWorking
                    ? t('actions.reingesting')
                    : t('actions.reingest')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-full px-4 text-xs font-medium hover:bg-muted/60"
                  onClick={() => detachPromise(runBatchLifecycle('disable'))}
                  disabled={
                    batchDeleting ||
                    batchLifecycleWorking ||
                    !anySelectedEnabled
                  }
                >
                  {t('actions.disable')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-full px-4 text-xs font-medium hover:bg-muted/60"
                  onClick={() => detachPromise(runBatchLifecycle('enable'))}
                  disabled={
                    batchDeleting ||
                    batchLifecycleWorking ||
                    !anySelectedDisabled
                  }
                >
                  {t('actions.enable')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-full px-4 text-xs font-medium hover:bg-muted/60"
                  onClick={() => detachPromise(runBatchLifecycle('archive'))}
                  disabled={
                    batchDeleting ||
                    batchLifecycleWorking ||
                    !anySelectedNotArchived
                  }
                >
                  {t('actions.archive')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-full px-4 text-xs font-medium hover:bg-muted/60"
                  onClick={() => detachPromise(runBatchLifecycle('unarchive'))}
                  disabled={
                    batchDeleting ||
                    batchLifecycleWorking ||
                    !anySelectedArchived
                  }
                >
                  {t('actions.unarchive')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-9 rounded-full px-4 text-xs font-medium bg-destructive/5 text-destructive hover:bg-destructive/15"
                  onClick={() => setBatchDeleteOpen(true)}
                  disabled={batchDeleting || batchLifecycleWorking}
                >
                  <Trash2 className="size-3 mr-1.5" />
                  {t('actions.batchDelete')}
                </Button>
              </div>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AlertDialog open={batchDeleteOpen} onOpenChange={setBatchDeleteOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('batchDelete.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('batchDelete.description', { count: selectedDocIds.length })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setBatchDeleteOpen(false)}
              disabled={batchDeleting}
            >
              {t('actions.cancel')}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => detachPromise(confirmBatchDelete())}
              disabled={batchDeleting || selectedDocIds.length === 0}
            >
              {batchDeleting
                ? t('actions.deleting')
                : t('actions.confirmDelete')}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog
        open={Boolean(activeDrawerDoc)}
        onOpenChange={handleDrawerOpenChange}
      >
        <DialogContent className="left-auto right-0 top-0 h-dvh w-[min(480px,100vw)] max-w-[480px] translate-x-0 translate-y-0 rounded-none p-0 overflow-hidden">
          <DialogHeader className="border-b border-border/70 px-5 py-4 text-left">
            <DialogTitle className="text-[15px] font-semibold text-foreground">
              文档审查视图
            </DialogTitle>
            <DialogDescription className="text-[12px] text-muted-foreground/76">
              查看分块、检索与健康细节，不挤占主表格宽度。
            </DialogDescription>
          </DialogHeader>
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <KnowledgeInspector
              embedded
              selectedDocs={activeDrawerDoc ? [activeDrawerDoc] : []}
            />
          </div>
        </DialogContent>
      </Dialog>

      <div
        className={cn(
          'flex min-h-0 flex-col overflow-hidden rounded-[22px] border border-border/60 bg-card/56 shadow-[0_16px_36px_-32px_hsl(var(--primary)/0.26),0_0_0_1px_hsl(var(--card)/0.72)] dark:border-border/50 dark:bg-card/35',
          embedded && 'h-full flex-1',
          embedded ? 'h-full' : 'min-h-[560px]'
        )}
      >
        <div className="relative overflow-hidden border-b border-border/60 bg-[radial-gradient(circle_at_14%_0%,hsl(var(--primary)/0.045),transparent_34%),linear-gradient(180deg,hsl(var(--card)/0.88),hsl(var(--surface-2)/0.52))] px-4 pb-2 pt-3.5 dark:border-border/60 dark:bg-background/45">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--primary)/0.42),transparent)]" />
          <div className="pointer-events-none absolute right-8 top-4 h-20 w-40 rounded-full bg-info/10 blur-3xl" />
          <div className="relative z-10 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0 space-y-1.5">
              <div className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/72">
                <div
                  className={cn(
                    'flex size-6 items-center justify-center rounded-lg border border-border/60 bg-card/72 text-primary/80 dark:border-border/70 dark:bg-muted/35',
                    iconShellClassName
                  )}
                >
                  <span className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(135deg,rgba(255,255,255,0.3),transparent_52%)] opacity-80" />
                  <Database className="size-3.5" />
                </div>
                Document Inventory
              </div>
              <div className="text-[19px] font-semibold text-foreground">
                {selectedDatasetLabel || '全部知识库文档总览'}
              </div>
              <div className="max-w-3xl text-[12px] leading-5 text-muted-foreground/76">
                集中查看文档资产、状态分布、分块体量与健康卡入口，支持直接在当前面板完成搜索和排序。
              </div>
            </div>

            <div className="grid gap-1 sm:grid-cols-3 xl:min-w-[330px]">
              <motion.div
                whileHover={{ y: -1, scale: 1.003 }}
                whileTap={{ scale: 0.992 }}
                transition={{ type: 'spring', stiffness: 340, damping: 24 }}
                className={inventoryStatCardClassName}
              >
                <span className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-[linear-gradient(90deg,hsl(var(--primary)/0.16),hsl(var(--info)/0.46),hsl(var(--primary)/0.10))]" />
                <div className="text-[8px] font-medium uppercase tracking-[0.12em] text-muted-foreground/68">
                  当前可见
                </div>
                <div className="mt-0.5 font-mono text-[14px] tabular-nums text-foreground transition-transform duration-200 group-hover:scale-[1.02]">
                  {visibleDocumentsCount}
                </div>
                <div className="mt-0.5 text-[9px] text-muted-foreground/72">
                  当前列表结果
                </div>
              </motion.div>
              <motion.div
                whileHover={{ y: -1, scale: 1.003 }}
                whileTap={{ scale: 0.992 }}
                transition={{ type: 'spring', stiffness: 340, damping: 24 }}
                className={inventoryStatCardClassName}
              >
                <span className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-[linear-gradient(90deg,hsl(var(--primary)/0.10),hsl(var(--info)/0.42),hsl(var(--primary)/0.12))]" />
                <div className="text-[8px] font-medium uppercase tracking-[0.12em] text-muted-foreground/68">
                  已选择
                </div>
                <div className="mt-0.5 font-mono text-[14px] tabular-nums text-foreground transition-transform duration-200 group-hover:scale-[1.02]">
                  {selectedDocIds.length}
                </div>
                <div className="mt-0.5 text-[9px] text-muted-foreground/72">
                  批量操作范围
                </div>
              </motion.div>
              <motion.div
                whileHover={{ y: -1, scale: 1.003 }}
                whileTap={{ scale: 0.992 }}
                transition={{ type: 'spring', stiffness: 340, damping: 24 }}
                className={inventoryStatCardClassName}
              >
                <span className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-[linear-gradient(90deg,hsl(var(--primary)/0.10),hsl(var(--success)/0.34),hsl(var(--info)/0.18))]" />
                <div className="text-[8px] font-medium uppercase tracking-[0.12em] text-muted-foreground/68">
                  展示模式
                </div>
                <div className="mt-0.5 text-[11px] font-normal text-foreground/88">
                  {viewMode === 'list' ? '列表模式' : '网格模式'}
                </div>
                <div className="mt-0.5 text-[9px] text-muted-foreground/72">
                  {showDatasetColumn ? '跨数据集视图' : '单数据集视图'}
                </div>
              </motion.div>
            </div>
          </div>

          {scopeSummary ? <div className="mt-2.5">{scopeSummary}</div> : null}
        </div>

        <div
          className={cn(
            'flex min-h-0 flex-1 flex-col',
            embedded && 'bg-transparent p-0 dark:bg-transparent',
            compactEmptyInventory && 'p-2'
          )}
        >
          <div
            className={cn(
              'flex min-h-0 flex-1 flex-col overflow-hidden rounded-none border-0 bg-transparent shadow-none',
              compactEmptyInventory && 'overflow-visible'
            )}
          >
            <div className="border-b border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)/0.78),hsl(var(--surface-2)/0.42))] px-3 py-2.5 dark:border-border/60 dark:bg-muted/[0.12]">
              {inventoryToolbar}
              {opsOpen ? (
                <div className="mt-2.5 rounded-[16px] border border-border/60 bg-card/82 p-2 shadow-[0_14px_34px_-30px_hsl(var(--primary)/0.28)] dark:border-border/70 dark:bg-background/70">
                  <DocumentOperationsPanel
                    selectedDocumentIds={selectedDocIds}
                    datasetId={selectedDatasetId}
                    datasets={datasets}
                  />
                </div>
              ) : null}
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              {(() => {
            if (isLoading && isDatasetEmpty) {
              return (
                <div className="flex h-full min-h-[360px] items-center justify-center px-6 py-10 text-muted-foreground">
                  <div className="flex flex-col items-center gap-3">
                    <Loader2 className="size-8 animate-spin motion-reduce:animate-none" />
                    <p className="text-sm">{t('loading')}</p>
                  </div>
                </div>
              )
            }

            if (showEmptyState) {
              const emptyTitle = getEmptyTitle(isDatasetEmpty, docFilter)
              const emptyDescription = isDatasetEmpty
                ? '使用右上角「导入/新增」上传文档或创建连接器后，资产列表会在这里形成可检索的文档货架。'
                : '当前筛选条件没有命中文档，可以放宽范围、清空搜索，或切回全部数据集重新查看。'

              return (
                <div
                  data-knowledge-empty-shelf-dock="integrated-canvas"
                  className="flex min-h-0 flex-1 px-2 pb-2 pt-1.5"
                >
                  <div
                    data-knowledge-empty-shelf="true"
                    className="relative flex min-h-[clamp(220px,30vh,320px)] w-full flex-1 overflow-hidden rounded-[20px] border border-dashed border-info/18 bg-[radial-gradient(circle_at_50%_0%,rgba(59,130,246,0.12),transparent_44%)]"
                  >
                    <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(59,130,246,0.055)_1px,transparent_1px),linear-gradient(90deg,rgba(59,130,246,0.055)_1px,transparent_1px)] bg-[size:34px_34px]" />
                    <div className="pointer-events-none absolute -left-12 top-16 size-44 rounded-full bg-info/10 blur-3xl" />
                    <div className="pointer-events-none absolute -right-10 bottom-8 size-52 rounded-full bg-info/10 blur-3xl" />
                    <div className="absolute right-4 top-4 z-10">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-9 rounded-full border-info/15 bg-background/82 px-3 text-[11px] font-medium text-foreground/82 shadow-[0_12px_28px_-22px_hsl(var(--primary)/0.55)] backdrop-blur-md hover:border-info/25 hover:bg-background"
                            aria-label="查看入库指引"
                          >
                            入库指引
                            <ChevronDown className="ml-1.5 size-3.5 text-muted-foreground/65" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="end"
                          sideOffset={10}
                          className="w-[330px] rounded-[18px] border-border/60 bg-card/95 p-2 shadow-[0_24px_64px_-34px_hsl(var(--foreground)/0.28)] backdrop-blur-xl dark:border-border/70 dark:bg-background/95"
                        >
                          <div className="rounded-[14px] border border-border/60 bg-muted/30 px-3 py-2.5 dark:border-border/70 dark:bg-muted/20">
                            <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-info/70">
                              Empty Shelf Guide
                            </div>
                            <div className="mt-1 text-[12px] font-medium text-foreground">
                              空数据集下一步
                            </div>
                          </div>
                          <div className="mt-2 space-y-1.5">
                            <div className="rounded-[14px] px-3 py-2.5 text-left transition-colors hover:bg-muted/40 dark:hover:bg-muted/30">
                              <div className="flex items-center gap-2 text-[12px] font-medium text-foreground">
                                <Database className="size-4 text-info" />
                                导入路径
                              </div>
                              <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground/74">
                                从右上角「导入/新增」上传文件、批量 URL
                                或连接器任务，文档会自动绑定当前数据集。
                              </p>
                            </div>
                            <div className="rounded-[14px] px-3 py-2.5 text-left transition-colors hover:bg-muted/40 dark:hover:bg-muted/30">
                              <div className="flex items-center gap-2 text-[12px] font-medium text-foreground">
                                <Filter className="size-4 text-info" />
                                筛选路径
                              </div>
                              <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground/74">
                                当前左侧范围会影响列表结果；如果误选生命周期或状态，可以先清空筛选。
                              </p>
                            </div>
                            <div className="rounded-[14px] px-3 py-2.5 text-left transition-colors hover:bg-muted/40 dark:hover:bg-muted/30">
                              <div className="flex items-center gap-2 text-[12px] font-medium text-foreground">
                                <Layers className="size-4 text-info" />
                                质量路径
                              </div>
                              <p className="mt-1.5 text-[11px] leading-5 text-muted-foreground/74">
                                文档入库后可在这里查看分块数量、解析状态、健康卡和后续检索测试入口。
                              </p>
                            </div>
                          </div>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                    <div className="relative mx-auto flex h-full max-w-5xl flex-col items-center justify-center px-4 py-8 text-center">
                      <div className="relative mb-3 flex h-[72px] w-24 items-end justify-center">
                        <div className="absolute bottom-0 h-12 w-20 rounded-[20px] border border-info/20 bg-background/80 shadow-[0_20px_44px_-34px_hsl(var(--primary)/0.7)]" />
                        <div className="absolute bottom-3.5 h-10 w-[68px] rounded-[15px] border border-info/20 bg-info/10" />
                        <div className="absolute bottom-5 flex size-11 items-center justify-center rounded-[17px] border border-info/20 bg-background text-info shadow-[0_15px_26px_-20px_hsl(var(--primary)/0.6)]">
                          {isDatasetEmpty ? (
                            <Database className="size-5" />
                          ) : (
                            <Filter className="size-5" />
                          )}
                        </div>
                        <span className="absolute left-4 top-2 size-1.5 rounded-full bg-info/50" />
                        <span className="absolute right-3 top-7 size-1.5 rounded-full bg-info/50" />
                      </div>

                      <div className="inline-flex items-center rounded-full border border-info/15 bg-background/78 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.22em] text-info/70 dark:text-info/78">
                        Asset Shelf
                      </div>
                      <h3 className="mt-2.5 text-[21px] font-semibold text-foreground">
                        {emptyTitle}
                      </h3>
                      <p className="mt-1.5 max-w-2xl text-[13px] leading-5 text-muted-foreground/78">
                        {emptyDescription}
                      </p>

                      <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                        {isDatasetEmpty ? null : (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-10 rounded-[14px] border-border/70 bg-background px-4"
                            onClick={onClearFilters}
                          >
                            <RotateCcw className="mr-2 size-3.5" />
                            清空所有筛选
                          </Button>
                        )}

                        {selectedDatasetId && onSwitchToAllDatasets ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-10 rounded-[14px] px-4 text-[12px] font-medium"
                            onClick={onSwitchToAllDatasets}
                          >
                            回到全部数据集
                          </Button>
                        ) : null}

                        {!selectedDatasetId && hasActiveFilters ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-10 rounded-[14px] px-4 text-[12px] font-medium"
                            onClick={onSwitchToAllDatasets}
                          >
                            回到全部数据集
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                </div>
              )
            }

            if (viewMode === 'grid') {
              return (
                <div className={sectionInsetClassName}>
                  <div
                    aria-label={t('grid.ariaLabel')}
                    style={{
                      height: `${docsGridVirtualizer.getTotalSize()}px`,
                      width: '100%',
                      position: 'relative',
                    }}
                  >
                    {docsGridVirtualRows.map((virtualRow) => {
                      const cols = Math.max(1, docGridColumns)
                      const startIndex = virtualRow.index * cols
                      const rowDocs = filteredDocuments.slice(
                        startIndex,
                        startIndex + cols
                      )
                      const isLastRow = virtualRow.index === docGridRowCount - 1

                      return (
                        <div
                          key={virtualRow.key}
                          data-index={virtualRow.index}
                          ref={docsGridVirtualizer.measureElement}
                          style={{
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            width: '100%',
                            transform: `translateY(${virtualRow.start}px)`,
                          }}
                          className={isLastRow ? undefined : 'pb-5'}
                        >
                          <div
                            className={cn(
                              'grid items-stretch gap-5',
                              docsGridColsClassName
                            )}
                          >
                            {rowDocs.map(renderGridDocCard)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            }

            return (
              <>
                {/* className="group hover:bg-muted/20 transition-colors" */}
                <div className="min-h-0 flex-1 overflow-auto">
                    <table
                      aria-label={t('table.ariaLabel')}
                      className="w-full table-fixed text-sm text-left"
                    >
                      <colgroup>
                        <col className="w-9" />
                        <col />
                        {showDatasetColumn ? (
                          <col className="w-[10rem]" />
                        ) : null}
                        <col className="w-[6.5rem]" />
                        <col className="w-[6rem]" />
                        <col className="w-[4.5rem]" />
                        <col className="w-[6rem]" />
                        <col className="w-[6.5rem]" />
                        <col className="w-[8.5rem]" />
                      </colgroup>
                      <thead className="border-b border-border/60 bg-muted/30 text-[11px] uppercase text-muted-foreground/78 dark:border-border/60 dark:bg-muted/[0.16]">
                        <tr>
                          <th
                            colSpan={tableColumnCount}
                            className="sticky top-0 z-10 bg-card/95 px-3 py-2 font-medium dark:bg-background/90"
                          >
                            <div
                              className="grid items-center gap-3"
                              style={{
                                gridTemplateColumns: documentListGridTemplate,
                              }}
                            >
                              <div className={checkboxCellClassName}>
                                <input
                                  type="checkbox"
                                  className={checkboxInputClassName}
                                  checked={allVisibleSelected}
                                  onChange={toggleSelectAllVisible}
                                  aria-label={t('table.selectAllVisible')}
                                />
                              </div>
                              <div>{t('table.columns.name')}</div>
                              {showDatasetColumn ? (
                                <div>{t('table.columns.dataset')}</div>
                              ) : null}
                              <div>{t('table.columns.tags')}</div>
                              <div>{t('table.columns.status')}</div>
                              <div className="text-right tabular-nums">
                                {t('table.columns.chunks')}
                              </div>
                              <div className="text-right tabular-nums">
                                {t('table.columns.size')}
                              </div>
                              <div>{t('table.columns.uploadedAt')}</div>
                              <div className="text-right">
                                {t('table.columns.actions')}
                              </div>
                            </div>
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-card/95">
                        {docsTablePaddingTop > 0 ? (
                          <tr>
                            <td
                              colSpan={tableColumnCount}
                              className="p-0"
                              style={{ height: `${docsTablePaddingTop}px` }}
                            />
                          </tr>
                        ) : null}

                        {docsTableVirtualRows.map((virtualRow) => {
                          const doc = filteredDocuments[virtualRow.index]
                          if (!doc) return null
                          const badge = getStatusBadge(doc.status, t)
                          const tags = getUserTagsFromDocument(doc)
                          const fileType = getFileTypeMeta(doc)
                          const TypeIcon = fileType.icon
                          const datasetLabel =
                            datasetLabelById?.[doc.dataset_id || ''] || '-'
                          const metadataItems = [
                            { label: '数据集', value: datasetLabel },
                            {
                              label: '标签',
                              value: getDocumentTagSummary(tags),
                            },
                            {
                              label: '生命周期',
                              value: getDocumentLifecycleLabel(doc),
                            },
                            {
                              label: '来源',
                              value: getDocumentSourceLabel(doc),
                            },
                            {
                              label: '更新时间',
                              value: formatDate(
                                doc.updated_at || doc.created_at
                              ),
                            },
                          ]

                          return (
                            <tr
                              key={doc.id}
                              data-index={virtualRow.index}
                              ref={docsTableVirtualizer.measureElement}
                              className="group/row"
                            >
                              <td
                                colSpan={tableColumnCount}
                                className="px-3 py-1.5"
                              >
                                <div className="rounded-[18px] border border-border/60 bg-card/88 shadow-[0_14px_30px_-28px_hsl(var(--primary)/0.24)] transition-[border-color,box-shadow,transform] duration-150 group-hover/row:-translate-y-px group-hover/row:border-primary/20 group-hover/row:shadow-[0_20px_34px_-28px_hsl(var(--primary)/0.32)] dark:border-border/70 dark:bg-background/78">
                                  <div
                                    className="grid min-h-[64px] items-center gap-3 px-3 py-3"
                                    style={{
                                      gridTemplateColumns:
                                        documentListGridTemplate,
                                    }}
                                  >
                                    <div className={checkboxCellClassName}>
                                      <input
                                        type="checkbox"
                                        className={checkboxInputClassName}
                                        checked={selectedSet.has(doc.id)}
                                        onChange={() =>
                                          toggleDocSelection(doc.id)
                                        }
                                        aria-label={t('table.selectDocument', {
                                          filename: doc.filename,
                                        })}
                                      />
                                    </div>

                                    <div className="min-w-0">
                                      <div className="flex min-w-0 items-center gap-3">
                                        <div
                                          className={cn(
                                            'flex size-8 shrink-0 items-center justify-center rounded-[10px] border transition-transform duration-150 group-hover/row:scale-[1.03]',
                                            iconShellClassName,
                                            fileType.bg,
                                            fileType.border,
                                            fileType.color
                                          )}
                                        >
                                          <span className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(135deg,rgba(255,255,255,0.28),transparent_52%)] opacity-75" />
                                          <TypeIcon className="size-4.5" />
                                        </div>
                                        <div className="min-w-0 flex-1">
                                          <div
                                            className="mb-1 max-w-[360px] truncate text-[13px] font-medium leading-none text-foreground/90 xl:max-w-[440px]"
                                            title={doc.filename}
                                          >
                                            {doc.filename}
                                          </div>
                                          <div className="max-w-[360px] truncate font-mono text-[10px] uppercase tracking-[0.04em] text-muted-foreground/48 xl:max-w-[440px]">
                                            {doc.id}
                                          </div>
                                        </div>
                                      </div>
                                    </div>

                                    {showDatasetColumn ? (
                                      <div className="min-w-0 text-[12px] leading-5 text-muted-foreground/82">
                                        <span className="line-clamp-2">
                                          {datasetLabel}
                                        </span>
                                      </div>
                                    ) : null}

                                    <div className="min-w-0">
                                      {tags.length ? (
                                        <DocumentTags
                                          tags={tags}
                                          max={2}
                                          dense
                                        />
                                      ) : (
                                        <span className="text-[12px] text-muted-foreground/32">
                                          —
                                        </span>
                                      )}
                                    </div>

                                    <div className="min-w-0">
                                      <StatusBadge
                                        status={badge.status}
                                        label={badge.label}
                                        dense
                                        className="rounded-full bg-muted/50"
                                      />
                                    </div>

                                    <div className="text-right font-mono text-[11px] tabular-nums text-foreground/70">
                                      {doc.chunk_count ?? '0'}
                                    </div>
                                    <div className="text-right font-mono text-[11px] tabular-nums text-muted-foreground">
                                      {formatFileSize(doc.file_size)}
                                    </div>
                                    <div className="whitespace-nowrap font-mono text-[11px] tabular-nums text-muted-foreground">
                                      {formatDate(doc.created_at)}
                                    </div>
                                    <div className="flex items-center justify-end gap-1">
                                      <IconButton
                                        label="查看详情"
                                        variant="ghost"
                                        className="h-7 w-7 rounded-full text-muted-foreground transition-[transform,background-color,color,box-shadow] hover:scale-[1.04] hover:text-primary hover:bg-primary/8 hover:shadow-[0_8px_18px_-12px_hsl(var(--primary)/0.45)]"
                                        onClick={buildOpenInspectorHandler(doc)}
                                      >
                                        <Eye className="h-3.5 w-3.5" />
                                      </IconButton>

                                      <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        className="h-7 rounded-full px-2.5 text-[10px] font-medium text-primary hover:bg-primary/10"
                                        onClick={(event) => {
                                          event.stopPropagation()
                                          if (onPeek) onPeek(doc.id)
                                          else
                                            globalThis.window.open(
                                              `/chunk-preview?docId=${doc.id}`,
                                              '_blank'
                                            )
                                        }}
                                      >
                                        <Layers className="mr-1 size-3" />
                                        {peekChunksLabel}
                                      </Button>

                                      <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                          <IconButton
                                            label={t('actions.moreActions')}
                                            variant="ghost"
                                            className="h-7 w-7 rounded-full text-muted-foreground transition-[transform,background-color,color] hover:scale-[1.04] hover:text-foreground hover:bg-muted/70"
                                          >
                                            <MoreVertical className="h-3.5 w-3.5" />
                                          </IconButton>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent
                                          align="end"
                                          className="w-56 rounded-xl border-border/60 shadow-strong/10"
                                        >
                                          <DropdownMenuItem
                                            onSelect={() =>
                                              detachPromise(
                                                copyText(
                                                  doc.id,
                                                  t('toasts.copyDocumentId')
                                                )
                                              )
                                            }
                                          >
                                            {t('actions.copyDocumentId')}
                                          </DropdownMenuItem>
                                          <DropdownMenuItem
                                            onSelect={() =>
                                              detachPromise(
                                                copyText(
                                                  doc.filename,
                                                  t('toasts.copyFilename')
                                                )
                                              )
                                            }
                                          >
                                            {t('actions.copyFilename')}
                                          </DropdownMenuItem>
                                          <DropdownMenuItem asChild>
                                            <Link
                                              href={`/knowledge/${doc.id}/health`}
                                              className="flex items-center"
                                            >
                                              <Activity className="mr-2 h-4 w-4" />
                                              {t('actions.healthCard')}
                                            </Link>
                                          </DropdownMenuItem>
                                          <DropdownMenuSeparator />
                                          <DropdownMenuItem
                                            className="text-destructive focus:text-destructive"
                                            onSelect={() =>
                                              requestSingleDelete(doc)
                                            }
                                          >
                                            <Trash2 className="mr-2 h-4 w-4" />
                                            {t('actions.deleteDocument')}
                                          </DropdownMenuItem>
                                        </DropdownMenuContent>
                                      </DropdownMenu>
                                    </div>
                                  </div>

                                  <div className="mx-3 mb-3 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-[12px] border border-border/60 bg-muted/[0.18] px-3 py-2 text-[11px] text-muted-foreground/76">
                                    {metadataItems.map((item, index) => (
                                      <div
                                        key={item.label}
                                        className={cn(
                                          'flex min-w-0 items-center gap-2',
                                          index > 0 &&
                                            'border-l border-border/60 pl-3'
                                        )}
                                      >
                                        <span className="shrink-0 text-muted-foreground/56">
                                          {item.label}
                                        </span>
                                        <span className="min-w-0 truncate text-foreground/66">
                                          {item.value}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )
                        })}

                        {docsTablePaddingBottom > 0 ? (
                          <tr>
                            <td
                              colSpan={tableColumnCount}
                              className="p-0"
                              style={{ height: `${docsTablePaddingBottom}px` }}
                            />
                          </tr>
                        ) : null}
                      </tbody>
                    </table>
                  </div>
                  <div className="mt-auto flex items-center justify-end gap-3 border-t border-border/60 px-4 py-3">
                    <span className="text-[12px] text-muted-foreground/78">
                      显示 {pageStart}-{pageEnd} / 共 {visibleDocumentsCount} 条
                    </span>
                    <button
                      type="button"
                      className="inline-flex h-9 items-center rounded-[12px] border border-border/70 bg-background px-3 text-[12px] text-muted-foreground"
                    >
                      {pageSize} 条/页
                    </button>
                    <div className="inline-flex items-center gap-2">
                      <button
                        type="button"
                        className="inline-flex h-9 w-9 items-center justify-center rounded-[12px] border border-border/70 bg-background text-muted-foreground transition-colors hover:border-primary/20 hover:bg-primary/5 disabled:cursor-not-allowed disabled:text-muted-foreground/35"
                        disabled={!canGoPrevious}
                        aria-label="上一页"
                        onClick={() => onPageChange(page - 1)}
                      >
                        ‹
                      </button>
                      <span className="inline-flex h-9 min-w-[5.5rem] items-center justify-center rounded-[12px] bg-primary px-3 text-[12px] font-medium text-primary-foreground">
                        第 {page} / {pageCount} 页
                      </span>
                      <button
                        type="button"
                        className="inline-flex h-9 w-9 items-center justify-center rounded-[12px] border border-border/70 bg-background text-muted-foreground transition-colors hover:border-primary/20 hover:bg-primary/5 disabled:cursor-not-allowed disabled:text-muted-foreground/35"
                        disabled={!canGoNext}
                        aria-label="下一页"
                        onClick={() => onPageChange(page + 1)}
                      >
                        ›
                      </button>
                    </div>
                  </div>
                </>
            )
          })()}
        </div>
      </div>
    </div>
    </div>
    </div>
  )
}

function DocumentCard({
  doc,
  statusBadge,
  statusBarClassName,
  onRequestDelete,
  copyText,
  t,
  selected,
  onToggleSelect,
  onPeek,
}: Readonly<{
  doc: Document
  statusBadge: { status: StatusBadgeStatus; label: string }
  statusBarClassName: string
  onRequestDelete: (doc: Document) => void
  copyText: (text: string, okMsg: string) => void | Promise<void>
  t: TranslateFn
  selected: boolean
  onToggleSelect: () => void
  onPeek?: (docId: string) => void
}>) {
  const peekChunksLabel = (() => {
    const resolved = t('actions.peekChunks')
    return resolved === 'KnowledgeDocumentsPanel.actions.peekChunks'
      ? '查看分块'
      : resolved
  })()
  const parserLabel = doc.metadata?.parser_backend
    ? getParserLabel(doc.metadata.parser_backend as string)
    : null
  const userTags = getUserTagsFromDocument(doc)
  const fileType = getFileTypeMeta(doc)
  const TypeIcon = fileType.icon
  const metadata = isRecord(doc.metadata) ? doc.metadata : {}
  const parseQuality = isRecord(metadata.parse_quality) ? metadata.parse_quality : {}
  const parseScoreRaw = parseQuality.score
  const parseScore =
    typeof parseScoreRaw === 'number' && Number.isFinite(parseScoreRaw)
      ? parseScoreRaw
      : null

  // 计算质量百分比和颜色
  const qualityPercent =
    parseScore === null ? null : Math.round(parseScore * 100)
  const qualityColor = getQualityColor(qualityPercent)

  return (
    <Panel
      padding="none"
      className={cn(
        'group relative flex h-full flex-col rounded-2xl overflow-hidden transition-all duration-300 motion-reduce:transition-none border-border/50 bg-card/40 backdrop-blur-sm',
        selected
          ? 'ring-2 ring-primary ring-offset-2 ring-offset-background border-primary/40 bg-primary/[0.03]'
          : 'hover:border-primary/30 hover:shadow-strong/10 hover:-translate-y-1'
      )}
    >
      <div className={cn('h-1 w-full', statusBarClassName)} />

      {/* Selection Checkbox */}
      <div
        className={cn(
          'absolute top-4 left-4 z-10 rounded-lg border border-border/60 bg-background/80 backdrop-blur-md p-1.5 transition-all duration-300',
          selected
            ? 'opacity-100 border-primary bg-primary/10'
            : contextualRevealClassName
        )}
      >
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-border/60 text-primary focus-ring cursor-pointer"
          checked={selected}
          onChange={onToggleSelect}
          aria-label={t('table.selectDocument', { filename: doc.filename })}
        />
      </div>

      <div className="p-6 flex-1 flex flex-col">
        <div className="flex items-start justify-between mb-5">
          <div className="relative">
            <div
              className={cn(
                'size-14 rounded-2xl flex items-center justify-center border shadow-sm transition-transform duration-500 group-hover:scale-110 group-hover:rotate-3',
                fileType.bg,
                fileType.border,
                fileType.color
              )}
            >
              <TypeIcon className="size-7" />
            </div>
            {/* Quality Indicator Mini-Ring */}
            {qualityPercent !== null && (
              <div
                className="absolute -bottom-1 -right-1 size-6 rounded-full bg-background border border-border/60 flex items-center justify-center shadow-sm"
                title={`解析质量: ${qualityPercent}%`}
              >
                <div
                  className={cn(
                    'text-[8px] font-medium font-mono tabular-nums',
                    qualityColor
                  )}
                >
                  {qualityPercent}
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <StatusBadge
              status={statusBadge.status}
              label={statusBadge.label}
              dense
            />
            <div
              className={cn(
                'px-2 py-0.5 rounded-full text-[11px] font-medium uppercase border ',
                fileType.bg,
                fileType.color,
                fileType.border
              )}
            >
              {fileType.label}
            </div>
          </div>
        </div>

        <h3
          className="text-sm font-medium text-foreground leading-snug line-clamp-2 mb-3 min-h-[2.5rem] group-hover:text-primary transition-colors"
          title={doc.filename}
        >
          {doc.filename}
        </h3>

        {userTags.length ? (
          <DocumentTags tags={userTags} max={3} dense className="mb-4" />
        ) : null}

        <div className="grid grid-cols-2 gap-3 mt-auto pt-4 border-t border-border/40">
          <div className="space-y-0.5">
            <p className="text-[11px] font-medium uppercase text-muted-foreground/50">
              {t('row.size')}
            </p>
            <p className="text-xs font-medium font-mono tabular-nums text-foreground/80">
              {formatFileSize(doc.file_size)}
            </p>
          </div>
          <div className="space-y-0.5">
            <p className="text-[11px] font-medium uppercase text-muted-foreground/50">
              {t('row.chunks')}
            </p>
            <p className="text-xs font-medium font-mono tabular-nums text-foreground/80">
              {doc.chunk_count ?? '-'}
            </p>
          </div>
        </div>
      </div>

      <div
        className={cn(
          'px-6 py-3.5 bg-muted/30 border-t border-border/40 flex items-center justify-between transition-all duration-300',
          contextualRevealClassName
        )}
      >
        <span className="text-[11px] text-muted-foreground/60 font-medium uppercase truncate max-w-[100px]">
          {parserLabel || t('row.parserAuto')}
        </span>
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 rounded-full px-3 text-[11px] font-medium text-primary hover:bg-primary/10"
            onClick={(e) => {
              e.stopPropagation()
              if (onPeek) onPeek(doc.id)
              else
                globalThis.window.open(
                  `/chunk-preview?docId=${doc.id}`,
                  '_blank'
                )
            }}
          >
            <Layers className="size-3 mr-1.5" />
            {peekChunksLabel}
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton
                label={t('actions.moreActions')}
                variant="ghost"
                className="h-8 w-8 rounded-full text-muted-foreground hover:text-foreground hover:bg-muted"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreVertical className="w-4 h-4" />
              </IconButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-56 rounded-xl border-border/60 shadow-strong/10"
            >
              <DropdownMenuItem
                onSelect={() =>
                  detachPromise(copyText(doc.id, t('toasts.copyDocumentId')))
                }
              >
                {t('actions.copyDocumentId')}
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() =>
                  detachPromise(
                    copyText(doc.filename, t('toasts.copyFilename'))
                  )
                }
              >
                {t('actions.copyFilename')}
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link
                  href={`/knowledge/${doc.id}/health`}
                  className="flex items-center"
                >
                  <Activity className="mr-2 h-4 w-4" />
                  {t('actions.healthCard')}
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={() => onRequestDelete(doc)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                {t('actions.deleteDocument')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {statusBadge.status === 'processing' ? (
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-muted/40">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${doc.processing_progress || 60}%` }}
            className="h-full bg-primary shadow-[0_0_8px_rgba(var(--primary),0.5)]"
          />
        </div>
      ) : null}
    </Panel>
  )
}
