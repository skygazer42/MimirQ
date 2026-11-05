// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChunkPreviewItem } from '@/types'

type MouseEvent = {
  event: { leftButton: boolean }
  target: { position: { lineNumber: number; column: number } | null }
}
type ScrollEvent = { scrollTop: number }
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
    deltaDecorations: vi.fn(() => [] as string[]),
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
    getScrollTop: vi.fn(() => 0),
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

function mount(props: React.ComponentProps<typeof OriginalPreviewMonaco>) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  act(() => root.render(<OriginalPreviewMonaco {...props} />))
  const editor = createEditor()
  act(() => mocks.onMount?.(editor, createMonaco()))
  return {
    editor,
    rerender: (next: React.ComponentProps<typeof OriginalPreviewMonaco>) => {
      act(() => root.render(<OriginalPreviewMonaco {...next} />))
    },
    unmount: () => {
      act(() => root.unmount())
      roots.splice(roots.indexOf(root), 1)
    },
  }
}

function clickAt(editor: ReturnType<typeof createEditor>, column: number) {
  act(() => {
    for (const listener of editor.mouse) {
      listener({ event: { leftButton: true }, target: { position: { lineNumber: 1, column } } })
    }
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount())
  document.body.replaceChildren()
  vi.clearAllMocks()
})

describe('Monaco preview listeners after document changes', () => {
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
      for (const listener of view.editor.scroll) listener({ scrollTop: 42 })
    })

    expect(oldSelect).not.toHaveBeenCalled()
    expect(oldScroll).not.toHaveBeenCalled()
    expect(nextSelect).toHaveBeenCalledExactlyOnceWith(0)
    expect(nextScroll).toHaveBeenCalledExactlyOnceWith(42)
  })

  it('keeps the SDK event guards for non-left clicks and absent model positions', () => {
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
