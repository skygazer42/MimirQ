'use client'

import { useCallback, useState } from 'react'

import { useParsedFiles } from '@/store/use-parsed-files-store'
import { useParsingEditorActions } from '@/components/parsing/use-parsing-editor-actions'
import { useParsingLibraryActions } from '@/components/parsing/use-parsing-library-actions'
import { useParsingPageState } from '@/components/parsing/use-parsing-page-state'
import { useParsingQueueActions } from '@/components/parsing/use-parsing-queue-actions'
import { useParsingRunActions } from '@/components/parsing/use-parsing-run-actions'
import { useParsingViewState } from '@/components/parsing/use-parsing-view-state'

import { bumpParsingProgress, countMarkdownHeadings, mapBackendStatusToLibraryStatus } from './parsing-page-utils'
import { ParsingWorkbenchShell } from './parsing-workbench-shell'
import type { ParsedFile } from './parsing-types'

export default function ParsingPage() {
  const [files, setFiles] = useState<ParsedFile[]>([])
  const pageState = useParsingPageState({ files, setFiles })

  const addParsedFile = useParsedFiles((state) => state.addParsedFile)
  const upsertParsedFile = useParsedFiles((state) => state.upsertParsedFile)
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
  const consumeUploadTargetFolderId = pageState.consumeUploadTargetFolderId

  const {
    addFiles,
    handleRebindFileSelect,
    mountLibraryFileToQueue,
    removeLibraryCaches,
    requestRebindForLibraryFile,
    requestUploadFolder,
    requestUploadToFolder,
    restoreLibraryFileFromCache,
  } = useParsingLibraryActions({
    activeFolderId,
    countMarkdownHeadings,
    createFolder,
    fileInputRef: pageState.fileInputRef,
    filesRef: pageState.filesRef,
    folderInputRef: pageState.folderInputRef,
    folders,
    libraryFiles,
    mapBackendStatusToLibraryStatus,
    parserBackend: pageState.parserBackend,
    rebindInputRef: pageState.rebindInputRef,
    rebindTargetRef: pageState.rebindTargetRef,
    setActiveBlockId: pageState.setActiveBlockId,
    setActiveFileId: pageState.setActiveFileId,
    setActiveFolderId,
    setActiveLibraryFileId: pageState.setActiveLibraryFileId,
    setActiveLibrarySourceStatus: pageState.setActiveLibrarySourceStatus,
    setAutoParseFileId: pageState.setAutoParseFileId,
    setFiles,
    setHoveredBlockId: pageState.setHoveredBlockId,
    setRightPanelMode: pageState.setRightPanelMode,
    updateParsedFile,
    uploadTargetFolderIdRef: pageState.uploadTargetFolderIdRef,
    upsertParsedFile,
  })

  const viewState = useParsingViewState({
    activeFileId: pageState.activeFileId,
    activeFolderId,
    activeLibraryFileId: pageState.activeLibraryFileId,
    didSyncLibraryFromServerRef: pageState.didSyncLibraryFromServerRef,
    files,
    folders,
    isLibraryLoaded,
    libraryFiles,
    mapBackendStatusToLibraryStatus,
    mountLibraryFileToQueue,
    rehydratedFolderIdsRef: pageState.rehydratedFolderIdsRef,
    setActiveFileId: pageState.setActiveFileId,
    setActiveLibrarySourceStatus: pageState.setActiveLibrarySourceStatus,
    setIsQueueRehydrating: pageState.setIsQueueRehydrating,
    setParsedFiles,
    updateParsedFile,
  })

  const handleFileSelect = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const targetFolderId = consumeUploadTargetFolderId()

      const selectedFiles = event.target.files ? Array.from(event.target.files) : []
      if (selectedFiles.length > 0) {
        await addFiles(selectedFiles, targetFolderId || undefined)
      }

      event.target.value = ''
    },
    [addFiles, consumeUploadTargetFolderId]
  )

  const queueActions = useParsingQueueActions({
    activeFileId: pageState.activeFileId,
    activeLibraryFileId: pageState.activeLibraryFileId,
    cancelParse: pageState.cancelParse,
    files,
    libraryFiles,
    moveFolder,
    removeLibraryCaches,
    removeParsedFile,
    setActiveFileId: pageState.setActiveFileId,
    setActiveLibraryFileId: pageState.setActiveLibraryFileId,
    setDragOverFolderId: pageState.setDragOverFolderId,
    setFiles,
    updateParsedFile,
  })

  const runActions = useParsingRunActions({
    activeFile: viewState.activeFile,
    autoParseFileId: pageState.autoParseFileId,
    bumpParsingProgress,
    cancelParse: pageState.cancelParse,
    countMarkdownHeadings,
    fileIdSetRef: pageState.fileIdSetRef,
    filesRef: pageState.filesRef,
    imageCaptionEnabled: pageState.imageCaptionEnabled,
    mapBackendStatusToLibraryStatus,
    parseControllersRef: pageState.parseControllersRef,
    parseProgressIntervalsRef: pageState.parseProgressIntervalsRef,
    parserBackend: pageState.parserBackend,
    setActiveBlockId: pageState.setActiveBlockId,
    setAutoParseFileId: pageState.setAutoParseFileId,
    setFiles,
    setHoveredBlockId: pageState.setHoveredBlockId,
    setRightPanelMode: pageState.setRightPanelMode,
    updateParsedFile,
    upsertParsedFile,
    visibleQueueFiles: viewState.visibleQueueFiles,
  })

  const editorActions = useParsingEditorActions({
    activeBlockId: pageState.activeBlockId,
    activeBlocksWithPositions: viewState.activeBlocksWithPositions,
    activeFile: viewState.activeFile,
    activeMarkdown: viewState.activeMarkdown,
    activeRun: viewState.activeRun,
    addParsedFile,
    countMarkdownHeadings,
    editSession: pageState.editSession,
    editedContent: pageState.editedContent,
    setActiveBlockId: pageState.setActiveBlockId,
    setCopied: pageState.setCopied,
    setEditSession: pageState.setEditSession,
    setEditedContent: pageState.setEditedContent,
    setFiles,
    setHoveredBlockId: pageState.setHoveredBlockId,
    setIsEditing: pageState.setIsEditing,
    setRightPanelMode: pageState.setRightPanelMode,
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
      activeLibrarySourceStatus={pageState.activeLibrarySourceStatus}
      activeMarkdown={viewState.activeMarkdown}
      activeElements={viewState.activeElements}
      activePdfQuality={viewState.activePdfQuality}
      activeQualityGate={viewState.activeQualityGate}
      activeRun={viewState.activeRun}
      copied={pageState.copied}
      copyMarkdown={editorActions.copyMarkdown}
      currentFolderId={viewState.currentFolderId}
      dragOverFolderId={pageState.dragOverFolderId}
      downloadMarkdown={editorActions.downloadMarkdown}
      editedContent={pageState.editedContent}
      fileInputRef={pageState.fileInputRef}
      files={files}
      folderInputRef={pageState.folderInputRef}
      folderPathById={viewState.folderPathById}
      folders={folders}
      handleCancelEdit={editorActions.handleCancelEdit}
      handleDeleteFolder={queueActions.handleDeleteFolder}
      handleFileDragStart={queueActions.handleFileDragStart}
      handleFileSelect={handleFileSelect}
      handleFolderDragLeave={queueActions.handleFolderDragLeave}
      handleFolderDragOver={queueActions.handleFolderDragOver}
      handleFolderDrop={queueActions.handleFolderDrop}
      handleRebindFileSelect={handleRebindFileSelect}
      handleSaveEdit={editorActions.handleSaveEdit}
      handleSelectRun={runActions.handleSelectRun}
      handleStartEdit={editorActions.handleStartEdit}
      handleSubmitToGovernance={editorActions.handleSubmitToGovernance}
      hoveredBlockId={pageState.hoveredBlockId}
      imageCaptionEnabled={pageState.imageCaptionEnabled}
      inspectorOpen={pageState.inspectorOpen}
      isEditing={pageState.isEditing}
      isLibraryLoaded={isLibraryLoaded}
      isPdf={viewState.isPdf}
      isQueueRehydrating={pageState.isQueueRehydrating}
      isSidebarCollapsed={pageState.isSidebarCollapsed}
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
      setInspectorOpen={pageState.setInspectorOpen}
      setIsSidebarCollapsed={pageState.setIsSidebarCollapsed}
      setParserBackend={pageState.setParserBackend}
      setPdfPreviewResetToken={pageState.setPdfPreviewResetToken}
      setPreviewMode={pageState.setPreviewMode}
      setQueueFileParserBackend={pageState.setQueueFileParserBackend}
      setQueueOpen={pageState.setQueueOpen}
      setRightPanelMode={pageState.setRightPanelMode}
      tocEnabled={viewState.tocEnabled}
      updateParsedFile={updateParsedFile}
      visibleLibraryOnlyFiles={viewState.visibleLibraryOnlyFiles}
      visibleQueueFiles={viewState.visibleQueueFiles}
    />
  )
}
