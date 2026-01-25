/**
 * ChunkInspectorDialog - Edit chunk content/metadata before ingestion/export.
 *
 * This is a frontend-only override layer: it does NOT re-run chunking, and does not
 * affect original-text highlighting offsets.
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import { Pencil, RotateCcw, Save } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { ChunkPreviewItem } from '@/types'

export type ChunkOverrideDraft = {
  content: string
  metadataText: string
}

export function ChunkInspectorDialog({
  open,
  onOpenChange,
  chunk,
  index,
  sourceFilename,
  overrideUpdatedAt,
  onSave,
  onReset,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  chunk: ChunkPreviewItem | null
  index: number | null
  sourceFilename?: string
  overrideUpdatedAt?: number
  onSave: (payload: { content: string; metadata: Record<string, any> }) => void
  onReset: () => void
}) {
  const [content, setContent] = useState('')
  const [metadataText, setMetadataText] = useState('{}')

  const title = useMemo(() => {
    const name = (sourceFilename || '').trim() || 'document'
    if (index == null) return name
    return `${name} · chunk #${index + 1}`
  }, [index, sourceFilename])

  // Initialize draft when dialog opens / chunk changes.
  useEffect(() => {
    if (!open) return
    if (!chunk || index == null) return
    setContent(String(chunk.content ?? ''))
    try {
      setMetadataText(JSON.stringify(chunk.metadata ?? {}, null, 2))
    } catch {
      setMetadataText('{}')
    }
  }, [chunk, index, open])

  const metadataParse = useMemo(() => {
    try {
      const obj = JSON.parse(metadataText || '{}')
      if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
        return { value: null as Record<string, any> | null, error: 'metadata 必须是 JSON 对象（{}）' }
      }
      return { value: obj as Record<string, any>, error: null as string | null }
    } catch (e: any) {
      return { value: null as Record<string, any> | null, error: (e?.message as string) || 'metadata JSON 解析失败' }
    }
  }, [metadataText])
  const parsedMetadata = metadataParse.value
  const metadataError = metadataParse.error

  const disabled = !chunk || index == null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Pencil className="w-5 h-5 text-primary" />
            Chunk Inspector
          </DialogTitle>
          <DialogDescription className="space-y-1">
            <div className="text-xs">
              {title}
              {chunk?.page_number != null ? ` · P.${chunk.page_number}` : ''}
              {chunk ? ` · ${chunk.start_index}-${chunk.end_index}` : ''}
            </div>
            <div className="text-[11px] text-muted-foreground">
              仅影响入库/导出；不会重新切块，也不会改变原文定位。
              {overrideUpdatedAt ? `（已编辑：${new Date(overrideUpdatedAt).toLocaleString()}）` : ''}
            </div>
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <div className="grid gap-1">
            <div className="text-xs font-medium text-muted-foreground">content</div>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="min-h-[200px] font-mono text-[12px]"
              disabled={disabled}
            />
          </div>

          <div className="grid gap-1">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-muted-foreground">metadata (JSON object)</div>
              {metadataError ? (
                <span className="text-[11px] text-destructive">{metadataError}</span>
              ) : (
                <span className="text-[11px] text-muted-foreground">OK</span>
              )}
            </div>
            <Textarea
              value={metadataText}
              onChange={(e) => setMetadataText(e.target.value)}
              className="min-h-[160px] font-mono text-[12px]"
              aria-invalid={metadataError ? 'true' : undefined}
              disabled={disabled}
            />
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 pt-2">
          <Button
            type="button"
            variant="outline"
            className="gap-2"
            onClick={() => {
              if (disabled) return
              onReset()
              onOpenChange(false)
            }}
            disabled={disabled}
          >
            <RotateCcw className="w-4 h-4" />
            重置本 chunk 编辑
          </Button>

          <Button
            type="button"
            className="gap-2"
            onClick={() => {
              if (disabled) return
              if (!parsedMetadata) return
              onSave({ content, metadata: parsedMetadata })
              onOpenChange(false)
            }}
            disabled={disabled || !parsedMetadata}
          >
            <Save className="w-4 h-4" />
            保存
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
