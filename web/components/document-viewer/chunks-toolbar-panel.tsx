'use client'

import type { KeyboardEvent, RefObject } from 'react'
import { Loader2, Plus, Sparkles } from '@/components/icons'

import type { DocumentChunk } from '@/types/backend'
import { Button } from '@/components/ui/button'

import { CitationSnapshotCard, DocumentChunkCard } from './chunk-renderer'
import type { DocumentChunkLocation, DocumentViewerHighlight } from './document-viewer-models'

type ChunksToolbarPanelProps = {
  chunkSearchRef: RefObject<HTMLInputElement | null>
  chunkQuery: string
  searchPlaceholder: string
  matchSummary: string
  canJumpMatches: boolean
  canEditChunks: boolean
  serverMatchTruncatedHint: boolean
  highlightChunkId: string | null
  chunksLoaded: boolean
  chunksLoading: boolean
  highlightChunkLoading: boolean
  highlightChunkError: string | null
  highlightContent: DocumentViewerHighlight | null
  chunkEditorSubmitting: boolean
  chunkDeleteSubmitting: string | null
  onChunkQueryChange: (value: string) => void
  onSearchKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void
  onPrevMatch: () => void
  onNextMatch: () => void
  onOpenCreateChunk: () => void
  onOpenQaDialog: () => void
  onClearHighlight: () => void
  onLoadAllChunks: () => void
  onCopyContent: (content: string) => Promise<void>
  onCopyLink: (location: DocumentChunkLocation) => Promise<void>
  onEditChunk: (chunk: DocumentChunk) => void
  onDeleteChunk: (chunk: DocumentChunk) => Promise<void>
}

export function ChunksToolbarPanel({
  chunkSearchRef,
  chunkQuery,
  searchPlaceholder,
  matchSummary,
  canJumpMatches,
  canEditChunks,
  serverMatchTruncatedHint,
  highlightChunkId,
  chunksLoaded,
  chunksLoading,
  highlightChunkLoading,
  highlightChunkError,
  highlightContent,
  chunkEditorSubmitting,
  chunkDeleteSubmitting,
  onChunkQueryChange,
  onSearchKeyDown,
  onPrevMatch,
  onNextMatch,
  onOpenCreateChunk,
  onOpenQaDialog,
  onClearHighlight,
  onLoadAllChunks,
  onCopyContent,
  onCopyLink,
  onEditChunk,
  onDeleteChunk,
}: Readonly<ChunksToolbarPanelProps>) {
  return (
    <div className="border-b border-border bg-background p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <input
          aria-label="搜索文档切片"
          ref={chunkSearchRef}
          value={chunkQuery}
          onChange={(event) => onChunkQueryChange(event.target.value)}
          onKeyDown={onSearchKeyDown}
          placeholder={searchPlaceholder}
          className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <div className="flex items-center gap-2">
          <div className="min-w-[88px] text-right text-xs text-muted-foreground tabular-nums">{matchSummary}</div>
          <Button size="sm" variant="outline" disabled={!canJumpMatches} onClick={onPrevMatch}>
            上一个
          </Button>
          <Button size="sm" variant="outline" disabled={!canJumpMatches} onClick={onNextMatch}>
            下一个
          </Button>
        </div>
      </div>

      <div className="mt-2 text-[11px] text-muted-foreground">
        快捷键：<span className="font-mono">/</span> 聚焦搜索 · <span className="font-mono">j / k</span> 快速切换结果
      </div>

      <div className="mt-2 flex items-center justify-end gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="gap-2"
          onClick={onOpenCreateChunk}
          disabled={!canEditChunks}
          title={canEditChunks ? 'Add a new chunk' : 'Document is processing; editing disabled'}
        >
          <Plus className="size-4" />
          Add chunk
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="gap-2"
          onClick={onOpenQaDialog}
          disabled={!canEditChunks}
          title={canEditChunks ? 'Generate FAQ-style Q&A chunks' : 'Document is processing; editing disabled'}
        >
          <Sparkles className="size-4" />
          Q&A
        </Button>
      </div>

      {serverMatchTruncatedHint ? (
        <div className="mt-2 text-[11px] text-muted-foreground">
          匹配结果过多，仅返回前若干条（计数后缀 “+” 表示截断）。
        </div>
      ) : null}

      {highlightChunkId && (!chunksLoaded || highlightContent?.kind === 'citation') ? (
        <div className="mt-3 rounded-xl border border-border/60 bg-background/60 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <div className="text-xs font-semibold text-foreground">引用切片</div>
              {!chunksLoaded ? (
                <div className="mt-1 text-[11px] text-muted-foreground">
                  当前展示命中内容，需要全文切片时可加载全部。
                </div>
              ) : null}
            </div>
            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onClearHighlight}
                disabled={highlightChunkLoading}
              >
                清除定位
              </Button>
              {!chunksLoaded ? (
                <Button type="button" size="sm" onClick={onLoadAllChunks} disabled={chunksLoading}>
                  加载全部切片
                </Button>
              ) : null}
            </div>
          </div>

          <div className="mt-3">
            {highlightContent?.kind === 'citation' ? (
              <CitationSnapshotCard
                snapshot={highlightContent.snapshot}
                query={chunkQuery}
                onCopyContent={onCopyContent}
                onCopyLink={onCopyLink}
              />
            ) : highlightChunkLoading ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                <span>加载命中切片…</span>
              </div>
            ) : highlightContent?.kind === 'chunk' ? (
              <DocumentChunkCard
                chunk={highlightContent.chunk}
                query={chunkQuery}
                isActive
                canEditChunks={canEditChunks && highlightChunkError === null}
                chunkEditorSubmitting={chunkEditorSubmitting}
                chunkDeleteSubmitting={chunkDeleteSubmitting}
                showHoverActions={false}
                onCopyContent={onCopyContent}
                onCopyLink={onCopyLink}
                onEdit={onEditChunk}
                onDelete={onDeleteChunk}
              />
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
