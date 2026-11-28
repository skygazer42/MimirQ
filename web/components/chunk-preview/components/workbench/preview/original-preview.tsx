/**
 * OriginalPreview - 原文预览
 */
'use client'

import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from 'react'
import { FileText, Loader2, AlertCircle } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { getChunkParentRange } from '@/components/chunk-preview/utils/metadata'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { extractMarkdownHeadings, type MarkdownHeading } from '@/lib/markdown'
import { createPositionTagIndexMapper, findPositionTagRanges, stripPositionTags } from '@/lib/parsing-positions'
import { createCodePointToUtf16Converter, expandTextRangeToCharacters } from '@/lib/text-offsets'
import { projectChunkTextPositions } from '@/lib/chunk-text-positions'
import { cn } from '@/lib/utils'
import { writeClientStorage } from '@/lib/client-storage'
import { OriginalPreviewMonaco } from './original-preview-monaco'
import { PdfPreview } from './pdf-preview'
import { CoverageStats } from './coverage-stats'
import styles from '../compare.module.css'
import {
  getStoredOriginalPreviewMode,
  isPdfOriginalFile,
  ORIGINAL_PREVIEW_MODE_STORAGE_KEY,
  type OriginalPreviewMode,
} from './pdf-dock'

const AUTO_LOAD_TEXT_MAX_BYTES = 800_000
const EXCERPT_THRESHOLD = 20_000

type LocalOriginalRead = {
  file: File
} & ({ status: 'loading' } | { status: 'ready'; text: string } | { status: 'failed'; message: string })

type IdleGlobal = typeof globalThis & {
  requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number
  cancelIdleCallback?: (id: number) => void
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function canReadFileAsText(file: File | null) {
  if (!file) return false
  const type = file.type.toLowerCase()
  if (type.startsWith('text/')) return true
  if (type === 'application/json') return true
  const name = file.name.toLowerCase()
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

function DeferredMarkdownToc({ headings }: Readonly<{ headings: readonly MarkdownHeading[] }>) {
  const t = useTranslations('ChunkPreview')
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    setReady(false)

    const enable = () => {
      if (cancelled) return
      setReady(true)
    }

    // Defer the directory and its observer until the browser is idle.
    const idleGlobal: IdleGlobal = globalThis
    const requestIdleCallback = idleGlobal.requestIdleCallback
    const cancelIdleCallback = idleGlobal.cancelIdleCallback
    if (typeof requestIdleCallback === 'function') {
      const id = requestIdleCallback(enable, { timeout: 800 })
      return () => {
        cancelled = true
        cancelIdleCallback?.(id)
      }
    }

    const timerId = setTimeout(enable, 0)
    return () => {
      cancelled = true
      clearTimeout(timerId)
    }
  }, [headings])

  if (!ready) {
    return <div className="text-[11px] text-muted-foreground">{t('originalPreview.tocLoading')}</div>
  }

  return <MarkdownToc headings={headings} />
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
    previewSourceFile,
    isLoading,
    error,
  } = useChunkPreview()
  const sourceFile = previewSourceFile === null ? currentFile : previewSourceFile
  const [preferredMode, setPreferredMode] = useState<OriginalPreviewMode>('raw')
  const [forceFullHighlight, setForceFullHighlight] = useState(false)
  const [localRead, setLocalRead] = useState<LocalOriginalRead | null>(null)
  const currentRead = localRead?.file === sourceFile ? localRead : null
  const localOriginalText = currentRead?.status === 'ready' ? currentRead.text : null
  const localReadRequestRef = useRef<{ file: File } | null>(null)
  const highlightRef = useRef<HTMLElement | null>(null)
  const sourceBodyRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const activeChunkIndex = selectedChunkIndex ?? hoveredChunkIndex
  const activeChunkMeta = useMemo(() => {
    if (activeChunkIndex == null) return null
    const chunk = previewData?.chunks[activeChunkIndex]
    if (chunk === undefined) return null
    return {
      label: `#${activeChunkIndex + 1}`,
      range: `${chunk.start_index}-${chunk.end_index}`,
      page: chunk.page_number,
    }
  }, [activeChunkIndex, previewData?.chunks])

  const isPdf = isPdfOriginalFile(previewData, sourceFile)
  const previewMode = preferredMode === 'pdf' && !isPdf ? 'raw' : preferredMode

  useEffect(() => {
    const storedMode = getStoredOriginalPreviewMode()
    const nextMode = storedMode ?? (isPdf ? 'pdf' : 'raw')
    setPreferredMode(nextMode)
    if (storedMode === null) writeClientStorage(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, nextMode)
  }, [isPdf])

  function selectPreviewMode(mode: OriginalPreviewMode) {
    setPreferredMode(mode)
    writeClientStorage(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, mode)
  }

  const serverTextInfo = useMemo(() => {
    const raw = previewData?.original_text
    const cleanedFromApi = previewData?.original_text_cleaned

    if (typeof raw !== 'string') {
      return {
        displayText: typeof cleanedFromApi === 'string' ? cleanedFromApi : null,
        indexMapper: null,
      }
    }
    const cleanedText = stripPositionTags(raw)
    const displayText = typeof cleanedFromApi === 'string' ? cleanedFromApi : cleanedText
    if (displayText !== cleanedText) return { displayText, indexMapper: null }

    const ranges = findPositionTagRanges(raw)
    const converter = createCodePointToUtf16Converter(raw)
    const removeTags = createPositionTagIndexMapper(raw, ranges)
    return {
      displayText,
      indexMapper: (offset: number) => {
        const utf16 = converter.toUtf16(offset)
        return utf16 === undefined ? undefined : removeTags(utf16)
      },
    }
  }, [previewData?.original_text, previewData?.original_text_cleaned])

  const canLoadFromFile = useMemo(() => canReadFileAsText(sourceFile), [sourceFile])
  const effectiveOriginalText = serverTextInfo.displayText ?? localOriginalText
  const originalTextSource = (() => {
    if (serverTextInfo.displayText !== null) return 'server'
    return localOriginalText === null ? null : 'local'
  })()

  useLayoutEffect(() => {
    setLocalRead(null)
    setForceFullHighlight(false)
    return () => {
      localReadRequestRef.current = null
    }
  }, [sourceFile])

  const readLocalOriginal = useCallback(async () => {
    if (sourceFile === null || localReadRequestRef.current !== null) return
    const request = { file: sourceFile }
    localReadRequestRef.current = request
    setLocalRead({ file: sourceFile, status: 'loading' })

    try {
      const text = await request.file.text()
      if (localReadRequestRef.current !== request) return
      setLocalRead({ file: request.file, status: 'ready', text })
    } catch (error: unknown) {
      if (localReadRequestRef.current !== request) return
      setLocalRead({
        file: request.file,
        status: 'failed',
        message: getErrorMessage(error, t('originalPreview.errors.readLocalFailed')),
      })
    } finally {
      if (localReadRequestRef.current === request) localReadRequestRef.current = null
    }
  }, [sourceFile, t])

  useEffect(() => {
    if (previewData === null || serverTextInfo.displayText !== null || currentRead !== null) return
    if (canLoadFromFile && sourceFile !== null && sourceFile.size <= AUTO_LOAD_TEXT_MAX_BYTES) {
      void readLocalOriginal()
    }
  }, [canLoadFromFile, currentRead, sourceFile, previewData, readLocalOriginal, serverTextInfo.displayText])

  const displayChunks = useMemo(() => {
    if (previewData === null || serverTextInfo.indexMapper === null) return []
    return projectChunkTextPositions(previewData.chunks, serverTextInfo.indexMapper)
  }, [previewData, serverTextInfo.indexMapper])

  const displayActiveChunkIndex = useMemo(() => {
    if (activeChunkIndex === null) return null
    const source = previewData?.chunks[activeChunkIndex]
    if (source === undefined) return null
    const index = displayChunks.findIndex((chunk) => chunk.index === source.index)
    return index < 0 ? null : index
  }, [activeChunkIndex, displayChunks, previewData])

  const selectDisplayChunk = useCallback(
    (chunkIndex: number) => {
      if (previewData === null) return
      const index = previewData.chunks.findIndex((chunk) => chunk.index === chunkIndex)
      if (index >= 0) setSelectedChunkIndex(index)
    },
    [previewData, setSelectedChunkIndex],
  )

  const highlightModel = useMemo(() => {
    if (effectiveOriginalText === null || displayActiveChunkIndex === null) return null
    const chunk = displayChunks[displayActiveChunkIndex]

    const text = effectiveOriginalText
    const activeStart = chunk.start_index
    const activeEnd = chunk.end_index
    if (activeStart >= text.length) return null
    const safeActiveEnd = Math.min(activeEnd, text.length)
    if (safeActiveEnd <= activeStart) return null

    const parentRange = getChunkParentRange(chunk, displayChunks)
    const baseStart = parentRange === null ? activeStart : parentRange.start
    const baseEnd = parentRange === null ? safeActiveEnd : parentRange.end

    // Avoid rendering giant before/after strings for large texts: default to a windowed excerpt.
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
        parentRange,
      }
    }

    const { start: excerptStart, end: excerptEnd } = expandTextRangeToCharacters(
      text,
      Math.max(0, baseStart - CONTEXT_CHARS),
      Math.min(text.length, baseEnd + CONTEXT_CHARS),
    )
    return {
      text,
      excerptStart,
      excerptEnd,
      prefixOmitted: excerptStart > 0,
      suffixOmitted: excerptEnd < text.length,
      activeStart,
      activeEnd: safeActiveEnd,
      parentRange,
    }
  }, [displayActiveChunkIndex, displayChunks, effectiveOriginalText, forceFullHighlight])

  const tocHeadings = useMemo(() => {
    if (previewMode !== 'rendered' || effectiveOriginalText === null) return []
    // Assign every anchor before filtering so repeated headings match the rendered source.
    return extractMarkdownHeadings(effectiveOriginalText).filter((heading) => heading.level <= 4)
  }, [effectiveOriginalText, previewMode])
  const readingRange = useMemo(
    () => (highlightModel ? { start: highlightModel.activeStart, end: highlightModel.activeEnd } : null),
    [highlightModel],
  )

  useEffect(() => {
    if (activeChunkIndex === null) return
    if (previewMode !== 'raw' && previewMode !== 'rendered') return
    const container = scrollRef.current
    if (!container) return
    const prefersReducedMotion = globalThis.window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
    const locate = () => {
      const target =
        previewMode === 'raw'
          ? highlightRef.current
          : sourceBodyRef.current?.querySelector<HTMLElement>('[data-source-selection-start]')
      if (!target || !container.clientHeight) return
      const top = container.scrollTop + target.getBoundingClientRect().top - container.getBoundingClientRect().top - 18
      container.scrollTo({ top: Math.max(0, top), behavior: prefersReducedMotion ? 'auto' : 'smooth' })
    }
    locate()
    // The mobile source pane stays mounted while hidden. Locate again when it becomes visible.
    const observer = new ResizeObserver(locate)
    observer.observe(container)
    return () => observer.disconnect()
  }, [activeChunkIndex, previewMode, readingRange])

  return (
    <div className={styles.pane}>
      <div data-original-preview-header data-original-preview-health-strip className={styles.paneHead}>
        <FileText />
        <span
          title={
            activeChunkMeta
              ? `${activeChunkMeta.label} · 位置 ${activeChunkMeta.range}${activeChunkMeta.page == null ? '' : ` · 第 ${activeChunkMeta.page} 页`}`
              : originalTextSource === 'local'
                ? '本地文档原文'
                : '解析原文'
          }
        >
          {previewMode === 'pdf' ? t('originalPreview.titlePdf') : '文档原文'}
        </span>
        {previewData && <span className={styles.metadata}>{previewData.total_characters.toLocaleString()} 字符</span>}
        {activeChunkMeta && <span className={styles.metadata}>位置 {activeChunkMeta.range}</span>}
        {previewData && <CoverageStats stats={previewData.stats} />}
        <div className={styles.sourceModes} role="group" aria-label="原文显示方式">
          <Button
            variant="ghost"
            aria-pressed={previewMode === 'raw'}
            onClick={() => selectPreviewMode('raw')}
            disabled={effectiveOriginalText === null}
          >
            源码
          </Button>
          <Button
            variant="ghost"
            aria-pressed={previewMode === 'rendered'}
            onClick={() => selectPreviewMode('rendered')}
            disabled={effectiveOriginalText === null}
          >
            阅读
          </Button>
          <Button
            variant="ghost"
            aria-pressed={previewMode === 'editor'}
            onClick={() => selectPreviewMode('editor')}
            disabled={effectiveOriginalText === null}
            title={t('originalPreview.tabs.editorTitle')}
          >
            编辑器
          </Button>
          {isPdf && (
            <Button
              variant="ghost"
              aria-pressed={previewMode === 'pdf'}
              onClick={() => selectPreviewMode('pdf')}
              disabled={!previewData || !sourceFile}
            >
              PDF
            </Button>
          )}
        </div>
      </div>
      {previewData && (
        <div className={styles.locationMeta}>
          {previewData.original_text_truncated && (
            <span
              className="text-warning"
              title={t('originalPreview.badges.originalTooLargeTitle', {
                limit: (previewData.original_text_max_chars ?? 100000).toLocaleString(),
              })}
            >
              <AlertCircle className="mr-1 inline size-3.5" />
              原文已截断
            </span>
          )}
          {effectiveOriginalText === null && <span className="text-warning">当前预览未返回原文</span>}
          {effectiveOriginalText !== null && serverTextInfo.indexMapper === null && previewData.chunks.length > 0 ? (
            <span className="text-warning">当前原文缺少可核对的解析位置</span>
          ) : null}
          {tocHeadings.length > 0 && (
            <details>
              <summary className="cursor-pointer">章节目录</summary>
              <DeferredMarkdownToc headings={tocHeadings} />
            </details>
          )}
          {previewMode === 'raw' && highlightModel !== null && highlightModel.text.length > EXCERPT_THRESHOLD && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-[13px]"
              onClick={() => setForceFullHighlight((value) => !value)}
            >
              {forceFullHighlight ? t('originalPreview.toggle.windowed') : t('originalPreview.toggle.full')}
            </Button>
          )}
        </div>
      )}
      <div
        ref={scrollRef}
        data-page-scroll-container="true"
        className={cn(styles.originalScroll, (previewMode === 'editor' || previewMode === 'pdf') && 'overflow-hidden')}
      >
        <div
          ref={sourceBodyRef}
          className={cn(styles.originalBody, previewMode === 'editor' || previewMode === 'pdf' ? 'h-full' : null)}
        >
          {(() => {
            if (previewData) {
              if (previewMode === 'pdf') {
                return (
                  <div className="mx-auto h-full w-full max-w-6xl">
                    <PdfPreview file={sourceFile} preview={previewData} />
                  </div>
                )
              }
              return effectiveOriginalText !== null ? (
                (() => {
                  if (effectiveOriginalText.length === 0) return <p role="status">原文为空</p>
                  if (previewMode === 'rendered') {
                    return (
                      <div className="w-full">
                        <div className="min-w-0 flex-1">
                          <div className="prose prose-slate dark:prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-a:text-primary prose-code:text-primary prose-code:bg-primary/10 dark:prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-muted">
                            <MarkdownRenderer markdown={effectiveOriginalText} sourceRange={readingRange} />
                          </div>
                        </div>
                      </div>
                    )
                  } else if (previewMode === 'editor') {
                    return (
                      <div className="mx-auto w-full max-w-6xl h-full">
                        <OriginalPreviewMonaco
                          text={effectiveOriginalText}
                          chunks={displayChunks}
                          activeChunkIndex={displayActiveChunkIndex}
                          chunkOverrides={chunkOverrides}
                          onSelectChunkIndex={selectDisplayChunk}
                        />
                        <p className="mt-3 text-[11px] text-muted-foreground">
                          {t('originalPreview.hints.editorMode')}
                        </p>
                      </div>
                    )
                  } else {
                    return (
                      <div className={styles.rawDocument}>
                        {activeChunkIndex !== null && highlightModel
                          ? (() => {
                              const excerpt = highlightModel.text.slice(
                                highlightModel.excerptStart,
                                highlightModel.excerptEnd,
                              )
                              const toExcerptOffset = (offset: number) => offset - highlightModel.excerptStart
                              const sliceExcerpt = (from: number, to: number) =>
                                excerpt.slice(Math.max(0, toExcerptOffset(from)), Math.max(0, toExcerptOffset(to)))
                              const { parentRange } = highlightModel
                              if (parentRange === null) {
                                return (
                                  <>
                                    {highlightModel.prefixOmitted ? (
                                      <span className="text-muted-foreground">…</span>
                                    ) : null}
                                    <span className="text-muted-foreground">
                                      {sliceExcerpt(highlightModel.excerptStart, highlightModel.activeStart)}
                                    </span>
                                    <mark ref={highlightRef} className={styles.sourceSelection}>
                                      {sliceExcerpt(highlightModel.activeStart, highlightModel.activeEnd)}
                                    </mark>
                                    <span className="text-muted-foreground">
                                      {sliceExcerpt(highlightModel.activeEnd, highlightModel.excerptEnd)}
                                    </span>
                                    {highlightModel.suffixOmitted ? (
                                      <span className="text-muted-foreground">…</span>
                                    ) : null}
                                  </>
                                )
                              }
                              return (
                                <>
                                  {highlightModel.prefixOmitted ? (
                                    <span className="text-muted-foreground">…</span>
                                  ) : null}
                                  <span className="text-muted-foreground">
                                    {sliceExcerpt(highlightModel.excerptStart, parentRange.start)}
                                  </span>

                                  <mark className={styles.sourceSelection}>
                                    {sliceExcerpt(parentRange.start, highlightModel.activeStart)}
                                    <mark ref={highlightRef} className={styles.sourceSelection}>
                                      {sliceExcerpt(highlightModel.activeStart, highlightModel.activeEnd)}
                                    </mark>
                                    {sliceExcerpt(highlightModel.activeEnd, parentRange.end)}
                                  </mark>

                                  <span className="text-muted-foreground">
                                    {sliceExcerpt(parentRange.end, highlightModel.excerptEnd)}
                                  </span>
                                  {highlightModel.suffixOmitted ? (
                                    <span className="text-muted-foreground">…</span>
                                  ) : null}
                                </>
                              )
                            })()
                          : effectiveOriginalText}
                      </div>
                    )
                  }
                })()
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
                  <FileText appearance="color" className="size-12" />
                  <p className="text-xs">
                    {previewData.original_text_truncated
                      ? t('originalPreview.empty.truncated')
                      : t('originalPreview.empty.missing')}
                  </p>
                  <p className="text-xs text-muted-foreground max-w-[480px] text-center leading-relaxed">
                    {(() => {
                      const limit = previewData.original_text_max_chars ?? 100000
                      if (previewData.original_text_truncated) {
                        return t('originalPreview.empty.truncatedDetail', {
                          limit: limit.toLocaleString(),
                          total: previewData.total_characters.toLocaleString(),
                        })
                      }
                      return t('originalPreview.empty.missingDetail', {
                        total: previewData.total_characters.toLocaleString(),
                      })
                    })()}
                    {t('originalPreview.empty.fallbackHint')}
                  </p>

                  {currentRead?.status === 'failed' ? (
                    <p className="text-[11px] text-destructive bg-destructive/10 border border-destructive/25 px-2 py-1 rounded-lg">
                      {currentRead.message}
                    </p>
                  ) : null}

                  {canLoadFromFile && sourceFile ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 px-3 text-[11px] mt-2"
                      disabled={currentRead?.status === 'loading'}
                      onClick={readLocalOriginal}
                    >
                      {currentRead?.status === 'loading'
                        ? t('originalPreview.empty.readLocalLoading')
                        : t('originalPreview.empty.readLocal')}
                    </Button>
                  ) : (
                    <p className="text-[11px] text-muted-foreground">{t('originalPreview.empty.unsupportedFile')}</p>
                  )}
                </div>
              )
            } else if (isLoading) {
              return (
                <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
                  <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none opacity-20" />
                  <p className="text-xs">{t('originalPreview.states.loading')}</p>
                </div>
              )
            } else if (error) {
              return (
                <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
                  <AlertCircle className="w-10 h-10 opacity-20" />
                  <p className="text-xs text-muted-foreground">{t('originalPreview.states.loadFailed')}</p>
                  <p className="text-xs text-muted-foreground max-w-[360px] text-center break-words line-clamp-3">
                    {error}
                  </p>
                </div>
              )
            } else {
              return (
                <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
                  <FileText appearance="color" className="size-12" />
                  <p className="text-xs">{t('originalPreview.states.waiting')}</p>
                </div>
              )
            }
          })()}
        </div>
      </div>
    </div>
  )
}
