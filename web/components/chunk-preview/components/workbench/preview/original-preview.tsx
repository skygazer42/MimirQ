/**
 * OriginalPreview - 原文预览
 */
'use client'

import { useState, useEffect, useRef, useMemo } from 'react'
import { FileText, Loader2, AlertCircle } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { getChunkRole } from '@/components/chunk-preview/utils/metadata'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { extractMarkdownHeadings } from '@/lib/markdown'
import { createPositionTagIndexMapper, findPositionTagRanges, stripPositionTags } from '@/lib/parsing-positions'
import { cn } from '@/lib/utils'
import type { ChunkPreviewItem } from '@/types'
import { OriginalPreviewMonaco } from './original-preview-monaco'
import { PdfPreview } from './pdf-preview'
import { CoverageHeatmapMini } from './coverage-heatmap-mini'
import { getInitialOriginalPreviewMode, ORIGINAL_PREVIEW_MODE_STORAGE_KEY } from './pdf-dock'

const AUTO_LOAD_TEXT_MAX_BYTES = 800_000
type PreviewMode = 'raw' | 'rendered' | 'editor' | 'pdf'

type IdleCallbackHandle = number
type IdleGlobal = typeof globalThis & {
  requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => IdleCallbackHandle
  cancelIdleCallback?: (id: IdleCallbackHandle) => void
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function canReadFileAsText(file: File | null) {
  if (!file) return false
  const type = (file.type || '').toLowerCase()
  if (type.startsWith('text/')) return true
  if (type === 'application/json') return true
  const name = (file.name || '').toLowerCase()
  return (
    name.endsWith('.md') ||
    name.endsWith('.txt') ||
    name.endsWith('.csv') ||
    name.endsWith('.json') ||
    name.endsWith('.yaml') ||
    name.endsWith('.yml') ||
    name.endsWith('.toml') ||
    name.endsWith('.log')
  )
}

function DeferredMarkdownToc({ markdown }: Readonly<{ markdown: string }>) {
  const t = useTranslations('ChunkPreview')
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    setReady(false)

    const enable = () => {
      if (cancelled) return
      setReady(true)
    }

    // Rendering + heading extraction for large markdown docs can block the main thread.
    // Defer the (non-critical) ToC until the browser is idle so the main preview shows ASAP.
    const idleGlobal: IdleGlobal = globalThis
    const ric = idleGlobal.requestIdleCallback
    const cic = idleGlobal.cancelIdleCallback
    if (typeof ric === 'function') {
      const id = ric(enable, { timeout: 800 })
      return () => {
        cancelled = true
        cic?.(id)
      }
    }

    const t = setTimeout(enable, 0)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [markdown])

  if (!ready) {
    return <div className="text-[11px] text-muted-foreground">{t('originalPreview.tocLoading')}</div>
  }

  return <MarkdownToc markdown={markdown} />
}

export function OriginalPreview() {
  const t = useTranslations('ChunkPreview')
  const {
    previewData,
    chunkOverrides,
    hoveredChunkIndex,
    selectedChunkIndex,
    setSelectedChunkIndex,
    currentFile,
    isLoading,
    error,
  } = useChunkPreview()
  const [previewMode, setPreviewMode] = useState<PreviewMode>('raw')
  const [forceFullHighlight, setForceFullHighlight] = useState(false)
  const [localOriginalText, setLocalOriginalText] = useState<string | null>(null)
  const [localLoading, setLocalLoading] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const highlightRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (globalThis.window === undefined) return
    globalThis.window.localStorage.setItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, previewMode)
  }, [previewMode])

  const activeChunkIndex = hoveredChunkIndex ?? selectedChunkIndex
  const activeChunkMeta = useMemo(() => {
    if (activeChunkIndex == null) return null
    const chunk = previewData?.chunks?.[activeChunkIndex]
    if (!chunk) return null
    return {
      label: `#${activeChunkIndex + 1}`,
      range: `${chunk.start_index}-${chunk.end_index}`,
      page: chunk.page_number,
      role: getChunkRole(chunk),
    }
  }, [activeChunkIndex, previewData?.chunks])

  const isPdf = useMemo(() => {
    const ft = String(previewData?.file_type || '').toLowerCase()
    if (ft === 'pdf') return true
    const name = String(currentFile?.name || '').toLowerCase()
    return name.endsWith('.pdf')
  }, [currentFile?.name, previewData?.file_type])

  // Keep the preferred preview mode sticky across chunk inspections (especially useful for PDF docking).
  useEffect(() => {
    if (globalThis.window === undefined) return
    setPreviewMode(getInitialOriginalPreviewMode(isPdf))
  }, [isPdf])

  useEffect(() => {
    if (previewMode === 'pdf' && !isPdf) setPreviewMode('raw')
  }, [isPdf, previewMode])

  const serverTextInfo = useMemo(() => {
    const raw = previewData?.original_text
    const cleanedFromApi = previewData?.original_text_cleaned

    const identity = (n: number) => Math.max(0, Math.trunc(Number(n) || 0))

    if (!raw) {
      return {
        displayText: null as string | null,
        indexMapper: identity,
        hasPositionTags: false,
      }
    }

    if (typeof cleanedFromApi === 'string' && cleanedFromApi.length > 0) {
      return {
        displayText: cleanedFromApi,
        indexMapper: createPositionTagIndexMapper(raw),
        hasPositionTags: true,
      }
    }

    const ranges = findPositionTagRanges(raw)
    if (ranges.length > 0) {
      return {
        displayText: stripPositionTags(raw),
        indexMapper: createPositionTagIndexMapper(raw, ranges),
        hasPositionTags: true,
      }
    }

    return {
      displayText: raw,
      indexMapper: identity,
      hasPositionTags: false,
    }
  }, [previewData?.original_text, previewData?.original_text_cleaned])

  const canLoadFromFile = useMemo(() => canReadFileAsText(currentFile), [currentFile])
  const effectiveOriginalText = serverTextInfo.displayText ?? localOriginalText ?? null
  const originalTextSource = (() => {
    if (previewData?.original_text) {
        return 'server';
    }
    else if (localOriginalText) {
            return 'local';
        }
        else {
            return null;
        }
})()

  useEffect(() => {
    setLocalOriginalText(null)
    setLocalError(null)
    setLocalLoading(false)
    setForceFullHighlight(false)
  }, [currentFile, previewData?.filename])

  useEffect(() => {
    if (!previewData) return
    if (previewData.original_text) return
    if (!canLoadFromFile) return
    if (!currentFile) return
    if (currentFile.size > AUTO_LOAD_TEXT_MAX_BYTES) return
    if (localOriginalText) return
    if (localLoading) return

    let alive = true
    setLocalLoading(true)
    setLocalError(null)
    currentFile
      .text()
      .then((text) => {
        if (!alive) return
        setLocalOriginalText(text)
      })
      .catch((error: unknown) => {
        if (!alive) return
        setLocalError(getErrorMessage(error, t('originalPreview.errors.readLocalFailed')))
      })
      .finally(() => {
        if (!alive) return
        setLocalLoading(false)
      })

    return () => {
      alive = false
    }
  }, [canLoadFromFile, currentFile, localLoading, localOriginalText, previewData, t])

  const highlightModel = useMemo(() => {
    if (!effectiveOriginalText || activeChunkIndex === null) return null

    const chunk = previewData?.chunks?.[activeChunkIndex]
    if (!chunk) return null

    const text = effectiveOriginalText
    const mapIndex = serverTextInfo.indexMapper
    const activeStartRaw = Math.max(0, Number(chunk.start_index) || 0)
    const activeEndRaw = Math.max(activeStartRaw, Number(chunk.end_index) || activeStartRaw)
    const activeStart = Math.max(0, mapIndex(activeStartRaw))
    const activeEnd = Math.max(activeStart, mapIndex(activeEndRaw))
    if (activeStart >= text.length) return null
    const safeActiveEnd = Math.min(activeEnd, text.length)
    if (safeActiveEnd <= activeStart) return null

    // Parent-child: when selecting a child, also highlight its parent range (if provided).
    const meta = (chunk.metadata || {})
    const role = String(meta.chunk_role || '')
    const parentStartRaw = meta.parent_start_char ?? meta.parent_start_index ?? meta.parent_start
    const parentEndRaw = meta.parent_end_char ?? meta.parent_end_index ?? meta.parent_end
    const parentStart = role === 'child' && parentStartRaw != null ? Number(parentStartRaw) : Number.NaN
    const parentEnd = role === 'child' && parentEndRaw != null ? Number(parentEndRaw) : Number.NaN
    const parentStartMapped = Number.isFinite(parentStart) ? mapIndex(parentStart) : Number.NaN
    const parentEndMapped = Number.isFinite(parentEnd) ? mapIndex(parentEnd) : Number.NaN
    const hasParent =
      role === 'child' &&
      Number.isFinite(parentStartMapped) &&
      Number.isFinite(parentEndMapped) &&
      parentEndMapped > parentStartMapped &&
      parentStartMapped <= activeStart &&
      parentEndMapped >= safeActiveEnd

    const baseStart = hasParent ? Math.min(activeStart, parentStartMapped) : activeStart
    const baseEnd = hasParent ? Math.max(safeActiveEnd, parentEndMapped) : safeActiveEnd

    // Avoid rendering giant before/after strings for large texts: default to a windowed excerpt.
    const EXCERPT_THRESHOLD = 20_000
    const CONTEXT_CHARS = 2000
    const useExcerpt = !forceFullHighlight && text.length > EXCERPT_THRESHOLD
    if (!useExcerpt) {
      return {
        text,
        excerptStart: 0,
        excerptEnd: text.length,
        prefixOmitted: false,
        suffixOmitted: false,
        activeStart,
        activeEnd: safeActiveEnd,
        parentStart: hasParent ? parentStartMapped : null,
        parentEnd: hasParent ? parentEndMapped : null,
      }
    }

    const excerptStart = Math.max(0, baseStart - CONTEXT_CHARS)
    const excerptEnd = Math.min(text.length, baseEnd + CONTEXT_CHARS)
    return {
      text,
      excerptStart,
      excerptEnd,
      prefixOmitted: excerptStart > 0,
      suffixOmitted: excerptEnd < text.length,
      activeStart,
      activeEnd: safeActiveEnd,
      parentStart: hasParent ? parentStartMapped : null,
      parentEnd: hasParent ? parentEndMapped : null,
    }
  }, [activeChunkIndex, effectiveOriginalText, forceFullHighlight, previewData?.chunks, serverTextInfo.indexMapper])

  const displayChunks = useMemo<ChunkPreviewItem[]>(() => {
    const chunks = previewData?.chunks || []
    if (!chunks.length) return chunks
    if (!serverTextInfo.hasPositionTags) return chunks

    const mapIndex = serverTextInfo.indexMapper
    return chunks.map((c) => {
      const startRaw = Number(c.start_index) || 0
      const endRaw = Math.max(startRaw, Number(c.end_index) || startRaw)
      const start = Math.max(0, mapIndex(startRaw))
      const end = Math.max(start, mapIndex(endRaw))

      const metadata = c.metadata ? { ...c.metadata } : undefined
      if (metadata) {
        const psRaw = metadata.parent_start_char ?? metadata.parent_start_index ?? metadata.parent_start
        const peRaw = metadata.parent_end_char ?? metadata.parent_end_index ?? metadata.parent_end
        const ps = psRaw == null ? null : mapIndex(Number(psRaw) || 0)
        const pe = peRaw == null ? null : mapIndex(Number(peRaw) || 0)
        if (ps != null) {
          metadata.parent_start_char = ps
          metadata.parent_start_index = ps
          metadata.parent_start = ps
        }
        if (pe != null) {
          metadata.parent_end_char = pe
          metadata.parent_end_index = pe
          metadata.parent_end = pe
        }
      }

      return {
        ...c,
        start_index: start,
        end_index: end,
        metadata,
      }
    })
  }, [previewData?.chunks, serverTextInfo.hasPositionTags, serverTextInfo.indexMapper])

  const tocEnabled = useMemo(
    () => extractMarkdownHeadings(effectiveOriginalText || '', { maxDepth: 4 }).length > 0,
    [effectiveOriginalText]
  )

  useEffect(() => {
    if (activeChunkIndex === null) return
    if (previewMode !== 'raw') return
    const el = highlightRef.current
    if (!el) return
    const prefersReducedMotion = globalThis.window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
    el.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'center' })
  }, [activeChunkIndex, previewMode])

  return (
    <div className="flex-1 flex flex-col min-w-0 border-b lg:border-b-0 lg:border-r border-border/60 bg-card">
      <div className="h-10 border-b border-border/60 bg-card flex items-center justify-between px-4 shrink-0">
        <span className="text-sm font-semibold text-foreground flex items-center gap-2 whitespace-nowrap shrink-0">
          <FileText className="w-4 h-4 text-muted-foreground" />
          {previewMode === 'pdf' ? t('originalPreview.titlePdf') : t('originalPreview.title')}
          {previewMode === 'pdf' ? (
            <span className="hidden xl:inline text-[11px] font-normal text-muted-foreground/75">
              {t('originalPreview.hints.pdfMode')}
            </span>
          ) : null}
        </span>
        <div className="flex items-center gap-2">
          {previewData && (
            <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono text-muted-foreground">
              {activeChunkMeta ? (
                <span className="inline-flex h-5 items-center rounded-md border border-primary/20 bg-primary/10 px-1.5 text-primary">
                  {activeChunkMeta.label}
                  {activeChunkMeta.page == null ? '' : ` P.${activeChunkMeta.page}`}
                  {' '}
                  <span className="text-muted-foreground">{activeChunkMeta.range}</span>
                  {activeChunkMeta.role ? (
                    <span className="ml-1 text-[9px] uppercase  text-muted-foreground">
                      {activeChunkMeta.role}
                    </span>
                  ) : null}
                </span>
              ) : null}
              <span className="inline-flex h-5 items-center rounded-md border border-border/60 bg-muted/35 px-1.5 tabular-nums">
                {t('originalPreview.charCount', {
                  count: (effectiveOriginalText?.length ?? previewData.total_characters).toLocaleString(),
                })}
              </span>
              <CoverageHeatmapMini
                chunks={displayChunks}
                totalChars={effectiveOriginalText?.length ?? previewData.total_characters}
                strategy={previewData.chunk_strategy}
                className="hidden lg:flex"
              />
              {originalTextSource ? (
                <span className="inline-flex h-5 items-center rounded-md border border-border/60 bg-muted/35 px-1.5">
                  {originalTextSource === 'server'
                    ? t('originalPreview.source.server')
                    : t('originalPreview.source.local')}
                </span>
              ) : null}
              {previewData.original_text ? null : (() => {
                const limit = previewData.original_text_max_chars ?? 100000
                const truncated = Boolean(previewData.original_text_truncated)
                const badgeTitle = truncated
                  ? t('originalPreview.badges.originalTooLargeTitle', {
                      limit: limit.toLocaleString(),
                    })
                  : t('originalPreview.badges.originalMissingTitle')
                const badgeLabel = truncated
                  ? t('originalPreview.badges.originalTooLarge')
                  : t('originalPreview.badges.originalMissing')
                const badgeDescription = badgeTitle === badgeLabel ? null : badgeTitle
                return (
                  <TooltipProvider delayDuration={120}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span
                          className="inline-flex h-5 w-5 items-center justify-center rounded-md border border-warning/25 bg-warning/10 text-warning"
                          aria-label={badgeLabel}
                        >
                          <AlertCircle className="h-3 w-3" />
                        </span>
                      </TooltipTrigger>
                      <TooltipContent className="max-w-[240px] text-[11px] leading-relaxed">
                        <div className="font-medium">{badgeLabel}</div>
                        {badgeDescription ? (
                          <div className="mt-0.5 text-muted-foreground">{badgeDescription}</div>
                        ) : null}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                )
              })()}
            </div>
          )}
          {previewMode === 'raw' && effectiveOriginalText && activeChunkIndex !== null && effectiveOriginalText.length > 20000 ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setForceFullHighlight((v) => !v)}
              title={
                forceFullHighlight
                  ? t('originalPreview.toggle.windowedTitle')
                  : t('originalPreview.toggle.fullTitle')
              }
            >
              {forceFullHighlight
                ? t('originalPreview.toggle.windowed')
                : t('originalPreview.toggle.full')}
            </Button>
          ) : null}
          <div className="flex items-center gap-1 rounded-md border border-border/60 bg-muted/20 p-0.5">
            <Button
              variant={previewMode === 'raw' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setPreviewMode('raw')}
              disabled={!effectiveOriginalText}
            >
              {t('originalPreview.tabs.raw')}
            </Button>
            <Button
              variant={previewMode === 'rendered' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setPreviewMode('rendered')}
              disabled={!effectiveOriginalText}
            >
              {t('originalPreview.tabs.rendered')}
            </Button>
            <Button
              variant={previewMode === 'editor' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setPreviewMode('editor')}
              disabled={!effectiveOriginalText}
              title={t('originalPreview.tabs.editorTitle')}
            >
              {t('originalPreview.tabs.editor')}
            </Button>
            {isPdf ? (
              <Button
                variant={previewMode === 'pdf' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 px-2 text-[11px]"
                onClick={() => setPreviewMode('pdf')}
                disabled={!previewData || !currentFile}
                title={
                  serverTextInfo.hasPositionTags
                    ? t('originalPreview.tabs.pdfAvailableTitle')
                    : t('originalPreview.tabs.pdfUnavailableTitle')
                }
              >
                {t('originalPreview.tabs.pdf')}
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <div
        data-page-scroll-container="true"
        className={cn(
          'flex-1 overscroll-contain no-scrollbar p-4 scroll-smooth',
          previewMode === 'editor' || previewMode === 'pdf' ? 'overflow-hidden' : 'overflow-y-auto'
        )}
      >
        <div
          className={cn(
            'min-h-full rounded-2xl border border-border/60 bg-card p-6 shadow-sm ring-1 ring-border/40',
            previewMode === 'editor' || previewMode === 'pdf' ? 'h-full' : null
          )}
        >
          {(() => {
    if (previewData) {
        return (effectiveOriginalText ? ((() => {
            if (previewMode === 'pdf') {
                return (<div className="mx-auto w-full max-w-6xl h-full">
                  <PdfPreview />
                </div>);
            }
            else if (previewMode === 'rendered') {
                    return (<div className="mx-auto w-full max-w-6xl flex gap-8">
                  <div className="min-w-0 flex-1">
                    <div className="prose prose-slate dark:prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-a:text-primary prose-code:text-primary prose-code:bg-primary/10 dark:prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-muted">
                      <MarkdownRenderer markdown={effectiveOriginalText} autoScrollToHash/>
                    </div>
                    <p className="mt-4 text-[11px] text-muted-foreground">
                      {t('originalPreview.hints.renderedMode')}
                    </p>
                  </div>
	                  {tocEnabled && (<aside className="hidden xl:block w-64 shrink-0">
	                      <div className="sticky top-6 max-h-[calc(100vh-220px)] overflow-y-auto overscroll-contain no-scrollbar rounded-xl border border-border/60 bg-card p-3">
	                        <DeferredMarkdownToc markdown={effectiveOriginalText}/>
	                      </div>
	                    </aside>)}
	                </div>);
                }
                else if (previewMode === 'editor') {
                        return (<div className="mx-auto w-full max-w-6xl h-full">
                  <OriginalPreviewMonaco text={effectiveOriginalText} chunks={displayChunks} activeChunkIndex={activeChunkIndex} chunkOverrides={chunkOverrides} onSelectChunkIndex={setSelectedChunkIndex}/>
                  <p className="mt-3 text-[11px] text-muted-foreground">
                    {t('originalPreview.hints.editorMode')}
                  </p>
                </div>);
                    }
                    else {
                        return (<div className="font-mono text-sm leading-relaxed text-muted-foreground whitespace-pre-wrap max-w-3xl mx-auto">
                  {activeChunkIndex !== null && highlightModel ? ((() => {
                                const excerpt = highlightModel.text.slice(highlightModel.excerptStart, highlightModel.excerptEnd);
                                const rel = (abs: number) => abs - highlightModel.excerptStart;
                                const safeSlice = (fromAbs: number, toAbs: number) => excerpt.slice(Math.max(0, rel(fromAbs)), Math.max(0, rel(toAbs)));
                                const hasParent = highlightModel.parentStart != null && highlightModel.parentEnd != null;
                                const parentStart = hasParent ? Number(highlightModel.parentStart) : null;
                                const parentEnd = hasParent ? Number(highlightModel.parentEnd) : null;
                                if (!hasParent || parentStart == null || parentEnd == null) {
                                    return (<>
                            {highlightModel.prefixOmitted ? <span className="opacity-40">…</span> : null}
                            <span className="opacity-40">{safeSlice(highlightModel.excerptStart, highlightModel.activeStart)}</span>
                            <mark ref={highlightRef} className="bg-primary/15 text-foreground rounded px-0.5 py-0.5 mx-0.5 shadow-sm font-medium">
                              {safeSlice(highlightModel.activeStart, highlightModel.activeEnd)}
                            </mark>
                            <span className="opacity-40">{safeSlice(highlightModel.activeEnd, highlightModel.excerptEnd)}</span>
                            {highlightModel.suffixOmitted ? <span className="opacity-40">…</span> : null}
                          </>);
                                }
                                return (<>
                          {highlightModel.prefixOmitted ? <span className="opacity-40">…</span> : null}
                          <span className="opacity-40">{safeSlice(highlightModel.excerptStart, parentStart)}</span>

                          <mark className="bg-primary/10 text-foreground rounded px-0.5 py-0.5 mx-0.5 shadow-sm">
                            {safeSlice(parentStart, highlightModel.activeStart)}
                            <mark ref={highlightRef} className="bg-primary/20 text-foreground rounded px-0.5 py-0.5 mx-0.5 shadow-sm font-medium">
                              {safeSlice(highlightModel.activeStart, highlightModel.activeEnd)}
                            </mark>
                            {safeSlice(highlightModel.activeEnd, parentEnd)}
                          </mark>

                          <span className="opacity-40">{safeSlice(parentEnd, highlightModel.excerptEnd)}</span>
                          {highlightModel.suffixOmitted ? <span className="opacity-40">…</span> : null}
                        </>);
                            })()) : (effectiveOriginalText)}
                </div>);
                    }
        })()) : (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
                <FileText className="w-12 h-12 opacity-10"/>
                <p className="text-xs">
                  {previewData.original_text_truncated
                    ? t('originalPreview.empty.truncated')
                    : t('originalPreview.empty.missing')}
                </p>
                <p className="text-xs text-muted-foreground max-w-[480px] text-center leading-relaxed">
                  {(() => {
                const limit = previewData.original_text_max_chars ?? 100000;
                if (previewData.original_text_truncated) {
                    return t('originalPreview.empty.truncatedDetail', {
                      limit: limit.toLocaleString(),
                      total: previewData.total_characters.toLocaleString(),
                    });
                }
                return t('originalPreview.empty.missingDetail', {
                  total: previewData.total_characters.toLocaleString(),
                });
            })()}
                  {t('originalPreview.empty.fallbackHint')}
                </p>

                {localError ? (<p className="text-[11px] text-destructive bg-destructive/10 border border-destructive/25 px-2 py-1 rounded-lg">
                    {localError}
                  </p>) : null}

                {canLoadFromFile && currentFile ? (<Button type="button" variant="outline" size="sm" className="h-8 px-3 text-[11px] mt-2" disabled={localLoading} onClick={async () => {
                    try {
                        setLocalLoading(true);
                        setLocalError(null);
                        const text = await currentFile.text();
                        setLocalOriginalText(text);
                    }
                    catch (error: unknown) {
                        setLocalError(getErrorMessage(error, t('originalPreview.errors.readLocalFailed')));
                    }
                    finally {
                        setLocalLoading(false);
                    }
                }}>
                    {localLoading
                      ? t('originalPreview.empty.readLocalLoading')
                      : t('originalPreview.empty.readLocal')}
                  </Button>) : (<p className="text-[11px] text-muted-foreground">{t('originalPreview.empty.unsupportedFile')}</p>)}
              </div>));
    }
    else if (isLoading) {
            return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
              <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none opacity-20"/>
              <p className="text-xs">{t('originalPreview.states.loading')}</p>
            </div>);
        }
        else if (error) {
                return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
              <AlertCircle className="w-10 h-10 opacity-20"/>
              <p className="text-xs text-muted-foreground">{t('originalPreview.states.loadFailed')}</p>
              <p className="text-xs text-muted-foreground max-w-[360px] text-center break-words line-clamp-3">{error}</p>
            </div>);
            }
            else {
                return (<div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
              <FileText className="w-12 h-12 opacity-10"/>
              <p className="text-xs">{t('originalPreview.states.waiting')}</p>
            </div>);
            }
})()}
        </div>
      </div>
    </div>
  )
}
