'use client'

import { useCallback, useEffect, useMemo, type Dispatch, type RefObject, type SetStateAction } from 'react'
import type { ChangeEvent as ReactChangeEvent, DragEvent as ReactDragEvent } from 'react'
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ArrowRight,
  FolderOpen,
  FolderUp,
  Loader2,
  Play,
  RotateCcw,
  Settings2,
  ShieldCheck,
  UploadCloud,
} from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { AppFrame } from '@/components/app-frame'
import { ParsingParserPicker } from './parsing-parser-picker'
import { DocumentFolderTree, type DocumentTreeFileItem } from '@/components/document-library/folder-tree'
import { ParsingActiveFilePane } from './parsing-active-file-pane'
import { ParsingLibraryPreviewPane } from './parsing-library-preview-pane'
import { getQualityGateGrade } from './parsing-quality-notice'
import { getParsingGovernanceTargets } from './parsing-governance'
import { Button } from '@/components/ui/button'
import { WorkspaceNotice, WorkspaceNoticeStack } from '@/components/ui/operational-workspace'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Switch } from '@/components/ui/switch'
import { WorkbenchPanelDialog } from '@/components/workbench'
import { formatApiError } from '@/lib/api-errors'
import type { ParsingElement } from '@/lib/api/parsing'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { UPLOAD_ACCEPT, UPLOAD_ACCEPT_WITH_ZIP } from '@/lib/upload-extensions'
import { cn, detachPromise } from '@/lib/utils'
import type { ParsingBlock } from '@/lib/parsing-positions'
import { type FolderNode, ROOT_FOLDER_ID, type ParsedFileData } from '@/store/use-parsed-files-store'
import type { ParsedFile, ParseRun, ParsingLibrarySourceStatus } from './parsing-types'
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
  activeLibrarySourceError: Error | null
  isLibrarySourceChecking: boolean
  retryLibrarySource: () => void
  activeMarkdown: string
  activeLibraryContentError: Error | null
  isLibraryContentLoading: boolean
  hasLibraryContent: boolean
  retryLibraryContent: () => void
  availableDatasets: DatasetScopeOption[]
  datasetsError: Error | null
  librarySyncError: Error | null
  isLibrarySyncing: boolean
  retryLibrarySync: () => void
  activeElements: ParsingElement[]
  activePdfQuality: unknown
  activeQualityGate: unknown
  activeRun: ParseRun | null
  isRunUnavailable: boolean
  copied: boolean
  copyMarkdown: () => Promise<void>
  currentFolderId: string
  downloadMarkdown: () => void
  editedContent: string
  fileInputRef: RefObject<HTMLInputElement | null>
  files: ParsedFile[]
  folderInputRef: RefObject<HTMLInputElement | null>
  folderPathById: Record<string, string>
  folders: FolderNode[]
  handleCancelEdit: () => void
  handleDeleteFolder: (folderIds: string[], fileIds: string[]) => void
  handleFileDragStart: (event: ReactDragEvent<HTMLElement>, fileId: string) => void
  handleFileSelect: (event: ReactChangeEvent<HTMLInputElement>) => Promise<void>
  addFiles: (files: File[], baseFolderId?: string) => Promise<void>
  handleFolderDrop: (event: ReactDragEvent<HTMLElement>, folderId: string) => Promise<void>
  handleRebindFileSelect: (event: ReactChangeEvent<HTMLInputElement>) => Promise<void>
  handleSaveEdit: () => Promise<void>
  handleSelectRun: (runId: string) => void
  handleStartEdit: () => void
  handleSubmitToGovernance: (libraryFile?: ParsedFileData) => Promise<void>
  hoveredBlockId: string | null
  imageCaptionEnabled: boolean
  imageOcrEnabled: boolean
  inspectorOpen: boolean
  isEditing: boolean
  isSubmittingGovernance: boolean
  isLibraryLoaded: boolean
  libraryLoadError: unknown
  retryLibraryLoad: () => void
  isPdf: boolean
  isQueueRehydrating: boolean
  libraryFiles: ParsedFileData[]
  moveFileToFolder: (fileId: string, folderId: string) => Promise<void>
  parseAllPending: () => Promise<void>
  parseFile: (fileId: string, backend?: string) => void
  parserBackend: string
  pdfPreviewResetToken: number
  previewMode: 'raw' | 'rendered'
  queueOpen: boolean
  rebindInputRef: RefObject<HTMLInputElement | null>
  removeFile: (fileId: string) => Promise<void>
  requestRebindForLibraryFile: (libraryId: string, autoParse: boolean) => void
  requestUploadFolder: (folderId: string) => void
  requestUploadToFolder: (folderId: string) => void
  restoreLibraryFileFromCache: (libraryId: string, autoParse: boolean) => Promise<void>
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
  setParserBackend: (backend: string) => void
  setPdfPreviewResetToken: Dispatch<SetStateAction<number>>
  setPreviewMode: (mode: 'raw' | 'rendered') => void
  setQueueOpen: (open: boolean) => void
  setQueueFileParserBackend: (params: { fileId: string; filename: string; backend: string }) => void
  setRightPanelMode: (mode: 'blocks' | 'markdown') => void
  selectedGovernanceFileIds: ReadonlySet<string>
  selectedDatasetId: string | null
  startKnowledgeParsing: (libraryId: string, backend: string) => Promise<void>
  setVlmCorrectionEnabled: (enabled: boolean) => void
  onSubmitSelectedToGovernance: () => Promise<void>
  onToggleGovernanceFileSelection: (fileId: string) => void
  onDatasetScopeChange: (datasetId: string | null) => void
  tocEnabled: boolean
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => Promise<void>
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
  activeLibrarySourceError,
  isLibrarySourceChecking,
  retryLibrarySource,
  activeMarkdown,
  activeLibraryContentError,
  isLibraryContentLoading,
  hasLibraryContent,
  retryLibraryContent,
  availableDatasets,
  datasetsError,
  librarySyncError,
  isLibrarySyncing,
  retryLibrarySync,
  activeElements,
  activePdfQuality,
  activeQualityGate,
  activeRun,
  isRunUnavailable,
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
  addFiles,
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
  isSubmittingGovernance,
  isLibraryLoaded,
  libraryLoadError,
  retryLibraryLoad,
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
  setActiveFolderId,
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
  startKnowledgeParsing,
  onSubmitSelectedToGovernance,
  onToggleGovernanceFileSelection,
  onDatasetScopeChange,

  updateParsedFile,
  visibleQueueFiles,
  vlmCorrectionEnabled,
}: Readonly<ParsingWorkbenchShellProps>) {
  const t = useTranslations('ParsingWorkbench')
  const librarySourceFeedback =
    activeLibrarySourceError === null ? null : (
      <div role="alert" className="break-words text-sm text-destructive">
        <p>{formatApiError(activeLibrarySourceError, '无法读取原文件状态')}</p>
        <Button size="sm" variant="ghost" disabled={isLibrarySourceChecking} onClick={retryLibrarySource}>
          重试检查原文件
        </Button>
      </div>
    )
  const libraryContentFeedback =
    activeLibraryContentError !== null ? (
      <div className="shrink-0 px-4">
        <WorkspaceNotice>{formatApiError(activeLibraryContentError, '读取解析正文失败')}</WorkspaceNotice>
        <Button
          className="mb-4 mt-4 gap-2 bg-accent text-accent-foreground hover:bg-accent/90"
          disabled={isLibraryContentLoading}
          onClick={retryLibraryContent}
        >
          {isLibraryContentLoading ? (
            <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
          ) : (
            <RotateCcw className="size-4" />
          )}
          {isLibraryContentLoading ? '正在读取…' : '重试读取正文'}
        </Button>
      </div>
    ) : null
  const librarySyncFeedback =
    librarySyncError !== null && libraryLoadError === undefined ? (
      <WorkspaceNotice
        placement="floating"
        tone="warning"
        title="文档目录同步失败"
        error={librarySyncError}
        fallbackMessage="文档目录同步失败"
        retry={retryLibrarySync}
        retryLabel="重试同步目录"
        pending={isLibrarySyncing}
      />
    ) : null
  const bumpPdfPreviewResetToken = () => setPdfPreviewResetToken((prev) => prev + 1)
  const parseableCount = visibleQueueFiles.filter(
    (file) => file.librarySource !== 'knowledge_base' && (file.status === 'pending' || file.status === 'error'),
  ).length
  const governanceTargets = useMemo(
    () => getParsingGovernanceTargets(files, libraryFiles, selectedDatasetId),
    [files, libraryFiles, selectedDatasetId],
  )
  const readyGovernanceFileIds = useMemo(
    () => new Set(governanceTargets.map((target) => target.selectionId)),
    [governanceTargets],
  )
  const readyGovernanceCount = governanceTargets.length
  const selectedReadyGovernanceCount = governanceTargets.filter((target) =>
    selectedGovernanceFileIds.has(target.selectionId),
  ).length
  const selectedOtherFolderCount = governanceTargets.filter(
    (target) =>
      selectedGovernanceFileIds.has(target.selectionId) && (target.file.folderId ?? ROOT_FOLDER_ID) !== currentFolderId,
  ).length

  const activeFolderPathLabel = folderPathById[activeFolderId || ROOT_FOLDER_ID] || t('rootFolder')
  const activeLibraryMarkdown = activeLibraryFile?.markdownContent || activeLibraryFile?.originalMarkdownContent
  const activeLibraryMarkdownAvailable = Boolean(activeLibraryMarkdown?.trim())
  const shouldAutoRestoreLibraryPdf =
    !activeFile &&
    activeLibraryFile?.status === 'parsed' &&
    activeLibraryMarkdownAvailable &&
    activeLibraryFile.filename.toLowerCase().endsWith('.pdf')

  const handleReprocessKnowledgeFile = useCallback(
    async (backend: string) => {
      if (!activeLibraryFile || activeLibraryFile.source !== 'knowledge_base') return
      await startKnowledgeParsing(activeLibraryFile.id, backend)
    },
    [activeLibraryFile, startKnowledgeParsing],
  )

  useEffect(() => {
    if (activeFile || !activeLibraryFile) return
    if (!shouldAutoRestoreLibraryPdf) return

    detachPromise(restoreLibraryFileFromCache(activeLibraryFile.id, false))
  }, [activeFile, activeLibraryFile, restoreLibraryFileFromCache, shouldAutoRestoreLibraryPdf])
  const datasetDocumentCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const file of libraryFiles) {
      if ((file.source !== 'knowledge_base' && file.source !== 'parsing_workspace') || !file.datasetId) {
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
    [availableDatasets, datasetDocumentCounts],
  )
  const sidebarFileItems = useMemo<DocumentTreeFileItem[]>(() => {
    const queueFiles = selectedDatasetId ? files.filter((file) => file.datasetId === selectedDatasetId) : files
    const libraryFilesForScope = selectedDatasetId
      ? libraryFiles.filter(
          (file) =>
            (file.source === 'knowledge_base' || file.source === 'parsing_workspace') &&
            file.datasetId === selectedDatasetId,
        )
      : libraryFiles
    const queueLibraryIds = new Set(
      queueFiles.map((file) => file.libraryId).filter((value): value is string => Boolean(value)),
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
      isSelectable: readyGovernanceFileIds.has(file.libraryId ?? file.id),
      isSelected: selectedGovernanceFileIds.has(file.libraryId ?? file.id),
      canRemove: file.status !== 'parsing' || file.libraryId !== undefined,
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
        isSelectable: readyGovernanceFileIds.has(file.id),
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
    readyGovernanceFileIds,
    selectedGovernanceFileIds,
    selectedDatasetId,
  ])

  const selectFile = (fileId: string) => {
    if (isEditing) return
    bumpPdfPreviewResetToken()
    const sidebarFile = sidebarFileItems.find((file) => file.id === fileId)
    if (sidebarFile !== undefined) setActiveFolderId(sidebarFile.folderId ?? ROOT_FOLDER_ID)
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
  const pendingCount = sidebarFileItems.filter((file) => file.status === 'pending').length
  const parsingCount = sidebarFileItems.filter((file) => file.status === 'parsing').length
  const parsedCount = sidebarFileItems.filter((file) => file.status === 'parsed').length
  const activeId = activeFile?.id || activeLibraryFile?.id
  const fileIndex = sidebarFileItems.findIndex((file) => file.id === activeId)
  const selectedFile = activeFile || activeLibraryFile
  const isEmptyWorkspace = !selectedFile && files.length === 0 && libraryFiles.length === 0
  const selectedFilename = activeFile?.name ?? activeLibraryFile?.filename
  const selectedSize = activeFile?.size ?? activeLibraryFile?.fileSize
  const selectedStatus = activeFile?.status || activeLibraryFile?.status
  const qualityGrade = getQualityGateGrade(activeQualityGate)
  const needsReview = selectedStatus === 'parsed' && (qualityGrade === 'warn' || qualityGrade === 'fail')
  const statusLabel = selectedStatus
    ? { pending: '待解析', parsing: '解析中', parsed: '已解析', error: '解析失败' }[selectedStatus] || selectedStatus
    : ''
  const activeBackend = activeFile?.parserBackend || activeLibraryFile?.parserBackend || parserBackend
  const resultReady = activeFile
    ? activeFile.status === 'parsed' && !isRunUnavailable
    : activeLibraryFile?.status === 'parsed' && hasLibraryContent && activeLibraryContentError === null
  const parseActiveFile = () => {
    if (!activeFile && activeLibraryFile) {
      if (activeLibraryFile.source === 'knowledge_base') {
        void handleReprocessKnowledgeFile(activeBackend)
      } else if (
        activeLibrarySourceStatus === 'available' ||
        (activeLibrarySourceStatus === 'unknown' &&
          activeLibraryFile.source !== undefined &&
          activeLibrarySourceError === null &&
          !isLibrarySourceChecking)
      ) {
        detachPromise(restoreLibraryFileFromCache(activeLibraryFile.id, true))
      } else {
        requestRebindForLibraryFile(activeLibraryFile.id, true)
      }
    } else if (activeFile?.librarySource === 'knowledge_base') {
      void handleReprocessKnowledgeFile(activeFile.parserBackend)
    } else if (activeFile) {
      parseFile(activeFile.id, activeFile.parserBackend)
    }
  }
  const parserPicker = (
    <ParsingParserPicker
      value={activeBackend}
      filename={selectedFilename}
      disabled={isEditing || selectedStatus === 'parsing'}
      onChange={(backend) => {
        if (activeFile && activeFile.librarySource !== 'knowledge_base') {
          setQueueFileParserBackend({ fileId: activeFile.id, filename: activeFile.name, backend })
        } else if (activeLibraryFile) {
          const resolved = resolveParserBackendForFilename(activeLibraryFile.filename, backend)
          void updateParsedFile(activeLibraryFile.id, {
            parserBackend: resolved.backend,
            parser: getParserLabel(resolved.backend),
          }).catch((error) => toast.error(formatApiError(error, '更新解析器失败')))
        }
      }}
    />
  )

  return (
    <AppFrame mainClassName="bg-background">
      <div className={styles.page} data-testid="parsing-workbench-grid">
        <header className={styles.header} data-testid="parsing-workbench-title" data-has-file={Boolean(selectedFile)}>
          <div className={styles.pageTitle}>
            <PageTitleIcon name="parsing" className="size-[18px]" />
            <h1>{t('title')}</h1>
          </div>
          <Select
            value={selectedDatasetId || '__all__'}
            disabled={isEditing}
            onValueChange={(value) => onDatasetScopeChange(value === '__all__' ? null : value)}
          >
            <SelectTrigger aria-label="数据范围" className={styles.scope}>
              <SelectValue placeholder="全部来源" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">全部来源</SelectItem>
              {datasetOptions.map((dataset) => (
                <SelectItem key={dataset.id} value={dataset.id}>
                  {dataset.name} · {dataset.count}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <button
            type="button"
            className={styles.filePicker}
            disabled={isEditing}
            onClick={() => setQueueOpen(true)}
            aria-label="选择文档"
            title={selectedFilename || activeFolderPathLabel}
          >
            {selectedFile ? (
              <FileTypeIcon filename={selectedFilename} className="size-[18px] shrink-0" />
            ) : (
              <FolderOpen className="size-4 shrink-0 text-muted-foreground" />
            )}
            <span className={styles.fileIdentity}>{selectedFilename || '选择文档'}</span>
            {selectedSize !== undefined && selectedSize !== null ? (
              <span className={styles.fileSize}>{formatFileSize(selectedSize)}</span>
            ) : null}
            <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
          </button>
          {selectedStatus ? (
            <span className={styles.status} data-status={needsReview ? 'review' : selectedStatus}>
              {selectedStatus === 'parsing' ? (
                <Loader2 className="size-3 animate-spin motion-reduce:animate-none" />
              ) : (
                <span className="size-1.5 rounded-full bg-current" />
              )}
              {needsReview ? '待核对' : statusLabel}
            </span>
          ) : null}
          {fileIndex >= 0 ? (
            <div className={styles.fileNavigation}>
              <Button
                variant="ghost"
                size="icon"
                aria-label="上一个文件"
                disabled={isEditing || fileIndex <= 0}
                onClick={() => selectFile(sidebarFileItems[fileIndex - 1].id)}
              >
                <ChevronLeft className="size-3.5" />
              </Button>
              <span>
                {fileIndex + 1} / {sidebarFileItems.length}
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label="下一个文件"
                disabled={isEditing || fileIndex >= sidebarFileItems.length - 1}
                onClick={() => selectFile(sidebarFileItems[fileIndex + 1].id)}
              >
                <ChevronRight className="size-3.5" />
              </Button>
            </div>
          ) : null}
          <div className={styles.headerActions}>
            <Button
              variant="ghost"
              size="sm"
              aria-label="解析设置"
              onClick={() => setInspectorOpen(true)}
              className="gap-2"
            >
              <Settings2 className="size-4" />
              <span className={styles.optionalLabel}>解析设置</span>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" aria-label="上传文件" disabled={isEditing} className="gap-2">
                  <UploadCloud className="size-4" />
                  <span className={styles.optionalLabel}>上传文件</span>
                  <ChevronDown className={cn('size-3', styles.optionalLabel)} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => requestUploadToFolder(currentFolderId)}>
                  <UploadCloud className="mr-2 size-4" />
                  选择文件
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => requestUploadFolder(currentFolderId)}>
                  <FolderUp className="mr-2 size-4" />
                  上传文件夹
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            {selectedFile && (selectedStatus === 'pending' || resultReady) ? (
              <Button
                size="sm"
                className="gap-1.5 bg-accent text-accent-foreground hover:bg-accent/90"
                aria-label={resultReady ? '继续数据治理' : '开始解析'}
                title={resultReady ? '继续数据治理' : '开始解析'}
                disabled={
                  isEditing || isSubmittingGovernance || (!activeFile && !resultReady && isLibrarySourceChecking)
                }
                onClick={() =>
                  resultReady
                    ? void handleSubmitToGovernance(activeFile ? undefined : (activeLibraryFile ?? undefined))
                    : parseActiveFile()
                }
              >
                {isSubmittingGovernance ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : resultReady ? (
                  <ArrowRight className="size-4" />
                ) : (
                  <Play className="size-4" />
                )}
                <span className={styles.optionalLabel}>
                  {isSubmittingGovernance ? '正在移交' : resultReady ? '继续数据治理' : '开始解析'}
                </span>
              </Button>
            ) : null}
          </div>
        </header>
        <WorkspaceNoticeStack ariaLabel="解析目录状态提示">
          {libraryLoadError !== undefined && !queueOpen ? (
            <WorkspaceNotice
              title="本地文档记录读取失败"
              error={libraryLoadError}
              fallbackMessage="无法读取文档目录"
              retry={retryLibraryLoad}
              retryLabel="重试读取文档"
            />
          ) : null}
          {datasetsError ? <WorkspaceNotice error={datasetsError} fallbackMessage="加载数据集失败" /> : null}
        </WorkspaceNoticeStack>
        {!queueOpen && librarySyncFeedback}

        <section className={styles.main} data-testid="parsing-main-panel" aria-label="解析工作区">
          {activeFile ? (
            <ParsingActiveFilePane
              key={activeFile.id}
              activeFile={activeFile}
              activeRun={activeRun}
              isRunUnavailable={isRunUnavailable}
              activeMarkdown={activeMarkdown}
              contentFeedback={libraryContentFeedback}
              activeElements={activeElements}
              activeQualityGate={activeQualityGate}
              activePdfQuality={activePdfQuality}
              activeBlocksWithPositions={activeBlocksWithPositions}
              isPdf={isPdf}
              previewMode={previewMode}
              rightPanelMode={rightPanelMode}
              isEditing={isEditing}
              editedContent={editedContent}
              copied={copied}
              activeBlockId={activeBlockId}
              hoveredBlockId={hoveredBlockId}
              onSelectRun={handleSelectRun}
              onPreviewModeChange={setPreviewMode}
              onRightPanelModeChange={setRightPanelMode}
              onStartEdit={handleStartEdit}
              parserPicker={parserPicker}
              onCancelEdit={handleCancelEdit}
              onSaveEdit={handleSaveEdit}
              onCopyMarkdown={() => void copyMarkdown()}
              onDownloadMarkdown={downloadMarkdown}
              onParseFile={(fileId, backend) => {
                if (activeFile.librarySource === 'knowledge_base') {
                  void handleReprocessKnowledgeFile(backend ?? activeFile.parserBackend)
                } else {
                  void parseFile(fileId, backend)
                }
              }}
              pdfPreviewResetToken={pdfPreviewResetToken}
              onEditedContentChange={setEditedContent}
              onActiveBlockIdChange={setActiveBlockId}
              onHoveredBlockIdChange={setHoveredBlockId}
            />
          ) : activeLibraryFile ? (
            <ParsingLibraryPreviewPane
              key={activeLibraryFile.id}
              file={activeLibraryFile}
              activeMarkdown={activeMarkdown}
              sourceStatus={activeLibrarySourceStatus}
              sourceFeedback={librarySourceFeedback}
              isSourceChecking={isLibrarySourceChecking}
              contentFeedback={libraryContentFeedback}
              isContentLoading={isLibraryContentLoading}
              hasContent={hasLibraryContent}
              qualityGate={activeQualityGate}
              pdfQuality={activePdfQuality}
              parserPicker={parserPicker}
              defaultParserBackend={parserBackend}
              onReprocessKnowledgeFile={(backend) => detachPromise(handleReprocessKnowledgeFile(backend))}
              onRestoreSource={(autoParse) =>
                detachPromise(restoreLibraryFileFromCache(activeLibraryFile.id, autoParse))
              }
              onRequestRebind={(autoParse) => requestRebindForLibraryFile(activeLibraryFile.id, autoParse)}
            />
          ) : isEmptyWorkspace && !isQueueRehydrating ? (
            <div className={styles.emptySplitStudio} data-parsing-empty-studio="true">
              <section
                className={styles.emptyIntakeStage}
                aria-label="上传待解析文档"
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault()
                  void addFiles(Array.from(event.dataTransfer.files), currentFolderId).catch((error) =>
                    toast.error(formatApiError(error, '添加文件失败')),
                  )
                }}
              >
                <div className={styles.emptyParsingIllust} aria-hidden="true">
                  <svg viewBox="0 0 228 112" fill="none">
                    <rect
                      x="18"
                      y="16"
                      width="68"
                      height="84"
                      rx="8"
                      fill="hsl(var(--card))"
                      stroke="currentColor"
                      strokeOpacity="0.34"
                      strokeWidth="1.25"
                    />
                    <path d="M68 16V34H86" stroke="currentColor" strokeOpacity="0.3" strokeWidth="1.25" />
                    <rect x="30" y="38" width="38" height="17" rx="3" fill="currentColor" fillOpacity="0.16" />
                    <text
                      x="49"
                      y="50.5"
                      textAnchor="middle"
                      fill="currentColor"
                      fillOpacity="0.72"
                      fontSize="10"
                      fontWeight="600"
                      fontFamily="var(--font-mono), monospace"
                    >
                      PDF
                    </text>
                    <rect x="30" y="65" width="44" height="3.5" rx="1.75" fill="currentColor" fillOpacity="0.2" />
                    <rect x="30" y="75" width="36" height="3.5" rx="1.75" fill="currentColor" fillOpacity="0.16" />
                    <rect x="30" y="85" width="26" height="3.5" rx="1.75" fill="currentColor" fillOpacity="0.14" />

                    <path
                      d="M101 58H125M125 58L119 52.5M125 58L119 63.5"
                      stroke="currentColor"
                      strokeOpacity="0.45"
                      strokeWidth="1.4"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />

                    <rect
                      x="140"
                      y="16"
                      width="68"
                      height="84"
                      rx="8"
                      fill="hsl(var(--card))"
                      stroke="currentColor"
                      strokeOpacity="0.34"
                      strokeWidth="1.25"
                    />
                    <path d="M190 16V34H208" stroke="currentColor" strokeOpacity="0.3" strokeWidth="1.25" />
                    <text
                      x="154"
                      y="46"
                      fill="currentColor"
                      fillOpacity="0.6"
                      fontSize="15"
                      fontWeight="500"
                      fontFamily="var(--font-mono), monospace"
                    >
                      #
                    </text>
                    <rect x="152" y="56" width="42" height="3.5" rx="1.75" fill="currentColor" fillOpacity="0.26" />
                    <rect x="152" y="66" width="42" height="3.5" rx="1.75" fill="currentColor" fillOpacity="0.2" />
                    <rect x="152" y="76" width="36" height="3.5" rx="1.75" fill="currentColor" fillOpacity="0.18" />
                    <rect x="152" y="86" width="24" height="3.5" rx="1.75" fill="currentColor" fillOpacity="0.14" />

                    <path
                      d="M204 10L206 3M211 14L217 8M215 20L222 18"
                      stroke="hsl(var(--accent))"
                      strokeWidth="1.75"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>
                <h2>上传待解析的文档</h2>
                <p>拖入文件或从本地选择，保留原版定位对照与结构化 Markdown 输出。</p>
                <div className={styles.formatChips} aria-label="支持的文件格式">
                  {['PDF', 'DOCX', 'XLSX', 'PPTX', 'PNG/JPG'].map((format) => (
                    <span key={format}>{format}</span>
                  ))}
                </div>
                <div className={styles.uploadActions}>
                  <Button
                    className="bg-accent text-accent-foreground hover:bg-accent/90"
                    onClick={() => requestUploadToFolder(currentFolderId)}
                  >
                    <UploadCloud className="size-4" />
                    选择文件
                  </Button>
                  <Button variant="outline" onClick={() => requestUploadFolder(currentFolderId)}>
                    <FolderUp className="size-4" />
                    上传文件夹
                  </Button>
                </div>
              </section>
              <aside className={styles.emptySettingsStage} aria-label="默认解析设置">
                <div className={styles.emptySettingsGroup}>
                  <h3>默认解析引擎</h3>
                  <ParsingParserPicker
                    value={parserBackend}
                    onChange={setParserBackend}
                    triggerVariant="row"
                    disabled={isEditing || selectedStatus === 'parsing'}
                  />
                </div>
                <div className={styles.emptySettingsGroup}>
                  <h3>图像与版面增强</h3>
                  <div className={styles.emptySwitchList}>
                    {[
                      {
                        id: 'ocr',
                        label: '图片 OCR 识别',
                        description: '提取图片中的文字内容',
                        checked: imageOcrEnabled,
                        change: setImageOcrEnabled,
                      },
                      {
                        id: 'caption',
                        label: '图片语义描述',
                        description: '为图片生成语义说明',
                        checked: imageCaptionEnabled,
                        change: setImageCaptionEnabled,
                      },
                      {
                        id: 'correction',
                        label: '视觉模型版面校对',
                        description: '校验复杂页面结构',
                        checked: vlmCorrectionEnabled,
                        change: setVlmCorrectionEnabled,
                      },
                    ].map((setting) => (
                      <label
                        key={setting.id}
                        className={styles.emptySwitchRow}
                        htmlFor={'parsing-empty-' + setting.id}
                      >
                        <span>
                          <strong>{setting.label}</strong>
                          <small>{setting.description}</small>
                        </span>
                        <Switch
                          id={'parsing-empty-' + setting.id}
                          checked={setting.checked}
                          onCheckedChange={setting.change}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              </aside>
            </div>
          ) : (
            <div
              className={cn(styles.empty, isQueueRehydrating && styles.loading)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => handleFolderDrop(event, currentFolderId)}
            >
              {isQueueRehydrating ? (
                <Loader2 className="size-7 animate-spin text-muted-foreground motion-reduce:animate-none" />
              ) : (
                <PageTitleIcon name="parsing" compact={false} className="size-11" />
              )}
              <h2>
                {isQueueRehydrating
                  ? '正在恢复文件'
                  : sidebarFileItems.length
                    ? '选择文档查看解析结果'
                    : '上传待解析的文档'}
              </h2>
              {!isQueueRehydrating && sidebarFileItems.length === 0 ? <p>支持 PDF、Word、表格和图片。</p> : null}
              <Button
                onClick={() => (sidebarFileItems.length ? setQueueOpen(true) : requestUploadToFolder(currentFolderId))}
                className="gap-2 bg-accent text-accent-foreground hover:bg-accent/90"
                disabled={isQueueRehydrating}
              >
                <UploadCloud className="size-4" />
                {sidebarFileItems.length ? '选择文档' : '选择文件'}
              </Button>
            </div>
          )}
        </section>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={UPLOAD_ACCEPT_WITH_ZIP}
        aria-label="选择待解析文件"
        className="hidden"
        onChange={(event) => void handleFileSelect(event)}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        {...{ webkitdirectory: '' }}
        aria-label="选择待解析文件夹"
        className="hidden"
        onChange={(event) => void handleFileSelect(event)}
      />
      <input
        ref={rebindInputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        aria-label="重新关联原文件"
        className="hidden"
        onChange={(event) => void handleRebindFileSelect(event)}
      />

      <WorkbenchPanelDialog open={queueOpen} onOpenChange={setQueueOpen} title="文件目录" className={styles.fileDialog}>
        <div className={styles.directoryTools}>
          <span>
            {sidebarFileItems.length} 个文件 · {parsedCount} 已解析
            {parsingCount ? ' · ' + parsingCount + ' 解析中' : ''}
            {pendingCount ? ' · ' + pendingCount + ' 待解析' : ''}
          </span>
          {parseableCount > 0 ? (
            <Button size="sm" variant="outline" onClick={() => detachPromise(parseAllPending())}>
              {selectedDatasetId === null ? '解析当前文件夹待处理文件' : '解析当前数据范围待处理文件'} ({parseableCount}
              )
            </Button>
          ) : null}
        </div>
        <div className={styles.tree}>
          {librarySyncFeedback}
          {libraryLoadError !== undefined && (
            <div className={styles.empty} role="alert">
              <p>本地文档记录读取失败：{formatApiError(libraryLoadError, '无法读取文档目录')}</p>
              <Button size="sm" variant="ghost" onClick={retryLibraryLoad}>
                重试读取文档
              </Button>
            </div>
          )}
          {isLibraryLoaded || libraryFiles.length > 0 ? (
            <DocumentFolderTree
              fileItems={sidebarFileItems}
              showFiles="expanded"
              onRequestUpload={requestUploadToFolder}
              onRequestUploadFolder={requestUploadFolder}
              onSelectFile={selectFile}
              onToggleFileSelected={onToggleGovernanceFileSelection}
              onDeleteFolder={handleDeleteFolder}
              onFileDrop={moveFileToFolder}
              onRetryFile={(fileId) => detachPromise(parseFile(fileId))}
              onRemoveFile={removeFile}
              onFileDragStart={handleFileDragStart}
            />
          ) : libraryLoadError === undefined ? (
            <div className={styles.empty}>
              <Loader2 className="size-5 animate-spin" />
              正在加载文件目录
            </div>
          ) : null}
        </div>
        {readyGovernanceCount > 0 ? (
          <div className={styles.directoryTools}>
            <span>
              {selectedReadyGovernanceCount} / {readyGovernanceCount} 个待治理文件已选
              {selectedOtherFolderCount > 0 ? `（其中 ${selectedOtherFolderCount} 个在其他文件夹）` : ''}
            </span>
            <Button
              size="sm"
              className="gap-2"
              disabled={!selectedReadyGovernanceCount || isSubmittingGovernance}
              onClick={() => void onSubmitSelectedToGovernance()}
            >
              {isSubmittingGovernance ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ShieldCheck className="size-4" />
              )}
              {isSubmittingGovernance ? '正在移交' : '提交所选文件'}
            </Button>
          </div>
        ) : null}
      </WorkbenchPanelDialog>

      <WorkbenchPanelDialog
        open={inspectorOpen}
        onOpenChange={setInspectorOpen}
        title="解析设置"
        className={styles.settingsDialog}
      >
        <div className={styles.settingsBody}>
          <div className={styles.settingGroup}>
            <h2>默认解析器</h2>
            <p>适用于新上传的文档。已上传的文档可单独更改。</p>
            <ParsingParserPicker
              value={parserBackend}
              onChange={setParserBackend}
              disabled={isEditing || selectedStatus === 'parsing'}
            />
          </div>
          <div className={styles.settingGroup}>
            <h2>图像处理</h2>
            {[
              {
                id: 'caption',
                label: '图片描述',
                description: '为文档中的图片生成文字描述',
                checked: imageCaptionEnabled,
                change: setImageCaptionEnabled,
              },
              {
                id: 'ocr',
                label: '图片文字识别',
                description: '提取图片中的文字',
                checked: imageOcrEnabled,
                change: setImageOcrEnabled,
              },
              {
                id: 'correction',
                label: '视觉校正',
                description: '通过视觉模型校正文档识别结果',
                checked: vlmCorrectionEnabled,
                change: setVlmCorrectionEnabled,
              },
            ].map((setting) => (
              <label key={setting.id} className={styles.settingRow} htmlFor={'parsing-' + setting.id}>
                <span>
                  <strong>{setting.label}</strong>
                  <small>{setting.description}</small>
                </span>
                <Switch id={'parsing-' + setting.id} checked={setting.checked} onCheckedChange={setting.change} />
              </label>
            ))}
          </div>
        </div>
      </WorkbenchPanelDialog>
    </AppFrame>
  )
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
