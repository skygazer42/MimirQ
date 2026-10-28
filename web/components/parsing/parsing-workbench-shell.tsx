'use client'

import { useCallback, useEffect, useMemo, type Dispatch, type RefObject, type SetStateAction } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, FolderOpen, FolderUp, Loader2, RotateCcw, Settings2, ShieldCheck, UploadCloud } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { AppFrame } from '@/components/app-frame'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { DocumentFolderTree, type DocumentTreeFileItem } from '@/components/document-library/folder-tree'
import { ParsingActiveFilePane } from './parsing-active-file-pane'
import { ParsingLibraryPreviewPane } from './parsing-library-preview-pane'
import { Button } from '@/components/ui/button'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Switch } from '@/components/ui/switch'
import { WorkbenchPanelDialog } from '@/components/workbench'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { ParsingElement } from '@/lib/api/parsing'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { UPLOAD_ACCEPT, UPLOAD_ACCEPT_WITH_ZIP } from '@/lib/upload-extensions'
import { cn, detachPromise } from '@/lib/utils'
import type { ParsingBlock } from '@/lib/parsing-positions'
import { type FolderNode, ROOT_FOLDER_ID, type ParsedFileData } from '@/store/use-parsed-files-store'
import { getLibraryStatusBadge } from './parsing-page-utils'
import type { ParsedFile, ParseRun } from './parsing-types'
import type { ParsingLibrarySourceStatus } from './use-parsing-page-state'
import styles from './parsing-compare.module.css'

type ParsingWorkbenchShellProps = {
  activeBlockId: string | null
  activeBlocksWithPositions: ParsingBlock[]
  activeFile: ParsedFile | null
  activeFileId: string | null
  activeFolderId: string
  activeLibraryFile: ParsedFileData | null
  activeLibraryFileId: string | null
  activeLibrarySourceStatus: ParsingLibrarySourceStatus
  activeMarkdown: string
  availableDatasets: DatasetScopeOption[]
  activeElements: ParsingElement[]
  activePdfQuality: unknown
  activeQualityGate: unknown
  activeRun: ParseRun | null
  copied: boolean
  copyMarkdown: () => Promise<void>
  currentFolderId: string
  dragOverFolderId: string | null
  downloadMarkdown: () => void
  editedContent: string
  fileInputRef: RefObject<HTMLInputElement | null>
  files: ParsedFile[]
  folderInputRef: RefObject<HTMLInputElement | null>
  folderPathById: Record<string, string>
  folders: FolderNode[]
  handleCancelEdit: () => void
  handleDeleteFolder: (folderIds: string[]) => void
  handleFileDragStart: (
    event: React.DragEvent<HTMLElement>,
    fileId: string
  ) => void
  handleFileSelect: (
    event: React.ChangeEvent<HTMLInputElement>
  ) => Promise<void>
  handleFolderDragLeave: () => void
  handleFolderDragOver: (
    event: React.DragEvent<HTMLElement>,
    folderId: string
  ) => void
  handleFolderDrop: (
    event: React.DragEvent<HTMLElement>,
    folderId: string
  ) => void
  handleRebindFileSelect: (
    event: React.ChangeEvent<HTMLInputElement>
  ) => Promise<void>
  handleSaveEdit: () => Promise<void>
  handleSelectRun: (runId: string) => void
  handleStartEdit: () => void
  handleSubmitToGovernance: () => void
  hoveredBlockId: string | null
  imageCaptionEnabled: boolean
  imageOcrEnabled: boolean
  inspectorOpen: boolean
  isEditing: boolean
  isLibraryLoaded: boolean
  isPdf: boolean
  isQueueRehydrating: boolean
  isSidebarCollapsed: boolean
  libraryFiles: ParsedFileData[]
  moveFileToFolder: (fileId: string, folderId: string) => void
  parseAllPending: () => Promise<void>
  parseFile: (fileId: string, backend?: string) => void
  parserBackend: string
  pdfPreviewResetToken: number
  previewMode: 'raw' | 'rendered'
  queueOpen: boolean
  rebindInputRef: RefObject<HTMLInputElement | null>
  removeFile: (fileId: string) => void
  requestRebindForLibraryFile: (libraryId: string, autoParse: boolean) => void
  requestUploadFolder: (folderId: string) => void
  requestUploadToFolder: (folderId: string) => void
  restoreLibraryFileFromCache: (
    libraryId: string,
    autoParse: boolean
  ) => Promise<void>
  rightPanelMode: 'blocks' | 'markdown'
  setActiveBlockId: (blockId: string | null) => void
  setActiveFileId: (fileId: string | null) => void
  setActiveFolderId: (folderId: string) => void
  setActiveLibraryFileId: (fileId: string | null) => void
  setEditedContent: (value: string) => void
  setHoveredBlockId: (blockId: string | null) => void
  setImageCaptionEnabled: (enabled: boolean) => void
  setImageOcrEnabled: (enabled: boolean) => void
  setInspectorOpen: (open: boolean) => void
  setIsSidebarCollapsed: (collapsed: boolean) => void
  setParserBackend: (backend: string) => void
  setPdfPreviewResetToken: Dispatch<SetStateAction<number>>
  setPreviewMode: (mode: 'raw' | 'rendered') => void
  setQueueOpen: (open: boolean) => void
  setQueueFileParserBackend: (params: {
    fileId: string
    filename: string
    backend: string
  }) => void
  setRightPanelMode: (mode: 'blocks' | 'markdown') => void
  selectedGovernanceFileIds: ReadonlySet<string>
  selectedDatasetId: string | null
  setVlmCorrectionEnabled: (enabled: boolean) => void
  onSubmitSelectedToGovernance: () => void
  onToggleGovernanceFileSelection: (fileId: string) => void
  onDatasetScopeChange: (datasetId: string | null) => void
  tocEnabled: boolean
  updateParsedFile: (
    id: string,
    updates: Partial<Omit<ParsedFileData, 'id'>>
  ) => void
  visibleLibraryOnlyFiles: ParsedFileData[]
  visibleQueueFiles: ParsedFile[]
  vlmCorrectionEnabled: boolean
}

type DatasetScopeOption = {
  id: string
  name: string
}

export function ParsingWorkbenchShell({
  activeBlockId,
  activeBlocksWithPositions,
  activeFile,
  activeFileId,
  activeFolderId,
  activeLibraryFile,
  activeLibraryFileId,
  activeLibrarySourceStatus,
  activeMarkdown,
  availableDatasets,
  activeElements,
  activePdfQuality,
  activeQualityGate,
  activeRun,
  copied,
  copyMarkdown,
  currentFolderId,

  downloadMarkdown,
  editedContent,
  fileInputRef,
  files,
  folderInputRef,
  folderPathById,

  handleCancelEdit,
  handleDeleteFolder,
  handleFileDragStart,
  handleFileSelect,
  handleFolderDragLeave,
  handleFolderDragOver,
  handleFolderDrop,
  handleRebindFileSelect,
  handleSaveEdit,
  handleSelectRun,
  handleStartEdit,
  handleSubmitToGovernance,
  hoveredBlockId,
  imageCaptionEnabled,
  imageOcrEnabled,
  inspectorOpen,
  isEditing,
  isLibraryLoaded,
  isPdf,
  isQueueRehydrating,

  libraryFiles,
  moveFileToFolder,
  parseAllPending,
  parseFile,
  parserBackend,
  pdfPreviewResetToken,
  previewMode,
  queueOpen,
  rebindInputRef,
  removeFile,
  requestRebindForLibraryFile,
  requestUploadFolder,
  requestUploadToFolder,
  restoreLibraryFileFromCache,
  rightPanelMode,
  setActiveBlockId,
  setActiveFileId,

  setActiveLibraryFileId,
  setEditedContent,
  setHoveredBlockId,
  setImageCaptionEnabled,
  setImageOcrEnabled,
  setInspectorOpen,

  setParserBackend,
  setPdfPreviewResetToken,
  setPreviewMode,
  setQueueOpen,
  setQueueFileParserBackend,
  setRightPanelMode,
  setVlmCorrectionEnabled,
  selectedGovernanceFileIds,
  selectedDatasetId,
  onSubmitSelectedToGovernance,
  onToggleGovernanceFileSelection,
  onDatasetScopeChange,

  updateParsedFile,
  visibleLibraryOnlyFiles,
  visibleQueueFiles,
  vlmCorrectionEnabled,
}: Readonly<ParsingWorkbenchShellProps>) {
  const t = useTranslations('ParsingWorkbench')
  const bumpPdfPreviewResetToken = () => setPdfPreviewResetToken((prev) => prev + 1)
  const pendingCount = visibleQueueFiles.filter(
    (file) => file.status === 'pending'
  ).length
  const parsingCount = visibleQueueFiles.filter(
    (file) => file.status === 'parsing'
  ).length
  const parsedCount = visibleQueueFiles.filter(
    (file) => file.status === 'parsed'
  ).length
  const parseableCount = visibleQueueFiles.filter(
    (file) =>
      file.librarySource !== 'knowledge_base' &&
      (file.status === 'pending' || file.status === 'error')
  ).length
  const currentFolderFileCount =
    visibleQueueFiles.length + visibleLibraryOnlyFiles.length
  const readyGovernanceFileIds = useMemo(
    () => [
      ...visibleQueueFiles
        .filter((file) => file.governanceStatus === 'ready')
        .map((file) => file.id),
      ...visibleLibraryOnlyFiles
        .filter((file) => file.governanceStatus === 'ready')
        .map((file) => file.id),
    ],
    [visibleLibraryOnlyFiles, visibleQueueFiles]
  )
  const readyGovernanceCount = readyGovernanceFileIds.length
  const selectedReadyGovernanceCount = readyGovernanceFileIds.filter((fileId) =>
    selectedGovernanceFileIds.has(fileId)
  ).length

  const activeFolderPathLabel =
    folderPathById[activeFolderId || ROOT_FOLDER_ID] || t('rootFolder')
  const activeLibraryFolderId = activeLibraryFile?.folderId || ROOT_FOLDER_ID
  const activeLibraryFolderPathLabel =
    folderPathById[activeLibraryFolderId] || t('rootFolder')
  const activeLibraryFolderName =
    (activeLibraryFolderPathLabel.split('/').pop() || '').trim() ||
    activeLibraryFolderPathLabel
  const activeLibraryStatusBadge = activeLibraryFile?.status
    ? getLibraryStatusBadge(t, activeLibraryFile.status)
    : null
  const filename = String(activeLibraryFile?.filename || '')
  const activeLibraryMarkdownAvailable = Boolean(
    (
      activeLibraryFile?.markdownContent ||
      activeLibraryFile?.originalMarkdownContent ||
      ''
    ).trim()
  )
  const shouldAutoRestoreLibraryPdf =
    !activeFile &&
    activeLibraryFile?.status === 'parsed' &&
    activeLibraryMarkdownAvailable &&
    filename.toLowerCase().endsWith('.pdf')

  const handleReprocessKnowledgeFile = useCallback(
    async (backend: string) => {
      if (!activeLibraryFile || activeLibraryFile.source !== 'knowledge_base') return

      const resolved = resolveParserBackendForFilename(activeLibraryFile.filename, backend)
      const parserLabel = getParserLabel(resolved.backend)

      updateParsedFile(activeLibraryFile.id, {
        error: undefined,
        markdownContent: '',
        originalMarkdownContent: '',
        parser: parserLabel,
        parserBackend: resolved.backend,
        status: 'parsing',
      })

      try {
        await documentApi.patchPipeline(activeLibraryFile.id, {
          patch: {
            persist_parsed_content: true,
            persist_parsed_content_max_chars: 2_000_000,
          },
          replace: false,
        })
        await documentApi.retry(activeLibraryFile.id, {
          force: true,
          parser_backend: resolved.backend,
        })
        toast.success('已开始解析')
      } catch (err: unknown) {
        const message = formatApiError(err, '开始解析失败')
        updateParsedFile(activeLibraryFile.id, {
          error: message,
          status: 'error',
        })
        toast.error(message)
      }
    },
    [activeLibraryFile, updateParsedFile]
  )

  useEffect(() => {
    if (activeFile || !activeLibraryFile) return
    if (!shouldAutoRestoreLibraryPdf) return

    detachPromise(restoreLibraryFileFromCache(activeLibraryFile.id, false))
  }, [
    activeFile,
    activeLibraryFile,
    restoreLibraryFileFromCache,
    shouldAutoRestoreLibraryPdf,
  ])
  const datasetDocumentCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const file of libraryFiles) {
      if (
        (file.source !== 'knowledge_base' && file.source !== 'parsing_workspace') ||
        !file.datasetId
      ) {
        continue
      }
      counts.set(file.datasetId, (counts.get(file.datasetId) || 0) + 1)
    }
    return counts
  }, [libraryFiles])
  const datasetOptions = useMemo(
    () =>
      availableDatasets.map((dataset) => ({
        ...dataset,
        count: datasetDocumentCounts.get(dataset.id) || 0,
      })),
    [availableDatasets, datasetDocumentCounts]
  )
  const sidebarFileItems = useMemo<DocumentTreeFileItem[]>(() => {
    const queueFiles = selectedDatasetId
      ? files.filter((file) => file.datasetId === selectedDatasetId)
      : files
    const libraryFilesForScope = selectedDatasetId
      ? libraryFiles.filter(
          (file) =>
            (file.source === 'knowledge_base' || file.source === 'parsing_workspace') &&
            file.datasetId === selectedDatasetId
        )
      : libraryFiles
    const queueLibraryIds = new Set(
      queueFiles
        .map((file) => file.libraryId)
        .filter((value): value is string => Boolean(value))
    )
    const merged: DocumentTreeFileItem[] = queueFiles.map((file) => ({
      id: file.id,
      name: file.name,
      folderId: file.folderId || ROOT_FOLDER_ID,
      sourcePath: file.sourcePath,
      status: file.status,
      error: file.error,
      progress: file.progress,
      parser: file.parserLabel,
      duration: file.duration,
      pageCount: file.stats?.pageCount,
      governanceStatus: file.governanceStatus,
      isActive: activeFileId === file.id,
      isSelectable: file.governanceStatus === 'ready',
      isSelected: selectedGovernanceFileIds.has(file.id),
    }))

    for (const file of libraryFilesForScope) {
      if (queueLibraryIds.has(file.id)) continue
      merged.push({
        id: file.id,
        name: file.filename,
        folderId: file.folderId || ROOT_FOLDER_ID,
        sourcePath: file.sourcePath || file.datasetName || undefined,
        status: file.status || 'parsed',
        parser: file.parser,
        duration: file.durationSec,
        governanceStatus: file.governanceStatus,
        isActive: activeLibraryFileId === file.id,
        isSelectable: file.governanceStatus === 'ready',
        isSelected: selectedGovernanceFileIds.has(file.id),
        readOnly: file.source === 'knowledge_base',
      })
    }

    return merged
  }, [
    activeFileId,
    activeLibraryFileId,
    files,
    libraryFiles,
    selectedGovernanceFileIds,
    selectedDatasetId,
  ])

  const selectFile = (fileId: string) => {
    if (isEditing) return
    bumpPdfPreviewResetToken()
    const queueMatch = files.find((file) => file.id === fileId || file.libraryId === fileId)
    if (queueMatch) {
      setActiveLibraryFileId(null)
      setActiveFileId(queueMatch.id)
    } else {
      setActiveFileId(null)
      setActiveLibraryFileId(fileId)
    }
    setQueueOpen(false)
  }
  const activeId = activeFile?.id || activeLibraryFile?.id
  const fileIndex = sidebarFileItems.findIndex((file) => file.id === activeId)
  const selectedFile = activeFile || activeLibraryFile
  const selectedFilename = activeFile?.name || activeLibraryFile?.filename || ''
  const selectedSize = activeFile?.file.size ?? activeLibraryFile?.fileSize
  const selectedStatus = activeFile?.status || activeLibraryFile?.status
  const statusLabel = selectedStatus ? { pending: '待解析', parsing: '解析中', parsed: '已解析', error: '解析失败' }[selectedStatus] || selectedStatus : ''
  const activeBackend = activeFile?.parserBackend || activeLibraryFile?.parserBackend || parserBackend

  return (
    <AppFrame mainClassName="bg-background">
      <div className={styles.page} data-testid="parsing-workbench-grid">
        <header className={styles.header} data-testid="parsing-workbench-title">
          <div className={styles.pageTitle}>
            <PageTitleIcon name="parsing" className="size-6" />
            <h1>{t('title')}</h1>
          </div>
          <Select value={selectedDatasetId || '__all__'} disabled={isEditing} onValueChange={(value) => onDatasetScopeChange(value === '__all__' ? null : value)}>
            <SelectTrigger aria-label="数据范围" className={styles.scope}>
              <SelectValue placeholder="全部来源" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">全部来源</SelectItem>
              {datasetOptions.map((dataset) => <SelectItem key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.count}</SelectItem>)}
            </SelectContent>
          </Select>
          <div className={styles.headerActions}>
            <Button variant="ghost" size="sm" aria-label="解析设置" onClick={() => setInspectorOpen(true)} className="gap-2">
              <Settings2 className="size-4" /><span className={styles.optionalLabel}>解析设置</span>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" aria-label="上传文件" disabled={isEditing} className="gap-2"><UploadCloud className="size-4" /><span className={styles.optionalLabel}>上传文件</span><ChevronDown className={cn('size-3', styles.optionalLabel)} /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => requestUploadToFolder(currentFolderId)}><UploadCloud className="mr-2 size-4" />选择文件</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => requestUploadFolder(currentFolderId)}><FolderUp className="mr-2 size-4" />上传文件夹</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        <div className={styles.documentBar}>
          <button type="button" className={styles.filePicker} disabled={isEditing} onClick={() => setQueueOpen(true)} aria-label="选择文档">
            {selectedFile ? <FileTypeIcon filename={selectedFilename} className="size-7 shrink-0" /> : <FolderOpen className="size-5 shrink-0 text-muted-foreground" />}
            <span className={styles.fileIdentity}>
              <strong title={selectedFilename || activeFolderPathLabel}>{selectedFilename || activeFolderPathLabel}</strong>
              <small>{selectedFile ? <>{selectedSize != null ? formatFileSize(selectedSize) + ' · ' : ''}{activeFile?.stats?.pageCount ? activeFile.stats.pageCount + ' 页 · ' : ''}{activeFolderPathLabel}<span className={styles.optionalLabel}> · {sidebarFileItems.length} 个文件</span></> : sidebarFileItems.length + ' 个文件'}</small>
            </span>
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          </button>
          {selectedStatus ? <span className={cn(styles.status, selectedStatus === 'parsed' ? 'text-success' : selectedStatus === 'error' ? 'text-destructive' : selectedStatus === 'parsing' ? 'text-info' : 'text-muted-foreground')}>
            {selectedStatus === 'parsing' ? <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" /> : <span className="size-1.5 rounded-full bg-current" />}
            {statusLabel}
          </span> : null}
          <div className={styles.fileActions}>
            {activeFile ? <>
              <fieldset className={styles.parserPicker} disabled={isEditing || selectedStatus === 'parsing'}><ParserDropdown value={activeBackend} filename={selectedFilename} compact side="top" onChange={(backend) => setQueueFileParserBackend({ fileId: activeFile.id, filename: selectedFilename, backend })} /></fieldset>
              {selectedStatus === 'parsed' || selectedStatus === 'error' ? <Button variant="outline" size="sm" aria-label={selectedStatus === 'error' ? '重试解析' : '重新解析'} disabled={isEditing} className="gap-1.5" onClick={() => parseFile(activeFile.id, activeFile.parserBackend)}>
                <RotateCcw className="size-3.5" /><span className={styles.optionalLabel}>{selectedStatus === 'error' ? '重试解析' : '重新解析'}</span>
              </Button> : null}
            </> : null}
            {sidebarFileItems.length > 0 ? <div className={styles.fileNavigation}>
              <Button variant="ghost" size="icon" className="size-8" aria-label="上一个文件" disabled={isEditing || fileIndex <= 0} onClick={() => selectFile(sidebarFileItems[fileIndex - 1].id)}><ChevronLeft className="size-4" /></Button>
              <span>{fileIndex >= 0 ? fileIndex + 1 : '–'} / {sidebarFileItems.length}</span>
              <Button variant="ghost" size="icon" className="size-8" aria-label="下一个文件" disabled={isEditing || fileIndex >= sidebarFileItems.length - 1} onClick={() => selectFile(sidebarFileItems[fileIndex + 1].id)}><ChevronRight className="size-4" /></Button>
            </div> : null}
          </div>
        </div>

        <main className={styles.main} data-testid="parsing-main-panel">
          {activeFile ? <ParsingActiveFilePane
            key={activeFile.id}
            activeFile={activeFile} activeRun={activeRun} activeMarkdown={activeMarkdown}
            activeElements={activeElements} activeQualityGate={activeQualityGate} activePdfQuality={activePdfQuality}
            activeBlocksWithPositions={activeBlocksWithPositions} isPdf={isPdf}
            previewMode={previewMode} rightPanelMode={rightPanelMode} isEditing={isEditing}
            editedContent={editedContent} copied={copied} activeBlockId={activeBlockId} hoveredBlockId={hoveredBlockId}
            onSelectRun={handleSelectRun} onPreviewModeChange={setPreviewMode} onRightPanelModeChange={setRightPanelMode}
            onStartEdit={handleStartEdit} onCancelEdit={handleCancelEdit} onSaveEdit={handleSaveEdit}
            onCopyMarkdown={() => detachPromise(copyMarkdown())} onDownloadMarkdown={downloadMarkdown} onParseFile={parseFile}
            pdfPreviewResetToken={pdfPreviewResetToken}
            onSubmitToGovernance={handleSubmitToGovernance} onEditedContentChange={setEditedContent}
            onActiveBlockIdChange={setActiveBlockId} onHoveredBlockIdChange={setHoveredBlockId}
          /> : activeLibraryFile ? <ParsingLibraryPreviewPane
            key={activeLibraryFile.id}
            file={activeLibraryFile} activeMarkdown={activeMarkdown} folderName={activeLibraryFolderName}
            folderPathLabel={activeLibraryFolderPathLabel} sourceStatus={activeLibrarySourceStatus}
            defaultParserBackend={parserBackend} statusBadge={activeLibraryStatusBadge}
            onClose={() => setActiveLibraryFileId(null)}
            onUpdateParser={(backend) => {
              const resolved = resolveParserBackendForFilename(activeLibraryFile.filename, backend)
              updateParsedFile(activeLibraryFile.id, { parserBackend: resolved.backend, parser: getParserLabel(resolved.backend) })
            }}
            onReprocessKnowledgeFile={(backend) => detachPromise(handleReprocessKnowledgeFile(backend))}
            onRestoreSource={(autoParse) => detachPromise(restoreLibraryFileFromCache(activeLibraryFile.id, autoParse))}
            onRequestRebind={(autoParse) => requestRebindForLibraryFile(activeLibraryFile.id, autoParse)}
          /> : <div className={cn(styles.empty, isQueueRehydrating && styles.loading)} onDragOver={(event) => handleFolderDragOver(event, currentFolderId)} onDragLeave={handleFolderDragLeave} onDrop={(event) => handleFolderDrop(event, currentFolderId)}>
            {isQueueRehydrating ? <Loader2 className="size-7 animate-spin text-muted-foreground motion-reduce:animate-none" /> : <PageTitleIcon name="parsing" compact={false} className="size-11" />}
            <h2>{isQueueRehydrating ? '正在恢复文件' : sidebarFileItems.length ? '选择文档，查看解析结果' : '上传文档，开始解析'}</h2>
            <p>{sidebarFileItems.length ? '打开文件目录，选择需要核对的文档。' : '支持 PDF、Word、表格和图片。'}</p>
            <Button onClick={() => sidebarFileItems.length ? setQueueOpen(true) : requestUploadToFolder(currentFolderId)} className="gap-2" disabled={isQueueRehydrating}><UploadCloud className="size-4" />{sidebarFileItems.length ? '选择文档' : '选择文件'}</Button>
          </div>}
        </main>
      </div>

      <input ref={fileInputRef} type="file" multiple accept={UPLOAD_ACCEPT_WITH_ZIP} aria-label="选择待解析文件" className="hidden" onChange={(event) => void handleFileSelect(event)} />
      <input ref={folderInputRef} type="file" multiple {...{ webkitdirectory: '' }} aria-label="选择待解析文件夹" className="hidden" onChange={(event) => void handleFileSelect(event)} />
      <input ref={rebindInputRef} type="file" accept={UPLOAD_ACCEPT} aria-label="重新关联原文件" className="hidden" onChange={(event) => void handleRebindFileSelect(event)} />

      <WorkbenchPanelDialog open={queueOpen} onOpenChange={setQueueOpen} title="文件目录" className={styles.fileDialog}>
        <div className={styles.directoryTools}>
          <span>{currentFolderFileCount} 个文件 · {parsedCount} 已解析{parsingCount ? ' · ' + parsingCount + ' 解析中' : ''}{pendingCount ? ' · ' + pendingCount + ' 待解析' : ''}</span>
          {parseableCount > 0 ? <Button size="sm" variant="outline" onClick={() => detachPromise(parseAllPending())}>解析待处理文件 ({parseableCount})</Button> : null}
        </div>
        <div className={styles.tree}>
          {isLibraryLoaded ? <DocumentFolderTree fileItems={sidebarFileItems} showFiles="expanded"
            onRequestUpload={requestUploadToFolder} onRequestUploadFolder={requestUploadFolder}
            onSelectFile={selectFile} onToggleFileSelected={onToggleGovernanceFileSelection}
            onDeleteFolder={handleDeleteFolder} onFileDrop={moveFileToFolder}
            onRetryFile={(fileId) => detachPromise(parseFile(fileId))} onRemoveFile={removeFile} onFileDragStart={handleFileDragStart}
          /> : <div className={styles.empty}><Loader2 className="size-5 animate-spin" />正在加载文件目录</div>}
        </div>
        {readyGovernanceCount > 0 ? <div className={styles.directoryTools}>
          <span>{selectedReadyGovernanceCount} / {readyGovernanceCount} 个待治理文件已选</span>
          <Button size="sm" className="gap-2" disabled={!selectedReadyGovernanceCount} onClick={onSubmitSelectedToGovernance}><ShieldCheck className="size-4" />提交所选文件</Button>
        </div> : null}
      </WorkbenchPanelDialog>

      <WorkbenchPanelDialog open={inspectorOpen} onOpenChange={setInspectorOpen} title="解析设置" className={styles.settingsDialog}>
        <div className={styles.settingsBody}>
          <div className={styles.settingGroup}>
            <h2>默认解析器</h2><p>用于后续上传的文件，当前文档可单独切换。</p>
            <ParserDropdown value={parserBackend} onChange={setParserBackend} />
          </div>
          <div className={styles.settingGroup}>
            <h2>图像处理</h2>
            {[
              { id: 'caption', label: '图片描述', description: '为文档中的图片生成文字描述', checked: imageCaptionEnabled, change: setImageCaptionEnabled },
              { id: 'ocr', label: '图片文字识别', description: '提取图片中的文字', checked: imageOcrEnabled, change: setImageOcrEnabled },
              { id: 'correction', label: '视觉校正', description: '通过视觉模型校正文档识别结果', checked: vlmCorrectionEnabled, change: setVlmCorrectionEnabled },
            ].map((setting) => <label key={setting.id} className={styles.settingRow} htmlFor={'parsing-' + setting.id}>
              <span><strong>{setting.label}</strong><small>{setting.description}</small></span>
              <Switch id={'parsing-' + setting.id} checked={setting.checked} onCheckedChange={setting.change} />
            </label>)}
          </div>
        </div>
      </WorkbenchPanelDialog>
    </AppFrame>
  )
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
