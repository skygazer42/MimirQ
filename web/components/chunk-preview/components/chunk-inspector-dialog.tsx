/**
 * ChunkInspectorDialog - Edit chunk content/metadata before ingestion/export.
 *
 * This is a frontend-only override layer: it does NOT re-run chunking, and does not
 * affect original-text highlighting offsets.
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import { Copy, Pencil, RotateCcw, Save, Sparkles } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { getChunkMetadata, getStringValue, isJsonObject } from '@/components/chunk-preview/utils/metadata'
import type { ChunkPreviewItem, JsonObject } from '@/types'
import { getChunkSectionLabel } from '@/components/chunk-preview/utils/sections'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'

export type ChunkOverrideDraft = {
  content: string
  metadataText: string
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function buildEmbeddingText(content: string, meta: JsonObject | null, sectionFull: string | null): string {
  const raw = String(content ?? '')
  if (!raw) return raw
  const header =
    (meta &&
      (getStringValue(meta, 'header_path') ||
        getStringValue(meta, 'outline_path_str') ||
        getStringValue(meta, 'header_context'))) ||
    sectionFull ||
    ''
  const headerStr = String(header || '').trim()
  if (!headerStr) return raw
  return `[Section] ${headerStr}\n${raw}`
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
}: Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  chunk: ChunkPreviewItem | null
  index: number | null
  sourceFilename?: string
  overrideUpdatedAt?: number
  onSave: (payload: { content: string; metadata: JsonObject }) => void
  onReset: () => void
}>) {
  const pipelineCtx = usePipelineOptions()
  const [content, setContent] = useState('')
  const [metadataText, setMetadataText] = useState('{}')
  const sectionLabel = useMemo(() => (chunk ? getChunkSectionLabel(chunk) : null), [chunk])

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
      const obj = JSON.parse(metadataText || '{}') as unknown
      if (!isJsonObject(obj)) {
        return { value: null as JsonObject | null, error: 'metadata 必须是 JSON 对象（{}）' }
      }
      return { value: obj, error: null as string | null }
    } catch (error: unknown) {
      return { value: null as JsonObject | null, error: getErrorMessage(error, 'metadata JSON 解析失败') }
    }
  }, [metadataText])
  const parsedMetadata = metadataParse.value
  const metadataError = metadataParse.error

  const disabled = !chunk || index == null
  const embeddingPrefixEnabled = Boolean(pipelineCtx.enabled && pipelineCtx.options.embedding_context_prefix_enabled)
  const embeddingText = useMemo(() => {
    if (!embeddingPrefixEnabled) return String(content ?? '')
    const meta = parsedMetadata ?? (chunk ? getChunkMetadata(chunk) : null)
    const sectionFull = sectionLabel?.full || null
    return buildEmbeddingText(String(content ?? ''), meta, sectionFull)
  }, [chunk, content, embeddingPrefixEnabled, parsedMetadata, sectionLabel?.full])

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
              {chunk?.page_number == null ? '' : ` · P.${chunk.page_number}`}
              {chunk ? ` · ${chunk.start_index}-${chunk.end_index}` : ''}
            </div>
            {sectionLabel ? (
              <div className="text-[11px] text-muted-foreground">
                Section: <span title={sectionLabel.full}>{sectionLabel.full}</span>
              </div>
            ) : null}
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

          <div className="grid gap-1">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary" />
                <div className="text-xs font-medium text-muted-foreground">embedding text (vector-only)</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-muted-foreground">
                  {embeddingPrefixEnabled ? 'prefix: on' : 'prefix: off'}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-[11px]"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(embeddingText || '')
                    } catch {
                      // ignore
                    }
                  }}
                  disabled={disabled || !embeddingText}
                  aria-label="复制 embedding text"
                  title="复制 embedding text"
                >
                  <Copy className="w-3.5 h-3.5 mr-1.5" />
                  复制
                </Button>
              </div>
            </div>
            <Textarea
              value={embeddingText}
              readOnly
              className="min-h-[140px] font-mono text-[12px] bg-muted/30"
              disabled={disabled}
            />
            <div className="text-[11px] text-muted-foreground">
              当启用 “Embedding · 结构化上下文前缀” 时，入库向量 embedding 会使用该文本；不会改变原文定位与 chunk.content（DB）。
            </div>
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
