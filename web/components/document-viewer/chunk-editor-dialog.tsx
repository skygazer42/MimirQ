"use client"

import { Loader2 } from "lucide-react"

import type { DocumentChunk } from "@/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

type ChunkEditorDialogProps = {
  open: boolean
  mode: "create" | "edit"
  target: DocumentChunk | null
  content: string
  pageNumber: string
  submitting: boolean
  canEditChunks: boolean
  onOpenChange: (open: boolean) => void
  onContentChange: (value: string) => void
  onPageNumberChange: (value: string) => void
  onSubmit: () => void
}

export function ChunkEditorDialog({
  open,
  mode,
  target,
  content,
  pageNumber,
  submitting,
  canEditChunks,
  onOpenChange,
  onContentChange,
  onPageNumberChange,
  onSubmit,
}: Readonly<ChunkEditorDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{mode === "create" ? "Add chunk" : `Edit chunk #${target?.chunk_index ?? "-"}`}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">Content</div>
            <Textarea
              value={content}
              onChange={(event) => onContentChange(event.target.value)}
              className="min-h-[220px] font-mono"
              placeholder="Paste or edit chunk content..."
            />
            <div className="text-xs text-muted-foreground tabular-nums">{content.length.toLocaleString()} chars</div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Page (optional)</div>
              <Input
                value={pageNumber}
                onChange={(event) => onPageNumberChange(event.target.value)}
                inputMode="numeric"
                placeholder="e.g. 12"
              />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Status</div>
              <div className="text-xs text-muted-foreground">
                {canEditChunks ? "Editable" : "Document is processing; editing disabled"}
              </div>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onSubmit}
            disabled={submitting || !canEditChunks || !content.trim()}
            className="gap-2"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
