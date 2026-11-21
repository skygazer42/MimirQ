'use client'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { HighlightedText } from '@/components/ui/highlighted-text'
import { cn } from '@/lib/utils'
import type { DocumentChunk } from '@/types/backend'
import { Copy, Link2, Loader2, Pencil, Trash2 } from '@/components/icons'

import type { CitationSnapshot, DocumentChunkLocation } from './document-viewer-models'

type DocumentChunkCardProps = {
  id?: string
  chunk: DocumentChunk
  query: string
  isActive?: boolean
  showHoverActions?: boolean
  canEditChunks: boolean
  chunkEditorSubmitting: boolean
  chunkDeleteSubmitting: string | null
  onCopyContent: (content: string) => Promise<void>
  onCopyLink: (location: DocumentChunkLocation) => Promise<void>
  onEdit: (chunk: DocumentChunk) => void
  onDelete: (chunk: DocumentChunk) => Promise<void>
}

type CitationSnapshotCardProps = {
  snapshot: CitationSnapshot
  query: string
  onCopyContent: (content: string) => Promise<void>
  onCopyLink: (location: DocumentChunkLocation) => Promise<void>
}

export function CitationSnapshotCard({
  snapshot,
  query,
  onCopyContent,
  onCopyLink,
}: Readonly<CitationSnapshotCardProps>) {
  return (
    <section aria-label="对话引用" className="rounded-xl border border-border bg-background p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>对话引用</span>
          <span>{typeof snapshot.chunkIndex === 'number' ? `#${snapshot.chunkIndex}` : '序号未知'}</span>
          {snapshot.pageNumber == null ? null : <span>P.{snapshot.pageNumber}</span>}
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onCopyContent(snapshot.content)}
            aria-label="复制引用原文"
            title="复制引用原文"
          >
            <Copy className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() =>
              onCopyLink({ id: snapshot.chunkId, start_char: snapshot.range?.start, end_char: snapshot.range?.end })
            }
            aria-label="复制定位链接"
            title="复制定位链接"
          >
            <Link2 className="size-4" />
          </Button>
        </div>
      </div>
      <p className="font-mono text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">
        {snapshot.content.length === 0 ? '引用原文为空' : <HighlightedText content={snapshot.content} query={query} />}
      </p>
    </section>
  )
}

export function DocumentChunkCard({
  id,
  chunk,
  query,
  isActive = false,
  showHoverActions = true,
  canEditChunks,
  chunkEditorSubmitting,
  chunkDeleteSubmitting,
  onCopyContent,
  onCopyLink,
  onEdit,
  onDelete,
}: Readonly<DocumentChunkCardProps>) {
  return (
    <div
      id={id}
      className={cn(
        'group rounded-xl border p-4 transition-[background-color,border-color,box-shadow] duration-200 motion-reduce:transition-none',
        isActive
          ? 'bg-primary/5 border-primary shadow-[0_0_0_1px_rgba(var(--primary),0.2)] ring-1 ring-primary/20'
          : 'bg-background border-border hover:border-primary/30 hover:shadow-sm',
      )}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium font-mono text-muted-foreground">
          #{chunk.chunk_index}
        </span>
        <div className="flex items-center gap-2">
          {chunk.page_number == null ? null : (
            <span className="text-xs text-muted-foreground">P.{chunk.page_number}</span>
          )}
          <div
            className={cn(
              'flex items-center gap-1',
              showHoverActions
                ? 'opacity-100 transition-opacity lg:opacity-0 lg:group-hover:opacity-100 lg:group-focus-within:opacity-100'
                : '',
            )}
          >
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => onCopyContent(chunk.content)}
              aria-label="复制切片内容"
              title="复制切片内容"
            >
              <Copy className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => onCopyLink(chunk)}
              aria-label="复制定位链接"
              title="复制定位链接"
            >
              <Link2 className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => onEdit(chunk)}
              disabled={!canEditChunks || chunkEditorSubmitting}
              aria-label="Edit chunk"
              title="Edit chunk"
            >
              <Pencil className="size-4" />
            </Button>
            <ConfirmDialog
              title={`Delete chunk #${chunk.chunk_index}?`}
              description="This cannot be undone."
              confirmLabel="Delete"
              cancelLabel="Cancel"
              confirmVariant="destructive"
              confirmDisabled={!canEditChunks || chunkDeleteSubmitting === chunk.id}
              onConfirm={() => onDelete(chunk)}
            >
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-destructive hover:text-destructive"
                disabled={!canEditChunks || chunkDeleteSubmitting === chunk.id}
                aria-label="Delete chunk"
                title="Delete chunk"
              >
                {chunkDeleteSubmitting === chunk.id ? (
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                ) : (
                  <Trash2 className="size-4" />
                )}
              </Button>
            </ConfirmDialog>
          </div>
        </div>
      </div>
      <p className="font-mono text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">
        <HighlightedText content={chunk.content} query={query} />
      </p>
    </div>
  )
}
