'use client'

import type { RefObject } from 'react'
import { FileText, FileStack, Settings2, Sparkles } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { AppFrame } from '@/components/app-frame'
import { ParsingActiveFilePane } from '@/components/parsing/parsing-active-file-pane'
import { ParsingLibraryBrowser } from '@/components/parsing/parsing-library-browser'
import { ParsingLibraryPreviewPane } from '@/components/parsing/parsing-library-preview-pane'
import { ParsingMainPanel } from '@/components/parsing/parsing-main-panel'
import { ParsingMobileInspectorContent } from '@/components/parsing/parsing-mobile-inspector-content'
import { ParsingMobileQueueContent } from '@/components/parsing/parsing-mobile-queue-content'
import { ParsingSidebarPane } from '@/components/parsing/parsing-sidebar-pane'
import { Button } from '@/components/ui/button'
import { PipelineRail, WorkbenchPanelDialog, WorkbenchScaffold } from '@/components/workbench'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { UPLOAD_ACCEPT, UPLOAD_ACCEPT_WITH_ZIP } from '@/lib/upload-extensions'
import { detachPromise } from '@/lib/utils'
import type { ParsingBlock } from '@/lib/parsing-positions'
import { type FolderNode, ROOT_FOLDER_ID, type ParsedFileData } from '@/store/use-parsed-files-store'

import { getLibraryStatusBadge } from './parsing-page-utils'
import type { ParsedFile, ParseRun } from './parsing-types'
import type { ParsingLibrarySourceStatus } from './use-parsing-page-state'

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
  handleFileDragStart: (event: React.DragEvent<HTMLElement>, fileId: string) => void
  handleFileSelect: (event: React.ChangeEvent<HTMLInputElement>) => Promise<void>
  handleFolderDragLeave: () => void
  handleFolderDragOver: (event: React.DragEvent<HTMLElement>, folderId: string) => void
  handleFolderDrop: (event: React.DragEvent<HTMLElement>, folderId: string) => void
  handleRebindFileSelect: (event: React.ChangeEvent<HTMLInputElement>) => Promise<void>
  handleSaveEdit: () => Promise<void>
  handleSelectRun: (runId: string) => void
  handleStartEdit: () => void
  handleSubmitToGovernance: () => void
  hoveredBlockId: string | null
  imageCaptionEnabled: boolean
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
  previewMode: 'raw' | 'rendered'
  queueOpen: boolean
  rebindInputRef: RefObject<HTMLInputElement | null>
  removeFile: (fileId: string) => void
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
  setInspectorOpen: (open: boolean) => void
  setIsSidebarCollapsed: (collapsed: boolean) => void
  setParserBackend: (backend: string) => void
  setPreviewMode: (mode: 'raw' | 'rendered') => void
  setQueueOpen: (open: boolean) => void
  setQueueFileParserBackend: (params: { fileId: string; filename: string; backend: string }) => void
  setRightPanelMode: (mode: 'blocks' | 'markdown') => void
  tocEnabled: boolean
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => void
  visibleLibraryOnlyFiles: ParsedFileData[]
  visibleQueueFiles: ParsedFile[]
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
  activePdfQuality,
  activeQualityGate,
  activeRun,
  copied,
  copyMarkdown,
  currentFolderId,
  dragOverFolderId,
  downloadMarkdown,
  editedContent,
  fileInputRef,
  files,
  folderInputRef,
  folderPathById,
  folders,
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
  inspectorOpen,
  isEditing,
  isLibraryLoaded,
  isPdf,
  isQueueRehydrating,
  isSidebarCollapsed,
  libraryFiles,
  moveFileToFolder,
  parseAllPending,
  parseFile,
  parserBackend,
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
  setInspectorOpen,
  setIsSidebarCollapsed,
  setParserBackend,
  setPreviewMode,
  setQueueOpen,
  setQueueFileParserBackend,
  setRightPanelMode,
  tocEnabled,
  updateParsedFile,
  visibleLibraryOnlyFiles,
  visibleQueueFiles,
}: Readonly<ParsingWorkbenchShellProps>) {
  const t = useTranslations('ParsingWorkbench')
  const pendingCount = visibleQueueFiles.filter((file) => file.status === 'pending').length
  const parsingCount = visibleQueueFiles.filter((file) => file.status === 'parsing').length
  const parsedCount = visibleQueueFiles.filter((file) => file.status === 'parsed').length
  const parseableCount = visibleQueueFiles.filter((file) => file.status === 'pending' || file.status === 'error').length
  const queueCountLabel = visibleQueueFiles.length === 0 ? '0' : `${parsedCount}/${visibleQueueFiles.length}`

  const activeFolderPathLabel = folderPathById[activeFolderId || ROOT_FOLDER_ID] || t('rootFolder')
  const activeLibraryFolderId = activeLibraryFile?.folderId || ROOT_FOLDER_ID
  const activeLibraryFolderPathLabel = folderPathById[activeLibraryFolderId] || t('rootFolder')
  const activeLibraryFolderName = (activeLibraryFolderPathLabel.split('/').pop() || '').trim() || activeLibraryFolderPathLabel
  const activeLibraryStatusBadge = activeLibraryFile?.status ? getLibraryStatusBadge(activeLibraryFile.status) : null

  const libraryFileListContent = (
    <ParsingLibraryBrowser
      currentFolderId={currentFolderId}
      activeFolderId={activeFolderId || ROOT_FOLDER_ID}
      activeFileId={activeFileId}
      activeLibraryFileId={activeLibraryFileId}
      dragOverFolderId={dragOverFolderId}
      isLibraryLoaded={isLibraryLoaded}
      isQueueRehydrating={isQueueRehydrating}
      folders={folders}
      files={files}
      libraryFiles={libraryFiles}
      visibleQueueFiles={visibleQueueFiles}
      visibleLibraryOnlyFiles={visibleLibraryOnlyFiles}
      folderPathById={folderPathById}
      onFolderSelect={setActiveFolderId}
      onFolderDragOver={handleFolderDragOver}
      onFolderDragLeave={handleFolderDragLeave}
      onFolderDrop={handleFolderDrop}
      onQueueFileDragStart={handleFileDragStart}
      onSelectQueueFile={(fileId) => {
        setActiveLibraryFileId(null)
        setActiveFileId(fileId)
      }}
      onSelectLibraryFile={(fileId) => {
        setActiveFileId(null)
        setActiveLibraryFileId(fileId)
      }}
      onRemoveFile={removeFile}
      onRetryParse={(fileId) => detachPromise(parseFile(fileId))}
    />
  )

  return (
    <AppFrame>
      <WorkbenchScaffold
        title={t('title')}
        description={t('description')}
        icon={Sparkles}
        iconColor="text-primary"
        size="full"
        bodyClassName="px-0 pb-0"
        pipelineRail={<PipelineRail />}
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 lg:hidden"
              onClick={() => setQueueOpen(true)}
            >
              <FileStack className="w-4 h-4" />
              {t('queue')}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 lg:hidden"
              onClick={() => setInspectorOpen(true)}
            >
              <Settings2 className="w-4 h-4" />
              {t('tools')}
            </Button>
          </div>
        }
        mainPanel={
          <ParsingMainPanel>
            <ParsingSidebarPane
              collapsed={isSidebarCollapsed}
              onToggleCollapsed={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
              className="hidden lg:flex"
              activeFolderId={activeFolderId || ROOT_FOLDER_ID}
              activeFolderPathLabel={activeFolderPathLabel}
              currentFolderId={currentFolderId}
              visibleQueueFilesCount={visibleQueueFiles.length}
              pendingCount={pendingCount}
              parsingCount={parsingCount}
              parsedCount={parsedCount}
              parseableCount={parseableCount}
              parserBackend={parserBackend}
              imageCaptionEnabled={imageCaptionEnabled}
              isLibraryLoaded={isLibraryLoaded}
              libraryFileListContent={libraryFileListContent}
              fileAccept={UPLOAD_ACCEPT_WITH_ZIP}
              rebindAccept={UPLOAD_ACCEPT}
              fileInputRef={fileInputRef}
              folderInputRef={folderInputRef}
              rebindInputRef={rebindInputRef}
              onRequestUploadToCurrentFolder={() => requestUploadToFolder(currentFolderId)}
              onRequestUploadToFolder={requestUploadToFolder}
              onRequestUploadFolder={requestUploadFolder}
              onParseAllPending={() => detachPromise(parseAllPending())}
              onParserBackendChange={setParserBackend}
              onImageCaptionEnabledChange={setImageCaptionEnabled}
              onFolderDragOver={handleFolderDragOver}
              onFolderDragLeave={handleFolderDragLeave}
              onFolderDrop={handleFolderDrop}
              onFolderTreeSelectFile={(fileId) => {
                const queueMatch = files.find((file) => file.libraryId === fileId)
                if (queueMatch) {
                  setActiveLibraryFileId(null)
                  setActiveFileId(queueMatch.id)
                  return
                }

                setActiveFileId(null)
                setActiveLibraryFileId(fileId)
              }}
              onDeleteFolder={handleDeleteFolder}
              onMoveFileToFolder={moveFileToFolder}
              onFileSelect={(event) => void handleFileSelect(event)}
              onRebindFileSelect={(event) => void handleRebindFileSelect(event)}
            />

            <div className="flex flex-1 min-h-0 min-w-0 flex-col overflow-hidden bg-card shadow-sm ring-1 ring-border/40 dark:bg-background dark:shadow-none">
              {activeFile || activeLibraryFile ? (
                <>
                  {!activeFile && activeLibraryFile ? (
                    <ParsingLibraryPreviewPane
                      file={activeLibraryFile}
                      activeMarkdown={activeMarkdown}
                      folderName={activeLibraryFolderName}
                      folderPathLabel={activeLibraryFolderPathLabel}
                      sourceStatus={activeLibrarySourceStatus}
                      defaultParserBackend={parserBackend}
                      statusBadge={activeLibraryStatusBadge}
                      onClose={() => setActiveLibraryFileId(null)}
                      onUpdateParser={(backend) => {
                        const resolved = resolveParserBackendForFilename(activeLibraryFile.filename, backend)
                        updateParsedFile(activeLibraryFile.id, {
                          parserBackend: resolved.backend,
                          parser: getParserLabel(resolved.backend),
                        })
                      }}
                      onRestoreSource={(autoParse) => {
                        detachPromise(restoreLibraryFileFromCache(activeLibraryFile.id, autoParse))
                      }}
                      onRequestRebind={(autoParse) => requestRebindForLibraryFile(activeLibraryFile.id, autoParse)}
                    />
                  ) : null}

                  {activeFile ? (
                    <ParsingActiveFilePane
                      activeFile={activeFile}
                      activeRun={activeRun}
                      activeMarkdown={activeMarkdown}
                      activeQualityGate={activeQualityGate}
                      activePdfQuality={activePdfQuality}
                      activeBlocksWithPositions={activeBlocksWithPositions}
                      isPdf={isPdf}
                      tocEnabled={tocEnabled}
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
                      onCancelEdit={handleCancelEdit}
                      onSaveEdit={() => detachPromise(handleSaveEdit())}
                      onCopyMarkdown={() => detachPromise(copyMarkdown())}
                      onDownloadMarkdown={downloadMarkdown}
                      onParseFile={parseFile}
                      onSetQueueFileParserBackend={setQueueFileParserBackend}
                      onSubmitToGovernance={handleSubmitToGovernance}
                      onEditedContentChange={setEditedContent}
                      onActiveBlockIdChange={setActiveBlockId}
                      onHoveredBlockIdChange={setHoveredBlockId}
                    />
                  ) : null}
                </>
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <div className="max-w-md text-center">
                    <div className="mx-auto mb-4 flex size-20 items-center justify-center rounded-2xl border border-border/60 bg-card shadow-soft">
                      <FileText className="h-10 w-10 text-muted-foreground dark:text-muted-foreground" />
                    </div>
                    <h3 className="mb-2 text-lg font-medium text-foreground/80 dark:text-muted-foreground">{t('emptyTitle')}</h3>
                    <p className="text-sm text-muted-foreground dark:text-muted-foreground">
                      {t('emptyDescription')}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </ParsingMainPanel>
        }
      />

      <WorkbenchPanelDialog open={queueOpen} onOpenChange={setQueueOpen} title={t('queue')}>
        <ParsingMobileQueueContent
          queueCountLabel={queueCountLabel}
          parseableCount={parseableCount}
          activeFileId={activeFileId}
          activeLibraryFileId={activeLibraryFileId}
          visibleQueueFiles={visibleQueueFiles}
          visibleLibraryOnlyFiles={visibleLibraryOnlyFiles}
          folderPathById={folderPathById}
          files={files}
          onParseAllPending={() => detachPromise(parseAllPending())}
          onRequestUploadToFolder={requestUploadToFolder}
          onRequestUploadFolder={requestUploadFolder}
          onSelectQueueFile={(fileId) => {
            setActiveLibraryFileId(null)
            setActiveFileId(fileId)
            setQueueOpen(false)
          }}
          onSelectLibraryFile={(fileId) => {
            setActiveFileId(null)
            setActiveLibraryFileId(fileId)
            setQueueOpen(false)
          }}
          onDeleteFolder={handleDeleteFolder}
          onMoveFileToFolder={moveFileToFolder}
          onRemoveFile={removeFile}
          onRetryParse={(fileId) => detachPromise(parseFile(fileId))}
          onFileDragStart={handleFileDragStart}
        />
      </WorkbenchPanelDialog>

      <WorkbenchPanelDialog open={inspectorOpen} onOpenChange={setInspectorOpen} title={t('tools')}>
        {activeFile && activeMarkdown ? (
          <ParsingMobileInspectorContent
            activeMarkdown={activeMarkdown}
            rightPanelMode={rightPanelMode}
            previewMode={previewMode}
            activeBlocksWithPositions={activeBlocksWithPositions}
            activeBlockId={activeBlockId}
            onRightPanelModeChange={setRightPanelMode}
            onPreviewModeChange={setPreviewMode}
            onSelectBlock={(blockId) => {
              setActiveBlockId(blockId)
              setInspectorOpen(false)
            }}
            onCopyMarkdown={() => detachPromise(copyMarkdown())}
            onDownloadMarkdown={downloadMarkdown}
          />
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain bg-muted/10 p-4 no-scrollbar">
            <div className="text-sm text-muted-foreground">{t('inspectorEmpty')}</div>
          </div>
        )}
      </WorkbenchPanelDialog>
    </AppFrame>
  )
}
