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
  startChar: string
  endChar: string
  submitting: boolean
  canEditChunks: boolean
  canRerunRetrieve: boolean
  onOpenChange: (open: boolean) => void
  onContentChange: (value: string) => void
  onPageNumberChange: (value: string) => void
  onStartCharChange: (value: string) => void
  onEndCharChange: (value: string) => void
  onSubmit: (mode?: "save" | "save_reembed" | "save_rerun") => void
}

export function ChunkEditorDialog({
  open,
  mode,
  target,
  content,
  pageNumber,
  startChar,
  endChar,
  submitting,
  canEditChunks,
  canRerunRetrieve,
  onOpenChange,
  onContentChange,
  onPageNumberChange,
  onStartCharChange,
  onEndCharChange,
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

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Start Char</div>
              <Input
                value={startChar}
                onChange={(event) => onStartCharChange(event.target.value)}
                inputMode="numeric"
                placeholder="e.g. 1200"
              />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">End Char</div>
              <Input
                value={endChar}
                onChange={(event) => onEndCharChange(event.target.value)}
                inputMode="numeric"
                placeholder="e.g. 1680"
              />
            </div>
          </div>

          <div className="rounded-xl border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            调整 Start/End Char 可以直接修正 chunk boundary。保存后可选择局部重嵌入，或在已有检索 query 时保存后复跑检索。
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => onSubmit("save")}
            disabled={submitting || !canEditChunks || !content.trim()}
            className="gap-2"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
            Save
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => onSubmit("save_reembed")}
            disabled={submitting || !canEditChunks || !content.trim()}
            className="gap-2"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
            保存并重新嵌入
          </Button>
          <Button
            type="button"
            onClick={() => onSubmit("save_rerun")}
            disabled={submitting || !canEditChunks || !content.trim() || !canRerunRetrieve}
            className="gap-2"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
            保存后复跑检索
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
