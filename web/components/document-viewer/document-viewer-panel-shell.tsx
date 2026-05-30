"use client"

import { useCallback, useRef, useState, type CSSProperties, type PointerEvent } from "react"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ChunkEditorDialog } from "@/components/document-viewer/chunk-editor-dialog"
import { ChunksTabPanel } from "@/components/document-viewer/chunks-tab-panel"
import { DocumentViewerHeader } from "@/components/document-viewer/document-viewer-header"
import { FloatingMenu } from "@/components/document-viewer/floating-menu"
import { PreviewTabPanel } from "@/components/document-viewer/preview-tab-panel"
import { QAGenerationDialog } from "@/components/document-viewer/qa-generation-dialog"
import { TextTabPanel } from "@/components/document-viewer/text-tab-panel"
import { cn, detachPromise } from "@/lib/utils"

import type { DocumentViewerPanelState } from "./use-document-viewer-panel-state"

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
  closeDocument,
  copyChunkContent,
  copyChunkLink,
  doc,
  documentId,
  downloadUrl,
  fileUrl,
  handleActiveTabChange,
  handleChunkEditorOpenChange,
  handleChunkSearchKeyDown,
  handleDeleteChunk,
  handleQaDialogOpenChange,
  handleSelectTextChunkIndex,
  handleTextScrollTopChange,
  highlightChunk,
  highlightChunkId,
  highlightChunkLoading,
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
  qaMaxSourceChars,
  qaNumPairs,
  qaPreferLlm,
  qaReplaceExisting,
  qaSubmitting,
  rawFileUrl,
  retrieveCitations,
  retrieveError,
  retrieveLoading,
  retrieveQuery,
  rowVirtualizer,
  runQaGeneration,
  runRetrievePreview,
  serverMatchTruncated,
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
  setQaMaxSourceChars,
  setQaNumPairs,
  setQaPreferLlm,
  setQaReplaceExisting,
  setRetrieveCitations,
  setRetrieveError,
  setRetrieveQuery,
  setTextMode,
  submitChunkEditor,
  textActiveChunkIndex,
  textChunkItems,
  textInitialScrollTop,
  textMode,
  textValue,
}: Readonly<DocumentViewerPanelState>) {
  const [isResizing, setIsResizing] = useState(false)
  const resizeStartRef = useRef<{ pointerId: number; startX: number; startWidth: number } | null>(null)

  const panelStyle = !isExpanded && panelWidthPx
    ? ({ "--document-viewer-panel-width": `min(${panelWidthPx}px, calc(100vw - 48px))` } as CSSProperties)
    : undefined

  const clampPanelWidth = useCallback((width: number) => {
    if (globalThis.window === undefined) return Math.max(360, Math.round(width))
    const maxWidth = Math.max(420, Math.floor(globalThis.window.innerWidth * 0.86))
    return Math.max(360, Math.min(maxWidth, Math.round(width)))
  }, [])

  const finishResize = useCallback((event: PointerEvent<HTMLButtonElement>) => {
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

  const handleResizePointerDown = useCallback((event: PointerEvent<HTMLButtonElement>) => {
    if (isExpanded || globalThis.window === undefined || globalThis.window.innerWidth < 768) return
    event.preventDefault()
    const panel = event.currentTarget.parentElement
    const currentWidth = panelWidthPx ?? panel?.getBoundingClientRect().width ?? 500
    resizeStartRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: currentWidth,
    }
    setIsResizing(true)
    event.currentTarget.setPointerCapture(event.pointerId)
  }, [isExpanded, panelWidthPx])

  const handleResizePointerMove = useCallback((event: PointerEvent<HTMLButtonElement>) => {
    const current = resizeStartRef.current
    if (current?.pointerId !== event.pointerId) return
    event.preventDefault()
    setPanelWidthPx(clampPanelWidth(current.startWidth + current.startX - event.clientX))
  }, [clampPanelWidth, setPanelWidthPx])

  if (!isOpen) return null

  return (
    <>
      <FloatingMenu />
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
        qaNumPairs={qaNumPairs}
        qaMaxSourceChars={qaMaxSourceChars}
        qaReplaceExisting={qaReplaceExisting}
        qaPreferLlm={qaPreferLlm}
        qaSubmitting={qaSubmitting}
        qaLastResult={qaLastResult}
        canEditChunks={canEditChunks}
        documentId={documentId}
        onOpenChange={handleQaDialogOpenChange}
        onNumPairsChange={setQaNumPairs}
        onMaxSourceCharsChange={setQaMaxSourceChars}
        onReplaceExistingChange={setQaReplaceExisting}
        onPreferLlmChange={setQaPreferLlm}
        onSubmit={() => detachPromise(runQaGeneration())}
      />
      <div
        style={panelStyle}
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex flex-col border-l border-sidebar-border/70 bg-sidebar/90 backdrop-blur-xl shadow-strong",
          isResizing ? "select-none" : "transition-[width] duration-150 ease-out motion-reduce:transition-none",
          isExpanded
            ? "w-full md:w-[80vw]"
            : panelWidthPx
              ? "w-full md:w-[var(--document-viewer-panel-width)]"
              : "w-full md:w-[40vw] lg:w-[500px] xl:w-[40vw]"
        )}
      >
        <button
          type="button"
          aria-label="拖动调整文档查看器宽度"
          title="拖动调整文档查看器宽度"
          data-document-viewer-resize-handle="true"
          onPointerDown={handleResizePointerDown}
          onPointerMove={handleResizePointerMove}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
          className={cn(
            "group absolute -left-2 top-0 z-20 hidden h-full w-4 cursor-col-resize items-center justify-center md:flex",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60",
            isExpanded && "pointer-events-none opacity-0",
            isResizing && "bg-primary/5"
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              "h-16 w-1 rounded-full border border-border/70 bg-background/80 shadow-sm transition-colors",
              isResizing ? "border-primary/50 bg-primary/35" : "group-hover:bg-primary/25"
            )}
          />
        </button>
        <DocumentViewerHeader
          filename={doc?.filename}
          chunkCount={doc?.chunk_count ?? chunks.length}
          isExpanded={isExpanded}
          downloadUrl={downloadUrl}
          onJumpToSource={sourceContext?.kind === 'chat-citation' ? jumpToSource : null}
          onToggleExpanded={() => setIsExpanded(!isExpanded)}
          onClose={closeDocument}
        />

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <Tabs value={activeTab} onValueChange={handleActiveTabChange} className="flex min-h-0 flex-1 flex-col">
            <div className="border-b border-sidebar-border/70 bg-sidebar/75 px-4 backdrop-blur-xl">
              <TabsList className="h-10 w-full justify-start gap-6 bg-transparent p-0">
                <TabsTrigger
                  value="preview"
                  className="h-10 rounded-none border-b-2 border-transparent px-2 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground"
                >
                  原文
                </TabsTrigger>
                <TabsTrigger
                  value="text"
                  className="h-10 rounded-none border-b-2 border-transparent px-2 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground"
                >
                  文本定位
                </TabsTrigger>
                <TabsTrigger
                  value="chunks"
                  className="h-10 rounded-none border-b-2 border-transparent px-2 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground"
                >
                  智能切片
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="preview" className="relative m-0 min-h-0 flex-1 overflow-hidden bg-muted/30 dark:bg-muted/20">
              <PreviewTabPanel
                isLoading={isLoading}
                doc={doc}
                canInlinePreview={canInlinePreview}
                fileUrl={fileUrl}
                rawFileUrl={rawFileUrl}
                downloadUrl={downloadUrl}
                previewAnchor={previewAnchor}
                highlightChunkId={highlightChunkId}
                highlightRange={highlightRange}
                onViewText={() => handleActiveTabChange("text")}
                onViewChunks={() => handleActiveTabChange("chunks")}
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
                retrieveCitations={retrieveCitations}
                parsedContent={parsedContent}
                parsedContentLoading={parsedContentLoading}
                parsedContentError={parsedContentError}
                textValue={textValue}
                textChunkItems={textChunkItems}
                textActiveChunkIndex={textActiveChunkIndex}
                initialScrollTop={textInitialScrollTop}
                highlightRange={highlightRange}
                highlightParentRange={sourceContext?.kind !== 'chat-citation'}
                onTextModeChange={setTextMode}
                onTextScrollTopChange={handleTextScrollTopChange}
                onClearHighlight={() => setHighlightChunk(null)}
                onLoadAllChunks={() => setLoadAllChunks(true)}
                onRetrieveQueryChange={setRetrieveQuery}
                onRunRetrieve={() => detachPromise(runRetrievePreview())}
                onClearRetrieve={() => {
                  setRetrieveCitations([])
                  setRetrieveError(null)
                }}
                onSelectRetrieveChunk={(chunkId) => {
                  handleActiveTabChange("text")
                  setHighlightChunk(chunkId)
                }}
                onSelectChunkIndex={handleSelectTextChunkIndex}
                onGoToChunks={() => handleActiveTabChange("chunks")}
                onGoToPreview={() => handleActiveTabChange("preview")}
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
                loadAllChunks={loadAllChunks}
                chunksLoaded={chunksLoaded}
                chunksLoading={chunksLoading}
                highlightChunkLoading={highlightChunkLoading}
                highlightChunk={highlightChunk}
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
