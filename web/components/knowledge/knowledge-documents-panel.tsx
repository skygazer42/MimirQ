'use client'

import { useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { FeedbackToast } from '@/components/feedback-toast'

import {
  Activity,
  AlertCircle,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Copy,
  Eye,
  FileStack,
  Ingestion,
  Layers,
  Loader2,
  MoreHorizontal,
  Globe,
  Link as LinkIcon,
  RefreshCw,
  Trash2,
  Upload,
} from '@/components/icons'
import { DocumentOperationsPanel } from '@/components/documents/document-operations-panel'
import { KnowledgeInspector } from '@/components/knowledge/knowledge-inspector'
import type { KnowledgeImportSource } from '@/components/knowledge/knowledge-workbench-actions'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { IconButton } from '@/components/ui/icon-button'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { SplitEmptyStudio } from '@/components/ui/split-empty-studio'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Link } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { getDatasetDomainTone } from '@/lib/dataset-domain-tone'
import { cn, detachPromise, formatDate, formatFileSize } from '@/lib/utils'
import type { Dataset } from '@/types/datasets'
import type { Document } from '@/types/documents'

import styles from './knowledge-page.module.css'

type KnowledgeDocumentsPanelProps = {
  isLoading: boolean
  isPlaceholderData: boolean
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
  onFilesDrop: (files: File[]) => Promise<void>
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
  inspectorRailVisible: boolean
  inspectorSheetOpen: boolean
  onInspectorSheetOpenChange: (open: boolean) => void
  onInspectorRailOpenChange: (open: boolean) => void
}

function getSourceFolder(doc: Document): string | undefined {
  const sourcePath = doc.metadata?.source_path
  if (typeof sourcePath !== 'string') return undefined
  const normalized = sourcePath.replaceAll('\\', '/')
  const separator = normalized.lastIndexOf('/')
  return separator > 0 ? normalized.slice(0, separator) : undefined
}

export function KnowledgeDocumentsPanel({
  isLoading,
  isPlaceholderData,
  error,
  documents,
  totalDocumentsCount,
  totalChunks,
  datasets,
  selectedDatasetId,
  selectedDatasetLabel,
  datasetLabelById,
  hasActiveFilters,
  showImportIntro,
  onImportSource,
  onFilesDrop,
  onClearFilters,
  onSwitchToAllDatasets,
  onImport,
  onRefresh,
  page,
  pageSize,
  pageCount,
  onPageChange,
  onPageSizeChange,
  selectedDocIds,
  setSelectedDocIds,
  selectedSet,
  allVisibleSelected,
  toggleSelectAllVisible,
  toggleDocSelection,
  batchDeleteOpen,
  setBatchDeleteOpen,
  batchDeleteError,
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
  onOpenDocument,
  onPeek,
  operationsOpen,
  setOperationsOpen,
  inspectorRailVisible,
  inspectorSheetOpen,
  onInspectorSheetOpenChange,
  onInspectorRailOpenChange,
}: Readonly<KnowledgeDocumentsPanelProps>) {
  const t = useTranslations('KnowledgeDocumentsPanel')
  const stageT = useTranslations('TaskCenter.stages')
  const [isDragging, setIsDragging] = useState(false)
  const dragDepth = useRef(0)
  const [inspectedDocId, setInspectedDocId] = useState<string | null>(null)
  const [singleDeleteDoc, setSingleDeleteDoc] = useState<Document | null>(null)
  const [singleDeleteWorking, setSingleDeleteWorking] = useState(false)
  const [singleDeleteError, setSingleDeleteError] = useState<string | null>(null)
  const singleDeletePending = useRef(false)
  const returnFocusRef = useRef<HTMLButtonElement | null>(null)
  const moreButtonsRef = useRef(new Map<string, HTMLButtonElement>())
  const tableRef = useRef<HTMLDivElement | null>(null)
  const restoreFocus = (event: Event) => {
    event.preventDefault()
    if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus()
    else tableRef.current?.focus()
  }
  const batchWorking = batchDeleting || batchLifecycleWorking || batchReingestWorking
  const visibleSelectedCount = documents.filter((doc) => selectedSet.has(doc.id)).length
  const empty = !documents.length
  const inspectedDocument = documents.find((doc) => doc.id === inspectedDocId) ?? documents[0] ?? null
  const inspectedDataset = datasets.find((dataset) => dataset.id === inspectedDocument?.dataset_id)
  const showInspector = (doc: Document) => {
    setInspectedDocId(doc.id)
    returnFocusRef.current = moreButtonsRef.current.get(doc.id) ?? null
    if (globalThis.matchMedia('(min-width: 1280px)').matches) onInspectorRailOpenChange(true)
    else onInspectorSheetOpenChange(true)
  }

  const requestSingleDelete = (doc: Document) => {
    returnFocusRef.current = moreButtonsRef.current.get(doc.id) ?? null
    setSingleDeleteError(null)
    setSingleDeleteDoc(doc)
  }
  async function confirmSingleDelete() {
    if (singleDeleteDoc === null || singleDeletePending.current) return
    singleDeletePending.current = true
    setSingleDeleteWorking(true)
    setSingleDeleteError(null)
    try {
      await deleteDocument(singleDeleteDoc.id)
    } catch (error) {
      reportClientError('Failed to delete knowledge document', error)
      setSingleDeleteError(formatApiError(error, t('singleDelete.errorFallback')))
      return
    } finally {
      singleDeletePending.current = false
      setSingleDeleteWorking(false)
    }

    setSingleDeleteDoc(null)
    toast.success(t('toasts.deleteSuccess'))
    try {
      await onRefresh()
    } catch (error) {
      reportClientError('Failed to refresh knowledge documents after deletion', error)
      toast.error(formatApiError(error, t('toasts.refreshFailed')))
    }
  }

  const copyText = async (text: string, success: string) => {
    try {
      await globalThis.navigator.clipboard.writeText(text)
      toast.success(success)
    } catch {
      toast.error(t('toasts.copyFailed'))
    }
  }

  const renderRow = (doc: Document) => {
    const isSelected = selectedSet.has(doc.id)
    const fileType = getFileTypeMeta(doc)
    const TypeIcon = fileType.icon
    const statusLabel =
      doc.status === 'cancelled' ? '已取消' : doc.status === 'deleting' ? '删除中' : t('status.' + doc.status)
    const datasetId = doc.dataset_id
    const datasetLabel =
      datasetId === null || datasetId === undefined ? '未分类' : (datasetLabelById[datasetId] ?? datasetId)
    const dataset = datasets.find((dataset) => dataset.id === datasetId)
    const folder = getSourceFolder(doc)
    const lifecycleLabel = doc.archived_at ? '已归档' : doc.disabled_at ? '已禁用' : null
    const documentMeta = [folder, lifecycleLabel].filter((value) => value !== null && value !== undefined).join(' · ')
    const needsAttention = doc.status === 'failed' || doc.status === 'quarantined'
    const progress = Math.round(Math.min(100, Math.max(0, doc.processing_progress)))
    const stage = doc.current_stage === 'vector_write' ? 'indexing' : doc.current_stage
    const stageLabel = stage && stageT.has(stage) ? stageT(stage) : stage
    const stateDetail = needsAttention ? doc.error_message : null
    const openDocument = () => (needsAttention ? showInspector(doc) : onOpenDocument(doc.id))

    return (
      <tr
        key={doc.id}
        data-document-row={doc.id}
        data-selected={isSelected}
        data-inspected={inspectedDocument?.id === doc.id}
        onClick={(event) => {
          if (!(event.target as HTMLElement).closest('button, a, [role="checkbox"]') && !isPlaceholderData)
            setInspectedDocId(doc.id)
        }}
      >
        <td>
          <Checkbox
            className={styles.checkbox}
            checked={isSelected}
            disabled={isLoading || batchWorking}
            onCheckedChange={() => toggleDocSelection(doc.id)}
            aria-label={t('table.selectDocument', { filename: doc.filename })}
          />
        </td>
        <td>
          <div className={styles.documentIdentity}>
            <span className={cn(styles.fileBadge, fileType.bg)}>
              <TypeIcon appearance="color" aria-hidden="true" className={styles.fileIcon} />
            </span>
            <div className={styles.documentCopy}>
              <button
                type="button"
                className={styles.documentName}
                title={doc.filename}
                disabled={isPlaceholderData}
                onFocus={(event) => {
                  returnFocusRef.current = event.currentTarget
                }}
                onClick={openDocument}
              >
                {doc.filename}
              </button>
              {documentMeta ? (
                <div className={styles.documentMeta} title={documentMeta}>
                  {documentMeta}
                </div>
              ) : null}
              <div className={styles.mobileMeta}>
                {formatFileSize(doc.file_size)} · {doc.chunk_count} 分块
              </div>
            </div>
          </div>
        </td>
        <td className={cn(styles.datasetCell, styles.desktopColumn)} title={datasetLabel}>
          <span className={styles.datasetPill} data-tone={dataset ? getDatasetDomainTone(dataset) : undefined}>
            {datasetLabel}
          </span>
        </td>
        <td>
          <div className={styles.statusCell}>
            <span className={styles.status} data-state={doc.status} title={stateDetail ?? stageLabel ?? undefined}>
              <span className={styles.statusDot} aria-hidden="true" />
              {statusLabel}
            </span>
            {doc.status === 'processing' ? (
              <span className={styles.processingDetail} title={stageLabel ?? undefined}>
                <span
                  className={styles.progressTrack}
                  role="progressbar"
                  aria-label="文档处理进度"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={progress}
                >
                  <span style={{ width: `${progress}%` }} />
                </span>
                <span>{progress}%</span>
              </span>
            ) : null}
          </div>
        </td>
        <td className={cn(styles.numeric, styles.desktopColumn)}>{doc.chunk_count}</td>
        <td className={cn(styles.size, styles.desktopColumn)}>{formatFileSize(doc.file_size)}</td>
        <td className={cn(styles.date, styles.desktopColumn)} title={doc.created_at}>
          {formatDate(doc.created_at)}
        </td>
        <td>
          <div className={styles.rowActions}>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className={styles.moreButton}
                  aria-label={doc.filename + '的更多操作'}
                  disabled={isLoading || batchWorking}
                  ref={(element) => {
                    if (element) moreButtonsRef.current.set(doc.id, element)
                    else moreButtonsRef.current.delete(doc.id)
                  }}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className={styles.actionMenu}>
                <DropdownMenuItem onSelect={() => onOpenDocument(doc.id)}>
                  <Eye className="size-4" />
                  {t('actions.previewContent')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => {
                    returnFocusRef.current = moreButtonsRef.current.get(doc.id) ?? null
                    showInspector(doc)
                  }}
                >
                  <FileStack className="size-4" />
                  {t('actions.openInspector')}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => onPeek(doc.id)}>
                  <Layers className="size-4" />
                  {t('actions.peekChunks')}
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link href={'/knowledge/' + doc.id + '/health'}>
                    <Activity className="size-4" />
                    {t('actions.healthCard')}
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.id, t('toasts.copyDocumentId')))}>
                  <Copy className="size-4" />
                  {t('actions.copyDocumentId')}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => detachPromise(copyText(doc.filename, t('toasts.copyFilename')))}>
                  <Copy className="size-4" />
                  {t('actions.copyFilename')}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={() => requestSingleDelete(doc)}
                >
                  <Trash2 className="size-4" />
                  {t('actions.deleteDocument')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </td>
      </tr>
    )
  }

  const inspector = (
    <KnowledgeInspector
      key={inspectedDocument?.id}
      document={inspectedDocument}
      datasetLabel={inspectedDocument?.dataset_id ? datasetLabelById[inspectedDocument.dataset_id] : undefined}
      datasetTone={inspectedDataset ? getDatasetDomainTone(inspectedDataset) : undefined}
      onOpenDocument={(id) => {
        onInspectorSheetOpenChange(false)
        onOpenDocument(id)
      }}
      onPeek={(id) => {
        onInspectorSheetOpenChange(false)
        onPeek(id)
      }}
      onRefresh={onRefresh}
      onDelete={(doc) => {
        onInspectorSheetOpenChange(false)
        requestSingleDelete(doc)
      }}
    />
  )

  return (
    <>
      <div className={styles.documents} aria-busy={isLoading} data-inspector-open={inspectorRailVisible}>
        {error && !isLoading && !empty && !singleDeleteDoc ? (
          <WorkspaceNotice placement="floating" tone="warning" retry={() => detachPromise(onRefresh())} retryLabel="重试">
            {error}
          </WorkspaceNotice>
        ) : null}
        {selectedDocIds.length ? (
          <div className={styles.selectionBar} role="region" aria-label="批量操作">
            <span aria-live="polite">{t('selection.selectedCount', { count: selectedDocIds.length })}</span>
            <Button variant="ghost" disabled={batchWorking} onClick={() => setSelectedDocIds([])}>
              {t('actions.clearSelection')}
            </Button>
            <Button variant="ghost" disabled={batchWorking} onClick={() => detachPromise(runBatchReingest())}>
              {batchReingestWorking ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <RefreshCw className="size-3.5" />
              )}
              {batchReingestWorking ? t('actions.reingesting') : t('actions.reingest')}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" disabled={batchWorking}>
                  生命周期
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className={styles.actionMenu}>
                <DropdownMenuItem
                  disabled={!anySelectedEnabled}
                  onSelect={() => detachPromise(runBatchLifecycle('disable'))}
                >
                  {t('actions.disable')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={!anySelectedDisabled}
                  onSelect={() => detachPromise(runBatchLifecycle('enable'))}
                >
                  {t('actions.enable')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={!anySelectedNotArchived}
                  onSelect={() => detachPromise(runBatchLifecycle('archive'))}
                >
                  {t('actions.archive')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={!anySelectedArchived}
                  onSelect={() => detachPromise(runBatchLifecycle('unarchive'))}
                >
                  {t('actions.unarchive')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="ghost"
              className="text-destructive"
              disabled={batchWorking}
              onClick={() => setBatchDeleteOpen(true)}
            >
              <Trash2 className="size-3.5" />
              {t('actions.batchDelete')}
            </Button>
          </div>
        ) : null}

        <div className={styles.tableWorkspace}>
          <div
            className={styles.tableScroll}
            data-empty={empty}
            ref={tableRef}
            tabIndex={0}
            role="region"
            aria-label="文档表格"
          >
            {!showImportIntro ? (
              <table className={styles.table} aria-label={t('table.ariaLabel')}>
                <colgroup>
                  <col className={styles.checkColumn} />
                  <col className={styles.nameColumn} />
                  <col className={cn(styles.datasetColumn, styles.desktopColumn)} />
                  <col className={styles.statusColumn} />
                  <col className={cn(styles.chunksColumn, styles.desktopColumn)} />
                  <col className={cn(styles.sizeColumn, styles.desktopColumn)} />
                  <col className={cn(styles.dateColumn, styles.desktopColumn)} />
                  <col className={styles.actionsColumn} />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">
                      <Checkbox
                        className={styles.checkbox}
                        checked={allVisibleSelected ? true : visibleSelectedCount ? 'indeterminate' : false}
                        disabled={isLoading || empty || batchWorking}
                        onCheckedChange={toggleSelectAllVisible}
                        aria-label={t('table.selectAllVisible')}
                      />
                    </th>
                    <th scope="col">{t('table.columns.name')}</th>
                    <th scope="col" className={styles.desktopColumn}>
                      所属数据集
                    </th>
                    <th scope="col">处理状态</th>
                    <th scope="col" className={cn(styles.numeric, styles.desktopColumn)}>
                      {t('table.columns.chunks')}
                    </th>
                    <th scope="col" className={cn(styles.size, styles.desktopColumn)}>
                      {t('table.columns.size')}
                    </th>
                    <th scope="col" className={cn(styles.date, styles.desktopColumn)}>
                      {t('table.columns.uploadedAt')}
                    </th>
                    <th scope="col" className={styles.actionHeading}>
                      {t('table.columns.actions')}
                    </th>
                  </tr>
                </thead>
                <tbody>{documents.map(renderRow)}</tbody>
              </table>
            ) : null}
            {showImportIntro ? (
              <SplitEmptyStudio
                className={styles.emptyStudio}
                role="region"
                ariaLabel="文件上传区"
                ariaDescribedBy="knowledge-import-description"
                dataAttributes={{
                  'data-knowledge-import-intro': 'true',
                  'data-dragging': isDragging ? 'true' : 'false',
                }}
                onDragEnter={(event) => {
                  event.preventDefault()
                  dragDepth.current += 1
                  setIsDragging(true)
                }}
                onDragOver={(event) => {
                  event.preventDefault()
                  event.dataTransfer.dropEffect = 'copy'
                }}
                onDragLeave={(event) => {
                  event.preventDefault()
                  dragDepth.current -= 1
                  if (dragDepth.current === 0) setIsDragging(false)
                }}
                onDrop={(event) => {
                  event.preventDefault()
                  dragDepth.current = 0
                  setIsDragging(false)
                  const files = Array.from(event.dataTransfer.files)
                  if (files.length > 0) detachPromise(onFilesDrop(files))
                }}
                illustration={
                  <svg width="84" height="82" viewBox="0 0 84 82" fill="none">
                    <rect
                      x="18"
                      y="14"
                      width="48"
                      height="56"
                      rx="6"
                      fill="hsl(var(--surface-2))"
                      stroke="hsl(var(--border))"
                      strokeWidth="1.5"
                    />
                    <line x1="28" y1="28" x2="50" y2="28" stroke="hsl(var(--muted-foreground) / 0.45)" strokeWidth="2.4" strokeLinecap="round" />
                    <line x1="28" y1="37" x2="44" y2="37" stroke="hsl(var(--muted-foreground) / 0.32)" strokeWidth="2.4" strokeLinecap="round" />
                    <line x1="28" y1="46" x2="54" y2="46" stroke="hsl(var(--muted-foreground) / 0.25)" strokeWidth="2.4" strokeLinecap="round" />
                    <circle cx="58" cy="56" r="11" fill="hsl(var(--accent))" />
                    <path
                      d="M58 60.5v-9m0 0-3.5 3.5M58 51.5l3.5 3.5"
                      stroke="hsl(var(--accent-foreground))"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                }
                title={selectedDatasetId ? '当前数据集暂无文档' : '知识库暂无文档'}
                titleId="knowledge-import-title"
                description={
                  selectedDatasetId
                    ? `拖入 PDF、Word、Excel、Markdown 文件直接导入至「${selectedDatasetLabel || selectedDatasetId}」，或选择导入方式`
                    : '拖入 PDF、Word、Excel、Markdown 文件到此处，或选择导入方式'
                }
                descriptionId="knowledge-import-description"
                actions={
                  <>
                    <Button
                      className="bg-accent text-accent-foreground hover:bg-accent/90"
                      data-tone="knowledge"
                      onClick={() => onImportSource('files')}
                    >
                      <Upload className="size-3.5" aria-hidden="true" />
                      选择本地文件
                    </Button>
                    {selectedDatasetId ? (
                      <Button variant="outline" onClick={onSwitchToAllDatasets}>
                        {t('empty.emptyDataset.actions.switchToAllDatasets')}
                        <ArrowRight className="size-3.5" aria-hidden="true" />
                      </Button>
                    ) : null}
                  </>
                }
                shortcutsHeading="导入方式"
                shortcuts={[
                  {
                    key: 'url',
                    icon: <LinkIcon />,
                    title: '导入网页',
                    description: '输入单页 URL 抓取正文并自动切块入库',
                    ariaLabel: '导入网页',
                    onClick: () => onImportSource('url'),
                  },
                  {
                    key: 'crawl',
                    icon: <Globe />,
                    title: '采集网站',
                    description: '通过网站连接器按规则批量采集站点文档',
                    ariaLabel: '采集网站',
                    onClick: () => onImportSource('crawl'),
                  },
                  {
                    key: 'ingestion',
                    icon: <Ingestion />,
                    title: '入库管理工作台',
                    description: '配置解析引擎、去重策略与处理模式后批量入库',
                    href: '/knowledge/ingestion',
                  },
                ]}
                footerNote={{
                  label: '支持直接拖拽上传',
                  value: 'PDF · Word (.docx) · Excel (.xlsx) · Markdown · TXT · HTML',
                }}
              />
            ) : empty ? (
              <div className={styles.emptyState}>
                {error && !isLoading ? (
                  <div className={styles.stateContent} role="alert">
                    <AlertCircle aria-hidden="true" />
                    <h2>文档加载失败</h2>
                    <p>{error}</p>
                    <div className={styles.stateActions}>
                      <Button variant="outline" onClick={() => detachPromise(onRefresh())}>
                        重试
                      </Button>
                    </div>
                  </div>
                ) : isLoading ? (
                  <div className={styles.stateContent} role="status">
                    <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                    <p>加载文档…</p>
                  </div>
                ) : (
                  <div className={styles.stateContent}>
                    <FileStack aria-hidden="true" />
                    <h2>
                      {hasActiveFilters
                        ? t('empty.filtered.title')
                        : selectedDatasetId
                          ? t('empty.emptyDataset.title')
                          : t('empty.blank.title')}
                    </h2>
                    <p>
                      {hasActiveFilters
                        ? t('empty.filtered.refinedDescription')
                        : selectedDatasetId
                          ? '可向「' + (selectedDatasetLabel || selectedDatasetId) + '」导入文件或网页。'
                          : t('empty.blank.description')}
                    </p>
                    <div className={styles.stateActions}>
                      {hasActiveFilters ? (
                        <Button variant="outline" onClick={onClearFilters}>
                          {t('actions.clearFilters')}
                        </Button>
                      ) : (
                        <Button onClick={onImport}>导入文档</Button>
                      )}
                      {selectedDatasetId ? (
                        <Button variant="ghost" onClick={onSwitchToAllDatasets}>
                          {t('empty.emptyDataset.actions.switchToAllDatasets')}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>

        {!showImportIntro ? (
          <footer className={styles.tableFooter} data-task-center-dock="true">
          <div className={styles.totals} aria-live="polite">
            {isPlaceholderData ? (
              <span>正在更新文档列表…</span>
            ) : (
              <>
                <span>
                  共 <strong>{totalDocumentsCount}</strong> 份文档
                </span>
                {typeof totalChunks === 'number' ? (
                  <>
                    <span aria-hidden="true">·</span>
                    <span>
                      <strong>{totalChunks}</strong> 个分块
                    </span>
                  </>
                ) : null}
              </>
            )}
          </div>
          {totalDocumentsCount > 0 ? (
            <div className={styles.pagination}>
              <Select
                value={String(pageSize)}
                onValueChange={(value) => onPageSizeChange(Number(value))}
                disabled={batchWorking}
              >
                <SelectTrigger aria-label="每页文档数" className={styles.pageSize}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[10, 20, 50].map((size) => (
                    <SelectItem key={size} value={String(size)}>
                      {size} 条 / 页
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {pageCount > 1 || totalDocumentsCount > pageSize ? (
                <nav className={styles.pageControls} aria-label="文档分页">
                  <IconButton
                    label="上一页"
                    variant="ghost"
                    className={styles.pageArrow}
                    disabled={page <= 1 || isLoading || batchWorking}
                    onClick={() => onPageChange(page - 1)}
                  >
                    <ChevronLeft className="size-3.5" />
                  </IconButton>
                  <span className={styles.pageNumber} aria-current="page">
                    {page}
                  </span>
                  {isPlaceholderData ? null : <span className={styles.pageOf}>/ {pageCount}</span>}
                  <IconButton
                    label="下一页"
                    variant="ghost"
                    className={styles.pageArrow}
                    disabled={page >= pageCount || isLoading || batchWorking}
                    onClick={() => onPageChange(page + 1)}
                  >
                    <ChevronRight className="size-3.5" />
                  </IconButton>
                </nav>
              ) : null}
            </div>
          ) : null}
        </footer>
        ) : null}

        <AlertDialog
          open={Boolean(singleDeleteDoc)}
          onOpenChange={(open) => {
            if (open || singleDeleteWorking) return
            setSingleDeleteDoc(null)
            setSingleDeleteError(null)
          }}
        >
          <AlertDialogContent className="max-w-md" onCloseAutoFocus={restoreFocus}>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('singleDelete.title')}</AlertDialogTitle>
              <AlertDialogDescription>
                {singleDeleteDoc ? t('singleDelete.description', { filename: singleDeleteDoc.filename }) : null}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <FeedbackToast type="error" message={singleDeleteError} id="knowledge-delete-feedback" />
            <AlertDialogFooter>
              <Button variant="outline" onClick={() => setSingleDeleteDoc(null)} disabled={singleDeleteWorking}>
                {t('actions.cancel')}
              </Button>
              <Button
                variant="destructive"
                onClick={() => detachPromise(confirmSingleDelete())}
                disabled={singleDeleteWorking || !singleDeleteDoc}
              >
                {singleDeleteWorking ? t('actions.deleting') : t('actions.confirmDelete')}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <AlertDialog
          open={batchDeleteOpen}
          onOpenChange={(open) => {
            if (!batchDeleting) setBatchDeleteOpen(open)
          }}
        >
          <AlertDialogContent className="max-w-md">
            <AlertDialogHeader>
              <AlertDialogTitle>{t('batchDelete.title')}</AlertDialogTitle>
              <AlertDialogDescription>
                {t('batchDelete.description', { count: selectedDocIds.length })}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <FeedbackToast type="error" message={batchDeleteError} id="knowledge-batch-delete-feedback" />
            <AlertDialogFooter>
              <Button variant="outline" disabled={batchDeleting} onClick={() => setBatchDeleteOpen(false)}>
                {t('actions.cancel')}
              </Button>
              <Button
                variant="destructive"
                disabled={batchDeleting || !selectedDocIds.length}
                onClick={() => detachPromise(confirmBatchDelete())}
              >
                {batchDeleting ? t('actions.deleting') : t('actions.confirmDelete')}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
      {inspectorRailVisible ? (
        <aside className={styles.inspectorRail} aria-label="文档详情" data-knowledge-inspector-rail="true">
          <header className={styles.inspectorRailHeader}>
            <h2>文档详情</h2>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconButton
                  label="文档详情操作"
                  variant="ghost"
                  className={styles.toolIcon}
                  disabled={!inspectedDocument}
                >
                  <MoreHorizontal className="size-4" />
                </IconButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onSelect={() =>
                    inspectedDocument && detachPromise(copyText(inspectedDocument.id, t('toasts.copyDocumentId')))
                  }
                >
                  复制文档 ID
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() =>
                    inspectedDocument && detachPromise(copyText(inspectedDocument.filename, t('toasts.copyFilename')))
                  }
                >
                  复制文件名
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={() => inspectedDocument && requestSingleDelete(inspectedDocument)}
                >
                  删除文档
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </header>
          <div className={styles.sheetBody}>{inspector}</div>
        </aside>
      ) : null}
      <Sheet open={!inspectorRailVisible && inspectorSheetOpen} onOpenChange={onInspectorSheetOpenChange}>
        <SheetContent className={cn(styles.sheet, styles.detailsSheet)} onCloseAutoFocus={restoreFocus}>
          <SheetHeader className={styles.sheetHeader}>
            <SheetTitle>文档详情</SheetTitle>
            <SheetDescription className="sr-only">{inspectedDocument?.filename}</SheetDescription>
          </SheetHeader>
          <div className={styles.sheetBody}>{!inspectorRailVisible ? inspector : null}</div>
        </SheetContent>
      </Sheet>

      <Sheet open={operationsOpen} onOpenChange={setOperationsOpen}>
        <SheetContent className={cn(styles.sheet, styles.operationsSheet)}>
          <SheetHeader className={styles.sheetHeader}>
            <SheetTitle>文档工具</SheetTitle>
            <SheetDescription className="sr-only">文档统计、解析内容、重复文件与批量移动</SheetDescription>
          </SheetHeader>
          <div className={styles.operationsBody}>
            <DocumentOperationsPanel
              selectedDocumentIds={selectedDocIds}
              datasetId={selectedDatasetId}
              datasets={datasets}
              onRefresh={onRefresh}
            />
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
