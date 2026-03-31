'use client'

import type { Document } from '@/types'

import { Activity, AlertTriangle, Database, Eye, Filter, Loader2, MoreVertical, Trash2, Upload } from 'lucide-react'
import { useTranslations } from 'next-intl'
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
type TranslateFn = (key: string, values?: Record<string, any>) => string

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
  const t = useTranslations('KnowledgeDocumentsPanel')
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
  const sortOptions = [
    { value: 'created_at:desc', label: t('sort.createdDesc') },
    { value: 'created_at:asc', label: t('sort.createdAsc') },
    { value: 'filename:asc', label: t('sort.filenameAsc') },
    { value: 'filename:desc', label: t('sort.filenameDesc') },
    { value: 'file_size:desc', label: t('sort.fileSizeDesc') },
    { value: 'file_size:asc', label: t('sort.fileSizeAsc') },
  ]

  const singleDeleteTitle = useMemo(() => {
    if (!singleDeleteDoc) return t('singleDelete.titleDefault')
    return t('singleDelete.title')
  }, [singleDeleteDoc, t])

  const singleDeleteDescription = useMemo(() => {
    if (!singleDeleteDoc) return null
    return (
      <div className="space-y-2">
        <div>
          {t('singleDelete.description', { filename: singleDeleteDoc.filename })}
        </div>
        <div className="text-xs text-muted-foreground font-mono break-all">{singleDeleteDoc.id}</div>
      </div>
    )
  }, [singleDeleteDoc, t])

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
      if (!navigator.clipboard?.writeText) {
        toast.error(t('toasts.copyUnsupported'))
        return
      }
      await navigator.clipboard.writeText(text)
      toast.success(okMsg)
    } catch {
      toast.error(t('toasts.copyFailed'))
    }
  }, [t])

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
    const badge = getStatusBadge(doc.status, t)
    return (
      <div key={doc.id} className="h-full">
        <DocumentCard
          doc={doc}
          statusBadge={badge}
          statusBarClassName={statusBarClassName(badge.status)}
          onRequestDelete={requestSingleDelete}
          copyText={copyText}
          t={t}
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

      {(() => {
    if (isLoading && documents.length === 0) {
        return (<div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
          <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none mb-3"/>
          <p className="text-sm">{t('loading')}</p>
        </div>);
    }
    else if (documents.length === 0 && hasActiveFilters) {
            return (<div className="py-10">
          <EmptyState icon={Filter} title={t("empty.filtered.title")} description={<span className="text-muted-foreground">{t('empty.filtered.description')}</span>} className="bg-transparent shadow-none">
            <Button type="button" variant="outline" className="rounded-xl" onClick={onClearFilters}>
              {t("actions.clearFilters")}
            </Button>
          </EmptyState>
        </div>);
        }
        else if (documents.length === 0 && selectedDatasetId && onSwitchToAllDatasets) {
                return (<div className="py-10">
          <EmptyState icon={Database} title={t('empty.emptyDataset.title')} description={<span className="text-muted-foreground">
                {t("empty.emptyDataset.description", {
                  dataset: selectedDatasetLabel || selectedDatasetId,
                })}
              </span>} className="bg-transparent shadow-none">
            <Button type="button" variant="outline" className="rounded-xl" onClick={onSwitchToAllDatasets}>
              {t("empty.emptyDataset.actions.switchToAllDatasets")}
            </Button>
          </EmptyState>
        </div>);
            }
            else if (documents.length === 0) {
                    return (<div className="py-10">
          <EmptyState icon={Upload} title={t('empty.blank.title')} description={<span className="text-muted-foreground">
                {t('empty.blank.description')}
                <br />
                {t('empty.blank.formats')}
              </span>} className="bg-transparent shadow-none">
            <div>
              <Button size="lg" className="gap-2 rounded-xl shadow-sm" asChild>
                <span>
                  <Upload className="w-5 h-5"/>
                  {t('actions.uploadNow')}
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
              <SearchInput value={docFilter} onValueChange={setDocFilter} placeholder={t('search.placeholder')} containerClassName="w-full" inputClassName="h-9 rounded-lg border-border/60 bg-background placeholder:text-muted-foreground/60 focus:border-primary/40"/>

              <Select value={`${sortKey}:${sortDir}`} onValueChange={(value) => {
                            const [k, d] = String(value || '').split(':');
                            if (k === 'created_at' || k === 'filename' || k === 'file_size')
                                setSortKey(k);
                            if (d === 'asc' || d === 'desc')
                                setSortDir(d);
                        }}>
                <SelectTrigger className="h-9 w-full sm:w-[200px] rounded-lg border-border/60 bg-background" aria-label={t("sort.ariaLabel")}>
                  <SelectValue placeholder={t("sort.placeholder")}/>
                </SelectTrigger>
                <SelectContent>
                  {sortOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {scopeSummary ? <div className="text-xs">{scopeSummary}</div> : null}
          </div>

          {selectedDocIds.length > 0 ? (<div className="mb-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
              <div className="text-sm text-foreground">
                {t('selection.selectedCount', { count: selectedDocIds.length })}
              </div>
              <div className="flex flex-wrap items-center gap-2 justify-end">
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={toggleSelectAllVisible}>
                  {allVisibleSelected ? t('selection.clearSelectAll') : t('selection.selectAllVisible')}
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => setSelectedDocIds([])}>
                  {t('actions.clearSelection')}
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchReingest())} disabled={batchDeleting || batchLifecycleWorking || batchReingestWorking}>
                  {batchReingestWorking ? t('actions.reingesting') : t('actions.reingest')}
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchLifecycle('disable'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedEnabled}>
                  {t('actions.disable')}
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchLifecycle('enable'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedDisabled}>
                  {t('actions.enable')}
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchLifecycle('archive'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedNotArchived}>
                  {t('actions.archive')}
                </Button>
                <Button type="button" variant="outline" size="sm" className="rounded-xl" onClick={() => detachPromise(runBatchLifecycle('unarchive'))} disabled={batchDeleting || batchLifecycleWorking || !anySelectedArchived}>
                  {t('actions.unarchive')}
                </Button>
                <Button type="button" variant="destructive" size="sm" className="rounded-xl" onClick={() => setBatchDeleteOpen(true)} disabled={batchDeleting || batchLifecycleWorking}>
                  {t('actions.batchDelete')}
                </Button>
              </div>
            </div>) : null}

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
                            if (filteredDocuments.length === 0) {
                                return (<div className="py-10">
              <EmptyState icon={Filter} title={t("empty.filtered.title")} description={<span className="text-muted-foreground">{t('empty.filtered.refinedDescription')}</span>} className="bg-transparent shadow-none">
                <Button type="button" variant="outline" className="rounded-xl" onClick={onClearFilters}>
                  {t("actions.clearFilters")}
                </Button>
              </EmptyState>
            </div>);
                            }
	                            else if (viewMode === 'grid') {
	                                    return (<div aria-label={t('grid.ariaLabel')} style={{
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
            </div>);
                                }
                                else {
                                    return (<Panel padding="none" className="rounded-xl overflow-hidden">
	              <table aria-label={t('table.ariaLabel')} className="w-full text-sm text-left">
	                <thead className="text-xs text-muted-foreground uppercase border-b border-border/60">
	                  <tr>
	                    <th className="sticky top-0 z-10 bg-card px-3 py-3 font-medium w-10">
	                      <input type="checkbox" className="h-4 w-4 rounded border-border/60 text-primary focus-ring" checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label={t('table.selectAllVisible')}/>
	                    </th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">{t('table.columns.name')}</th>
	                    {showDatasetColumn ? (<th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">{t("table.columns.dataset")}</th>) : null}
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">{t('table.columns.tags')}</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">{t('table.columns.status')}</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium text-right">{t('table.columns.chunks')}</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium text-right">{t('table.columns.size')}</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium">{t('table.columns.uploadedAt')}</th>
	                    <th className="sticky top-0 z-10 bg-card px-4 py-3 font-medium text-right">{t('table.columns.actions')}</th>
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
	                                            const badge = getStatusBadge(doc.status, t);
                                            const fileType = getFileTypeMeta(doc);
                                            const TypeIcon = fileType.icon;
                                            const userTags = getUserTagsFromDocument(doc);
	                                            const sourcePath = String((doc.metadata as any)?.source_path || '').trim();
	                                            const parseScoreRaw = (doc.metadata as any)?.parse_quality?.score;
	                                            const parseScore = typeof parseScoreRaw === 'number' && Number.isFinite(parseScoreRaw) ? parseScoreRaw : null;
	                                            const parseLow = parseScore !== null && parseScore < 0.35;
	                                            return (<tr key={virtualRow.key} data-index={virtualRow.index} ref={docsTableVirtualizer.measureElement} className="group hover:bg-muted/20 transition-colors">
		                        <td className="px-3 py-3 align-middle">
		                          <input type="checkbox" className="h-4 w-4 rounded border-border/60 text-primary focus-ring" checked={selectedSet.has(doc.id)} onChange={buildToggleDocSelectionHandler(doc.id)} aria-label={t('table.selectDocument', { filename: doc.filename })}/>
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
	                                    title={t("row.parseQualityLow", { score: parseScore?.toFixed?.(3) ?? '—' })}
	                                  >
	                                    <AlertTriangle className="h-3.5 w-3.5" />
	                                  </span>
	                                ) : null}
	                              </div>
	                              {sourcePath ? (<button type="button" className={cn('mt-0.5 block max-w-[420px] truncate text-[11px] font-mono tabular-nums text-muted-foreground hover:text-foreground underline underline-offset-4 transition-opacity', contextualRevealClassName)} onClick={buildCopyHandler(sourcePath, t('toasts.copySourcePath'))} title={t('row.copySourcePathTitle')}>
	                                  {sourcePath}
	                                </button>) : null}
	                            </div>
	                          </div>
	                        </td>
	                        {showDatasetColumn ? (<td className="px-4 py-3 align-middle">
	                            {doc.dataset_id ? (<span className="text-xs text-muted-foreground truncate block max-w-[180px]" title={doc.dataset_id}>
	                                {datasetLabelById?.[doc.dataset_id] ?? doc.dataset_id}
	                              </span>) : (<span className="text-xs text-muted-foreground">{t('table.emptyValue')}</span>)}
	                          </td>) : null}
	                        <td className="px-4 py-3 align-middle">
	                          {userTags.length ? (<DocumentTags tags={userTags} max={3} dense/>) : (<span className="text-xs text-muted-foreground">{t('table.emptyValue')}</span>)}
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
	                          <DocumentDetailDialog document={doc} trigger={<IconButton label={t('actions.previewContent')} variant="ghost" className={cn('h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted transition-opacity', contextualRevealClassName)}>
	                                <Eye className="h-4 w-4"/>
	                              </IconButton>}/>

                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
	                              <IconButton label={t('actions.moreActions')} variant="ghost" className={cn('h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted transition-opacity', contextualRevealClassName)}>
	                                <MoreVertical className="h-4 w-4"/>
	                              </IconButton>
	                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-56">
                              <DropdownMenuItem onSelect={buildCopyHandler(doc.id, t('toasts.copyDocumentId'))}>
                                {t('actions.copyDocumentId')}
                              </DropdownMenuItem>
                              <DropdownMenuItem onSelect={buildCopyHandler(doc.filename, t('toasts.copyFilename'))}>
                                {t('actions.copyFilename')}
                              </DropdownMenuItem>
                              {sourcePath ? (<DropdownMenuItem onSelect={buildCopyHandler(sourcePath, t('toasts.copySourcePath'))}>
                                  {t('actions.copySourcePath')}
                                </DropdownMenuItem>) : null}
                              <DropdownMenuItem asChild>
                                <Link href={`/knowledge/${doc.id}/health`} className="flex items-center">
                                  <Activity className="mr-2 h-4 w-4" />
                                  {t('actions.healthCard')}
                                </Link>
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={buildRequestSingleDeleteHandler(doc)}>
                                <Trash2 className="mr-2 h-4 w-4"/>
                                {t('actions.deleteDocument')}
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
  t,
  selected,
  onToggleSelect,
}: Readonly<{
  doc: Document
  statusBadge: { status: StatusBadgeStatus; label: string }
  statusBarClassName: string
  onRequestDelete: (doc: Document) => void
  copyText: (text: string, okMsg: string) => void | Promise<void>
  t: TranslateFn
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
      className="group relative h-full rounded-2xl overflow-hidden hover:shadow-strong/20 hover:border-primary/30 transition-colors transition-shadow duration-200 motion-reduce:transition-none"
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
          aria-label={t('table.selectDocument', { filename: doc.filename })}
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
                title={t("row.parseQualityLow", { score: parseScore?.toFixed?.(3) ?? '—' })}
              >
                <AlertTriangle className="h-3.5 w-3.5" />
              </div>
            ) : null}
            {doc.disabled_at ? (
              <div className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border border-border/60 bg-muted/60 text-muted-foreground">
                {t('row.disabled')}
              </div>
            ) : null}
            {!doc.disabled_at && doc.archived_at ? (
              <div className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border border-border/60 bg-muted/60 text-muted-foreground">
                {t('row.archived')}
              </div>
            ) : null}
            <StatusBadge status={statusBadge.status} label={statusBadge.label} dense />
          </div>
        </div>

        <h3 className="font-semibold text-foreground line-clamp-2 mb-2 min-h-[2.5rem]" title={doc.filename}>
          {doc.filename}
        </h3>

        {userTags.length ? <DocumentTags tags={userTags} max={3} dense className="mb-3 flex-nowrap overflow-hidden" /> : null}

        <div className="space-y-2 mt-auto">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{t('row.size')}</span>
            <span className="font-mono">{formatFileSize(doc.file_size)}</span>
          </div>
	          <div className="flex items-center justify-between text-xs text-muted-foreground">
	            <span>{t('row.chunks')}</span>
	            <span className="font-mono tabular-nums">{doc.chunk_count ?? '-'}</span>
	          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{t('row.time')}</span>
            <span>{formatDate(doc.created_at)}</span>
          </div>
        </div>
      </div>

      <div className={cn('px-5 py-3 border-t border-border/60 bg-muted/20 flex items-center justify-between transition-opacity', contextualRevealClassName)}>
        <span className="text-[10px] text-muted-foreground font-medium truncate max-w-[80px]">{parserLabel || t('row.parserAuto')}</span>
        <div className="flex items-center gap-1">
          <DocumentDetailDialog
            document={doc}
            trigger={
              <IconButton
                label={t('actions.previewContent')}
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
                label={t('actions.moreActions')}
                variant="ghost"
                className="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreVertical className="w-4 h-4" />
              </IconButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.id, t('toasts.copyDocumentId')))}>
                {t('actions.copyDocumentId')}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.filename, t('toasts.copyFilename')))}>
                {t('actions.copyFilename')}
              </DropdownMenuItem>
              {String((doc.metadata as any)?.source_path || '').trim() ? (
                <DropdownMenuItem
                  onSelect={() =>
                    detachPromise(copyText(String((doc.metadata as any)?.source_path || ''), t('toasts.copySourcePath')))
                  }
                >
                  {t('actions.copySourcePath')}
                </DropdownMenuItem>
              ) : null}
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
