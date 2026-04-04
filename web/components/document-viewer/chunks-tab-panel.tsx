"use client"

import type { Key, KeyboardEvent, RefObject } from "react"
import { Loader2 } from "lucide-react"

import type { DocumentChunk } from "@/types"

import { DocumentChunkCard } from "./chunk-renderer"
import { ChunksToolbarPanel } from "./chunks-toolbar-panel"

type VirtualRow = {
  index: number
  key: Key
  start: number
}

type VirtualizerLike = {
  getTotalSize: () => number
  getVirtualItems: () => VirtualRow[]
  measureElement: (node: Element | null) => void
}

type ChunksTabPanelProps = {
  chunkSearchRef: RefObject<HTMLInputElement | null>
  chunksListRef: RefObject<HTMLDivElement | null>
  rowVirtualizer: VirtualizerLike
  chunkQuery: string
  searchPlaceholder: string
  matchSummary: string
  canJumpMatches: boolean
  canEditChunks: boolean
  serverMatchTruncatedHint: boolean
  highlightChunkId: string | null
  loadAllChunks: boolean
  chunksLoaded: boolean
  chunksLoading: boolean
  highlightChunkLoading: boolean
  highlightChunk: DocumentChunk | null
  chunkEditorSubmitting: boolean
  chunkDeleteSubmitting: string | null
  matchCursor: number
  chunks: DocumentChunk[]
  onChunkQueryChange: (value: string) => void
  onSearchKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void
  onJumpToMatch: (nextIndex: number) => void
  onOpenCreateChunk: () => void
  onOpenQaDialog: () => void
  onClearHighlight: () => void
  onLoadAllChunks: () => void
  onCopyContent: (content: string) => void
  onCopyLink: (chunk: DocumentChunk) => void
  onEditChunk: (chunk: DocumentChunk) => void
  onDeleteChunk: (chunk: DocumentChunk) => void
}

export function ChunksTabPanel({
  chunkSearchRef,
  chunksListRef,
  rowVirtualizer,
  chunkQuery,
  searchPlaceholder,
  matchSummary,
  canJumpMatches,
  canEditChunks,
  serverMatchTruncatedHint,
  highlightChunkId,
  loadAllChunks,
  chunksLoaded,
  chunksLoading,
  highlightChunkLoading,
  highlightChunk,
  chunkEditorSubmitting,
  chunkDeleteSubmitting,
  matchCursor,
  chunks,
  onChunkQueryChange,
  onSearchKeyDown,
  onJumpToMatch,
  onOpenCreateChunk,
  onOpenQaDialog,
  onClearHighlight,
  onLoadAllChunks,
  onCopyContent,
  onCopyLink,
  onEditChunk,
  onDeleteChunk,
}: Readonly<ChunksTabPanelProps>) {
  return (
    <div className="flex h-full flex-col overflow-hidden bg-muted/20 dark:bg-muted/10">
      <ChunksToolbarPanel
        chunkSearchRef={chunkSearchRef}
        chunkQuery={chunkQuery}
        searchPlaceholder={searchPlaceholder}
        matchSummary={matchSummary}
        canJumpMatches={canJumpMatches}
        canEditChunks={canEditChunks}
        serverMatchTruncatedHint={serverMatchTruncatedHint}
        highlightChunkId={highlightChunkId}
        loadAllChunks={loadAllChunks}
        chunksLoaded={chunksLoaded}
        chunksLoading={chunksLoading}
        highlightChunkLoading={highlightChunkLoading}
        highlightChunk={highlightChunk}
        chunkEditorSubmitting={chunkEditorSubmitting}
        chunkDeleteSubmitting={chunkDeleteSubmitting}
        onChunkQueryChange={onChunkQueryChange}
        onSearchKeyDown={onSearchKeyDown}
        onPrevMatch={() => onJumpToMatch(matchCursor - 1)}
        onNextMatch={() => onJumpToMatch(matchCursor + 1)}
        onOpenCreateChunk={onOpenCreateChunk}
        onOpenQaDialog={onOpenQaDialog}
        onClearHighlight={onClearHighlight}
        onLoadAllChunks={onLoadAllChunks}
        onCopyContent={onCopyContent}
        onCopyLink={onCopyLink}
        onEditChunk={onEditChunk}
        onDeleteChunk={onDeleteChunk}
      />

      <div className="no-scrollbar flex-1 overflow-y-auto overscroll-contain p-4 scroll-smooth" ref={chunksListRef}>
        {chunksLoading && chunks.length === 0 ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground">
            <Loader2 className="size-6 animate-spin motion-reduce:animate-none" />
          </div>
        ) : null}

        {chunks.length > 0 ? (
          <div
            style={{
              height: `${rowVirtualizer.getTotalSize()}px`,
              width: "100%",
              position: "relative",
            }}
          >
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const chunk = chunks[virtualRow.index]
              if (!chunk) return null

              return (
                <div
                  key={virtualRow.key}
                  data-index={virtualRow.index}
                  ref={rowVirtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                  className="pb-4"
                >
                  <DocumentChunkCard
                    chunk={chunk}
                    query={chunkQuery}
                    isActive={highlightChunkId === chunk.id}
                    canEditChunks={canEditChunks}
                    chunkEditorSubmitting={chunkEditorSubmitting}
                    chunkDeleteSubmitting={chunkDeleteSubmitting}
                    onCopyContent={onCopyContent}
                    onCopyLink={onCopyLink}
                    onEdit={onEditChunk}
                    onDelete={onDeleteChunk}
                  />
                </div>
              )
            })}
          </div>
        ) : null}

        {chunksLoaded && !chunksLoading && chunks.length === 0 ? (
          <div className="py-10 text-center text-muted-foreground">暂无切片数据</div>
        ) : null}
      </div>
    </div>
  )
}
