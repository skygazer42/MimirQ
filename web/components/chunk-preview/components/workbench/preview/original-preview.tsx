/**
 * OriginalPreview - 原文预览
 */
'use client'

import { useState, useEffect, useRef, useMemo } from 'react'
import { FileText, Loader2, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { extractMarkdownHeadings } from '@/lib/markdown'

const AUTO_LOAD_TEXT_MAX_BYTES = 800_000

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

export function OriginalPreview() {
  const { previewData, hoveredChunkIndex, selectedChunkIndex, currentFile, isLoading, error } = useChunkPreview()
  const [previewMode, setPreviewMode] = useState<'raw' | 'rendered'>('raw')
  const [localOriginalText, setLocalOriginalText] = useState<string | null>(null)
  const [localLoading, setLocalLoading] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const highlightRef = useRef<HTMLElement | null>(null)

  const activeChunkIndex = hoveredChunkIndex ?? selectedChunkIndex
  const activeChunkMeta = useMemo(() => {
    if (activeChunkIndex == null) return null
    const chunk = previewData?.chunks?.[activeChunkIndex]
    if (!chunk) return null
    return {
      label: `#${activeChunkIndex + 1}`,
      range: `${chunk.start_index}-${chunk.end_index}`,
      page: chunk.page_number,
    }
  }, [activeChunkIndex, previewData?.chunks])

  const canLoadFromFile = useMemo(() => canReadFileAsText(currentFile), [currentFile])
  const effectiveOriginalText = previewData?.original_text ?? localOriginalText ?? null
  const originalTextSource = previewData?.original_text ? 'server' : localOriginalText ? 'local' : null

  useEffect(() => {
    setLocalOriginalText(null)
    setLocalError(null)
    setLocalLoading(false)
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
      .catch((err: any) => {
        if (!alive) return
        setLocalError((err?.message as string) || '从本地文件读取失败')
      })
      .finally(() => {
        if (!alive) return
        setLocalLoading(false)
      })

    return () => {
      alive = false
    }
  }, [canLoadFromFile, currentFile, localLoading, localOriginalText, previewData])

  const getHighlightedText = useMemo(() => {
    if (!effectiveOriginalText || activeChunkIndex === null) return null

    const chunk = previewData?.chunks?.[activeChunkIndex]
    if (!chunk) return null

    const text = effectiveOriginalText
    const start = Math.max(0, Number(chunk.start_index) || 0)
    const end = Math.max(start, Number(chunk.end_index) || start)
    if (start >= text.length) return null
    const safeEnd = Math.min(end, text.length)
    if (safeEnd <= start) return null
    return {
      before: text.slice(0, start),
      highlighted: text.slice(start, safeEnd),
      after: text.slice(safeEnd),
    }
  }, [activeChunkIndex, effectiveOriginalText, previewData?.chunks])

  const tocEnabled = useMemo(
    () => extractMarkdownHeadings(effectiveOriginalText || '', { maxDepth: 4 }).length > 0,
    [effectiveOriginalText]
  )

  useEffect(() => {
    if (activeChunkIndex === null) return
    if (previewMode !== 'raw') return
    const el = highlightRef.current
    if (!el) return
    const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
    el.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'center' })
  }, [activeChunkIndex, previewMode])

  return (
    <div className="flex-1 flex flex-col min-w-0 border-b lg:border-b-0 lg:border-r border-border/60 bg-card/85 backdrop-blur">
      <div className="h-10 border-b border-border/60 bg-card/80 flex items-center justify-between px-4 shrink-0 backdrop-blur">
        <span className="text-xs font-semibold text-primary flex items-center gap-2">
          <FileText className="w-3.5 h-3.5 text-primary" />
          原文内容
        </span>
        <div className="flex items-center gap-2">
          {previewData && (
            <div className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground">
              {activeChunkMeta ? (
                <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                  {activeChunkMeta.label}
                  {activeChunkMeta.page != null ? ` P.${activeChunkMeta.page}` : ''}
                  {' '}
                  <span className="text-muted-foreground">{activeChunkMeta.range}</span>
                </span>
              ) : null}
              <span>{(effectiveOriginalText?.length ?? previewData.total_characters).toLocaleString()} chars</span>
              {originalTextSource ? (
                <span className="px-1.5 py-0.5 rounded bg-muted border border-border/60">
                  {originalTextSource === 'server' ? 'server' : 'local'}
                </span>
              ) : null}
              {!previewData.original_text ? (() => {
                const limit = previewData.original_text_max_chars ?? 100000
                const truncated = Boolean(previewData.original_text_truncated)
                return (
                  <span
                    className="px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/25"
                    title={truncated ? `原文超过 ${limit.toLocaleString()} chars，后端已省略返回` : '原文未返回'}
                  >
                    {truncated ? '原文过大，已省略' : '原文未返回'}
                  </span>
                )
              })() : null}
            </div>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-[11px]"
            onClick={() => setPreviewMode((m) => (m === 'raw' ? 'rendered' : 'raw'))}
            disabled={!effectiveOriginalText}
          >
            {previewMode === 'raw' ? '预览' : '源码'}
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-4 scroll-smooth">
        <div className="min-h-full rounded-2xl border border-border/60 bg-card/70 p-6 shadow-sm backdrop-blur ring-1 ring-border/40">
          {previewData ? (
            effectiveOriginalText ? (
              previewMode === 'rendered' ? (
                <div className="mx-auto w-full max-w-6xl flex gap-8">
                  <div className="min-w-0 flex-1">
                    <div className="prose prose-slate dark:prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-a:text-primary prose-code:text-primary prose-code:bg-primary/10 dark:prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-muted">
                      <MarkdownRenderer markdown={effectiveOriginalText} autoScrollToHash />
                    </div>
                    <p className="mt-4 text-[11px] text-muted-foreground">
                      提示：渲染模式下不支持高亮显示，请切换至源码模式查看切片对应位置
                    </p>
                  </div>
                  {tocEnabled && (
                    <aside className="hidden xl:block w-64 shrink-0">
                      <div className="sticky top-6 max-h-[calc(100vh-220px)] overflow-y-auto overscroll-contain no-scrollbar rounded-xl border border-border/60 bg-card p-3">
                        <MarkdownToc markdown={effectiveOriginalText} />
                      </div>
                    </aside>
                  )}
                </div>
              ) : (
                <div className="font-mono text-sm leading-relaxed text-muted-foreground whitespace-pre-wrap max-w-3xl mx-auto">
                  {activeChunkIndex !== null && getHighlightedText ? (
                    <>
                      <span className="opacity-40">{getHighlightedText.before}</span>
                      <mark
                        ref={highlightRef}
                        className="bg-primary/15 text-foreground rounded px-0.5 py-0.5 mx-0.5 shadow-sm font-medium"
                      >
                        {getHighlightedText.highlighted}
                      </mark>
                      <span className="opacity-40">{getHighlightedText.after}</span>
                    </>
                  ) : (
                    effectiveOriginalText
                  )}
                </div>
              )
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
                <FileText className="w-12 h-12 opacity-10" />
                <p className="text-xs">{previewData.original_text_truncated ? '原文已省略' : '原文未返回'}</p>
                <p className="text-xs text-muted-foreground max-w-[480px] text-center leading-relaxed">
                  {(() => {
                    const limit = previewData.original_text_max_chars ?? 100000
                    if (previewData.original_text_truncated) {
                      return `原文超过 ${limit.toLocaleString()} chars（当前 ${previewData.total_characters.toLocaleString()} chars），后端已省略返回以避免传输过大。`
                    }
                    return `原文内容较大（${previewData.total_characters.toLocaleString()} chars）时，后端可能会省略原文以避免传输过大。`
                  })()}
                  你仍可使用右侧切片列表进行检查与入库。
                </p>

                {localError ? (
                  <p className="text-[10px] text-destructive bg-destructive/10 border border-destructive/25 px-2 py-1 rounded-lg">
                    {localError}
                  </p>
                ) : null}

                {canLoadFromFile && currentFile ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 px-3 text-[11px] mt-2"
                    disabled={localLoading}
                    onClick={async () => {
                      try {
                        setLocalLoading(true)
                        setLocalError(null)
                        const text = await currentFile.text()
                        setLocalOriginalText(text)
                      } catch (err: any) {
                        setLocalError((err?.message as string) || '从本地文件读取失败')
                      } finally {
                        setLocalLoading(false)
                      }
                    }}
                  >
                    {localLoading ? '正在读取本地原文...' : '从本地文件读取原文'}
                  </Button>
                ) : (
                  <p className="text-[10px] text-muted-foreground">当前文件格式不支持在浏览器侧读取原文。</p>
                )}
              </div>
            )
          ) : isLoading ? (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
              <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none opacity-20" />
              <p className="text-xs">加载中...</p>
            </div>
          ) : error ? (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
              <AlertCircle className="w-10 h-10 opacity-20" />
              <p className="text-xs text-muted-foreground">加载失败</p>
              <p className="text-xs text-muted-foreground max-w-[360px] text-center break-words line-clamp-3">{error}</p>
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
              <FileText className="w-12 h-12 opacity-10" />
              <p className="text-xs">等待预览</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
