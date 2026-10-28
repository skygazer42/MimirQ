'use client'

import { useCallback, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { FeedbackToast } from '@/components/feedback-toast'

import {
  Activity, AlertCircle, ArrowUpRight, CheckCircle, ChevronLeft, ChevronRight,
  Clock, Copy, Eye, FileStack, Layers, Loader2, Lock, MoreHorizontal,
  Globe, Link as LinkIcon, RefreshCw, Trash2, Upload,
} from '@/components/icons'
import { DocumentOperationsPanel } from '@/components/documents/document-operations-panel'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
import type { KnowledgeImportSource } from '@/components/knowledge/knowledge-workbench-actions'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { IconButton } from '@/components/ui/icon-button'
import {
  AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Link } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { cn, detachPromise, formatDate, formatFileSize } from '@/lib/utils'
import type { Dataset, Document } from '@/types'

import styles from './knowledge-page.module.css'

type KnowledgeDocumentsPanelProps = {
  isLoading: boolean
  error?: string | null
  documents: Document[]
  totalDocumentsCount: number
  totalChunks?: number
  datasets: Dataset[]
  selectedDatasetId?: string
  selectedDatasetLabel?: string
  datasetLabelById: Record<string, string>
  hasActiveFilters: boolean
  showImportIntro: boolean
  onImportSource: (source: KnowledgeImportSource) => void
  onClearFilters: () => void
  onSwitchToAllDatasets: () => void
  onImport: () => void
  onRefresh: () => Promise<void>
  page: number
  pageSize: number
  pageCount: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  selectedDocIds: string[]
  setSelectedDocIds: (ids: string[]) => void
  selectedSet: Set<string>
  allVisibleSelected: boolean
  toggleSelectAllVisible: () => void
  toggleDocSelection: (id: string) => void
  batchDeleteOpen: boolean
  setBatchDeleteOpen: (open: boolean) => void
  batchDeleteError: string | null
  batchDeleting: boolean
  confirmBatchDelete: () => Promise<void>
  batchLifecycleWorking: boolean
  batchReingestWorking: boolean
  runBatchReingest: () => Promise<void>
  runBatchLifecycle: (action: 'enable' | 'disable' | 'archive' | 'unarchive') => Promise<void>
  anySelectedDisabled: boolean
  anySelectedEnabled: boolean
  anySelectedArchived: boolean
  anySelectedNotArchived: boolean
  deleteDocument: (id: string) => void | Promise<void>
  onOpenDocument: (id: string) => void
  onPeek: (id: string) => void
  operationsOpen: boolean
  setOperationsOpen: (open: boolean) => void
}

const STATUS_ICONS = {
  completed: CheckCircle,
  pending: Clock,
  processing: Loader2,
  failed: AlertCircle,
  quarantined: Lock,
  cancelled: AlertCircle,
  deleting: Loader2,
}

function getSourceFolder(doc: Document): string {
  const sourcePath = typeof doc.metadata?.source_path === 'string' ? doc.metadata.source_path : ''
  const normalized = sourcePath.replaceAll('\\', '/')
  const separator = normalized.lastIndexOf('/')
  return separator > 0 ? normalized.slice(0, separator) : ''
}

export function KnowledgeDocumentsPanel({
  isLoading, error, documents, totalDocumentsCount, totalChunks, datasets,
  selectedDatasetId, selectedDatasetLabel, datasetLabelById, hasActiveFilters, showImportIntro, onImportSource,
  onClearFilters, onSwitchToAllDatasets, onImport, onRefresh,
  page, pageSize, pageCount, onPageChange, onPageSizeChange,
  selectedDocIds, setSelectedDocIds, selectedSet, allVisibleSelected,
  toggleSelectAllVisible, toggleDocSelection,
  batchDeleteOpen, setBatchDeleteOpen, batchDeleteError, batchDeleting,
  confirmBatchDelete, batchLifecycleWorking, batchReingestWorking,
  runBatchReingest, runBatchLifecycle, anySelectedDisabled, anySelectedEnabled,
  anySelectedArchived, anySelectedNotArchived, deleteDocument,
  onOpenDocument, onPeek, operationsOpen, setOperationsOpen,
}: Readonly<KnowledgeDocumentsPanelProps>) {
  const t = useTranslations('KnowledgeDocumentsPanel')
  const stageT = useTranslations('TaskCenter.stages')
  const [activeDrawerDoc, setActiveDrawerDoc] = useState<Document | null>(null)
  const [singleDeleteDoc, setSingleDeleteDoc] = useState<Document | null>(null)
  const [singleDeleteWorking, setSingleDeleteWorking] = useState(false)
  const [singleDeleteError, setSingleDeleteError] = useState<string | null>(null)
  const returnFocusRef = useRef<HTMLButtonElement | null>(null)
  const moreButtonsRef = useRef(new Map<string, HTMLButtonElement>())
  const tableRef = useRef<HTMLDivElement | null>(null)
  const restoreFocus = (event: Event) => {
    event.preventDefault()
    if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus()
    else tableRef.current?.focus()
  }
  const batchWorking = batchDeleting || batchLifecycleWorking || batchReingestWorking
  const visibleSelectedCount = documents.filter(doc => selectedSet.has(doc.id)).length
  const showDatasetColumn = !selectedDatasetId
  const empty = !documents.length
  const activeDocument = documents.find(doc => doc.id === activeDrawerDoc?.id) ?? activeDrawerDoc

  const requestSingleDelete = (doc: Document) => {
    returnFocusRef.current = moreButtonsRef.current.get(doc.id) ?? null
    setSingleDeleteError(null)
    setSingleDeleteDoc(doc)
  }
  const confirmSingleDelete = useCallback(async () => {
    if (!singleDeleteDoc || singleDeleteWorking) return
    setSingleDeleteWorking(true)
    setSingleDeleteError(null)
    try {
      await deleteDocument(singleDeleteDoc.id)
      toast.success(t('toasts.deleteSuccess'))
      setSingleDeleteDoc(null)
      await onRefresh()
    } catch (err) {
      reportClientError('Failed to delete knowledge document', err)
      setSingleDeleteError(formatApiError(err, t('singleDelete.errorFallback')))
    } finally {
      setSingleDeleteWorking(false)
    }
  }, [deleteDocument, onRefresh, singleDeleteDoc, singleDeleteWorking, t])

  const copyText = async (text: string, success: string) => {
    try {
      await globalThis.navigator.clipboard.writeText(text)
      toast.success(success)
    } catch {
      toast.error(t('toasts.copyFailed'))
    }
  }

  const renderRow = (doc: Document) => {
    const fileType = getFileTypeMeta(doc)
    const TypeIcon = fileType.icon
    const StatusIcon = STATUS_ICONS[doc.status] || Clock
    const statusLabel = doc.status === 'cancelled' ? '已取消'
      : doc.status === 'deleting' ? '删除中' : t('status.' + doc.status)
    const datasetLabel = datasetLabelById[doc.dataset_id || ''] || '未分类'
    const folder = getSourceFolder(doc)
    const documentMeta = [
      fileType.label,
      folder,
      doc.archived_at ? '已归档' : doc.disabled_at ? '已禁用' : '',
    ].filter(Boolean).join(' · ')
    const needsAttention = doc.status === 'failed' || doc.status === 'quarantined'
    const progress = Math.round(Math.min(100, Math.max(0, doc.processing_progress || 0)))
    const stage = doc.current_stage === 'vector_write' ? 'indexing' : doc.current_stage
    const stageLabel = stage && stageT.has(stage) ? stageT(stage) : stage
    const stateDetail = needsAttention ? doc.error_message
      : doc.status === 'processing' ? [stageLabel, progress ? progress + '%' : null].filter(Boolean).join(' · ') : null
    const openDocument = () => needsAttention ? setActiveDrawerDoc(doc) : onOpenDocument(doc.id)

    return (
      <tr key={doc.id} data-document-row={doc.id} data-selected={selectedSet.has(doc.id)}>
        <td>
          <Checkbox
            className={styles.checkbox} checked={selectedSet.has(doc.id)}
            disabled={isLoading || batchWorking} onCheckedChange={() => toggleDocSelection(doc.id)}
            aria-label={t('table.selectDocument', { filename: doc.filename })}
          />
        </td>
        <td>
          <div className={styles.documentIdentity}>
            <TypeIcon appearance="color" aria-hidden="true" className={styles.fileIcon} />
            <div className={styles.documentCopy}>
              <button type="button" className={styles.documentName} title={doc.filename} onFocus={event => { returnFocusRef.current = event.currentTarget }} onClick={openDocument}>{doc.filename}</button>
              <div className={styles.documentMeta} title={documentMeta}>{documentMeta}</div>
              <div className={styles.mobileMeta}>{formatFileSize(doc.file_size)} · {doc.chunk_count ?? 0} 分块</div>
            </div>
          </div>
        </td>
        {showDatasetColumn ? <td className={cn(styles.datasetCell, styles.desktopColumn)} title={datasetLabel}>{datasetLabel}</td> : null}
        <td>
          <span className={styles.status} data-state={doc.status}>
            <StatusIcon aria-hidden="true" className={doc.status === 'processing' || doc.status === 'deleting' ? 'animate-spin motion-reduce:animate-none' : undefined} />
            {statusLabel}
          </span>
          {stateDetail ? <span className={styles.stateDetail} title={stateDetail}>{stateDetail}</span> : null}
        </td>
        <td className={cn(styles.numeric, styles.desktopColumn)}>{doc.chunk_count ?? '—'}</td>
        <td className={cn(styles.size, styles.desktopColumn)}>{formatFileSize(doc.file_size)}</td>
        <td className={cn(styles.date, styles.desktopColumn)} title={doc.created_at}>{formatDate(doc.created_at)}</td>
        <td>
          <div className={styles.rowActions}>
            <Button variant="ghost" className={styles.viewButton} onFocus={event => { returnFocusRef.current = event.currentTarget }} onClick={openDocument}>{needsAttention ? '查看原因' : '查看'}</Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button" variant="ghost" size="icon" className={styles.moreButton}
                  aria-label={doc.filename + '的更多操作'} disabled={isLoading || batchWorking}
                  ref={element => { if (element) moreButtonsRef.current.set(doc.id, element); else moreButtonsRef.current.delete(doc.id) }}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className={styles.actionMenu}>
                <DropdownMenuItem onSelect={() => onOpenDocument(doc.id)}><Eye className="size-4" />{t('actions.previewContent')}</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => { returnFocusRef.current = moreButtonsRef.current.get(doc.id) ?? null; setActiveDrawerDoc(doc) }}><FileStack className="size-4" />{t('actions.openInspector')}</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => onPeek(doc.id)}><Layers className="size-4" />{t('actions.peekChunks')}</DropdownMenuItem>
                <DropdownMenuItem asChild><Link href={'/knowledge/' + doc.id + '/health'}><Activity className="size-4" />{t('actions.healthCard')}</Link></DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.id, t('toasts.copyDocumentId')))}><Copy className="size-4" />{t('actions.copyDocumentId')}</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.filename, t('toasts.copyFilename')))}>{t('actions.copyFilename')}</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={() => requestSingleDelete(doc)}><Trash2 className="size-4" />{t('actions.deleteDocument')}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </td>
      </tr>
    )
  }

  return (
    <div className={styles.documents} aria-busy={isLoading}>
      {error && !isLoading && !empty && !singleDeleteDoc ? (
        <div className={styles.inlineError} role="alert"><span>{error}</span><Button variant="ghost" onClick={() => detachPromise(onRefresh())}>重试</Button></div>
      ) : null}
      {selectedDocIds.length ? (
        <div className={styles.selectionBar} role="region" aria-label="批量操作">
          <span aria-live="polite">{t('selection.selectedCount', { count: selectedDocIds.length })}</span>
          <Button variant="ghost" disabled={batchWorking} onClick={() => setSelectedDocIds([])}>{t('actions.clearSelection')}</Button>
          <Button variant="ghost" disabled={batchWorking} onClick={() => detachPromise(runBatchReingest())}>
            {batchReingestWorking ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            {batchReingestWorking ? t('actions.reingesting') : t('actions.reingest')}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" disabled={batchWorking}>生命周期</Button></DropdownMenuTrigger>
            <DropdownMenuContent className={styles.actionMenu}>
              <DropdownMenuItem disabled={!anySelectedEnabled} onSelect={() => detachPromise(runBatchLifecycle('disable'))}>{t('actions.disable')}</DropdownMenuItem>
              <DropdownMenuItem disabled={!anySelectedDisabled} onSelect={() => detachPromise(runBatchLifecycle('enable'))}>{t('actions.enable')}</DropdownMenuItem>
              <DropdownMenuItem disabled={!anySelectedNotArchived} onSelect={() => detachPromise(runBatchLifecycle('archive'))}>{t('actions.archive')}</DropdownMenuItem>
              <DropdownMenuItem disabled={!anySelectedArchived} onSelect={() => detachPromise(runBatchLifecycle('unarchive'))}>{t('actions.unarchive')}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="ghost" className="text-destructive" disabled={batchWorking} onClick={() => setBatchDeleteOpen(true)}><Trash2 className="size-3.5" />{t('actions.batchDelete')}</Button>
        </div>
      ) : null}

      {showImportIntro ? (
        <section className={styles.importIntro} aria-labelledby="knowledge-import-title" data-knowledge-import-intro="true">
          <div className={styles.importIntroInner}>
            <div className={styles.importIntroCopy}>
              <h2 id="knowledge-import-title">{selectedDatasetId ? t('empty.emptyDataset.title') : t('empty.blank.title')}</h2>
              <p>{selectedDatasetId
                ? '向「' + (selectedDatasetLabel || selectedDatasetId) + '」添加文件或网页内容。解析完成后即可检索。'
                : '添加文件或网页，解析后即可检索与引用。'}</p>
              {selectedDatasetId ? <Button variant="link" onClick={onSwitchToAllDatasets}>{t('empty.emptyDataset.actions.switchToAllDatasets')}<ArrowUpRight className="size-3.5" /></Button> : null}
            </div>
            <div className={styles.importOptions} aria-label="选择导入方式">
              <button type="button" className={styles.importOption} onClick={() => onImportSource('files')}>
                <Upload className={styles.importFileIcon} aria-hidden="true" />
                <span><strong>上传文件</strong><span>PDF、Word、Excel、Markdown 等格式</span></span>
                <ArrowUpRight aria-hidden="true" />
              </button>
              <button type="button" className={styles.importOption} onClick={() => onImportSource('url')}>
                <LinkIcon className={styles.importLinkIcon} aria-hidden="true" />
                <span><strong>导入网页</strong><span>通过网址导入单个页面</span></span>
                <ArrowUpRight aria-hidden="true" />
              </button>
              <button type="button" className={styles.importOption} onClick={() => onImportSource('crawl')}>
                <Globe className={styles.importWebIcon} aria-hidden="true" />
                <span><strong>采集网站</strong><span>按指定范围采集多个页面</span></span>
                <ArrowUpRight aria-hidden="true" />
              </button>
            </div>
          </div>
        </section>
      ) : <>
      <div className={styles.tableWorkspace}>
        <div className={styles.tableScroll} data-empty={empty} ref={tableRef} tabIndex={0} role="region" aria-label="文档表格">
          <table className={styles.table} aria-label={t('table.ariaLabel')}>
            <colgroup>
              <col className={styles.checkColumn} /><col className={styles.nameColumn} />
              {showDatasetColumn ? <col className={cn(styles.datasetColumn, styles.desktopColumn)} /> : null}
              <col className={styles.statusColumn} /><col className={cn(styles.chunksColumn, styles.desktopColumn)} />
              <col className={cn(styles.sizeColumn, styles.desktopColumn)} /><col className={cn(styles.dateColumn, styles.desktopColumn)} /><col className={styles.actionsColumn} />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">
                  <Checkbox
                    className={styles.checkbox}
                    checked={allVisibleSelected ? true : visibleSelectedCount ? 'indeterminate' : false}
                    disabled={isLoading || empty || batchWorking} onCheckedChange={toggleSelectAllVisible}
                    aria-label={t('table.selectAllVisible')}
                  />
                </th>
                <th scope="col">{t('table.columns.name')}</th>
                {showDatasetColumn ? <th scope="col" className={styles.desktopColumn}>所属数据集</th> : null}
                <th scope="col">处理状态</th>
                <th scope="col" className={cn(styles.numeric, styles.desktopColumn)}>{t('table.columns.chunks')}</th>
                <th scope="col" className={cn(styles.size, styles.desktopColumn)}>{t('table.columns.size')}</th>
                <th scope="col" className={cn(styles.date, styles.desktopColumn)}>{t('table.columns.uploadedAt')}</th>
                <th scope="col" className={styles.actionHeading}>{t('table.columns.actions')}</th>
              </tr>
            </thead>
            <tbody>{documents.map(renderRow)}</tbody>
          </table>
          {empty ? (
            <div className={styles.emptyState}>
              {error && !isLoading ? (
                <div className={styles.stateContent} role="alert">
                  <AlertCircle aria-hidden="true" /><h2>文档加载失败</h2><p>{error}</p>
                  <div className={styles.stateActions}><Button variant="outline" onClick={() => detachPromise(onRefresh())}>重试</Button></div>
                </div>
              ) : isLoading ? (
                <div className={styles.stateContent} role="status"><Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" /><p>加载文档…</p></div>
              ) : (
                <div className={styles.stateContent}>
                  <FileStack aria-hidden="true" />
                  <h2>{hasActiveFilters ? t('empty.filtered.title') : selectedDatasetId ? t('empty.emptyDataset.title') : t('empty.blank.title')}</h2>
                  <p>{hasActiveFilters ? t('empty.filtered.refinedDescription') : selectedDatasetId
                    ? '当前数据集「' + (selectedDatasetLabel || selectedDatasetId) + '」中还没有文档。'
                    : t('empty.blank.description')}</p>
                  <div className={styles.stateActions}>
                    {hasActiveFilters ? <Button variant="outline" onClick={onClearFilters}>{t('actions.clearFilters')}</Button> : <Button onClick={onImport}>导入文档</Button>}
                    {selectedDatasetId ? <Button variant="ghost" onClick={onSwitchToAllDatasets}>{t('empty.emptyDataset.actions.switchToAllDatasets')}</Button> : null}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>

      <footer className={styles.tableFooter} data-task-center-dock="true">
        <div className={styles.totals} aria-live="polite">
          <span>共 <strong>{totalDocumentsCount}</strong> 份文档</span>
          {typeof totalChunks === 'number' ? <><span aria-hidden="true">·</span><span><strong>{totalChunks}</strong> 个分块</span></> : null}
        </div>
        <div className={styles.pagination}>
          <Select value={String(pageSize)} onValueChange={value => onPageSizeChange(Number(value))} disabled={batchWorking}>
            <SelectTrigger aria-label="每页文档数" className={styles.pageSize}><SelectValue /></SelectTrigger>
            <SelectContent>{[10, 20, 50].map(size => <SelectItem key={size} value={String(size)}>{size} 条 / 页</SelectItem>)}</SelectContent>
          </Select>
          <nav className={styles.pageControls} aria-label="文档分页">
            <IconButton label="上一页" variant="ghost" className={styles.pageArrow} disabled={page <= 1 || isLoading || batchWorking} onClick={() => onPageChange(page - 1)}><ChevronLeft className="size-3.5" /></IconButton>
            <span className={styles.pageNumber} aria-current="page">{page}</span><span className={styles.pageOf}>/ {pageCount}</span>
            <IconButton label="下一页" variant="ghost" className={styles.pageArrow} disabled={page >= pageCount || isLoading || batchWorking} onClick={() => onPageChange(page + 1)}><ChevronRight className="size-3.5" /></IconButton>
          </nav>
        </div>
      </footer>
      </>}

      <AlertDialog open={Boolean(singleDeleteDoc)} onOpenChange={open => {
        if (open || singleDeleteWorking) return
        setSingleDeleteDoc(null)
        setSingleDeleteError(null)
      }}>
        <AlertDialogContent className="max-w-md" onCloseAutoFocus={restoreFocus}>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('singleDelete.title')}</AlertDialogTitle>
            <AlertDialogDescription>{singleDeleteDoc ? t('singleDelete.description', { filename: singleDeleteDoc.filename }) : null}</AlertDialogDescription>
          </AlertDialogHeader>
          <FeedbackToast type="error" message={singleDeleteError} id="knowledge-delete-feedback" />
          <AlertDialogFooter>
            <Button variant="outline" onClick={() => setSingleDeleteDoc(null)} disabled={singleDeleteWorking}>{t('actions.cancel')}</Button>
            <Button variant="destructive" onClick={() => detachPromise(confirmSingleDelete())} disabled={singleDeleteWorking || !singleDeleteDoc}>{singleDeleteWorking ? t('actions.deleting') : t('actions.confirmDelete')}</Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={batchDeleteOpen} onOpenChange={open => { if (!batchDeleting) setBatchDeleteOpen(open) }}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('batchDelete.title')}</AlertDialogTitle>
            <AlertDialogDescription>{t('batchDelete.description', { count: selectedDocIds.length })}</AlertDialogDescription>
          </AlertDialogHeader>
          <FeedbackToast type="error" message={batchDeleteError} id="knowledge-batch-delete-feedback" />
          <AlertDialogFooter>
            <Button variant="outline" disabled={batchDeleting} onClick={() => setBatchDeleteOpen(false)}>{t('actions.cancel')}</Button>
            <Button variant="destructive" disabled={batchDeleting || !selectedDocIds.length} onClick={() => detachPromise(confirmBatchDelete())}>{batchDeleting ? t('actions.deleting') : t('actions.confirmDelete')}</Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Sheet open={Boolean(activeDrawerDoc)} onOpenChange={open => { if (!open) setActiveDrawerDoc(null) }}>
        <SheetContent className={cn(styles.sheet, styles.detailsSheet)} onCloseAutoFocus={restoreFocus}>
          <SheetHeader className={styles.sheetHeader}>
            <SheetTitle>文档详情</SheetTitle>
            <SheetDescription className="sr-only">{activeDocument?.filename}</SheetDescription>
          </SheetHeader>
          <div className={styles.sheetBody}><KnowledgeInspector embedded selectedDocs={activeDocument ? [activeDocument] : []} datasetLabel={activeDocument?.dataset_id ? datasetLabelById[activeDocument.dataset_id] : undefined} /></div>
        </SheetContent>
      </Sheet>

      <Sheet open={operationsOpen} onOpenChange={setOperationsOpen}>
        <SheetContent className={cn(styles.sheet, styles.operationsSheet)}>
          <SheetHeader className={styles.sheetHeader}><SheetTitle>文档工具</SheetTitle><SheetDescription className="sr-only">文档统计、解析内容、重复文件与批量移动</SheetDescription></SheetHeader>
          <div className={styles.operationsBody}><DocumentOperationsPanel selectedDocumentIds={selectedDocIds} datasetId={selectedDatasetId} datasets={datasets} /></div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
