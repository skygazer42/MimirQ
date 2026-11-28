// @vitest-environment happy-dom

import React, { act, type ComponentProps } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChunkPreviewContextType } from '@/components/chunk-preview/types'
import type { ChunkPreviewResponse } from '@/types'
import { computePdfPreviewData, type PdfPreviewComputationResult } from '@/lib/pdf-preview-computation'

type ViewerProps = ComponentProps<typeof import('@/components/parsing/pdf-viewer').PdfViewer>
const mocks = vi.hoisted(() => ({
  context: {} as Partial<ChunkPreviewContextType>,
  translate: (key: string) => key,
  compute: vi.fn(),
  wrap: vi.fn(),
  release: vi.fn(),
  releaseProxy: Symbol('releaseProxy'),
  warning: vi.fn(),
  renders: [] as ViewerProps[],
}))

vi.mock('next-intl', () => ({ useTranslations: () => mocks.translate }))
vi.mock('@/components/chunk-preview/context', () => ({ useChunkPreview: () => mocks.context }))
vi.mock('@/lib/client-logging', () => ({ reportClientWarning: mocks.warning }))
vi.mock('comlink', () => ({
  releaseProxy: mocks.releaseProxy,
  wrap: mocks.wrap,
}))
vi.mock('next/dynamic', () => ({
  default: () => (props: ViewerProps) => {
    mocks.renders.push(props)
    return <div data-pdf-viewer>{props.file?.name}</div>
  },
}))

import { PdfPreview } from './pdf-preview'

const roots: Root[] = []
const workers: PreviewWorker[] = []

class PreviewWorker extends EventTarget {
  terminate = vi.fn()

  constructor() {
    super()
    workers.push(this)
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function preview(rawOriginal: string | null = 'AB@@1 0 10 0 10##'): ChunkPreviewResponse {
  return {
    filename: 'source.pdf',
    file_type: 'pdf',
    file_size: 10,
    total_characters: 2,
    total_chunks: 1,
    params: { chunk_size: 1000, chunk_overlap: 200 },
    chunks: [{ index: 9, content: 'AB', length: 2, start_index: 0, end_index: 2 }],
    original_text: rawOriginal,
    parser_backend: 'basic',
    chunk_strategy: 'langchain_recursive',
  }
}

async function mount() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  async function render(file = new File(['pdf'], 'source.pdf', { type: 'application/pdf' })) {
    await act(async () => root.render(<PdfPreview file={file} preview={mocks.context.previewData!} />))
  }
  await render()
  return { container, render }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  workers.length = 0
  mocks.renders.length = 0
  mocks.context = {
    previewData: preview(),
    includeOriginalText: true,
    hoveredChunkIndex: null,
    selectedChunkIndex: null,
    setHoveredChunkIndex: vi.fn(),
    setSelectedChunkIndex: vi.fn(),
  }
  mocks.compute.mockImplementation(async (params: Parameters<typeof computePdfPreviewData>[0]) =>
    computePdfPreviewData(params),
  )
  mocks.wrap.mockReset().mockImplementation(() => ({
    computePdfPreviewData: mocks.compute,
    [mocks.releaseProxy]: mocks.release,
  }))
  vi.stubGlobal('Worker', PreviewWorker)
})

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount())
  document.body.replaceChildren()
  vi.unstubAllGlobals()
})

describe('actual PDF source and optional overlay lifetime', () => {
  it.each([null, '', 'plain text without position tags'])(
    'keeps the actual PDF readable with source text %j',
    async (text) => {
      mocks.context.previewData = preview(text)
      const { container } = await mount()
      expect(container.querySelector('[data-pdf-viewer]')).not.toBeNull()
    },
  )

  it.each(['error', 'messageerror'])(
    'uses the existing local computation after an asynchronous worker %s and releases that worker',
    async (eventType) => {
      const response = deferred<PdfPreviewComputationResult>()
      mocks.compute.mockReturnValue(response.promise)
      const { container } = await mount()
      await act(async () =>
        workers[0].dispatchEvent(
          eventType === 'error'
            ? new ErrorEvent('error', { message: 'module loading failed' })
            : new Event('messageerror'),
        ),
      )

      expect(container.querySelector('[data-pdf-viewer]')).not.toBeNull()
      expect(
        mocks.renders
          .at(-1)
          ?.boxesByPage?.get(0)
          ?.map((box) => box.id),
      ).toEqual(['block-0'])
      expect(workers[0].terminate).toHaveBeenCalledOnce()
      expect(mocks.warning).toHaveBeenCalledOnce()
    },
  )

  it('terminates the worker when the proxy setup fails and keeps the PDF visible', async () => {
    mocks.wrap.mockImplementationOnce(() => {
      throw new Error('proxy setup failed')
    })

    const { container } = await mount()

    expect(workers[0].terminate).toHaveBeenCalledOnce()
    expect(container.querySelector('[data-pdf-viewer]')).not.toBeNull()
    expect(
      mocks.renders
        .at(-1)
        ?.boxesByPage?.get(0)
        ?.map((box) => box.id),
    ).toEqual(['block-0'])
  })

  it('does not publish a retired worker failure or disable the next actual computation', async () => {
    const previous = deferred<PdfPreviewComputationResult>()
    mocks.compute.mockReturnValueOnce(previous.promise)
    const { render } = await mount()
    mocks.context.previewData = preview('CD@@2 0 10 0 10##')
    await render(new File(['second pdf'], 'second.pdf'))

    await act(async () => previous.reject(new Error('retired calculation failed')))
    mocks.context.previewData = preview('EF@@3 0 10 0 10##')
    await render(new File(['third pdf'], 'third.pdf'))

    expect(mocks.warning).not.toHaveBeenCalled()
    expect(mocks.compute).toHaveBeenCalledTimes(3)
  })

  it('never pairs the next PDF file with boxes from the previous preview, including the first committed render', async () => {
    const { render } = await mount()
    mocks.context.previewData = preview('CD@@2 0 10 0 10##')
    await render(new File(['second pdf'], 'second.pdf'))

    const secondFileRenders = mocks.renders.filter((props) => props.file?.name === 'second.pdf')
    expect(secondFileRenders.length).toBeGreaterThan(0)
    expect(secondFileRenders.some((props) => props.boxesByPage?.has(0))).toBe(false)
  })

  it('keeps an explicit selected chunk without boxes from inheriting the hovered chunk highlight', async () => {
    mocks.context.previewData = {
      ...preview(),
      chunks: [
        { index: 9, content: 'AB', length: 2, start_index: 0, end_index: 2 },
        { index: 15, content: '', length: 0, start_index: 2, end_index: 2 },
      ],
    }
    mocks.context.selectedChunkIndex = 1
    mocks.context.hoveredChunkIndex = 0
    await mount()

    expect(mocks.renders.at(-1)?.activeBlockIds).toEqual([])
    expect(mocks.renders.at(-1)?.hoveredBlockIds).toEqual(['block-0'])
  })

  it('clears the highlighted chunk when the hovered PDF block has no mapping', async () => {
    await mount()
    const hoverBlock = mocks.renders.at(-1)?.onHoverBlockId

    act(() => {
      hoverBlock?.('block-0')
      hoverBlock?.('unmapped-block')
    })

    expect(mocks.context.setHoveredChunkIndex).toHaveBeenNthCalledWith(1, 0)
    expect(mocks.context.setHoveredChunkIndex).toHaveBeenNthCalledWith(2, null)
  })
})
