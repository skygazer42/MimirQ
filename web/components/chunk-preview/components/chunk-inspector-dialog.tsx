/**
 * ChunkInspectorDialog - Edit chunk content/metadata before ingestion/export.
 *
 * This is a frontend-only override layer: it does NOT re-run chunking, and does not
 * affect original-text highlighting offsets.
 */
'use client'

import { useMemo, useState } from 'react'
import { Braces, Copy, FileText, Pencil, RotateCcw, Save, Sparkles } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { readMetadataString, isJsonObject } from '@/components/chunk-preview/utils/metadata'
import type { ChunkPreviewItem, JsonObject } from '@/types'
import { getChunkSectionLabel, getChunkSectionPath } from '@/components/chunk-preview/utils/sections'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'

type MetadataParseResult = { value: JsonObject; error: null } | { value: null; error: string }

function buildEmbeddingText(content: string, metadata: JsonObject, sectionFull: string | null): string {
  if (content.length === 0) return content
  const header =
    readMetadataString(metadata.header_path) ??
    readMetadataString(metadata.outline_path_str) ??
    readMetadataString(metadata.header_context) ??
    sectionFull
  return header === null ? content : `[Section] ${header}\n${content}`
}

export function ChunkInspectorDialog({ open, ...props }: Readonly<ChunkInspectorEditorProps & { open: boolean }>) {
  return (
    <Dialog open={open} onOpenChange={props.onOpenChange}>
      <DialogContent className="grid h-[min(92vh,880px)] max-w-[min(96vw,1280px)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0">
        <ChunkInspectorEditor
          key={`${open ? 'editing' : 'closed'}:${props.position}:${props.chunk.index}`}
          {...props}
        />
      </DialogContent>
    </Dialog>
  )
}

type ChunkInspectorEditorProps = {
  onOpenChange: (open: boolean) => void
  chunk: ChunkPreviewItem
  position: number
  sourceFilename: string
  overrideUpdatedAt?: number
  onSave: (payload: { content: string; metadata: JsonObject }) => void
  onReset: () => void
}

function ChunkInspectorEditor({
  onOpenChange,
  chunk,
  position,
  sourceFilename,
  overrideUpdatedAt,
  onSave,
  onReset,
}: Readonly<ChunkInspectorEditorProps>) {
  const t = useTranslations('ChunkPreview')
  const pipelineCtx = usePipelineOptions()
  const [content, setContent] = useState(chunk.content)
  const [metadataText, setMetadataText] = useState(() =>
    chunk.metadata === undefined ? '{}' : JSON.stringify(chunk.metadata, null, 2),
  )
  const sectionLabel = useMemo(() => getChunkSectionLabel(chunk), [chunk])
  const title = t('chunkInspector.chunkLabel', { name: sourceFilename, index: position + 1 })

  const metadataParse = useMemo<MetadataParseResult>(() => {
    let obj: unknown
    try {
      obj = JSON.parse(metadataText)
    } catch (error: unknown) {
      if (!(error instanceof SyntaxError)) throw error
      return { value: null, error: error.message }
    }
    if (!isJsonObject(obj)) return { value: null, error: t('chunkInspector.metadataObjectError') }
    return { value: obj, error: null }
  }, [metadataText, t])
  const parsedMetadata = metadataParse.value
  const metadataError = metadataParse.error
  const contentStats = useMemo(() => {
    const lineCount = content.length > 0 ? content.split(/\r\n|\r|\n/).length : 0
    return { chars: Array.from(content).length, lines: lineCount }
  }, [content])

  const embeddingPrefixEnabled = pipelineCtx.enabled && pipelineCtx.options.embedding_context_prefix_enabled === true
  const embeddingText = useMemo(() => {
    if (!embeddingPrefixEnabled) return content
    if (parsedMetadata === null) return null
    const sectionFull = getChunkSectionPath({ metadata: parsedMetadata })
    return buildEmbeddingText(content, parsedMetadata, sectionFull)
  }, [content, embeddingPrefixEnabled, parsedMetadata])

  return (
    <>
      <DialogHeader className="border-b border-border/60 bg-popover/95 px-6 py-5 pr-14">
        <DialogTitle className="flex items-center gap-2">
          <Pencil className="w-5 h-5 text-primary" />
          {t('chunkInspector.title')}
        </DialogTitle>
        <DialogDescription asChild>
          <div className="space-y-1">
            <div className="text-xs">
              {title}
              {chunk.page_number == null ? '' : ` · P.${chunk.page_number}`}
              {` · ${chunk.start_index}-${chunk.end_index}`}
            </div>
            {sectionLabel ? (
              <div className="text-[13px] text-muted-foreground">
                {t('chunkInspector.sectionLabel')}: <span title={sectionLabel.full}>{sectionLabel.full}</span>
              </div>
            ) : null}
            <div className="text-[13px] text-muted-foreground">
              {t('chunkInspector.description')}
              {overrideUpdatedAt !== undefined
                ? t('chunkInspector.editedAt', {
                    value: new Date(overrideUpdatedAt).toLocaleString(),
                  })
                : null}
            </div>
          </div>
        </DialogDescription>
      </DialogHeader>

      <div className="grid min-h-0 gap-4 overflow-y-auto bg-muted/20 p-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.8fr)] lg:overflow-hidden">
        <section className="flex min-h-[420px] flex-col border-border bg-card lg:min-h-0">
          <div className="flex items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <FileText className="h-4 w-4 text-primary" />
                {t('chunkInspector.contentLabel')}
              </div>
              <div className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                {t('chunkInspector.contentHelper')}
              </div>
            </div>
            <span className="shrink-0 rounded-full border border-border/60 bg-background px-2.5 py-1 text-[13px] tabular-nums text-muted-foreground">
              {t('chunkInspector.contentStats', contentStats)}
            </span>
          </div>
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="min-h-[360px] flex-1 resize-none rounded-none border-0 bg-background/75 px-4 py-3 font-sans text-[14px] leading-7 shadow-none focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-ring/30 lg:min-h-0"
            aria-label={t('chunkInspector.contentLabel')}
          />
        </section>

        <aside className="flex min-h-[420px] flex-col border-border bg-card lg:min-h-0">
          <div className="border-b border-border/60 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <Braces className="h-4 w-4 text-primary" />
              {t('chunkInspector.sidePanelLabel')}
            </div>
            <div className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
              {t('chunkInspector.sidePanelHelper')}
            </div>
          </div>

          <Tabs defaultValue="metadata" className="flex min-h-0 flex-1 flex-col p-3">
            <TabsList className="grid h-9 w-full grid-cols-2 rounded-xl bg-muted/60 p-1">
              <TabsTrigger value="metadata" className="h-7 text-[13px]">
                {t('chunkInspector.metadataTab')}
              </TabsTrigger>
              <TabsTrigger value="embedding" className="h-7 text-[13px]">
                {t('chunkInspector.embeddingTab')}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="metadata" className="mt-3 min-h-0 flex-1 data-[state=inactive]:hidden">
              <div className="flex h-full min-h-0 flex-col rounded-xl border border-border/55 bg-background/70">
                <div className="flex items-start justify-between gap-3 border-b border-border/55 px-3 py-2.5">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-foreground">{t('chunkInspector.metadataLabel')}</div>
                    <div className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                      {t('chunkInspector.metadataHelper')}
                    </div>
                  </div>
                  {metadataError === null ? (
                    <span className="shrink-0 rounded-full border border-success/25 bg-success/10 px-2 py-0.5 text-[13px] text-success">
                      {t('chunkInspector.metadataOk')}
                    </span>
                  ) : null}
                </div>
                {metadataError !== null ? (
                  <p
                    id="chunk-inspector-metadata-error"
                    role="alert"
                    className="break-words px-3 py-2 text-sm text-destructive"
                  >
                    {metadataError}
                  </p>
                ) : null}
                <Textarea
                  value={metadataText}
                  onChange={(e) => setMetadataText(e.target.value)}
                  className="min-h-[300px] flex-1 resize-none rounded-none border-0 bg-transparent px-3 py-3 font-sans text-[14px] leading-7 shadow-none focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-ring/30 lg:min-h-0"
                  aria-label={t('chunkInspector.metadataLabel')}
                  aria-invalid={metadataError !== null}
                  aria-describedby={metadataError === null ? undefined : 'chunk-inspector-metadata-error'}
                />
              </div>
            </TabsContent>

            <TabsContent value="embedding" className="mt-3 min-h-0 flex-1 data-[state=inactive]:hidden">
              <div className="flex h-full min-h-0 flex-col rounded-xl border border-border/55 bg-background/70">
                <div className="flex items-start justify-between gap-3 border-b border-border/55 px-3 py-2.5">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                      <Sparkles className="w-3.5 h-3.5 text-primary" />
                      {t('chunkInspector.embeddingLabel')}
                    </div>
                    <div className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                      {embeddingPrefixEnabled ? t('chunkInspector.prefixOn') : t('chunkInspector.prefixOff')}
                    </div>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 shrink-0 px-2 text-[13px]"
                    onClick={async () => {
                      if (embeddingText === null) return
                      try {
                        await navigator.clipboard.writeText(embeddingText)
                        toast.success(t('chunkInspector.copySuccess'))
                      } catch {
                        toast.error(t('chunkInspector.copyFailed'))
                      }
                    }}
                    disabled={embeddingText === null}
                    aria-label={t('chunkInspector.copyEmbedding')}
                    title={t('chunkInspector.copyEmbedding')}
                  >
                    <Copy className="w-3.5 h-3.5 mr-1.5" />
                    {t('chunkInspector.copyEmbedding')}
                  </Button>
                </div>
                {embeddingText === null ? (
                  <p role="status" className="p-3 text-sm text-destructive">
                    {metadataError}
                  </p>
                ) : (
                  <Textarea
                    value={embeddingText}
                    readOnly
                    className="min-h-[280px] flex-1 resize-none rounded-none border-0 bg-muted/25 px-3 py-3 font-sans text-[14px] leading-7 shadow-none focus-visible:border-transparent focus-visible:ring-2 focus-visible:ring-ring/30 lg:min-h-0"
                    aria-label={t('chunkInspector.embeddingLabel')}
                  />
                )}
                <div className="border-t border-border/55 px-3 py-2 text-[13px] leading-relaxed text-muted-foreground">
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
            onReset()
            onOpenChange(false)
          }}
        >
          <RotateCcw className="w-4 h-4" />
          {t('chunkInspector.reset')}
        </Button>

        <Button
          type="button"
          className="gap-2"
          onClick={() => {
            if (parsedMetadata === null) return
            onSave({ content, metadata: parsedMetadata })
            onOpenChange(false)
          }}
          disabled={parsedMetadata === null}
        >
          <Save className="w-4 h-4" />
          {t('chunkInspector.save')}
        </Button>
      </div>
    </>
  )
}
