/**
 * ChunkInspectorDialog - Edit chunk content/metadata before ingestion/export.
 *
 * This is a frontend-only override layer: it does NOT re-run chunking, and does not
 * affect original-text highlighting offsets.
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  Braces,
  Copy,
  FileText,
  Pencil,
  RotateCcw,
  Save,
  Sparkles,
} from 'lucide-react'
import { useTranslations } from 'next-intl'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  getChunkMetadata,
  getStringValue,
  isJsonObject,
} from '@/components/chunk-preview/utils/metadata'
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

function buildEmbeddingText(
  content: string,
  meta: JsonObject | null,
  sectionFull: string | null
): string {
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
  const t = useTranslations('ChunkPreview')
  const pipelineCtx = usePipelineOptions()
  const [content, setContent] = useState('')
  const [metadataText, setMetadataText] = useState('{}')
  const sectionLabel = useMemo(
    () => (chunk ? getChunkSectionLabel(chunk) : null),
    [chunk]
  )

  const title = useMemo(() => {
    const name =
      (sourceFilename || '').trim() || t('chunkInspector.documentFallback')
    if (index == null) return name
    return t('chunkInspector.chunkLabel', { name, index: index + 1 })
  }, [index, sourceFilename, t])

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
        return {
          value: null as JsonObject | null,
          error: t('chunkInspector.metadataObjectError'),
        }
      }
      return { value: obj, error: null as string | null }
    } catch (error: unknown) {
      return {
        value: null as JsonObject | null,
        error: getErrorMessage(error, t('chunkInspector.metadataParseError')),
      }
    }
  }, [metadataText, t])
  const parsedMetadata = metadataParse.value
  const metadataError = metadataParse.error
  const contentStats = useMemo(() => {
    const text = String(content ?? '')
    const lineCount = text ? text.split(/\r\n|\r|\n/).length : 0
    return { chars: text.length, lines: lineCount }
  }, [content])

  const disabled = !chunk || index == null
  const embeddingPrefixEnabled = Boolean(
    pipelineCtx.enabled && pipelineCtx.options.embedding_context_prefix_enabled
  )
  const embeddingText = useMemo(() => {
    if (!embeddingPrefixEnabled) return String(content ?? '')
    const meta = parsedMetadata ?? (chunk ? getChunkMetadata(chunk) : null)
    const sectionFull = sectionLabel?.full || null
    return buildEmbeddingText(String(content ?? ''), meta, sectionFull)
  }, [
    chunk,
    content,
    embeddingPrefixEnabled,
    parsedMetadata,
    sectionLabel?.full,
  ])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="grid h-[min(92vh,880px)] max-w-[min(96vw,1280px)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border/60 bg-popover/95 px-6 py-5 pr-14">
          <DialogTitle className="flex items-center gap-2">
            <Pencil className="w-5 h-5 text-primary" />
            {t('chunkInspector.title')}
          </DialogTitle>
          <DialogDescription className="space-y-1">
            <div className="text-xs">
              {title}
              {chunk?.page_number == null ? '' : ` · P.${chunk.page_number}`}
              {chunk ? ` · ${chunk.start_index}-${chunk.end_index}` : ''}
            </div>
            {sectionLabel ? (
              <div className="text-[11px] text-muted-foreground">
                {t('chunkInspector.sectionLabel')}:{' '}
                <span title={sectionLabel.full}>{sectionLabel.full}</span>
              </div>
            ) : null}
            <div className="text-[11px] text-muted-foreground">
              {t('chunkInspector.description')}
              {overrideUpdatedAt
                ? t('chunkInspector.editedAt', {
                    value: new Date(overrideUpdatedAt).toLocaleString(),
                  })
                : ''}
            </div>
          </DialogDescription>
        </DialogHeader>

        <div className="grid min-h-0 gap-4 overflow-y-auto bg-muted/20 p-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.8fr)] lg:overflow-hidden">
          <section className="flex min-h-[420px] flex-col rounded-2xl border border-border/60 bg-card shadow-sm lg:min-h-0">
            <div className="flex items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <FileText className="h-4 w-4 text-primary" />
                  {t('chunkInspector.contentLabel')}
                </div>
                <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  {t('chunkInspector.contentHelper')}
                </div>
              </div>
              <span className="shrink-0 rounded-full border border-border/60 bg-background px-2.5 py-1 text-[11px] tabular-nums text-muted-foreground">
                {t('chunkInspector.contentStats', contentStats)}
              </span>
            </div>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="min-h-[360px] flex-1 resize-none rounded-none border-0 bg-background/75 px-4 py-3 font-mono text-[12px] leading-relaxed shadow-none focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-ring/30 lg:min-h-0"
              aria-label={t('chunkInspector.contentLabel')}
              disabled={disabled}
            />
          </section>

          <aside className="flex min-h-[420px] flex-col rounded-2xl border border-border/60 bg-card shadow-sm lg:min-h-0">
            <div className="border-b border-border/60 px-4 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Braces className="h-4 w-4 text-primary" />
                {t('chunkInspector.sidePanelLabel')}
              </div>
              <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                {t('chunkInspector.sidePanelHelper')}
              </div>
            </div>

            <Tabs
              defaultValue="metadata"
              className="flex min-h-0 flex-1 flex-col p-3"
            >
              <TabsList className="grid h-9 w-full grid-cols-2 rounded-xl bg-muted/60 p-1">
                <TabsTrigger value="metadata" className="h-7 text-[12px]">
                  {t('chunkInspector.metadataTab')}
                </TabsTrigger>
                <TabsTrigger value="embedding" className="h-7 text-[12px]">
                  {t('chunkInspector.embeddingTab')}
                </TabsTrigger>
              </TabsList>

              <TabsContent
                value="metadata"
                className="mt-3 min-h-0 flex-1 data-[state=inactive]:hidden"
              >
                <div className="flex h-full min-h-0 flex-col rounded-xl border border-border/55 bg-background/70">
                  <div className="flex items-start justify-between gap-3 border-b border-border/55 px-3 py-2.5">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-foreground">
                        {t('chunkInspector.metadataLabel')}
                      </div>
                      <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        {t('chunkInspector.metadataHelper')}
                      </div>
                    </div>
                    {metadataError ? (
                      <span className="shrink-0 rounded-full border border-destructive/25 bg-destructive/10 px-2 py-0.5 text-[11px] text-destructive">
                        {metadataError}
                      </span>
                    ) : (
                      <span className="shrink-0 rounded-full border border-success/25 bg-success/10 px-2 py-0.5 text-[11px] text-success">
                        {t('chunkInspector.metadataOk')}
                      </span>
                    )}
                  </div>
                  <Textarea
                    value={metadataText}
                    onChange={(e) => setMetadataText(e.target.value)}
                    className="min-h-[300px] flex-1 resize-none rounded-none border-0 bg-transparent px-3 py-3 font-mono text-[12px] leading-relaxed shadow-none focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-ring/30 lg:min-h-0"
                    aria-label={t('chunkInspector.metadataLabel')}
                    aria-invalid={metadataError ? 'true' : undefined}
                    disabled={disabled}
                  />
                </div>
              </TabsContent>

              <TabsContent
                value="embedding"
                className="mt-3 min-h-0 flex-1 data-[state=inactive]:hidden"
              >
                <div className="flex h-full min-h-0 flex-col rounded-xl border border-border/55 bg-background/70">
                  <div className="flex items-start justify-between gap-3 border-b border-border/55 px-3 py-2.5">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                        <Sparkles className="w-3.5 h-3.5 text-primary" />
                        {t('chunkInspector.embeddingLabel')}
                      </div>
                      <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        {embeddingPrefixEnabled
                          ? t('chunkInspector.prefixOn')
                          : t('chunkInspector.prefixOff')}
                      </div>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 shrink-0 px-2 text-[11px]"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(
                            embeddingText || ''
                          )
                        } catch {
                          // ignore
                        }
                      }}
                      disabled={disabled || !embeddingText}
                      aria-label={t('chunkInspector.copyEmbedding')}
                      title={t('chunkInspector.copyEmbedding')}
                    >
                      <Copy className="w-3.5 h-3.5 mr-1.5" />
                      {t('chunkInspector.copyEmbedding')}
                    </Button>
                  </div>
                  <Textarea
                    value={embeddingText}
                    readOnly
                    className="min-h-[280px] flex-1 resize-none rounded-none border-0 bg-muted/25 px-3 py-3 font-mono text-[12px] leading-relaxed shadow-none focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-ring/30 lg:min-h-0"
                    aria-label={t('chunkInspector.embeddingLabel')}
                    disabled={disabled}
                  />
                  <div className="border-t border-border/55 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
                    {t('chunkInspector.embeddingHint')}
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </aside>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-border/60 bg-popover/95 px-6 py-4">
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
            {t('chunkInspector.reset')}
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
            {t('chunkInspector.save')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
