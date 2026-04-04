"use client"

import type { KeyboardEvent, RefObject } from "react"
import { Loader2, Plus, Sparkles } from "lucide-react"

import type { DocumentChunk } from "@/types"
import { Button } from "@/components/ui/button"

import { DocumentChunkCard } from "./chunk-renderer"

type ChunksToolbarPanelProps = {
  chunkSearchRef: RefObject<HTMLInputElement | null>
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
  onChunkQueryChange: (value: string) => void
  onSearchKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void
  onPrevMatch: () => void
  onNextMatch: () => void
  onOpenCreateChunk: () => void
  onOpenQaDialog: () => void
  onClearHighlight: () => void
  onLoadAllChunks: () => void
  onCopyContent: (content: string) => void
  onCopyLink: (chunk: DocumentChunk) => void
  onEditChunk: (chunk: DocumentChunk) => void
  onDeleteChunk: (chunk: DocumentChunk) => void
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
  loadAllChunks,
  chunksLoaded,
  chunksLoading,
  highlightChunkLoading,
  highlightChunk,
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
    <div className="border-b border-border bg-background/60 p-4 backdrop-blur-sm">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <input
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

      <div className="mt-2 text-[11px] text-muted-foreground">快捷键：<span className="font-mono">/</span> 聚焦搜索 · <span className="font-mono">j / k</span> 快速切换结果</div>

      <div className="mt-2 flex items-center justify-end gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="gap-2"
          onClick={onOpenCreateChunk}
          disabled={!canEditChunks}
          title={canEditChunks ? "Add a new chunk" : "Document is processing; editing disabled"}
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
          title={canEditChunks ? "Generate FAQ-style Q&A chunks" : "Document is processing; editing disabled"}
        >
          <Sparkles className="size-4" />
          Q&A
        </Button>
      </div>

      {serverMatchTruncatedHint ? (
        <div className="mt-2 text-[11px] text-muted-foreground">匹配结果过多，仅返回前若干条（计数后缀 “+” 表示截断）。</div>
      ) : null}

      {highlightChunkId && !loadAllChunks && !chunksLoaded ? (
        <div className="mt-3 rounded-xl border border-border/60 bg-background/60 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <div className="text-xs font-semibold text-foreground">引用切片</div>
              <div className="mt-1 text-[11px] text-muted-foreground">为避免一次性加载大量切片，先展示命中内容；需要全文切片可点击「加载全部切片」。</div>
            </div>
            <div className="flex items-center justify-end gap-2">
              <Button type="button" size="sm" variant="outline" onClick={onClearHighlight} disabled={highlightChunkLoading}>
                清除定位
              </Button>
              <Button type="button" size="sm" onClick={onLoadAllChunks} disabled={chunksLoading}>
                加载全部切片
              </Button>
            </div>
          </div>

          <div className="mt-3">
            {highlightChunkLoading ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                <span>加载命中切片…</span>
              </div>
            ) : highlightChunk ? (
              <DocumentChunkCard
                chunk={highlightChunk}
                query={chunkQuery}
                isActive
                canEditChunks={canEditChunks}
                chunkEditorSubmitting={chunkEditorSubmitting}
                chunkDeleteSubmitting={chunkDeleteSubmitting}
                showHoverActions={false}
                onCopyContent={onCopyContent}
                onCopyLink={onCopyLink}
                onEdit={onEditChunk}
                onDelete={onDeleteChunk}
              />
            ) : (
              <div className="text-xs text-muted-foreground">未找到命中切片（可能已被删除或无权限）</div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
