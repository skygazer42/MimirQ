"use client"

import { Loader2, Sparkles } from "lucide-react"

import type { DocumentQAGenerateResponse } from "@/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"

type QAGenerationDialogProps = {
  open: boolean
  qaNumPairs: number
  qaMaxSourceChars: number
  qaReplaceExisting: boolean
  qaPreferLlm: boolean
  qaSubmitting: boolean
  qaLastResult: DocumentQAGenerateResponse | null
  canEditChunks: boolean
  documentId: string | null
  onOpenChange: (open: boolean) => void
  onNumPairsChange: (value: number) => void
  onMaxSourceCharsChange: (value: number) => void
  onReplaceExistingChange: (value: boolean) => void
  onPreferLlmChange: (value: boolean) => void
  onSubmit: () => void
}

export function QAGenerationDialog({
  open,
  qaNumPairs,
  qaMaxSourceChars,
  qaReplaceExisting,
  qaPreferLlm,
  qaSubmitting,
  qaLastResult,
  canEditChunks,
  documentId,
  onOpenChange,
  onNumPairsChange,
  onMaxSourceCharsChange,
  onReplaceExistingChange,
  onPreferLlmChange,
  onSubmit,
}: Readonly<QAGenerationDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Generate Q&A chunks</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Num pairs</div>
              <Input value={String(qaNumPairs)} onChange={(event) => onNumPairsChange(Number(event.target.value || 0))} inputMode="numeric" />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Max source chars</div>
              <Input
                value={String(qaMaxSourceChars)}
                onChange={(event) => onMaxSourceCharsChange(Number(event.target.value || 0))}
                inputMode="numeric"
              />
            </div>
          </div>

          <label className="flex cursor-pointer select-none items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-sm">
            <span className="text-muted-foreground">Replace existing QA chunks</span>
            <input
              type="checkbox"
              checked={qaReplaceExisting}
              onChange={(event) => onReplaceExistingChange(event.target.checked)}
              className="accent-primary h-4 w-4"
            />
          </label>

          <label className="flex cursor-pointer select-none items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-sm">
            <span className="text-muted-foreground">Prefer LLM (if configured)</span>
            <input
              type="checkbox"
              checked={qaPreferLlm}
              onChange={(event) => onPreferLlmChange(event.target.checked)}
              className="accent-primary h-4 w-4"
            />
          </label>

          <div className="text-[11px] text-muted-foreground">
            Generated chunks are tagged with <span className="font-mono">file_type=qa</span> in metadata.
            You can include/exclude them via <span className="font-mono">metadata_filter</span>.
          </div>

          {qaLastResult?.preview?.length ? (
            <div className="rounded-xl border border-border bg-background/60 p-3">
              <div className="mb-2 text-xs font-semibold text-foreground">Preview</div>
              <div className="max-h-[220px] space-y-2 overflow-auto">
                {qaLastResult.preview.slice(0, 10).map((preview) => (
                  <div key={`${preview.question}-${preview.answer}`} className="rounded-lg border border-border/60 bg-muted/10 p-2">
                    <div className="text-[11px] text-muted-foreground">Q</div>
                    <div className="whitespace-pre-wrap text-xs text-foreground">{preview.question}</div>
                    <div className="mt-2 text-[11px] text-muted-foreground">A</div>
                    <div className="whitespace-pre-wrap text-xs text-foreground">{preview.answer}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={qaSubmitting}>
            Close
          </Button>
          <Button
            type="button"
            onClick={onSubmit}
            disabled={!canEditChunks || qaSubmitting || !documentId}
            className="gap-2"
          >
            {qaSubmitting ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Sparkles className="size-4" />}
            Generate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
