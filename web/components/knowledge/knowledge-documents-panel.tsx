'use client'

import type { Document } from '@/types'

import { Activity, AlertTriangle, Database, Eye, Filter, Loader2, MoreVertical, Trash2, Layers, RefreshCw, RotateCcw } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { useCallback, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { motion, AnimatePresence } from 'framer-motion'

import { EmptyState } from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { SearchInput } from '@/components/ui/search-input'
import { Panel } from '@/components/ui/panel'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import { DocumentTags } from '@/components/documents/document-tags'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
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
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Link } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatDate, formatFileSize, detachPromise } from '@/lib/utils'
import { getParserLabel } from '@/lib/parser-options'
import { getUserTagsFromDocument } from '@/lib/document-user-tags'
import { getFileTypeMeta } from '@/components/knowledge/file-type'

type ViewMode = 'grid' | 'list'
type DocSortKey = 'created_at' | 'filename' | 'file_size'
type DocSortDir = 'asc' | 'desc'
type TranslateFn = (key: string, values?: Record<string, any>) => string

type KnowledgeDocumentsPanelProps = {
  isLoading: boolean
  documents: Document[]
  filteredDocuments: Document[]
  embedded?: boolean

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
  onPeek?: (docId: string) => void
}

function getStatusBadge(status: string, t: TranslateFn): { status: StatusBadgeStatus; label: string } {
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
  onPeek,
}: Readonly<KnowledgeDocumentsPanelProps>) {
  const t = useTranslations('KnowledgeDocumentsPanel')
  const [activeDrawerDoc, setActiveDrawerDoc] = useState<Document | null>(null)
  const [singleDeleteDoc, setSingleDeleteDoc] = useState<Document | null>(null)
  const [singleDeleteWorking, setSingleDeleteWorking] = useState(false)
  const [singleDeleteError, setSingleDeleteError] = useState<string | null>(null)

  const docsGridColsClassName =
    docGridColumns >= 5
      ? 'grid-cols-5'
      : docGridColumns === 4
        ? 'grid-cols-4'
        : docGridColumns === 3
          ? 'grid-cols-3'
          : docGridColumns === 2
            ? 'grid-cols-2'
            : 'grid-cols-1'

  const showDatasetColumn = !selectedDatasetId
  const tableColumnCount = showDatasetColumn ? 9 : 8

  const docsGridVirtualRows = docsGridVirtualizer.getVirtualItems()
  const docsTableVirtualRows = docsTableVirtualizer.getVirtualItems()
  const docsTablePaddingTop = docsTableVirtualRows.length ? docsTableVirtualRows[0].start : 0
  const docsTablePaddingBottom = docsTableVirtualRows.length
    ? docsTableVirtualizer.getTotalSize() - docsTableVirtualRows[docsTableVirtualRows.length - 1].end
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
      toast.success(t("toasts.deleteSuccess"))
      setSingleDeleteDoc(null)
    } catch (err: any) {
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

  const copyText = useCallback(async (text: string, okMsg: string) => {
    try {
      await globalThis.navigator.clipboard.writeText(text)
      toast.success(okMsg)
    } catch {
      toast.error(t('toasts.copyFailed'))
    }
  }, [t])

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

  return (
    <div
      className={cn(
        'animate-in fade-in slide-in-from-bottom-4 duration-300 motion-reduce:animate-none motion-reduce:transition-none',
        embedded && 'h-full'
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
            <AlertDialogTitle>{singleDeleteDoc ? t('singleDelete.title') : t('singleDelete.titleDefault')}</AlertDialogTitle>
            <AlertDialogDescription>
              {singleDeleteDoc && (
                <div className="space-y-2">
                  <div>{t('singleDelete.description', { filename: singleDeleteDoc.filename })}</div>
                  <div className="text-xs text-muted-foreground font-mono break-all">{singleDeleteDoc.id}</div>
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
              {singleDeleteWorking ? t('actions.deleting') : t('actions.confirmDelete')}
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
            <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-background/95 via-background/78 to-background/95" />
            <div className="pointer-events-none absolute inset-x-10 top-0 h-px bg-white/30 dark:bg-white/10" />
            <div className="pointer-events-none absolute -left-8 top-1/2 size-28 -translate-y-1/2 rounded-full bg-primary/10 blur-3xl" />
            <div className="pointer-events-none absolute -right-6 top-2 size-24 rounded-full bg-foreground/5 blur-2xl" />

            <div className="relative flex items-center gap-4">
              <div className="flex items-center gap-3 pr-4 border-r border-border/40">
                <div className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold font-mono tabular-nums shadow-[inset_0_1px_0_rgba(255,255,255,0.18)]">
                  {selectedDocIds.length}
                </div>
                <span className="text-[13px] font-bold text-foreground/90 whitespace-nowrap">
                  {t('selection.selectedCount', { count: selectedDocIds.length })}
                </span>
              </div>

              <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5 pr-0.5">
                <Button type="button" variant="ghost" size="sm" className="h-9 rounded-full px-4 text-xs font-bold hover:bg-muted/60" onClick={toggleSelectAllVisible}>
                  {allVisibleSelected ? t('selection.clearSelectAll') : t('selection.selectAllVisible')}
                </Button>
                <Button type="button" variant="ghost" size="sm" className="h-9 rounded-full px-4 text-xs font-bold hover:bg-muted/60" onClick={() => setSelectedDocIds([])}>
                  {t('actions.clearSelection')}
                </Button>
                <div className="w-px h-4 bg-border/40 mx-1" />
                <Button type="button" variant="ghost" size="sm" className="h-9 rounded-full px-4 text-xs font-bold hover:bg-muted/60 text-primary" onClick={() => detachPromise(runBatchReingest())} disabled={batchDeleting || batchLifecycleWorking || batchReingestWorking}>
                  {batchReingestWorking ? <Loader2 className="size-3 animate-spin mr-1.5" /> : <RefreshCw className="size-3 mr-1.5" />}
                  {batchReingestWorking ? t('actions.reingesting') : t('actions.reingest')}
                </Button>
                <Button type="button" variant="ghost" size="sm" className="h-9 rounded-full px-4 text-xs font-bold hover:bg-muted/60" onClick={() => detachPromise(runBatchLifecycle('disable'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedEnabled}>
                  {t('actions.disable')}
                </Button>
                <Button type="button" variant="ghost" size="sm" className="h-9 rounded-full px-4 text-xs font-bold hover:bg-muted/60" onClick={() => detachPromise(runBatchLifecycle('enable'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedDisabled}>
                  {t('actions.enable')}
                </Button>
                <Button type="button" variant="ghost" size="sm" className="h-9 rounded-full px-4 text-xs font-bold hover:bg-muted/60" onClick={() => detachPromise(runBatchLifecycle('archive'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedNotArchived}>
                  {t('actions.archive')}
                </Button>
                <Button type="button" variant="ghost" size="sm" className="h-9 rounded-full px-4 text-xs font-bold hover:bg-muted/60" onClick={() => detachPromise(runBatchLifecycle('unarchive'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedArchived}>
                  {t('actions.unarchive')}
                </Button>
                <Button type="button" variant="ghost" size="sm" className="h-9 rounded-full px-4 text-xs font-bold bg-destructive/5 text-destructive hover:bg-destructive/15" onClick={() => setBatchDeleteOpen(true)} disabled={batchDeleting || batchLifecycleWorking}>
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
            <AlertDialogTitle>{t("batchDelete.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('batchDelete.description', { count: selectedDocIds.length })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button type="button" variant="outline" onClick={() => setBatchDeleteOpen(false)} disabled={batchDeleting}>
              {t('actions.cancel')}
            </Button>
            <Button type="button" variant="destructive" onClick={() => detachPromise(confirmBatchDelete())} disabled={batchDeleting || selectedDocIds.length === 0}>
              {batchDeleting ? t('actions.deleting') : t('actions.confirmDelete')}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {(() => {
                            if (isLoading && documents.length === 0) {
                                return (<div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
              <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none mb-3"/>
              <p className="text-sm">{t('loading')}</p>
            </div>);
                            }
                            if (filteredDocuments.length === 0) {
                                return (
                                  <div className="flex flex-col items-center justify-center min-h-[400px] px-6 py-12">
                                    <motion.div 
                                      initial={{ opacity: 0, y: 10, scale: 0.98 }}
                                      animate={{ opacity: 1, y: 0, scale: 1 }}
                                      className="flex flex-col items-center text-center max-w-sm"
                                    >
                                      <div className="relative mb-6">
                                        <div className="absolute inset-0 bg-primary/20 rounded-full blur-2xl opacity-50 animate-pulse" />
                                        <div className="relative size-20 rounded-3xl bg-background/80 border border-border/60 shadow-strong flex items-center justify-center backdrop-blur-md">
                                          <Filter className="size-8 text-primary/60" />
                                        </div>
                                      </div>

                                      <h3 className="text-lg font-bold tracking-tight text-foreground mb-2">
                                        {docFilter ? '未找到匹配的文档' : '当前筛选无结果'}
                                      </h3>
                                      <p className="text-sm font-medium text-muted-foreground/60 leading-relaxed mb-8">
                                        尝试调整筛选条件，或清空筛选后重新查看全部文档。
                                      </p>

                                      <div className="flex flex-col gap-3 w-full">
                                        <Button 
                                          type="button" 
                                          className="h-11 rounded-2xl bg-primary text-primary-foreground font-bold shadow-md shadow-primary/20 hover:scale-[1.02] transition-transform active:scale-[0.98]" 
                                          onClick={onClearFilters}
                                        >
                                          <RotateCcw className="mr-2 size-4" />
                                          清空所有筛选条件
                                        </Button>
                                        
                                        {!selectedDatasetId && hasActiveFilters && (
                                          <Button 
                                            variant="ghost" 
                                            className="h-10 rounded-xl text-xs font-bold text-muted-foreground/80 hover:text-foreground"
                                            onClick={onSwitchToAllDatasets}
                                          >
                                            回到“全部分类视图”
                                          </Button>
                                        )}
                                      </div>
                                    </motion.div>
                                  </div>
                                );
                            }
                            else if (viewMode === 'grid') {
                                    return (<div className={sectionInsetClassName}>
              <div aria-label={t('grid.ariaLabel')} style={{
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
		                      <div className={cn('grid items-stretch gap-5', docsGridColsClassName)}>
		                        {rowDocs.map(renderGridDocCard)}
		                      </div>
		                    </div>);
		                                        })}
              </div>
            </div>);
                                }
                                else {
                                    return (<div className={cn(embedded ? 'overflow-hidden border-t border-border/60 bg-background/15' : 'rounded-xl overflow-hidden')}>
	              <table aria-label={t('table.ariaLabel')} className="w-full table-fixed text-sm text-left">
                  <colgroup>
                    <col className="w-10" />
                    <col />
                    {showDatasetColumn ? <col className="w-[11rem]" /> : null}
                    <col className="w-[7.5rem]" />
                    <col className="w-[7rem]" />
                    <col className="w-[5rem]" />
                    <col className="w-[7rem]" />
                    <col className="w-[9rem]" />
                    <col className="w-[5.5rem]" />
                  </colgroup>
	                <thead className="border-b border-border/60 text-[11px] uppercase text-muted-foreground">
	                  <tr>
	                    <th className="sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium w-10">
	                      <input type="checkbox" className="h-4 w-4 rounded border-border/60 text-primary focus-ring" checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label={t('table.selectAllVisible')}/>
	                    </th>
	                    <th className="sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium">{t('table.columns.name')}</th>
	                    {showDatasetColumn ? (<th className="sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium">{t("table.columns.dataset")}</th>) : null}
	                    <th className="sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium">{t('table.columns.tags')}</th>
	                    <th className="sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium">{t('table.columns.status')}</th>
	                    <th className="sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium text-right tabular-nums">{t('table.columns.chunks')}</th>
	                    <th className="sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium text-right tabular-nums">{t('table.columns.size')}</th>
	                    <th className="sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium">{t('table.columns.uploadedAt')}</th>
	                    <th className="sticky top-0 z-10 bg-card/95 px-3 py-2.5 font-medium text-right">{t('table.columns.actions')}</th>
	                  </tr>
	                </thead>
	                <tbody className="divide-y divide-border/60">
		                  {docsTablePaddingTop > 0 ? (<tr>
		                      <td colSpan={tableColumnCount} className="p-0" style={{ height: `${docsTablePaddingTop}px` }}/>
		                    </tr>) : null}

	                  {docsTableVirtualRows.map((virtualRow: any) => {
	                                            const doc = filteredDocuments[virtualRow.index];
	                                            if (!doc) return null;
	                                            const badge = getStatusBadge(doc.status, t);
	                                            const tags = getUserTagsFromDocument(doc);
	                                            return (<tr key={doc.id} className="group/row hover:bg-muted/35 transition-colors">
	                        <td className="px-3 py-2.5">
	                          <input type="checkbox" className="h-4 w-4 rounded border-border/60 text-primary focus-ring" checked={selectedSet.has(doc.id)} onChange={() => toggleDocSelection(doc.id)} aria-label={t('table.selectDocument', { filename: doc.filename })}/>
	                        </td>
	                        <td className="px-3 py-2.5 min-w-0">
	                          <div className="flex items-center gap-3">
	                            <div className={cn('size-8 shrink-0 rounded-lg flex items-center justify-center border', getFileTypeMeta(doc).bg, getFileTypeMeta(doc).border, getFileTypeMeta(doc).color)}>
	                              {(() => { const Icon = getFileTypeMeta(doc).icon; return <Icon className="size-4.5"/>; })()}
	                            </div>
	                            <div className="min-w-0 flex-1">
	                              <div className="truncate font-bold text-foreground/90 leading-none mb-1" title={doc.filename}>{doc.filename}</div>
	                              <div className="text-[11px] font-mono text-muted-foreground/50 truncate uppercase tracking-tight">{doc.id}</div>
	                            </div>
	                          </div>
	                        </td>
	                        {showDatasetColumn ? (<td className="px-3 py-2.5">
	                            <div className="truncate text-xs text-muted-foreground font-medium">{datasetLabelById?.[doc.dataset_id || ''] || '-'}</div>
	                          </td>) : null}
	                        <td className="px-3 py-2.5">
	                          {tags.length ? <DocumentTags tags={tags} max={2} dense/> : <span className="text-muted-foreground/30">—</span>}
	                        </td>
	                        <td className="px-3 py-2.5">
	                          <StatusBadge status={badge.status} label={badge.label} dense/>
	                        </td>
	                        <td className="px-3 py-2.5 align-middle text-right text-xs font-mono tabular-nums font-semibold text-foreground/70">
	                          {doc.chunk_count ?? '0'}
	                        </td>
	                        <td className="px-3 py-2.5 align-middle text-right text-xs font-mono tabular-nums text-muted-foreground">
	                          {formatFileSize(doc.file_size)}
	                        </td>
	                        <td className="px-3 py-2.5">
	                          <div className="text-xs font-mono text-muted-foreground tabular-nums whitespace-nowrap">{formatDate(doc.created_at)}</div>
	                        </td>
	                        <td className="px-3 py-2.5 text-right">
	                          <div className="flex items-center justify-end gap-1">
                               <Button
                                 type="button"
                                 variant="ghost"
                                 size="sm"
                                 className="h-8 rounded-full px-3 text-[11px] font-bold text-primary hover:bg-primary/10"
                                 onClick={(e) => {
                                   e.stopPropagation()
                                   if (onPeek) onPeek(doc.id)
                                   else globalThis.window.open(`/chunk-preview?docId=${doc.id}`, '_blank')
                                 }}
                               >
                                 <Layers className="size-3 mr-1.5" />
                                 {t('actions.peekChunks')}
                               </Button>

	                            <DropdownMenu>
	                              <DropdownMenuTrigger asChild>
	                                <IconButton label={t('actions.moreActions')} variant="ghost" className="h-8 w-8 text-muted-foreground hover:text-foreground">
	                                  <MoreVertical className="w-4 h-4"/>
	                                </IconButton>
	                              </DropdownMenuTrigger>
	                              <DropdownMenuContent align="end" className="w-56 rounded-xl shadow-strong/10 border-border/60">
	                                <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.id, t('toasts.copyDocumentId')))}>{t('actions.copyDocumentId')}</DropdownMenuItem>
	                                <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.filename, t('toasts.copyFilename')))}>{t('actions.copyFilename')}</DropdownMenuItem>
	                                <DropdownMenuItem asChild>
	                                  <Link href={`/knowledge/${doc.id}/health`} className="flex items-center">
	                                    <Activity className="mr-2 h-4 w-4"/>
	                                    {t('actions.healthCard')}
	                                  </Link>
	                                </DropdownMenuItem>
	                                <DropdownMenuSeparator />
	                                <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={() => requestSingleDelete(doc)}>
	                                  <Trash2 className="mr-2 h-4 w-4"/>
	                                  {t('actions.deleteDocument')}
	                                </DropdownMenuItem>
	                              </DropdownMenuContent>
	                            </DropdownMenu>
	                          </div>
	                        </td>
	                      </tr>);
	                                            })}

	                  {docsTablePaddingBottom > 0 ? (<tr>
		                      <td colSpan={tableColumnCount} className="p-0" style={{ height: `${docsTablePaddingBottom}px` }}/>
		                    </tr>) : null}
	                </tbody>
	              </table>
	            </div>);
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
  const parserLabel = doc.metadata?.parser_backend ? getParserLabel(doc.metadata.parser_backend as string) : null
  const userTags = getUserTagsFromDocument(doc)
  const fileType = getFileTypeMeta(doc)
  const TypeIcon = fileType.icon
  const parseScoreRaw = (doc.metadata as any)?.parse_quality?.score
  const parseScore = typeof parseScoreRaw === 'number' && Number.isFinite(parseScoreRaw) ? parseScoreRaw : null
  
  // 计算质量百分比和颜色
  const qualityPercent = parseScore !== null ? Math.round(parseScore * 100) : null
  const qualityColor = qualityPercent !== null 
    ? qualityPercent > 80 ? 'text-emerald-500' : qualityPercent > 50 ? 'text-amber-500' : 'text-rose-500'
    : 'text-muted-foreground/20'

  return (
    <Panel
      padding="none"
      className={cn(
        "group relative flex h-full flex-col rounded-2xl overflow-hidden transition-all duration-300 motion-reduce:transition-none border-border/50 bg-card/40 backdrop-blur-sm",
        selected ? "ring-2 ring-primary ring-offset-2 ring-offset-background border-primary/40 bg-primary/[0.03]" : "hover:border-primary/30 hover:shadow-strong/10 hover:-translate-y-1"
      )}
    >
      <div className={cn('h-1 w-full', statusBarClassName)} />

      {/* Selection Checkbox */}
      <div
        className={cn(
          'absolute top-4 left-4 z-10 rounded-lg border border-border/60 bg-background/80 backdrop-blur-md p-1.5 transition-all duration-300',
          selected ? 'opacity-100 border-primary bg-primary/10' : contextualRevealClassName
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
            <div className={cn(
              'size-14 rounded-2xl flex items-center justify-center border shadow-sm transition-transform duration-500 group-hover:scale-110 group-hover:rotate-3', 
              fileType.bg, fileType.border, fileType.color
            )}>
              <TypeIcon className="size-7" />
            </div>
            {/* Quality Indicator Mini-Ring */}
            {qualityPercent !== null && (
              <div 
                className="absolute -bottom-1 -right-1 size-6 rounded-full bg-background border border-border/60 flex items-center justify-center shadow-sm"
                title={`解析质量: ${qualityPercent}%`}
              >
                <div className={cn("text-[8px] font-semibold font-mono tabular-nums tracking-tighter", qualityColor)}>
                  {qualityPercent}
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <StatusBadge status={statusBadge.status} label={statusBadge.label} dense />
            <div className={cn('px-2 py-0.5 rounded-full text-[11px] font-bold uppercase border tracking-wider', fileType.bg, fileType.color, fileType.border)}>
              {fileType.label}
            </div>
          </div>
        </div>

        <h3 className="text-sm font-bold text-foreground leading-snug line-clamp-2 mb-3 min-h-[2.5rem] group-hover:text-primary transition-colors" title={doc.filename}>
          {doc.filename}
        </h3>

        {userTags.length ? <DocumentTags tags={userTags} max={3} dense className="mb-4" /> : null}

        <div className="grid grid-cols-2 gap-3 mt-auto pt-4 border-t border-border/40">
          <div className="space-y-0.5">
            <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50">{t('row.size')}</p>
            <p className="text-xs font-semibold font-mono tabular-nums text-foreground/80">{formatFileSize(doc.file_size)}</p>
          </div>
          <div className="space-y-0.5">
            <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50">{t('row.chunks')}</p>
            <p className="text-xs font-semibold font-mono tabular-nums text-foreground/80">{doc.chunk_count ?? '-'}</p>
          </div>
        </div>
      </div>

      <div className={cn(
        'px-6 py-3.5 bg-muted/30 border-t border-border/40 flex items-center justify-between transition-all duration-300', 
        contextualRevealClassName
      )}>
        <span className="text-[11px] text-muted-foreground/60 font-bold uppercase tracking-widest truncate max-w-[100px]">
          {parserLabel || t('row.parserAuto')}
        </span>
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 rounded-full px-3 text-[11px] font-bold text-primary hover:bg-primary/10"
            onClick={(e) => {
              e.stopPropagation()
              if (onPeek) onPeek(doc.id)
              else globalThis.window.open(`/chunk-preview?docId=${doc.id}`, '_blank')
            }}
          >
            <Layers className="size-3 mr-1.5" />
            {t('actions.peekChunks')}
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
            <DropdownMenuContent align="end" className="w-56 rounded-xl border-border/60 shadow-strong/10">
              <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.id, t('toasts.copyDocumentId')))}>
                {t('actions.copyDocumentId')}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.filename, t('toasts.copyFilename')))}>
                {t('actions.copyFilename')}
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href={`/knowledge/${doc.id}/health`} className="flex items-center">
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
