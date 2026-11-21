// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChunkPreviewItem } from '@/types'
import type { editor as MonacoEditorApi } from 'monaco-editor'
import { THEME_APPEARANCE_CHANGED_EVENT } from '@/lib/theme-surface'

type MouseEvent = {
  event: { leftButton: boolean }
  target: { position: { lineNumber: number; column: number } | null }
}
type ScrollEvent = { scrollTop: number; scrollTopChanged: boolean }
type EditorProps = {
  onMount: (editor: ReturnType<typeof createEditor>, monaco: ReturnType<typeof createMonaco>) => void
}
const mocks = vi.hoisted(() => ({
  onMount: undefined as EditorProps['onMount'] | undefined,
  configure: vi.fn(),
  translate: (key: string) => key,
}))

vi.mock('@monaco-editor/loader', () => ({ default: { config: mocks.configure } }))
vi.mock('next/dynamic', () => ({
  default: () =>
    function EditorBoundary(props: EditorProps) {
      mocks.onMount = props.onMount
      return <div data-testid="editor-boundary" />
    },
}))
vi.mock('next-intl', () => ({ useTranslations: () => mocks.translate }))
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', systemTheme: 'light' }) }))

import { OriginalPreviewMonaco } from './original-preview-monaco'

const roots: Root[] = []

function createEditor() {
  const mouse = new Set<(event: MouseEvent) => void>()
  const scroll = new Set<(event: ScrollEvent) => void>()
  const model = { getOffsetAt: ({ column }: { column: number }) => column - 1 }
  return {
    mouse,
    scroll,
    deltaDecorations: vi.fn((_previous: string[], decorations: MonacoEditorApi.IModelDeltaDecoration[]) =>
      decorations.map((_, index) => `decoration-${index}`),
    ),
    revealRangeInCenter: vi.fn(),
    onMouseDown: vi.fn((listener: (event: MouseEvent) => void) => {
      mouse.add(listener)
      return { dispose: vi.fn(() => mouse.delete(listener)) }
    }),
    onDidScrollChange: vi.fn((listener: (event: ScrollEvent) => void) => {
      scroll.add(listener)
      return { dispose: vi.fn(() => scroll.delete(listener)) }
    }),
    getModel: vi.fn((): typeof model | null => model),
    setScrollTop: vi.fn(),
  }
}

function createMonaco() {
  return {
    Range: class Range {
      constructor(
        public startLineNumber: number,
        public startColumn: number,
        public endLineNumber: number,
        public endColumn: number,
      ) {}
    },
    editor: { OverviewRulerLane: { Right: 1 }, ScrollType: { Smooth: 0 } },
  }
}

function chunk(index: number, start: number, end: number): ChunkPreviewItem {
  return { index, start_index: start, end_index: end, content: 'x'.repeat(end - start), length: end - start }
}

function mount(props: React.ComponentProps<typeof OriginalPreviewMonaco>, delayed = false) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  act(() => root.render(<OriginalPreviewMonaco {...props} />))
  const editor = createEditor()
  const onMount = mocks.onMount!
  if (!delayed) act(() => onMount(editor, createMonaco()))
  return {
    editor,
    attach: () => act(() => onMount(editor, createMonaco())),
    rerender: (next: React.ComponentProps<typeof OriginalPreviewMonaco>) => {
      act(() => root.render(<OriginalPreviewMonaco {...next} />))
    },
    unmount: () => {
      act(() => root.unmount())
      roots.splice(roots.indexOf(root), 1)
    },
  }
}

function clickAt(editor: ReturnType<typeof createEditor>, column: number, lineNumber = 1) {
  act(() => {
    for (const listener of editor.mouse) {
      listener({ event: { leftButton: true }, target: { position: { lineNumber, column } } })
    }
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  document.documentElement.style.setProperty('--foreground', '210 20% 20%')
  document.documentElement.style.setProperty('--muted-foreground', '210 10% 50%')
})

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount())
  document.body.replaceChildren()
  document.documentElement.removeAttribute('style')
  vi.clearAllMocks()
})

describe('Monaco preview listeners after document changes', () => {
  it('maps a source BOM to the first visible SDK column without changing source chunk offsets', () => {
    const select = vi.fn()
    const item = chunk(0, 1, 3)
    const view = mount({ text: '\uFEFFaa', chunks: [item], activeChunkIndex: 0, onSelectChunkIndex: select })
    const decorations = view.editor.deltaDecorations.mock.calls.flatMap(([, items]) => items)
    expect(decorations).toContainEqual(
      expect.objectContaining({
        range: expect.objectContaining({ startLineNumber: 1, startColumn: 1, endLineNumber: 1, endColumn: 3 }),
        options: { inlineClassName: 'mimirq-monaco-active-highlight' },
      }),
    )
    clickAt(view.editor, 1)
    expect(select).toHaveBeenCalledExactlyOnceWith(0)
    expect([item.start_index, item.end_index]).toEqual([1, 3])
  })

  it('highlights the actual line when source text uses CR line breaks', () => {
    const view = mount({
      text: 'aa\rbb\rcc',
      chunks: [chunk(0, 0, 2), chunk(1, 3, 5), chunk(2, 6, 8)],
      activeChunkIndex: 1,
    })
    const decorations = view.editor.deltaDecorations.mock.calls.flatMap(([, items]) => items)
    expect(decorations).toContainEqual(
      expect.objectContaining({
        range: expect.objectContaining({ startLineNumber: 2, startColumn: 1, endLineNumber: 2, endColumn: 3 }),
        options: { inlineClassName: 'mimirq-monaco-active-highlight' },
      }),
    )
  })

  it('selects source chunks when the SDK normalizes mixed line endings', () => {
    const select = vi.fn()
    const view = mount({
      text: 'aa\r\nbb\ncc',
      chunks: [chunk(0, 0, 2), chunk(1, 4, 6), chunk(2, 7, 9)],
      activeChunkIndex: null,
      onSelectChunkIndex: select,
    })
    // Installed Monaco normalizes this mixed source to LF: row 2 starts at model offset 3.
    view.editor.getModel.mockReturnValue({ getOffsetAt: () => 3 })
    clickAt(view.editor, 1, 2)
    expect(select).toHaveBeenCalledExactlyOnceWith(1)
  })

  it('repaints overview colors for the current theme and releases the theme listener on unmount', () => {
    const item = chunk(0, 0, 10)
    item.metadata = { chunk_role: 'child' }
    const view = mount({ text: 'abcdefghij', chunks: [item], activeChunkIndex: null })
    const overviewColors = () =>
      view.editor.deltaDecorations.mock.calls.flatMap(([, decorations]) =>
        decorations.flatMap((decoration) =>
          decoration.options.overviewRuler == null ? [] : [decoration.options.overviewRuler.color],
        ),
      )
    const before = overviewColors()
    expect(before).toHaveLength(1)
    view.editor.deltaDecorations.mockClear()
    document.documentElement.style.setProperty('--foreground', '210 20% 90%')
    act(() => window.dispatchEvent(new Event(THEME_APPEARANCE_CHANGED_EVENT)))
    expect(overviewColors()).toHaveLength(1)
    expect(overviewColors()).not.toEqual(before)
    view.unmount()
    view.editor.deltaDecorations.mockClear()
    act(() => window.dispatchEvent(new Event(THEME_APPEARANCE_CHANGED_EVENT)))
    expect(view.editor.deltaDecorations).not.toHaveBeenCalled()
  })

  it('uses the current document when the SDK invokes its original mount callback later', () => {
    const first = { text: 'old!', chunks: [chunk(0, 0, 4)], activeChunkIndex: null, initialScrollTop: 5 }
    const view = mount(first, true)
    view.rerender({
      text: 'abcdefghij',
      chunks: [chunk(0, 0, 5), chunk(1, 5, 10)],
      activeChunkIndex: 1,
      initialScrollTop: 42,
    })
    view.attach()
    const decorations = view.editor.deltaDecorations.mock.calls.flatMap(([, items]) => items)
    expect(decorations).toContainEqual(
      expect.objectContaining({
        range: expect.objectContaining({ startColumn: 6, endColumn: 11 }),
        options: { inlineClassName: 'mimirq-monaco-active-highlight' },
      }),
    )
    expect(view.editor.setScrollTop).not.toHaveBeenCalled()
  })

  it('accepts selection and scroll callbacks added after the SDK mounts', () => {
    const first = { text: 'abcdefghij', chunks: [chunk(0, 0, 10)], activeChunkIndex: null }
    const view = mount(first)
    const select = vi.fn()
    const scroll = vi.fn()
    view.rerender({ ...first, onSelectChunkIndex: select, onScrollTopChange: scroll })
    clickAt(view.editor, 2)
    act(() => {
      for (const listener of view.editor.scroll) listener({ scrollTop: 20, scrollTopChanged: true })
    })
    expect(select).toHaveBeenCalledExactlyOnceWith(0)
    expect(scroll).toHaveBeenCalledExactlyOnceWith(20)
  })

  it('releases the old editor resources and starts new decoration identities on replacement', () => {
    const view = mount({
      text: 'abcdefghij',
      chunks: [chunk(0, 0, 10)],
      activeChunkIndex: 0,
      onSelectChunkIndex: vi.fn(),
      onScrollTopChange: vi.fn(),
    })
    const next = createEditor()
    act(() => mocks.onMount?.(next, createMonaco()))
    expect(view.editor.mouse.size).toBe(0)
    expect(view.editor.scroll.size).toBe(0)
    expect(next.deltaDecorations.mock.calls[0][0]).toEqual([])
    view.unmount()
    expect(next.mouse.size).toBe(0)
    expect(next.scroll.size).toBe(0)
  })
  it('selects from the current chunk ranges after the preview changes', () => {
    const select = vi.fn()
    const first = { text: 'abcdefghij', chunks: [chunk(0, 0, 10)], activeChunkIndex: null, onSelectChunkIndex: select }
    const view = mount(first)
    clickAt(view.editor, 8)
    expect(select).toHaveBeenLastCalledWith(0)

    view.rerender({ ...first, chunks: [chunk(0, 0, 5), chunk(1, 5, 10)] })
    select.mockClear()
    clickAt(view.editor, 8)

    expect(select).toHaveBeenCalledExactlyOnceWith(1)
  })

  it('uses the current selection and scroll callbacks for a new document', () => {
    const oldSelect = vi.fn()
    const oldScroll = vi.fn()
    const nextSelect = vi.fn()
    const nextScroll = vi.fn()
    const first = {
      text: 'first text',
      chunks: [chunk(0, 0, 10)],
      activeChunkIndex: null,
      onSelectChunkIndex: oldSelect,
      onScrollTopChange: oldScroll,
    }
    const view = mount(first)

    view.rerender({ ...first, text: 'next text!', onSelectChunkIndex: nextSelect, onScrollTopChange: nextScroll })
    clickAt(view.editor, 2)
    act(() => {
      for (const listener of view.editor.scroll) listener({ scrollTop: 42, scrollTopChanged: true })
    })

    expect(oldSelect).not.toHaveBeenCalled()
    expect(oldScroll).not.toHaveBeenCalled()
    expect(nextSelect).toHaveBeenCalledExactlyOnceWith(0)
    expect(nextScroll).toHaveBeenCalledExactlyOnceWith(42)
  })

  it('ignores non-left clicks and positions outside the current editor text', () => {
    const select = vi.fn()
    const view = mount({
      text: 'abcdefghij',
      chunks: [chunk(0, 0, 10)],
      activeChunkIndex: null,
      onSelectChunkIndex: select,
    })
    act(() => {
      for (const listener of view.editor.mouse) {
        listener({ event: { leftButton: false }, target: { position: { lineNumber: 1, column: 2 } } })
        listener({ event: { leftButton: true }, target: { position: null } })
      }
    })
    clickAt(view.editor, 2, 2)
    view.editor.getModel.mockReturnValue(null)
    clickAt(view.editor, 2)

    expect(select).not.toHaveBeenCalled()
  })

  it('disposes both SDK listener subscriptions when unmounted', () => {
    const view = mount({
      text: 'abcdefghij',
      chunks: [chunk(0, 0, 10)],
      activeChunkIndex: null,
      onSelectChunkIndex: vi.fn(),
      onScrollTopChange: vi.fn(),
    })
    expect(view.editor.mouse.size).toBe(1)
    expect(view.editor.scroll.size).toBe(1)

    view.unmount()

    expect(view.editor.mouse.size).toBe(0)
    expect(view.editor.scroll.size).toBe(0)
  })
})
