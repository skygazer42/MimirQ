'use client'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { cn } from '@/lib/utils'
import type { DocumentChunk } from '@/types'
import { Copy, Link2, Loader2, Pencil, Trash2 } from 'lucide-react'

import { HighlightLayer } from './highlight-layer'

type DocumentChunkCardProps = {
  chunk: DocumentChunk
  query: string
  isActive?: boolean
  showHoverActions?: boolean
  canEditChunks: boolean
  chunkEditorSubmitting: boolean
  chunkDeleteSubmitting: string | null
  onCopyContent: (content: string) => void
  onCopyLink: (chunk: DocumentChunk) => void
  onEdit: (chunk: DocumentChunk) => void
  onDelete: (chunk: DocumentChunk) => void
}

export function DocumentChunkCard({
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
      id={`chunk-${chunk.id}`}
      className={cn(
        'group rounded-xl border p-4 transition-colors transition-shadow duration-200 motion-reduce:transition-none',
        isActive
          ? 'bg-primary/5 border-primary shadow-[0_0_0_1px_rgba(var(--primary),0.2)] ring-1 ring-primary/20'
          : 'bg-background border-border hover:border-primary/30 hover:shadow-sm'
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
              showHoverActions ? 'opacity-100 transition-opacity lg:opacity-0 lg:group-hover:opacity-100' : ''
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
        <HighlightLayer content={chunk.content} query={query} />
      </p>
    </div>
  )
}
