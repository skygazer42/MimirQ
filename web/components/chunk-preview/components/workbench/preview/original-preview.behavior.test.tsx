// @vitest-environment happy-dom

import React, { act, StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChunkPreviewContextType } from '@/components/chunk-preview/types'
import type { ChunkPreviewResponse } from '@/types'

type PreviewEditorProps = React.ComponentProps<typeof import('./original-preview-monaco').OriginalPreviewMonaco>

const mocks = vi.hoisted(() => ({
  context: {} as Partial<ChunkPreviewContextType>,
  translate: (key: string) => key,
  editorProps: undefined as PreviewEditorProps | undefined,
}))

vi.mock('next-intl', () => ({ useTranslations: () => mocks.translate }))
vi.mock('@/components/chunk-preview/context', () => ({ useChunkPreview: () => mocks.context }))
vi.mock('./original-preview-monaco', () => ({
  OriginalPreviewMonaco: (props: PreviewEditorProps) => {
    mocks.editorProps = props
    return <div data-testid="monaco-mode">{props.text}</div>
  },
}))
vi.mock('./pdf-preview', () => ({ PdfPreview: () => <div data-testid="pdf-mode">PDF</div> }))
vi.mock('@/components/markdown/markdown-renderer', () => ({
  MarkdownRenderer: ({ markdown }: { markdown: string }) => <div data-testid="rendered-mode">{markdown}</div>,
}))
vi.mock('@/components/markdown/markdown-toc', () => ({ MarkdownToc: () => null }))

import { OriginalPreview } from './original-preview'
import { ORIGINAL_PREVIEW_MODE_STORAGE_KEY } from './pdf-dock'

const roots: Root[] = []

function preview(filename: string, originalText?: string): ChunkPreviewResponse {
  return {
    filename,
    file_type: filename.endsWith('.pdf') ? 'pdf' : 'md',
    file_size: 12,
    total_characters: 12,
    total_chunks: 1,
    params: { chunk_size: 1000, chunk_overlap: 200 },
    chunks: [{ index: 0, content: 'chunk', length: 5, start_index: 0, end_index: 5 }],
    parser_backend: 'basic',
    chunk_strategy: 'langchain_recursive',
    ...(originalText === undefined ? {} : { original_text: originalText }),
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function fileWithRead(name: string, promise: Promise<string>, large = false) {
  const file = new File([large ? 'x'.repeat(800_001) : 'text'], name, { type: 'text/markdown' })
  const read = vi.fn(() => promise)
  Object.defineProperty(file, 'text', { value: read })
  return { file, read }
}

function mount(strict = false) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  const render = () =>
    root.render(
      strict ? (
        <StrictMode>
          <OriginalPreview />
        </StrictMode>
      ) : (
        <OriginalPreview />
      ),
    )
  act(render)
  return { container, rerender: () => act(render) }
}

function readButton(container: HTMLElement): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll('button')).find(
    (item) => item.textContent === 'originalPreview.empty.readLocal',
  )
  if (!button) throw new Error('Expected the local-file read button')
  return button
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  mocks.editorProps = undefined
  mocks.context = {
    previewData: preview('document.md', 'server original'),
    previewSourceFile: null,
    currentFile: new File(['server original'], 'document.md', { type: 'text/markdown' }),
    chunkOverrides: {},
    hoveredChunkIndex: null,
    selectedChunkIndex: null,
    setSelectedChunkIndex: vi.fn(),
    isLoading: false,
    error: null,
  }
})

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount())
  vi.restoreAllMocks()
  document.body.replaceChildren()
})

describe('original preview preference and local-file lifetime', () => {
  it('reads the captured preview File when the selected input already has a newer source revision', async () => {
    const captured = fileWithRead('document.md', Promise.resolve('captured source'))
    const current = fileWithRead('document.md', Promise.resolve('newer source'))
    mocks.context.previewSourceFile = captured.file
    mocks.context.currentFile = current.file
    mocks.context.previewData = preview('document.md')
    const { container } = mount()
    await act(async () => Promise.resolve())

    expect(captured.read).toHaveBeenCalledOnce()
    expect(current.read).not.toHaveBeenCalled()
    expect(container.textContent).toContain('captured source')
    expect(container.textContent).not.toContain('newer source')
  })

  it('shows a linked parent in source mode using the same displayed positions as the editor', () => {
    const data = preview('linked.md', '😀AB')
    data.chunks = [
      {
        index: 10,
        content: '😀AB',
        length: 3,
        start_index: 0,
        end_index: 3,
        metadata: { chunk_role: 'parent', node_id: 'parent-node' },
      },
      {
        index: 42,
        content: 'AB',
        length: 2,
        start_index: 1,
        end_index: 3,
        metadata: { chunk_role: 'child', parent_node_id: 'parent-node' },
      },
    ]
    mocks.context.previewData = data
    mocks.context.selectedChunkIndex = 1
    const { container } = mount()
    const marks = container.querySelectorAll('mark')
    expect(Array.from(marks, (mark) => mark.textContent)).toEqual(['😀AB', 'AB'])
    expect(data.chunks[0].end_index).toBe(3)
    expect(data.chunks[1].metadata).toEqual({ chunk_role: 'child', parent_node_id: 'parent-node' })
  })

  it('preserves an authoritative empty server original without reading a local replacement', async () => {
    const local = fileWithRead('document.md', Promise.resolve('local replacement'))
    mocks.context.currentFile = local.file
    mocks.context.previewData = preview('document.md', '')
    const { container } = mount()
    await act(async () => Promise.resolve())
    expect(local.read).not.toHaveBeenCalled()
    expect(container.textContent).toContain('原文为空')
    expect(container.textContent).not.toContain('local replacement')
  })

  it('uses actual UTF-16 text positions without changing API chunks or their parent metadata', () => {
    localStorage.setItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, 'editor')
    const data = preview('unicode.md', '😀AB')
    data.chunks = [
      {
        index: 4,
        content: 'AB',
        length: 2,
        start_index: 1,
        end_index: 3,
        metadata: { chunk_role: 'child', parent_start_char: 0, parent_end_char: 3 },
      },
    ]
    mocks.context.previewData = data
    mocks.context.selectedChunkIndex = 0
    mount()
    expect(mocks.editorProps?.chunks[0]).toMatchObject({
      index: 4,
      start_index: 2,
      end_index: 4,
      metadata: { parent_start_char: 0, parent_end_char: 4 },
    })
    expect(data.chunks[0]).toMatchObject({ start_index: 1, end_index: 3, metadata: { parent_end_char: 3 } })
  })

  it('keeps source selection positions separate from actual override identities when projecting text', () => {
    localStorage.setItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, 'editor')
    const raw = '😀A@@1 0 10 0 10##B'
    const start = Array.from(raw.slice(0, raw.indexOf('B'))).length
    const data = preview('tagged.md', raw)
    data.original_text_cleaned = '😀AB'
    data.chunks = [
      { index: 3, content: 'outside', length: 7, start_index: 999, end_index: 1006 },
      { index: 11, content: 'B', length: 1, start_index: start, end_index: start + 1 },
    ]
    mocks.context.previewData = data
    mocks.context.selectedChunkIndex = 1
    mocks.context.chunkOverrides = { 11: { disabled: true } }
    mount()
    expect(mocks.editorProps?.text).toBe('😀AB')
    expect(mocks.editorProps?.chunks).toMatchObject([{ index: 11, start_index: 3, end_index: 4 }])
    expect(mocks.editorProps?.activeChunkIndex).toBe(0)
    expect(mocks.editorProps?.chunkOverrides?.[11]?.disabled).toBe(true)
    expect(mocks.editorProps?.chunkOverrides?.[1]).toBeUndefined()
    act(() => mocks.editorProps?.onSelectChunkIndex?.(11))
    expect(mocks.context.setSelectedChunkIndex).toHaveBeenCalledWith(1)
  })

  it('keeps local source readable without claiming it is the server coordinate basis', async () => {
    localStorage.setItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, 'editor')
    const local = fileWithRead('local.md', Promise.resolve('😀AB'))
    mocks.context.currentFile = local.file
    mocks.context.previewData = preview('local.md')
    mocks.context.selectedChunkIndex = 0
    const { container } = mount()
    await act(async () => Promise.resolve())
    expect(container.textContent).toContain('😀AB')
    expect(mocks.editorProps?.chunks).toEqual([])
    expect(container.textContent).toContain('当前原文缺少可核对的解析位置')
  })

  it('keeps whole emoji at both edges of a windowed original-text highlight', () => {
    const text = `${'a'.repeat(5000)}😀${'a'.repeat(1999)}X${'b'.repeat(1999)}😀${'b'.repeat(20000)}`
    const data = preview('window.md', text)
    data.total_characters = 29001
    data.chunks = [{ index: 11, content: 'X', length: 1, start_index: 7000, end_index: 7001 }]
    mocks.context.previewData = data
    mocks.context.selectedChunkIndex = 0
    const { container } = mount()

    expect(container.textContent?.match(/😀/gu)).toHaveLength(2)
    expect(container.querySelector('mark')?.textContent).toBe('X')
  })
  it.each([
    { mode: 'editor', panel: 'monaco-mode' },
    { mode: 'rendered', panel: 'rendered-mode' },
  ])('restores saved $mode mode when effects replay in StrictMode', ({ mode, panel }) => {
    localStorage.setItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, mode)

    const { container } = mount(true)

    expect(container.querySelector(`[data-testid="${panel}"]`)).not.toBeNull()
    expect(localStorage.getItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY)).toBe(mode)
  })

  it('opens a PDF in its default PDF mode when there is no saved preference', () => {
    mocks.context.currentFile = new File(['pdf'], 'document.pdf', { type: 'application/pdf' })
    mocks.context.previewData = preview('document.pdf', 'parsed PDF text')

    const { container } = mount(true)

    expect(container.querySelector('[data-testid="pdf-mode"]')).not.toBeNull()
  })

  it('restores the saved PDF mode after inspecting a text file', () => {
    localStorage.setItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, 'pdf')
    const { container, rerender } = mount()

    expect(container.textContent).toContain('server original')
    expect(localStorage.getItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY)).toBe('pdf')

    mocks.context.currentFile = new File(['pdf'], 'document.pdf', { type: 'application/pdf' })
    mocks.context.previewData = preview('document.pdf', 'parsed PDF text')
    rerender()

    expect(container.querySelector('[data-testid="pdf-mode"]')).not.toBeNull()
  })

  it.each([undefined, ''])('keeps PDF original pages independent of returned text %j', (text) => {
    mocks.context.currentFile = new File(['pdf'], 'document.pdf', { type: 'application/pdf' })
    mocks.context.previewData = preview('document.pdf', text)
    const { container } = mount()

    expect(container.querySelector('[data-testid="pdf-mode"]')).not.toBeNull()
  })

  it('finishes the existing local read when the preview filename changes', async () => {
    const response = deferred<string>()
    const { file, read } = fileWithRead('local.md', response.promise)
    mocks.context.currentFile = file
    mocks.context.previewData = preview('local.md')
    const { container, rerender } = mount()
    await act(async () => {
      await Promise.resolve()
    })
    expect(read).toHaveBeenCalledOnce()

    mocks.context.previewData = preview('normalized.md')
    rerender()
    expect(read).toHaveBeenCalledOnce()

    await act(async () => response.resolve('local original is ready'))

    expect(container.textContent).toContain('local original is ready')
    expect(container.textContent).not.toContain('originalPreview.empty.readLocalLoading')
  })

  it('discards a manual read that finishes after selecting another file', async () => {
    const oldResponse = deferred<string>()
    const nextResponse = deferred<string>()
    const old = fileWithRead('first.md', oldResponse.promise, true)
    const next = fileWithRead('second.md', nextResponse.promise, true)
    mocks.context.currentFile = old.file
    mocks.context.previewData = preview('first.md')
    const { container, rerender } = mount()
    act(() => readButton(container).click())
    expect(old.read).toHaveBeenCalledOnce()

    mocks.context.currentFile = next.file
    mocks.context.previewData = preview('second.md')
    rerender()
    await act(async () => oldResponse.resolve('private first-file original'))

    expect(container.textContent).not.toContain('private first-file original')
    act(() => readButton(container).click())
    await act(async () => nextResponse.resolve('second-file original'))
    expect(container.textContent).toContain('second-file original')
  })

  it('keeps the document usable when browser preference storage is blocked', () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new Error('storage blocked')
    })

    const { container } = mount()

    expect(container.textContent).toContain('server original')
  })

  it('shows a manual read error and lets the user retry', async () => {
    const file = new File(['x'.repeat(800_001)], 'retry.md', { type: 'text/markdown' })
    const read = vi.fn().mockRejectedValueOnce(new Error('local read failed')).mockResolvedValueOnce('retried original')
    Object.defineProperty(file, 'text', { value: read })
    mocks.context.currentFile = file
    mocks.context.previewData = preview('retry.md')
    const { container } = mount()

    await act(async () => readButton(container).click())
    expect(container.textContent).toContain('local read failed')
    expect(readButton(container).disabled).toBe(false)
    await act(async () => readButton(container).click())

    expect(container.textContent).toContain('retried original')
    expect(read).toHaveBeenCalledTimes(2)
  })

  it('keeps server text visible in raw mode without reading the local file', () => {
    const { file, read } = fileWithRead('document.md', Promise.resolve('unused local copy'))
    mocks.context.currentFile = file

    const { container } = mount()

    expect(container.textContent).toContain('server original')
    expect(read).not.toHaveBeenCalled()
  })

  it('shows the coverage control for measured zero values and hides it for invalid metrics', () => {
    const documentPreview = preview('document.md', 'server original')
    mocks.context.previewData = {
      ...documentPreview,
      stats: { coverage_ratio: 0, overlap_waste_ratio: 0, gap_count: 0, largest_gap: 0 },
    }
    const { container, rerender } = mount()
    expect(container.textContent).toContain('覆盖统计')

    mocks.context.previewData = {
      ...documentPreview,
      stats: { coverage_ratio: 1.2, overlap_waste_ratio: -0.1, gap_count: 1.5, largest_gap: -1 },
    }
    rerender()
    expect(container.textContent).not.toContain('覆盖统计')
  })
})
