/**
 * OriginalPreviewMonaco - Large-text viewer with stable highlight + overview markers.
 */
'use client'

import loader from '@monaco-editor/loader'
import type { Monaco } from '@monaco-editor/react'
import type { editor as MonacoEditorApi, IDisposable, IRange } from 'monaco-editor'
import dynamic from 'next/dynamic'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { useTheme } from 'next-themes'
import { PageLoading } from '@/components/ui/page-loading'
import { getChunkParentRange, getChunkRole } from '@/components/chunk-preview/utils/metadata'
import type { ChunkPreviewItem } from '@/types'
import { reportClientWarning } from '@/lib/client-logging'
import { THEME_APPEARANCE_CHANGED_EVENT } from '@/lib/theme-surface'
import styles from './original-preview-monaco.module.css'

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

/** UTF-16 bounds already projected into this viewer's text. */
type DisplayRange = Readonly<{ start: number; end: number }>

function buildLineStarts(text: string) {
  // Monaco stores a leading BOM separately from the visible first line.
  const starts = [text.charCodeAt(0) === 0xfeff ? 1 : 0]
  for (let index = 0; index < text.length; index++) {
    const charCode = text.charCodeAt(index)
    if (charCode === 13 && text.charCodeAt(index + 1) === 10) index++
    if (charCode === 13 || charCode === 10) starts.push(index + 1)
  }
  return starts
}

function offsetToPosition(lineStarts: number[], offset: number) {
  // lineStarts is sorted; find last start <= offset.
  let lo = 0
  let hi = lineStarts.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const lineStart = lineStarts[mid]
    if (lineStart === offset) {
      return { lineNumber: mid + 1, column: 1 }
    }
    if (lineStart < offset) lo = mid + 1
    else hi = mid - 1
  }
  const lineIndex = Math.max(0, lo - 1)
  const lineStart = lineStarts[lineIndex]
  return {
    lineNumber: lineIndex + 1,
    column: Math.max(1, offset - lineStart + 1),
  }
}

function pickBestChunkAtOffset(chunks: readonly ChunkPreviewItem[], offset: number) {
  let best: ChunkPreviewItem | null = null
  let bestLength = Number.POSITIVE_INFINITY
  for (const chunk of chunks) {
    const start = chunk.start_index
    const end = chunk.end_index
    if (offset < start || offset >= end) continue
    const length = end - start
    if (length < bestLength) {
      best = chunk
      bestLength = length
    }
  }
  return best
}

export function OriginalPreviewMonaco(
  props: Readonly<{
    text: string
    chunks: readonly ChunkPreviewItem[]
    activeChunkIndex: number | null
    activeRange?: DisplayRange | null
    highlightParentRange?: boolean
    initialScrollTop?: number
    chunkOverrides?: Record<number, { disabled?: boolean }>
    onScrollTopChange?: (scrollTop: number) => void
    onSelectChunkIndex?: (index: number) => void
  }>,
) {
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

  const editorRef = useRef<MonacoEditorApi.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<Monaco | null>(null)
  const overviewDecorationIdsRef = useRef<string[]>([])
  const activeDecorationIdsRef = useRef<string[]>([])
  const clickDisposableRef = useRef<IDisposable | null>(null)
  const scrollDisposableRef = useRef<IDisposable | null>(null)

  const lineStarts = useMemo(() => buildLineStarts(text), [text])
  const { theme, systemTheme } = useTheme()
  const resolvedTheme = theme === 'system' ? systemTheme : theme
  const monacoTheme = resolvedTheme === 'dark' ? 'vs-dark' : 'vs'

  const applyOverviewDecorations = useCallback(() => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    if (!editor || !monaco) return
    if (chunks.length === 0) {
      overviewDecorationIdsRef.current = editor.deltaDecorations(overviewDecorationIdsRef.current, [])
      return
    }
    if (chunks.length > MAX_OVERVIEW_MARKERS) {
      overviewDecorationIdsRef.current = editor.deltaDecorations(overviewDecorationIdsRef.current, [])
      return
    }

    const palette = getComputedStyle(document.documentElement)
    const foreground = palette.getPropertyValue('--foreground').trim()
    const mutedForeground = palette.getPropertyValue('--muted-foreground').trim()
    const decorations = chunks.map((chunk) => {
      const startPos = offsetToPosition(lineStarts, chunk.start_index)
      const endPos = offsetToPosition(lineStarts, chunk.end_index)
      const isChild = getChunkRole(chunk) === 'child'
      const disabled = Boolean(chunkOverrides?.[chunk.index]?.disabled)

      const color = (() => {
        if (disabled) {
          return `hsl(${mutedForeground} / 0.35)`
        }
        if (isChild) return `hsl(${foreground} / 0.65)`
        return `hsl(${mutedForeground} / 0.45)`
      })()

      return {
        range: new monaco.Range(startPos.lineNumber, startPos.column, endPos.lineNumber, endPos.column),
        options: {
          overviewRuler: { color, position: monaco.editor.OverviewRulerLane.Right },
        },
      }
    })

    overviewDecorationIdsRef.current = editor.deltaDecorations(overviewDecorationIdsRef.current, decorations)
  }, [chunkOverrides, chunks, lineStarts])

  const applyActiveDecorations = useCallback(() => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    if (!editor || !monaco) return

    const chunk = activeChunkIndex == null ? null : chunks[activeChunkIndex]
    const parent = highlightParentRange && chunk ? getChunkParentRange(chunk, chunks) : null
    const decorations: MonacoEditorApi.IModelDeltaDecoration[] = []
    const decorateRange = (range: DisplayRange, className: string) => {
      const start = offsetToPosition(lineStarts, range.start)
      const end = offsetToPosition(lineStarts, range.end)
      const selection = new monaco.Range(start.lineNumber, start.column, end.lineNumber, end.column)
      decorations.push({ range: selection, options: { inlineClassName: className } })
      return selection
    }

    if (parent) {
      decorateRange(parent, 'mimirq-monaco-parent-highlight')
    }

    let revealRange: IRange | null = null
    if (chunk && chunk.end_index > chunk.start_index) {
      revealRange = decorateRange({ start: chunk.start_index, end: chunk.end_index }, 'mimirq-monaco-active-highlight')
    }
    if (activeRange && activeRange.end > activeRange.start) {
      revealRange = decorateRange(activeRange, 'mimirq-monaco-citation-highlight')
    }

    activeDecorationIdsRef.current = editor.deltaDecorations(activeDecorationIdsRef.current, decorations)

    try {
      if (revealRange) {
        editor.revealRangeInCenter(revealRange, monaco.editor.ScrollType.Smooth)
      }
    } catch (error) {
      reportClientWarning('Reveal original preview range failed', error)
    }
  }, [activeChunkIndex, activeRange, chunks, highlightParentRange, lineStarts])

  const currentEditorPropsRef = useRef({
    chunks,
    lineStarts,
    onSelectChunkIndex,
    onScrollTopChange,
    initialScrollTop,
    activeChunkIndex,
    activeRange,
    applyOverviewDecorations,
    applyActiveDecorations,
  })
  useLayoutEffect(() => {
    currentEditorPropsRef.current = {
      chunks,
      lineStarts,
      onSelectChunkIndex,
      onScrollTopChange,
      initialScrollTop,
      activeChunkIndex,
      activeRange,
      applyOverviewDecorations,
      applyActiveDecorations,
    }
  }, [
    chunks,
    lineStarts,
    onSelectChunkIndex,
    onScrollTopChange,
    initialScrollTop,
    activeChunkIndex,
    activeRange,
    applyOverviewDecorations,
    applyActiveDecorations,
  ])

  useEffect(() => {
    applyOverviewDecorations()
    window.addEventListener(THEME_APPEARANCE_CHANGED_EVENT, applyOverviewDecorations)
    return () => window.removeEventListener(THEME_APPEARANCE_CHANGED_EVENT, applyOverviewDecorations)
  }, [applyOverviewDecorations, resolvedTheme])

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
    } catch (error) {
      reportClientWarning('Restore original preview scroll failed', error)
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
      editorRef.current = null
      monacoRef.current = null
    }
  }, [])

  return (
    <div
      className={`${styles.viewer} relative h-full min-h-[520px] rounded-xl border border-border/60 overflow-hidden bg-background`}
    >
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
        onMount={(editor, monaco) => {
          clickDisposableRef.current?.dispose()
          scrollDisposableRef.current?.dispose()
          overviewDecorationIdsRef.current = []
          activeDecorationIdsRef.current = []
          editorRef.current = editor
          monacoRef.current = monaco
          const current = currentEditorPropsRef.current
          current.applyOverviewDecorations()
          current.applyActiveDecorations()

          if (
            typeof current.initialScrollTop === 'number' &&
            Number.isFinite(current.initialScrollTop) &&
            current.activeChunkIndex == null &&
            !current.activeRange
          ) {
            try {
              editor.setScrollTop(Math.max(0, current.initialScrollTop))
            } catch (error) {
              reportClientWarning('Restore mounted original preview scroll failed', error)
            }
          }

          clickDisposableRef.current = editor.onMouseDown((event) => {
            const current = currentEditorPropsRef.current
            if (!current.onSelectChunkIndex) return
            if (!event.event.leftButton) return
            const position = event.target.position
            if (!position) return
            if (editor.getModel() === null) return
            const lineStart = current.lineStarts[position.lineNumber - 1]
            if (lineStart === undefined) return
            const offset = lineStart + position.column - 1
            const best = pickBestChunkAtOffset(current.chunks, offset)
            if (!best) return
            current.onSelectChunkIndex(best.index)
          })

          scrollDisposableRef.current = editor.onDidScrollChange((event) => {
            if (event.scrollTopChanged) currentEditorPropsRef.current.onScrollTopChange?.(event.scrollTop)
          })
        }}
      />
    </div>
  )
}
