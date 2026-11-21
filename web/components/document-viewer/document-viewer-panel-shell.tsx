'use client'

import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from 'react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ChunkEditorDialog } from '@/components/document-viewer/chunk-editor-dialog'
import { ChunksTabPanel } from '@/components/document-viewer/chunks-tab-panel'
import { DocumentViewerHeader } from '@/components/document-viewer/document-viewer-header'
import { FloatingMenu } from '@/components/document-viewer/floating-menu'
import { PreviewTabPanel } from '@/components/document-viewer/preview-tab-panel'
import { QAGenerationDialog } from '@/components/document-viewer/qa-generation-dialog'
import { TextTabPanel } from '@/components/document-viewer/text-tab-panel'
import { cn, detachPromise } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { MIN_DOCUMENT_VIEWER_PANEL_WIDTH, MAX_DOCUMENT_VIEWER_PANEL_WIDTH } from '@/store/document-view'

import type { DocumentViewerPanelState } from './use-document-viewer-panel-state'

const DOCUMENT_VIEWER_PANEL_RESIZE_STEP = 24

function ReadErrorFeedback({
  error,
  loading,
  label,
  onRetry,
}: Readonly<{
  error: string | null
  loading: boolean
  label: string
  onRetry: () => void
}>) {
  if (error === null) return null
  return (
    <div
      role="alert"
      className="flex shrink-0 items-center justify-between gap-3 border-b border-border bg-destructive/10 px-4 py-2 text-xs text-destructive"
    >
      <p className="min-w-0 break-words">{error}</p>
      <Button size="sm" variant="ghost" disabled={loading} onClick={onRetry}>
        {label}
      </Button>
    </div>
  )
}

export function DocumentViewerPanelShell({
  activeTab,
  canEditChunks,
  canInlinePreview,
  chunkDeleteSubmitting,
  chunkEditorContent,
  chunkEditorEndChar,
  chunkEditorMode,
  chunkEditorOpen,
  chunkEditorPageNumber,
  chunkEditorStartChar,
  chunkEditorSubmitting,
  chunkEditorTarget,
  canRerunRetrieve,
  chunkMatchSummary,
  chunkQuery,
  chunkSearchPlaceholder,
  chunkSearchRef,
  chunks,
  chunksListRef,
  chunksLoaded,
  chunksLoading,
  chunksError,
  clearRetrievePreview,
  closeDocument,
  copyChunkContent,
  copyChunkLink,
  doc,
  documentError,
  documentId,
  canDownloadOriginalFile,
  downloadOriginalFile,
  downloadLoading,
  downloadError,
  fileUrl,
  handleActiveTabChange,
  handleChunkEditorOpenChange,
  handleChunkSearchKeyDown,
  handleDeleteChunk,
  handleQaDialogOpenChange,
  handleSelectTextChunkIndex,
  handleTextScrollTopChange,
  highlightContent,
  highlightChunkId,
  highlightChunkLoading,
  highlightChunkError,
  highlightRange,
  isExpanded,
  isLoading,
  isOpen,
  jumpToMatch,
  jumpToSource,
  loadAllChunks,
  matchCursor,
  matchChunkIds,
  openCreateChunk,
  openEditChunk,
  parsedContent,
  parsedContentError,
  parsedContentLoading,
  panelWidthPx,
  previewAnchor,
  qaDialogOpen,
  qaLastResult,
  qaMaxSourceCharsInput,
  qaNumPairsInput,
  qaPreferLlm,
  qaReplaceExisting,
  qaSubmitting,
  retrieveCitations,
  retrieveError,
  retrieveFailedQuery,
  retrieveLoading,
  retrieveQuery,
  retrieveResultQuery,
  retryDocument,
  retryChunks,
  retryParsedContent,
  retryChunkSearch,
  retryHighlightedChunk,
  rowVirtualizer,
  runQaGeneration,
  runRetrievePreview,
  serverMatchTruncated,
  serverMatchError,
  sourceContext,
  setChunkEditorContent,
  setChunkEditorEndChar,
  setChunkEditorPageNumber,
  setChunkEditorStartChar,
  setChunkQuery,
  setHighlightChunk,
  setIsExpanded,
  setPanelWidthPx,
  setLoadAllChunks,
  setQaMaxSourceCharsInput,
  setQaNumPairsInput,
  setQaPreferLlm,
  setQaReplaceExisting,
  setRetrieveQuery,
  setTextMode,
  submitChunkEditor,
  textActiveChunkIndex,
  textChunkItems,
  textHighlightRange,
  textUnpositionedChunkCount,
  textInitialScrollTop,
  textMode,
  textValue,
}: Readonly<DocumentViewerPanelState>) {
  const [isResizing, setIsResizing] = useState(false)
  const [measuredPanelWidthPx, setMeasuredPanelWidthPx] = useState<number | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  function selectViewerTab(tab: typeof activeTab) {
    handleActiveTabChange(tab)
    panelRef.current?.querySelector<HTMLButtonElement>(`[data-viewer-tab="${tab}"]`)?.focus()
  }
  const resizeStartRef = useRef<{ pointerId: number; startX: number; startWidth: number } | null>(null)

  const panelStyle = {
    '--document-viewer-panel-width': panelWidthPx === null ? undefined : `${panelWidthPx}px`,
    '--document-viewer-panel-min-width': `${MIN_DOCUMENT_VIEWER_PANEL_WIDTH}px`,
    '--document-viewer-panel-max-width': `min(${MAX_DOCUMENT_VIEWER_PANEL_WIDTH}px, 86vw, calc(100vw - 48px))`,
  } as CSSProperties

  const clampPanelWidth = useCallback((width: number) => {
    const maxWidth =
      globalThis.window === undefined
        ? MAX_DOCUMENT_VIEWER_PANEL_WIDTH
        : Math.max(
            MIN_DOCUMENT_VIEWER_PANEL_WIDTH,
            Math.min(MAX_DOCUMENT_VIEWER_PANEL_WIDTH, Math.floor(globalThis.window.innerWidth * 0.86)),
          )
    return Math.max(MIN_DOCUMENT_VIEWER_PANEL_WIDTH, Math.min(maxWidth, Math.round(width)))
  }, [])

  useLayoutEffect(() => {
    if (!isOpen || isExpanded) return
    const panel = panelRef.current
    if (panel === null) return
    const updateMeasuredWidth = () => {
      const width = panel.getBoundingClientRect().width
      if (width > 0) setMeasuredPanelWidthPx(Math.floor(width))
    }
    updateMeasuredWidth()
    const observer = new ResizeObserver(updateMeasuredWidth)
    observer.observe(panel)
    return () => observer.disconnect()
  }, [isExpanded, isOpen])

  const effectivePanelWidthPx = measuredPanelWidthPx ?? panelWidthPx ?? 500

  const finishResize = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const current = resizeStartRef.current
    if (current?.pointerId !== event.pointerId) return
    resizeStartRef.current = null
    setIsResizing(false)
    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      // Pointer capture may already be released by the browser.
    }
  }, [])

  const handleResizePointerDown = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (isExpanded || globalThis.window === undefined || globalThis.window.innerWidth < 768) return
      event.preventDefault()
      const panel = event.currentTarget.parentElement
      if (panel === null) return
      const currentWidth = panel.getBoundingClientRect().width
      resizeStartRef.current = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startWidth: currentWidth,
      }
      setIsResizing(true)
      event.currentTarget.setPointerCapture(event.pointerId)
    },
    [isExpanded],
  )

  const handleResizePointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      const current = resizeStartRef.current
      if (current?.pointerId !== event.pointerId) return
      event.preventDefault()
      setPanelWidthPx(clampPanelWidth(current.startWidth + current.startX - event.clientX))
    },
    [clampPanelWidth, setPanelWidthPx],
  )

  const handleResizeKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (isExpanded || globalThis.window === undefined || globalThis.window.innerWidth < 768) {
        return
      }

      const step = event.shiftKey ? DOCUMENT_VIEWER_PANEL_RESIZE_STEP * 2 : DOCUMENT_VIEWER_PANEL_RESIZE_STEP
      const currentWidth = clampPanelWidth(
        panelWidthPx ?? panelRef.current?.getBoundingClientRect().width ?? effectivePanelWidthPx,
      )

      if (event.key === 'ArrowLeft') {
        event.preventDefault()
        setPanelWidthPx(clampPanelWidth(currentWidth + step))
        return
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault()
        setPanelWidthPx(clampPanelWidth(currentWidth - step))
      }
    },
    [clampPanelWidth, effectivePanelWidthPx, isExpanded, panelWidthPx, setPanelWidthPx],
  )

  if (!isOpen) return null

  return (
    <>
      <FloatingMenu panelRef={panelRef} />
      <ChunkEditorDialog
        open={chunkEditorOpen}
        mode={chunkEditorMode}
        target={chunkEditorTarget}
        content={chunkEditorContent}
        pageNumber={chunkEditorPageNumber}
        startChar={chunkEditorStartChar}
        endChar={chunkEditorEndChar}
        submitting={chunkEditorSubmitting}
        canEditChunks={canEditChunks}
        canRerunRetrieve={canRerunRetrieve}
        onOpenChange={handleChunkEditorOpenChange}
        onContentChange={setChunkEditorContent}
        onPageNumberChange={setChunkEditorPageNumber}
        onStartCharChange={setChunkEditorStartChar}
        onEndCharChange={setChunkEditorEndChar}
        onSubmit={(mode) => detachPromise(submitChunkEditor(mode))}
      />
      <QAGenerationDialog
        open={qaDialogOpen}
        qaNumPairsInput={qaNumPairsInput}
        qaMaxSourceCharsInput={qaMaxSourceCharsInput}
        qaReplaceExisting={qaReplaceExisting}
        qaPreferLlm={qaPreferLlm}
        qaSubmitting={qaSubmitting}
        qaLastResult={qaLastResult}
        canEditChunks={canEditChunks}
        documentId={documentId}
        onOpenChange={handleQaDialogOpenChange}
        onNumPairsInputChange={setQaNumPairsInput}
        onMaxSourceCharsInputChange={setQaMaxSourceCharsInput}
        onReplaceExistingChange={setQaReplaceExisting}
        onPreferLlmChange={setQaPreferLlm}
        onSubmit={() => detachPromise(runQaGeneration())}
      />
      <div
        ref={panelRef}
        style={panelStyle}
        className={cn(
          'fixed inset-y-0 right-0 z-50 flex flex-col border-l border-sidebar-border/70 bg-sidebar/90 backdrop-blur-xl shadow-strong',
          isResizing ? 'select-none' : 'transition-[width] duration-150 ease-out motion-reduce:transition-none',
          !isExpanded &&
            'md:min-w-[var(--document-viewer-panel-min-width)] md:max-w-[var(--document-viewer-panel-max-width)]',
          isExpanded
            ? 'w-full md:w-[80vw]'
            : panelWidthPx
              ? 'w-full md:w-[var(--document-viewer-panel-width)]'
              : 'w-full md:w-[40vw] lg:w-[500px] xl:w-[40vw]',
        )}
      >
        <div
          role="separator"
          aria-label="拖动调整文档查看器宽度"
          aria-orientation="vertical"
          aria-valuemin={MIN_DOCUMENT_VIEWER_PANEL_WIDTH}
          aria-valuemax={clampPanelWidth(globalThis.window?.innerWidth ?? panelWidthPx ?? 500)}
          aria-valuenow={effectivePanelWidthPx}
          aria-valuetext={`${effectivePanelWidthPx}px`}
          title="拖动调整文档查看器宽度"
          data-document-viewer-resize-handle="true"
          tabIndex={isExpanded ? -1 : 0}
          onPointerDown={handleResizePointerDown}
          onPointerMove={handleResizePointerMove}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
          onKeyDown={handleResizeKeyDown}
          className={cn(
            'group absolute -left-2 top-0 z-20 hidden h-full w-4 cursor-col-resize items-center justify-center md:flex',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
            isExpanded && 'pointer-events-none opacity-0',
            isResizing && 'bg-primary/5',
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              'h-16 w-1 rounded-full border border-border/70 bg-background/80 shadow-sm transition-colors',
              isResizing ? 'border-primary/50 bg-primary/35' : 'group-hover:bg-primary/25',
            )}
          />
        </div>
        <DocumentViewerHeader
          doc={doc}
          isLoading={isLoading}
          isExpanded={isExpanded}
          canDownload={canDownloadOriginalFile}
          downloadLoading={downloadLoading}
          onDownload={downloadOriginalFile}
          onJumpToSource={sourceContext?.kind === 'chat-citation' ? jumpToSource : null}
          onToggleExpanded={() => setIsExpanded(!isExpanded)}
          onClose={closeDocument}
        />
        <ReadErrorFeedback error={documentError} loading={isLoading} label="重试读取文档" onRetry={retryDocument} />
        <ReadErrorFeedback
          error={downloadError}
          loading={downloadLoading}
          label="重试下载原文件"
          onRetry={downloadOriginalFile}
        />
        <ReadErrorFeedback
          error={highlightChunkError}
          loading={highlightChunkLoading}
          label="重试读取引用切片"
          onRetry={retryHighlightedChunk}
        />
        {activeTab === 'chunks' || activeTab === 'text' ? (
          <ReadErrorFeedback error={chunksError} loading={chunksLoading} label="重试读取切片" onRetry={retryChunks} />
        ) : null}
        {activeTab === 'chunks' && !chunksLoaded ? (
          <ReadErrorFeedback error={serverMatchError} loading={false} label="重试搜索" onRetry={retryChunkSearch} />
        ) : null}

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <Tabs value={activeTab} onValueChange={handleActiveTabChange} className="flex min-h-0 flex-1 flex-col">
            <div className="border-b border-sidebar-border/70 bg-sidebar/75 px-4 backdrop-blur-xl">
              <TabsList className="h-10 w-full justify-start gap-6 bg-transparent p-0">
                <TabsTrigger
                  value="preview"
                  data-viewer-tab="preview"
                  className="h-10 rounded-none border-b-2 border-transparent px-2 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground"
                >
                  原文
                </TabsTrigger>
                <TabsTrigger
                  value="text"
                  data-viewer-tab="text"
                  className="h-10 rounded-none border-b-2 border-transparent px-2 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground"
                >
                  文本定位
                </TabsTrigger>
                <TabsTrigger
                  value="chunks"
                  data-viewer-tab="chunks"
                  className="h-10 rounded-none border-b-2 border-transparent px-2 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground"
                >
                  切片
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent
              value="preview"
              className="relative m-0 min-h-0 flex-1 overflow-hidden bg-muted/30 dark:bg-muted/20"
            >
              <PreviewTabPanel
                isLoading={isLoading}
                doc={doc}
                canInlinePreview={canInlinePreview}
                fileUrl={fileUrl}
                downloadLoading={downloadLoading}
                onDownload={downloadOriginalFile}
                previewAnchor={previewAnchor}
                highlightChunkId={highlightChunkId}
                highlightRange={highlightRange}
                onViewText={() => selectViewerTab('text')}
                onViewChunks={() => selectViewerTab('chunks')}
              />
            </TabsContent>

            <TabsContent value="text" className="m-0 min-h-0 flex-1 overflow-hidden">
              <TextTabPanel
                textMode={textMode}
                highlightChunkId={highlightChunkId}
                loadAllChunks={loadAllChunks}
                chunksLoaded={chunksLoaded}
                chunksLoading={chunksLoading}
                retrieveQuery={retrieveQuery}
                retrieveLoading={retrieveLoading}
                retrieveError={retrieveError}
                retrieveFailedQuery={retrieveFailedQuery}
                retrieveCitations={retrieveCitations}
                retrieveResultQuery={retrieveResultQuery}
                parsedContent={parsedContent}
                parsedContentLoading={parsedContentLoading}
                parsedContentError={parsedContentError}
                onRetryParsedContent={retryParsedContent}
                textValue={textValue}
                textChunkItems={textChunkItems}
                unpositionedChunkCount={textUnpositionedChunkCount}
                textActiveChunkIndex={textActiveChunkIndex}
                initialScrollTop={textInitialScrollTop}
                highlightRange={textHighlightRange}
                highlightParentRange={sourceContext?.kind !== 'chat-citation'}
                onTextModeChange={setTextMode}
                onTextScrollTopChange={handleTextScrollTopChange}
                onClearHighlight={() => setHighlightChunk(null)}
                onLoadAllChunks={() => setLoadAllChunks(true)}
                onRetrieveQueryChange={setRetrieveQuery}
                onRunRetrieve={() => detachPromise(runRetrievePreview())}
                onClearRetrieve={clearRetrievePreview}
                onSelectRetrieveChunk={(chunkId) => {
                  handleActiveTabChange('text')
                  setHighlightChunk(chunkId)
                }}
                onSelectChunkIndex={handleSelectTextChunkIndex}
                onGoToChunks={() => selectViewerTab('chunks')}
                onGoToPreview={() => selectViewerTab('preview')}
              />
            </TabsContent>

            <TabsContent value="chunks" className="m-0 min-h-0 flex-1 overflow-hidden">
              <ChunksTabPanel
                chunkSearchRef={chunkSearchRef}
                chunksListRef={chunksListRef}
                rowVirtualizer={rowVirtualizer}
                chunkQuery={chunkQuery}
                searchPlaceholder={chunkSearchPlaceholder}
                matchSummary={chunkMatchSummary}
                canJumpMatches={Boolean(matchChunkIds.length)}
                canEditChunks={canEditChunks}
                serverMatchTruncatedHint={Boolean(!chunksLoaded && chunkQuery.trim() && serverMatchTruncated)}
                highlightChunkId={highlightChunkId}
                chunksLoaded={chunksLoaded}
                chunksLoading={chunksLoading}
                highlightChunkLoading={highlightChunkLoading}
                highlightChunkError={highlightChunkError}
                highlightContent={highlightContent}
                chunkEditorSubmitting={chunkEditorSubmitting}
                chunkDeleteSubmitting={chunkDeleteSubmitting}
                matchCursor={matchCursor}
                chunks={chunks}
                onChunkQueryChange={setChunkQuery}
                onSearchKeyDown={handleChunkSearchKeyDown}
                onJumpToMatch={jumpToMatch}
                onOpenCreateChunk={openCreateChunk}
                onOpenQaDialog={() => handleQaDialogOpenChange(true)}
                onClearHighlight={() => setHighlightChunk(null)}
                onLoadAllChunks={() => setLoadAllChunks(true)}
                onCopyContent={copyChunkContent}
                onCopyLink={copyChunkLink}
                onEditChunk={openEditChunk}
                onDeleteChunk={handleDeleteChunk}
              />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </>
  )
}
