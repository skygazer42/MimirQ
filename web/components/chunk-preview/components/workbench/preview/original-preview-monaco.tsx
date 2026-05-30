/**
 * OriginalPreviewMonaco - Large-text viewer with stable highlight + overview markers.
 */
'use client'

import loader from '@monaco-editor/loader'
import dynamic from 'next/dynamic'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { useTheme } from 'next-themes'
import { PageLoading } from '@/components/ui/page-loading'
import { getChunkMetadata, getChunkRole } from '@/components/chunk-preview/utils/metadata'
import type { ChunkPreviewItem } from '@/types'

loader.config({
  paths: {
    vs: '/monaco/vs',
  },
})

function OriginalPreviewMonacoLoading() {
  const t = useTranslations('ChunkPreview')

  return (
    <PageLoading
      message={t('originalPreview.monaco.loadingMessage')}
      srMessage={t('originalPreview.monaco.loadingSrMessage')}
      className="h-full min-h-[520px] rounded-xl border border-border/60 bg-background"
    />
  )
}

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => <OriginalPreviewMonacoLoading />,
})

const MAX_OVERVIEW_MARKERS = 4000

type MonacoRangeLike = {
  startLineNumber: number
  startColumn: number
  endLineNumber: number
  endColumn: number
}

type MonacoDecoration = {
  range: MonacoRangeLike
  options: {
    overviewRuler?: { color: string; position: number }
    inlineClassName?: string
  }
}

type MonacoPosition = {
  lineNumber: number
  column: number
}

type MonacoMouseEvent = {
  event: { leftButton: boolean }
  target: { position: MonacoPosition | null }
}

type MonacoScrollEvent = {
  scrollTop: number
}

type MonacoDisposable = {
  dispose: () => void
}

type MonacoModel = {
  getOffsetAt: (position: MonacoPosition) => number
}

type MonacoEditorInstance = {
  deltaDecorations: (oldDecorations: string[], newDecorations: MonacoDecoration[]) => string[]
  revealRangeInCenter: (range: MonacoRangeLike, scrollType?: number) => void
  onMouseDown: (listener: (event: MonacoMouseEvent) => void) => MonacoDisposable
  onDidScrollChange: (listener: (event: MonacoScrollEvent) => void) => MonacoDisposable
  getModel: () => MonacoModel | null
  getScrollTop: () => number
  setScrollTop: (scrollTop: number) => void
}

type MonacoModule = {
  Range: new (startLineNumber: number, startColumn: number, endLineNumber: number, endColumn: number) => MonacoRangeLike
  editor: {
    OverviewRulerLane: { Right: number }
    ScrollType: { Smooth: number }
  }
}

function buildLineStarts(text: string) {
  const starts = [0]
  for (let i = 0; i < text.length; i++) {
    if (text.codePointAt(i) === 10) starts.push(i + 1) // '\n'
  }
  return starts
}

function clampOffset(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function offsetToPosition(lineStarts: number[], offset: number) {
  // lineStarts is sorted; find last start <= offset.
  let lo = 0
  let hi = lineStarts.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const v = lineStarts[mid]
    if (v === offset) {
      return { lineNumber: mid + 1, column: 1 }
    }
    if (v < offset) lo = mid + 1
    else hi = mid - 1
  }
  const lineIndex = Math.max(0, lo - 1)
  const lineStart = lineStarts[lineIndex] ?? 0
  return {
    lineNumber: lineIndex + 1,
    column: offset - lineStart + 1,
  }
}

function pickBestChunkAtOffset(chunks: ChunkPreviewItem[], offset: number) {
  let best: ChunkPreviewItem | null = null
  let bestLen = Number.POSITIVE_INFINITY
  for (const chunk of chunks) {
    const start = Number(chunk.start_index) || 0
    const end = Number(chunk.end_index) || start
    if (offset < start || offset >= end) continue
    const len = Math.max(0, end - start)
    if (len < bestLen) {
      best = chunk
      bestLen = len
    }
  }
  return best
}

function resolveParentRange(chunk: ChunkPreviewItem, chunks: ChunkPreviewItem[]) {
  const meta = getChunkMetadata(chunk)
  const role = getChunkRole(chunk) ?? ''
  if (role !== 'child') return null

  const parentStartRaw = meta.parent_start_char ?? meta.parent_start_index ?? meta.parent_start
  const parentEndRaw = meta.parent_end_char ?? meta.parent_end_index ?? meta.parent_end
  const parentStart = parentStartRaw == null ? Number.NaN : Number(parentStartRaw)
  const parentEnd = parentEndRaw == null ? Number.NaN : Number(parentEndRaw)
  if (Number.isFinite(parentStart) && Number.isFinite(parentEnd) && parentEnd > parentStart) {
    return { start: parentStart, end: parentEnd }
  }

  const parentId = meta.parent_id ?? meta.parent_node_id
  if (!parentId) return null
  const parent = chunks.find((it) => {
    const parentMeta = getChunkMetadata(it)
    return getChunkRole(it) === 'parent' && (parentMeta.parent_id === parentId || parentMeta.node_id === parentId || parentMeta.id === parentId)
  })
  if (!parent) return null
  const start = Number(parent.start_index) || 0
  const end = Number(parent.end_index) || start
  if (end <= start) return null
  return { start, end }
}

export function OriginalPreviewMonaco(props: Readonly<{
  text: string
  chunks: ChunkPreviewItem[]
  activeChunkIndex: number | null
  activeRange?: { start: number; end: number } | null
  highlightParentRange?: boolean
  initialScrollTop?: number
  chunkOverrides?: Record<number, { disabled?: boolean }>
  onScrollTopChange?: (scrollTop: number) => void
  onSelectChunkIndex?: (index: number) => void
}>) {
  const {
    text,
    chunks,
    activeChunkIndex,
    activeRange,
    highlightParentRange = true,
    initialScrollTop,
    chunkOverrides,
    onScrollTopChange,
    onSelectChunkIndex,
  } = props

  const editorRef = useRef<MonacoEditorInstance | null>(null)
  const monacoRef = useRef<MonacoModule | null>(null)
  const overviewDecorationIdsRef = useRef<string[]>([])
  const activeDecorationIdsRef = useRef<string[]>([])
  const clickDisposableRef = useRef<MonacoDisposable | null>(null)
  const scrollDisposableRef = useRef<MonacoDisposable | null>(null)

  const lineStarts = useMemo(() => buildLineStarts(text), [text])
  const { theme, systemTheme } = useTheme()
  const resolvedTheme = theme === 'system' ? systemTheme : theme
  const monacoTheme = resolvedTheme === 'dark' ? 'vs-dark' : 'vs'

  const applyOverviewDecorations = useCallback(() => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    if (!editor || !monaco) return
    if (!Array.isArray(chunks) || chunks.length === 0) {
      overviewDecorationIdsRef.current = editor.deltaDecorations(overviewDecorationIdsRef.current, [])
      return
    }
    if (chunks.length > MAX_OVERVIEW_MARKERS) {
      overviewDecorationIdsRef.current = editor.deltaDecorations(overviewDecorationIdsRef.current, [])
      return
    }

    const textLen = text.length
    const decorations = chunks.map((chunk) => {
      const start = clampOffset(Number(chunk.start_index) || 0, 0, textLen)
      const end = clampOffset(Math.max(start, Number(chunk.end_index) || start), 0, textLen)
      const startPos = offsetToPosition(lineStarts, start)
      const endPos = offsetToPosition(lineStarts, end)
      const meta = (chunk.metadata || {})
      const role = String(meta.chunk_role || '')
      const isChild = role === 'child'
      const disabled = Boolean(chunkOverrides?.[chunk.index]?.disabled)

      const color = (() => {
    if (disabled) {
        return 'rgba(148,163,184,0.35)';
    }
    else if (isChild) {
            return 'rgba(59,130,246,0.65)' // child highlight
            ;
        }
        else {
            return 'rgba(148,163,184,0.45)' // parent/others
            ;
        }
})() // parent/others

      return {
        range: new monaco.Range(startPos.lineNumber, startPos.column, endPos.lineNumber, endPos.column),
        options: {
          overviewRuler: { color, position: monaco.editor.OverviewRulerLane.Right },
        },
      }
    })

    overviewDecorationIdsRef.current = editor.deltaDecorations(overviewDecorationIdsRef.current, decorations)
  }, [chunkOverrides, chunks, lineStarts, text.length])

  const applyActiveDecorations = useCallback(() => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    if (!editor || !monaco) return

    const textLen = text.length
    const chunk = activeChunkIndex == null ? null : chunks[activeChunkIndex]
    const explicitStartRaw = activeRange?.start
    const explicitEndRaw = activeRange?.end
    const explicitStart =
      typeof explicitStartRaw === 'number' && Number.isFinite(explicitStartRaw) ? Math.trunc(explicitStartRaw) : null
    const explicitEnd =
      typeof explicitEndRaw === 'number' && Number.isFinite(explicitEndRaw) ? Math.trunc(explicitEndRaw) : null

    const explicit =
      explicitStart != null && explicitEnd != null && explicitEnd > explicitStart
        ? {
            start: clampOffset(explicitStart, 0, textLen),
            end: clampOffset(Math.max(explicitStart, explicitEnd), 0, textLen),
          }
        : null

    if (!chunk && !explicit) {
      activeDecorationIdsRef.current = editor.deltaDecorations(activeDecorationIdsRef.current, [])
      return
    }

    const activeStart = chunk ? clampOffset(Number(chunk.start_index) || 0, 0, textLen) : 0
    const activeEnd = chunk ? clampOffset(Math.max(activeStart, Number(chunk.end_index) || activeStart), 0, textLen) : 0

    const parent = highlightParentRange && chunk ? resolveParentRange(chunk, chunks) : null

    const decos: MonacoDecoration[] = []
    if (parent) {
      const parentStart = clampOffset(parent.start, 0, textLen)
      const parentEnd = clampOffset(Math.max(parentStart, parent.end), 0, textLen)
      if (parentEnd > parentStart) {
        const s = offsetToPosition(lineStarts, parentStart)
        const e = offsetToPosition(lineStarts, parentEnd)
        decos.push({
          range: new monaco.Range(s.lineNumber, s.column, e.lineNumber, e.column),
          options: {
            inlineClassName: 'mimirq-monaco-parent-highlight',
          },
        })
      }
    }

    let revealRange: MonacoRangeLike | null = null

    if (chunk && activeEnd > activeStart) {
      const s = offsetToPosition(lineStarts, activeStart)
      const e = offsetToPosition(lineStarts, activeEnd)
      const chunkRange = new monaco.Range(s.lineNumber, s.column, e.lineNumber, e.column)
      decos.push({
        range: chunkRange,
        options: {
          inlineClassName: 'mimirq-monaco-active-highlight',
        },
      })
      revealRange = chunkRange
    }

    if (explicit && explicit.end > explicit.start) {
      const s = offsetToPosition(lineStarts, explicit.start)
      const e = offsetToPosition(lineStarts, explicit.end)
      const explicitRange = new monaco.Range(s.lineNumber, s.column, e.lineNumber, e.column)
      decos.push({
        range: explicitRange,
        options: {
          inlineClassName: 'mimirq-monaco-citation-highlight',
        },
      })
      revealRange = explicitRange
    }

    activeDecorationIdsRef.current = editor.deltaDecorations(activeDecorationIdsRef.current, decos)

    try {
      if (revealRange) {
        editor.revealRangeInCenter(revealRange, monaco.editor.ScrollType.Smooth)
      }
    } catch {
      // no-op
    }
  }, [activeChunkIndex, activeRange, chunks, highlightParentRange, lineStarts, text.length])

  useEffect(() => {
    applyOverviewDecorations()
  }, [applyOverviewDecorations])

  useEffect(() => {
    applyActiveDecorations()
  }, [applyActiveDecorations])

  useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    if (activeChunkIndex != null || activeRange) return
    if (typeof initialScrollTop !== 'number' || !Number.isFinite(initialScrollTop)) return

    try {
      editor.setScrollTop(Math.max(0, initialScrollTop))
    } catch {
      // no-op
    }
  }, [activeChunkIndex, activeRange, initialScrollTop, text])

  useEffect(() => {
    return () => {
      if (clickDisposableRef.current) {
        clickDisposableRef.current.dispose()
        clickDisposableRef.current = null
      }
      if (scrollDisposableRef.current) {
        scrollDisposableRef.current.dispose()
        scrollDisposableRef.current = null
      }
    }
  }, [])

  return (
    <div className="relative h-full min-h-[520px] rounded-xl border border-border/60 overflow-hidden bg-background">
      <MonacoEditor
        height="100%"
        language="markdown"
        theme={monacoTheme}
        value={text}
        options={{
          readOnly: true,
          domReadOnly: true,
          lineNumbers: 'off',
          wordWrap: 'on',
          minimap: { enabled: false },
          scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
          scrollBeyondLastLine: false,
          renderLineHighlight: 'none',
          glyphMargin: false,
          folding: false,
          overviewRulerBorder: false,
        }}
        onMount={(editor: MonacoEditorInstance, monaco: MonacoModule) => {
          editorRef.current = editor
          monacoRef.current = monaco

          applyOverviewDecorations()
          applyActiveDecorations()

          if (typeof initialScrollTop === 'number' && Number.isFinite(initialScrollTop) && activeChunkIndex == null && !activeRange) {
            try {
              editor.setScrollTop(Math.max(0, initialScrollTop))
            } catch {
              // no-op
            }
          }

          if (onSelectChunkIndex) {
            clickDisposableRef.current?.dispose()
            clickDisposableRef.current = editor.onMouseDown((event: MonacoMouseEvent) => {
              if (!event.event.leftButton) return
              const position = event.target.position
              if (!position) return
              const model = editor.getModel()
              if (!model) return
              const offset = model.getOffsetAt(position)
              const best = pickBestChunkAtOffset(chunks, offset)
              if (!best) return
              onSelectChunkIndex(best.index)
            })
          }

          if (onScrollTopChange) {
            scrollDisposableRef.current?.dispose()
            scrollDisposableRef.current = editor.onDidScrollChange((event: MonacoScrollEvent) => {
              onScrollTopChange(typeof event.scrollTop === 'number' ? event.scrollTop : editor.getScrollTop())
            })
          }
        }}
      />

      <style jsx global>{`
        .mimirq-monaco-parent-highlight {
          background: rgba(59, 130, 246, 0.08);
        }
        .mimirq-monaco-active-highlight {
          background: rgba(59, 130, 246, 0.18);
          border-radius: 2px;
          box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.25);
        }
        .mimirq-monaco-citation-highlight {
          background: rgba(245, 158, 11, 0.22);
          border-radius: 2px;
          box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.35);
        }
      `}</style>
    </div>
  )
}
