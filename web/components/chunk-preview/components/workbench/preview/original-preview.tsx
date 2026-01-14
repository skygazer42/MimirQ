/**
 * OriginalPreview - ?????????
 */
'use client'

import { useState, useEffect, useRef, useMemo } from 'react'
import { FileText, Loader2, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { extractMarkdownHeadings } from '@/lib/markdown'

export function OriginalPreview() {
  const { previewData, hoveredChunkIndex, isLoading, error } = useChunkPreview()
  const [previewMode, setPreviewMode] = useState<'raw' | 'rendered'>('raw')
  const highlightRef = useRef<HTMLElement | null>(null)

  const getHighlightedText = useMemo(() => {
    if (!previewData?.original_text || hoveredChunkIndex === null) return null

    const chunk = previewData.chunks[hoveredChunkIndex]
    if (!chunk) return null

    const text = previewData.original_text
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
  }, [previewData, hoveredChunkIndex])

  const tocEnabled = useMemo(
    () => extractMarkdownHeadings(previewData?.original_text || '', { maxDepth: 4 }).length > 0,
    [previewData?.original_text]
  )

  useEffect(() => {
    if (hoveredChunkIndex === null) return
    if (previewMode !== 'raw') return
    const el = highlightRef.current
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [hoveredChunkIndex, previewMode])

  return (
    <div className="flex-1 flex flex-col min-w-0 border-r border-slate-200/70 bg-white/85 backdrop-blur shadow-[inset_-1px_0_0_rgba(255,255,255,0.6)]">
      <div className="h-10 border-b border-slate-200/70 bg-white/80 flex items-center justify-between px-4 shrink-0 backdrop-blur">
        <span className="text-xs font-semibold text-sky-700 flex items-center gap-2">
          <FileText className="w-3.5 h-3.5 text-sky-700" />
          原文内容
        </span>
        <div className="flex items-center gap-2">
          {previewData && (
            <span className="text-[10px] font-mono text-slate-400">
              {previewData.total_characters.toLocaleString()} chars
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-[11px]"
            onClick={() => setPreviewMode((m) => (m === 'raw' ? 'rendered' : 'raw'))}
            disabled={!previewData?.original_text}
          >
            {previewMode === 'raw' ? '预览' : '源码'}
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 scroll-smooth">
        <div className="min-h-full rounded-2xl border border-slate-200/70 bg-white/70 p-6 shadow-sm backdrop-blur ring-1 ring-white/60">
          {previewData ? (
            previewData.original_text ? (
              previewMode === 'rendered' ? (
                <div className="mx-auto w-full max-w-6xl flex gap-8">
                  <div className="min-w-0 flex-1">
                    <div className="prose prose-slate max-w-none prose-headings:text-slate-900 prose-p:text-slate-700 prose-a:text-sky-700 prose-code:text-sky-700 prose-code:bg-sky-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-slate-900">
                      <MarkdownRenderer markdown={previewData.original_text} autoScrollToHash />
                    </div>
                    <p className="mt-4 text-[11px] text-slate-400">
                      提示：渲染模式下不支持高亮显示，请切换至源码模式查看切片对应位置
                    </p>
                  </div>
                  {tocEnabled && (
                    <aside className="hidden xl:block w-64 shrink-0">
                      <div className="sticky top-6 max-h-[calc(100vh-220px)] overflow-y-auto rounded-xl border border-slate-200/70 bg-white p-3">
                        <MarkdownToc markdown={previewData.original_text} />
                      </div>
                    </aside>
                  )}
                </div>
              ) : (
                <div className="font-mono text-sm leading-relaxed text-slate-600 whitespace-pre-wrap max-w-3xl mx-auto">
                  {hoveredChunkIndex !== null && getHighlightedText ? (
                    <>
                      <span className="opacity-40">{getHighlightedText.before}</span>
                      <mark
                        ref={highlightRef}
                        className="bg-sky-200 text-slate-900 rounded px-0.5 py-0.5 mx-0.5 shadow-sm font-medium"
                      >
                        {getHighlightedText.highlighted}
                      </mark>
                      <span className="opacity-40">{getHighlightedText.after}</span>
                    </>
                  ) : (
                    previewData.original_text
                  )}
                </div>
              )
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 gap-2">
                <FileText className="w-12 h-12 opacity-10" />
                <p className="text-xs">暂无原文内容</p>
                <p className="text-xs text-slate-400">请先生成预览</p>
              </div>
            )
          ) : isLoading ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-400 gap-2">
              <Loader2 className="w-8 h-8 animate-spin opacity-20" />
              <p className="text-xs">加载中...</p>
            </div>
          ) : error ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-400 gap-2">
              <AlertCircle className="w-10 h-10 opacity-20" />
              <p className="text-xs text-slate-500">加载失败</p>
              <p className="text-xs text-slate-400 max-w-[360px] text-center break-words line-clamp-3">{error}</p>
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-slate-300 gap-2">
              <FileText className="w-12 h-12 opacity-10" />
              <p className="text-xs">等待预览</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
