'use client'

import { useCallback, useState } from 'react'
import type { ChangeEvent as ReactChangeEvent } from 'react'
import { toast } from 'sonner'

import { ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'
import { useParsingEditorActions } from '@/components/parsing/use-parsing-editor-actions'
import { useParsingLibraryActions } from '@/components/parsing/use-parsing-library-actions'
import { useParsingPageState } from '@/components/parsing/use-parsing-page-state'
import { useParsingQueueActions } from '@/components/parsing/use-parsing-queue-actions'
import { useParsingRunActions } from '@/components/parsing/use-parsing-run-actions'
import { useParsingViewState } from '@/components/parsing/use-parsing-view-state'
import { formatApiError } from '@/lib/api-errors'

import { ParsingWorkbenchShell } from './parsing-workbench-shell'
import type { ParsedFile } from './parsing-types'

export default function ParsingPage() {
  const [files, setFiles] = useState<ParsedFile[]>([])
  const [selectedGovernanceFileIds, setSelectedGovernanceFileIds] = useState<Set<string>>(() => new Set())
  const pageState = useParsingPageState({ files, setFiles })

  const upsertParsedFile = useParsedFiles((state) => state.upsertParsedFile)
  const replaceParsedFile = useParsedFiles((state) => state.replaceParsedFile)
  const setParsedFiles = useParsedFiles((state) => state.setParsedFiles)
  const libraryFiles = useParsedFiles((state) => state.files)
  const updateParsedFile = useParsedFiles((state) => state.updateParsedFile)
  const removeParsedFile = useParsedFiles((state) => state.removeFile)
  const moveFolder = useParsedFiles((state) => state.moveFolder)
  const activeFolderId = useParsedFiles((state) => state.activeFolderId)
  const folders = useParsedFiles((state) => state.folders)
  const createFolder = useParsedFiles((state) => state.createFolder)
  const setActiveFolderId = useParsedFiles((state) => state.setActiveFolderId)
  const isLibraryLoaded = useParsedFiles((state) => state.isLoaded)
  const libraryLoadError = useParsedFiles((state) => state.loadError)
  const consumeUploadTargetFolderId = pageState.consumeUploadTargetFolderId

  const {
    addFiles,
    handleRebindFileSelect,
    requestRebindForLibraryFile,
    requestUploadFolder,
    requestUploadToFolder,
    restoreLibraryFileFromCache,
  } = useParsingLibraryActions({
    activeFolderId,
    activeFileId: pageState.activeFileId,
    activeLibraryFileId: pageState.activeLibraryFileId,
    createFolder,
    fileInputRef: pageState.fileInputRef,
    filesRef: pageState.filesRef,
    folderInputRef: pageState.folderInputRef,
    isLibraryLoaded,
    libraryFiles,
    parserBackend: pageState.parserBackend,
    selectedDatasetId: pageState.selectedDatasetId,
    rebindInputRef: pageState.rebindInputRef,
    rebindTargetRef: pageState.rebindTargetRef,
    removeParsedFile,
    setActiveBlockId: pageState.setActiveBlockId,
    setActiveFileId: pageState.setActiveFileId,
    setActiveFolderId,
    setActiveLibraryFileId: pageState.setActiveLibraryFileId,
    setAutoParseFileId: pageState.setAutoParseFileId,
    setFiles,
    setHoveredBlockId: pageState.setHoveredBlockId,
    setIsQueueRehydrating: pageState.setIsQueueRehydrating,
    setRightPanelMode: pageState.setRightPanelMode,
    updateParsedFile,
    uploadTargetFolderIdRef: pageState.uploadTargetFolderIdRef,
    upsertParsedFile,
  })

  const viewState = useParsingViewState({
    activeFileId: pageState.activeFileId,
    activeFolderId,
    activeLibraryFileId: pageState.activeLibraryFileId,
    files,
    folders,
    isEditing: pageState.isEditing,
    isLibraryLoaded,
    libraryFiles,
    selectedDatasetId: pageState.selectedDatasetId,
    setActiveFileId: pageState.setActiveFileId,
    setActiveLibraryFileId: pageState.setActiveLibraryFileId,
    setParsedFiles,
    updateParsedFile,
  })

  const handleFileSelect = useCallback(
    async (event: ReactChangeEvent<HTMLInputElement>) => {
      const targetFolderId = consumeUploadTargetFolderId()
      const input = event.currentTarget
      if (input.files === null || input.files.length === 0) return
      const selectedFiles = Array.from(input.files)
      input.value = ''
      try {
        await addFiles(selectedFiles, targetFolderId ?? undefined)
      } catch (error) {
        toast.error(formatApiError(error, '添加文件失败'))
      }
    },
    [addFiles, consumeUploadTargetFolderId],
  )

  const toggleGovernanceFileSelection = useCallback(
    (fileId: string) => {
      const queueFile = pageState.filesRef.current.find((file) => file.id === fileId)
      const selectionId = queueFile?.libraryId ?? fileId
      setSelectedGovernanceFileIds((prev) => {
        const next = new Set(prev)
        if (next.has(selectionId)) {
          next.delete(selectionId)
        } else {
          next.add(selectionId)
        }
        return next
      })
    },
    [pageState.filesRef],
  )

  const queueActions = useParsingQueueActions({
    cancelParse: pageState.cancelParse,
    filesRef: pageState.filesRef,
    moveFolder,
    removeParsedFile,
    setSelectedGovernanceFileIds,
    setActiveFileId: pageState.setActiveFileId,
    setActiveLibraryFileId: pageState.setActiveLibraryFileId,
    setFiles,
    updateParsedFile,
  })

  const runActions = useParsingRunActions({
    restoreLibraryFileFromCache,
    replaceParsedFile,
    removeParsedFile,
    setActiveLibraryFileId: pageState.setActiveLibraryFileId,
    setSelectedGovernanceFileIds,
    activeFile: viewState.activeFile,
    autoParseFileId: pageState.autoParseFileId,
    cancelParse: pageState.cancelParse,
    filesRef: pageState.filesRef,
    imageCaptionEnabled: pageState.imageCaptionEnabled,
    imageOcrEnabled: pageState.imageOcrEnabled,
    parseControllersRef: pageState.parseControllersRef,
    parseProgressIntervalsRef: pageState.parseProgressIntervalsRef,
    setActiveBlockId: pageState.setActiveBlockId,
    setAutoParseFileId: pageState.setAutoParseFileId,
    setFiles,
    setHoveredBlockId: pageState.setHoveredBlockId,
    setRightPanelMode: pageState.setRightPanelMode,
    updateParsedFile,
    upsertParsedFile,
    visibleQueueFiles: viewState.visibleQueueFiles,
    vlmCorrectionEnabled: pageState.vlmCorrectionEnabled,
  })

  const editorActions = useParsingEditorActions({
    filesRef: pageState.filesRef,
    activeBlockId: pageState.activeBlockId,
    activeBlocksWithPositions: viewState.activeBlocksWithPositions,
    activeFile: viewState.activeFile,
    activeMarkdown: viewState.activeMarkdown,
    activeRun: viewState.activeRun,
    editSession: pageState.editSession,
    editedContent: pageState.editedContent,
    currentFolderId: viewState.currentFolderId,
    selectedDatasetId: pageState.selectedDatasetId,
    queueFiles: viewState.queueFiles,
    libraryFiles,
    selectedGovernanceFileIds,
    setActiveBlockId: pageState.setActiveBlockId,
    setEditSession: pageState.setEditSession,
    setEditedContent: pageState.setEditedContent,
    setFiles,
    setHoveredBlockId: pageState.setHoveredBlockId,
    setIsEditing: pageState.setIsEditing,
    setRightPanelMode: pageState.setRightPanelMode,
    setSelectedGovernanceFileIds,
    updateParsedFile,
  })

  return (
    <ParsingWorkbenchShell
      activeBlockId={pageState.activeBlockId}
      activeBlocksWithPositions={viewState.activeBlocksWithPositions}
      activeFile={viewState.activeFile}
      activeFileId={pageState.activeFileId}
      activeFolderId={activeFolderId}
      activeLibraryFile={viewState.activeLibraryFile}
      activeLibraryFileId={pageState.activeLibraryFileId}
      activeLibrarySourceStatus={viewState.activeLibrarySourceStatus}
      activeLibrarySourceError={viewState.activeLibrarySourceError}
      isLibrarySourceChecking={viewState.isLibrarySourceChecking}
      retryLibrarySource={viewState.retryLibrarySource}
      activeMarkdown={viewState.activeMarkdown}
      activeLibraryContentError={viewState.activeLibraryContentError}
      isLibraryContentLoading={viewState.isLibraryContentLoading}
      hasLibraryContent={viewState.hasLibraryContent}
      retryLibraryContent={viewState.retryLibraryContent}
      availableDatasets={viewState.availableDatasets}
      datasetsError={viewState.datasetsError}
      librarySyncError={viewState.librarySyncError}
      isLibrarySyncing={viewState.isLibrarySyncing}
      retryLibrarySync={viewState.retryLibrarySync}
      activeElements={viewState.activeElements}
      activePdfQuality={viewState.activePdfQuality}
      activeQualityGate={viewState.activeQualityGate}
      activeRun={viewState.activeRun}
      isRunUnavailable={viewState.isRunUnavailable}
      copied={editorActions.copied}
      copyMarkdown={editorActions.copyMarkdown}
      currentFolderId={viewState.currentFolderId}
      downloadMarkdown={editorActions.downloadMarkdown}
      editedContent={pageState.editedContent}
      fileInputRef={pageState.fileInputRef}
      files={viewState.queueFiles}
      folderInputRef={pageState.folderInputRef}
      folderPathById={viewState.folderPathById}
      folders={folders}
      handleCancelEdit={editorActions.handleCancelEdit}
      handleDeleteFolder={queueActions.handleDeleteFolder}
      handleFileDragStart={queueActions.handleFileDragStart}
      handleFileSelect={handleFileSelect}
      addFiles={addFiles}
      handleFolderDrop={queueActions.handleFolderDrop}
      handleRebindFileSelect={handleRebindFileSelect}
      handleSaveEdit={editorActions.handleSaveEdit}
      handleSelectRun={runActions.handleSelectRun}
      handleStartEdit={editorActions.handleStartEdit}
      handleSubmitToGovernance={editorActions.handleSubmitToGovernance}
      hoveredBlockId={pageState.hoveredBlockId}
      imageCaptionEnabled={pageState.imageCaptionEnabled}
      imageOcrEnabled={pageState.imageOcrEnabled}
      inspectorOpen={pageState.inspectorOpen}
      isEditing={pageState.isEditing}
      isSubmittingGovernance={editorActions.isSubmittingGovernance}
      isLibraryLoaded={isLibraryLoaded}
      libraryLoadError={libraryLoadError}
      retryLibraryLoad={() => void useParsedFiles.persist.rehydrate()}
      isPdf={viewState.isPdf}
      isQueueRehydrating={pageState.isQueueRehydrating}
      libraryFiles={libraryFiles}
      moveFileToFolder={queueActions.moveFileToFolder}
      parseAllPending={runActions.parseAllPending}
      parseFile={runActions.parseFile}
      parserBackend={pageState.parserBackend}
      pdfPreviewResetToken={pageState.pdfPreviewResetToken}
      previewMode={pageState.previewMode}
      queueOpen={pageState.queueOpen}
      rebindInputRef={pageState.rebindInputRef}
      removeFile={queueActions.removeFile}
      requestRebindForLibraryFile={requestRebindForLibraryFile}
      requestUploadFolder={requestUploadFolder}
      requestUploadToFolder={requestUploadToFolder}
      restoreLibraryFileFromCache={restoreLibraryFileFromCache}
      rightPanelMode={pageState.rightPanelMode}
      setActiveBlockId={pageState.setActiveBlockId}
      setActiveFileId={pageState.setActiveFileId}
      setActiveFolderId={setActiveFolderId}
      setActiveLibraryFileId={pageState.setActiveLibraryFileId}
      setEditedContent={pageState.setEditedContent}
      setHoveredBlockId={pageState.setHoveredBlockId}
      setImageCaptionEnabled={pageState.setImageCaptionEnabled}
      setImageOcrEnabled={pageState.setImageOcrEnabled}
      setInspectorOpen={pageState.setInspectorOpen}
      setParserBackend={pageState.setParserBackend}
      setPdfPreviewResetToken={pageState.setPdfPreviewResetToken}
      setPreviewMode={pageState.setPreviewMode}
      setQueueFileParserBackend={pageState.setQueueFileParserBackend}
      setQueueOpen={pageState.setQueueOpen}
      setRightPanelMode={pageState.setRightPanelMode}
      setVlmCorrectionEnabled={pageState.setVlmCorrectionEnabled}
      selectedGovernanceFileIds={selectedGovernanceFileIds}
      selectedDatasetId={pageState.selectedDatasetId}
      startKnowledgeParsing={runActions.startKnowledgeParsing}
      onSubmitSelectedToGovernance={editorActions.handleSubmitSelectedToGovernance}
      onToggleGovernanceFileSelection={toggleGovernanceFileSelection}
      onDatasetScopeChange={(datasetId) => {
        setSelectedGovernanceFileIds(new Set())
        pageState.setSelectedDatasetId(datasetId)
        pageState.setActiveFileId(null)
        pageState.setActiveLibraryFileId(null)
        setActiveFolderId(ROOT_FOLDER_ID)
      }}
      tocEnabled={viewState.tocEnabled}
      updateParsedFile={updateParsedFile}
      visibleQueueFiles={viewState.visibleQueueFiles}
      vlmCorrectionEnabled={pageState.vlmCorrectionEnabled}
    />
  )
}
