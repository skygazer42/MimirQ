// @vitest-environment jsdom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getDocument: vi.fn(),
  view: {
    isOpen: true,
    documentId: 'doc-a',
    highlightChunkId: null,
    highlightRange: null,
    previewAnchor: null,
    sourceContext: null,
    activeTab: 'preview',
    documentLayouts: {},
    getDocumentLayout: vi.fn(() => null),
    closeDocument: vi.fn(),
    setActiveTab: vi.fn(),
    setDocumentLayout: vi.fn(),
    setHighlightChunk: vi.fn(),
  },
}))

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: () => ({ getVirtualItems: () => [], getTotalSize: () => 0 }),
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('@/components/auth-image', () => ({ useResolvedAuthAssetUrl: () => null }))
vi.mock('@/lib/api', () => ({
  documentApi: { get: mocks.getDocument },
  ragApi: {},
}))
vi.mock('@/lib/api-errors', () => ({ formatApiError: () => 'error' }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn() }))
vi.mock('@/lib/doc-content-cache', () => ({
  getDocContentFromCache: vi.fn().mockResolvedValue(null),
  saveDocContentToCache: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/lib/document-chunks', () => ({ mapDocumentChunksToPreviewItems: () => [] }))
vi.mock('@/lib/document-preview-anchor', () => ({
  recoverDocumentPreviewAnchorFromChunkPositions: () => null,
  sanitizeDocumentPreviewAnchor: () => null,
}))
vi.mock('@/lib/document-view-prefetch', () => ({
  getPrefetchedChunk: () => undefined,
  getPrefetchedDocument: () => undefined,
}))
vi.mock('@/lib/env', () => ({ API_V1_BASE_URL: '/api/v1', toAbsoluteBackendUrl: (url: string) => url }))
vi.mock('@/lib/event-bus', () => ({ globalEventBus: { emit: vi.fn() } }))
vi.mock('@/lib/utils', () => ({ detachPromise: vi.fn() }))
vi.mock('@/store/document-view', () => ({ useDocumentView: () => mocks.view }))
vi.mock('./keyboard-shortcuts', () => ({ resolveChunkKeyboardNavigation: () => null }))
vi.mock('./document-viewer-panel-utils', () => ({ toCitation: vi.fn() }))

import { useDocumentViewerPanelState } from './use-document-viewer-panel-state'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useDocumentViewerPanelState document switching', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  function Probe() {
    const state = useDocumentViewerPanelState()
    return <div data-document-id={state.doc?.id || ''} />
  }

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    root = createRoot(container)
    mocks.getDocument.mockReset()
    mocks.view.getDocumentLayout.mockReset()
    mocks.view.getDocumentLayout.mockReturnValue(null)
    mocks.view.documentId = 'doc-a'
    mocks.view.documentLayouts = {}
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(() => {
    act(() => root.unmount())
    vi.unstubAllGlobals()
  })

  it('ignores a stale document response after switching documents', async () => {
    const docA = deferred<never>()
    const docB = deferred<never>()
    mocks.getDocument.mockImplementation((id: string) => id === 'doc-a' ? docA.promise : docB.promise)

    await act(async () => root.render(<Probe />))
    mocks.view.documentId = 'doc-b'
    await act(async () => root.render(<Probe />))

    await act(async () => docB.resolve({ id: 'doc-b' } as never))
    expect(container.firstElementChild?.getAttribute('data-document-id')).toBe('doc-b')

    await act(async () => docA.resolve({ id: 'doc-a' } as never))
    expect(container.firstElementChild?.getAttribute('data-document-id')).toBe('doc-b')
  })

  it('keeps loading document details when the saved layout changes', async () => {
    const doc = deferred<never>()
    mocks.getDocument.mockReturnValue(doc.promise)

    await act(async () => root.render(<Probe />))
    mocks.view.documentLayouts = { 'doc-a': { isExpanded: false } }
    await act(async () => root.render(<Probe />))

    await act(async () => doc.resolve({ id: 'doc-a' } as never))

    expect(mocks.getDocument).toHaveBeenCalledTimes(1)
    expect(container.firstElementChild?.getAttribute('data-document-id')).toBe('doc-a')
  })
})
