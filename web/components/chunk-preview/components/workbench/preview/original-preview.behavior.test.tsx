// @vitest-environment happy-dom

import React, { act, StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChunkPreviewContextType } from '@/components/chunk-preview/types'
import type { ChunkPreviewResponse } from '@/types'

const mocks = vi.hoisted(() => ({
  context: {} as Partial<ChunkPreviewContextType>,
  translate: (key: string) => key,
}))

vi.mock('next-intl', () => ({ useTranslations: () => mocks.translate }))
vi.mock('@/components/chunk-preview/context', () => ({ useChunkPreview: () => mocks.context }))
vi.mock('./original-preview-monaco', () => ({
  OriginalPreviewMonaco: ({ text }: { text: string }) => <div data-testid="monaco-mode">{text}</div>,
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
  mocks.context = {
    previewData: preview('document.md', 'server original'),
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

  it('finishes an automatic local read after the loading state rerenders', async () => {
    const response = deferred<string>()
    const { file, read } = fileWithRead('local.md', response.promise)
    mocks.context.currentFile = file
    mocks.context.previewData = preview('local.md')
    const { container } = mount()
    await act(async () => {
      await Promise.resolve()
    })
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
})
