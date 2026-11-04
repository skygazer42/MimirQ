// @vitest-environment happy-dom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DocumentChunk, DocumentQAGenerateResponse } from '@/types/backend'

const mocks = vi.hoisted(() => ({
  getDocument: vi.fn(),
  retrievePreview: vi.fn(),
  reportClientError: vi.fn(),
  createChunk: vi.fn(),
  updateChunk: vi.fn(),
  reembedChunks: vi.fn(),
  deleteChunk: vi.fn(),
  generateQa: vi.fn(),
  getChunk: vi.fn(),
  listChunks: vi.fn(),
  getChunkMatches: vi.fn(),
  clipboardWrite: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  toastMessage: vi.fn(),
  measure: vi.fn(),
  view: {
    isOpen: true,
    documentId: 'doc-a' as string | null,
    highlightChunkId: null as string | null,
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
  useVirtualizer: () => ({ getVirtualItems: () => [], getTotalSize: () => 0, measure: mocks.measure }),
}))
vi.mock('sonner', () => ({
  toast: { error: mocks.toastError, success: mocks.toastSuccess, message: mocks.toastMessage },
}))
vi.mock('@/components/auth-image', () => ({ useResolvedAuthAssetUrl: () => null }))
vi.mock('@/lib/api', () => ({
  documentApi: {
    get: mocks.getDocument,
    createChunk: mocks.createChunk,
    updateChunk: mocks.updateChunk,
    reembedChunks: mocks.reembedChunks,
    deleteChunk: mocks.deleteChunk,
    generateQa: mocks.generateQa,
    getChunk: mocks.getChunk,
    listChunks: mocks.listChunks,
    getChunkMatches: mocks.getChunkMatches,
  },
  ragApi: { retrievePreview: mocks.retrievePreview },
}))
vi.mock('@/lib/api-errors', () => ({ formatApiError: () => 'error' }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: mocks.reportClientError }))
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
vi.mock('@/store/document-view', () => ({
  useDocumentView: Object.assign(() => mocks.view, { getState: () => mocks.view }),
}))
vi.mock('./keyboard-shortcuts', () => ({ resolveChunkKeyboardNavigation: () => null }))

import { useDocumentViewerPanelState } from './use-document-viewer-panel-state'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function retrievalResponse(documentId: string, content: string) {
  return {
    citations: [{ document_id: documentId, document_name: documentId, chunk_content: content, relevance_score: 1 }],
  }
}

function chunk(id: string, content = id): DocumentChunk {
  return {
    id,
    content,
    chunk_index: 0,
    page_number: null,
    start_char: null,
    end_char: null,
    disabled_at: null,
    created_at: null,
    updated_at: null,
    metadata: {},
  }
}

function qaResponse(documentId: string): DocumentQAGenerateResponse {
  return { document_id: documentId, mode: 'extract', created: 1, deleted: 0, chunk_ids: [], preview: [] }
}

describe('useDocumentViewerPanelState document switching', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>
  let viewerState: ReturnType<typeof useDocumentViewerPanelState>

  function Probe() {
    viewerState = useDocumentViewerPanelState()
    return (
      <div
        data-document-id={viewerState.doc?.id || ''}
        data-retrieving={viewerState.retrieveLoading}
        data-error={viewerState.retrieveError || ''}
        data-chunk-count={viewerState.doc?.chunk_count ?? 0}
        data-chunks={viewerState.chunks.map((item) => item.id).join(',')}
        data-editor-open={viewerState.chunkEditorOpen}
        data-editor-content={viewerState.chunkEditorContent}
        data-editor-submitting={viewerState.chunkEditorSubmitting}
        data-deleting={viewerState.chunkDeleteSubmitting || ''}
        data-qa-open={viewerState.qaDialogOpen}
        data-qa-submitting={viewerState.qaSubmitting}
        data-qa-document={viewerState.qaLastResult?.document_id || ''}
        data-qa-chunks={viewerState.qaLastResult?.chunk_ids?.join(',') || ''}
      >
        {viewerState.retrieveCitations.map((citation) => citation.chunk_content).join('\n')}
      </div>
    )
  }

  async function startRetrieval(query: string) {
    await act(async () => viewerState.setRetrieveQuery(query))
    let completion!: Promise<void>
    act(() => {
      completion = viewerState.runRetrievePreview()
    })
    return { completion }
  }

  function retrievalSnapshot() {
    const panel = container.firstElementChild!
    return {
      documentId: panel.getAttribute('data-document-id'),
      loading: panel.getAttribute('data-retrieving'),
      error: panel.getAttribute('data-error'),
      content: panel.textContent,
    }
  }

  function mutationSnapshot() {
    const panel = container.firstElementChild!
    return {
      documentId: panel.getAttribute('data-document-id'),
      chunkCount: panel.getAttribute('data-chunk-count'),
      chunks: panel.getAttribute('data-chunks'),
      editorOpen: panel.getAttribute('data-editor-open'),
      editorContent: panel.getAttribute('data-editor-content'),
      editorSubmitting: panel.getAttribute('data-editor-submitting'),
      deleting: panel.getAttribute('data-deleting'),
      qaOpen: panel.getAttribute('data-qa-open'),
      qaSubmitting: panel.getAttribute('data-qa-submitting'),
      qaDocument: panel.getAttribute('data-qa-document'),
      qaChunks: panel.getAttribute('data-qa-chunks'),
    }
  }

  async function switchDocument(documentId: string) {
    mocks.view.documentId = documentId
    await act(async () => root.render(<Probe />))
  }

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    root = createRoot(container)
    mocks.getDocument.mockReset()
    mocks.getDocument.mockImplementation(async (id: string) => ({
      id,
      status: 'indexed',
      chunk_count: id === 'doc-a' ? 3 : 10,
    }))
    mocks.retrievePreview.mockReset()
    mocks.reportClientError.mockReset()
    mocks.createChunk.mockReset().mockResolvedValue(chunk('created'))
    mocks.updateChunk.mockReset().mockResolvedValue(chunk('updated'))
    mocks.reembedChunks.mockReset().mockResolvedValue({ reembedded: 1 })
    mocks.deleteChunk.mockReset().mockResolvedValue(undefined)
    mocks.generateQa.mockReset().mockResolvedValue(qaResponse('doc-a'))
    mocks.getChunk.mockReset().mockImplementation(async (_id: string, chunkId: string) => chunk(chunkId))
    mocks.listChunks.mockReset().mockResolvedValue({ total: 0, items: [] })
    mocks.getChunkMatches.mockReset().mockResolvedValue({ total: 0, truncated: false, items: [] })
    mocks.clipboardWrite.mockReset().mockResolvedValue(undefined)
    mocks.toastSuccess.mockReset()
    mocks.toastError.mockReset()
    mocks.toastMessage.mockReset()
    mocks.measure.mockReset()
    mocks.view.setHighlightChunk.mockClear()
    mocks.view.getDocumentLayout.mockReset()
    mocks.view.getDocumentLayout.mockReturnValue(null)
    mocks.view.isOpen = true
    mocks.view.documentId = 'doc-a'
    mocks.view.highlightChunkId = null
    mocks.view.activeTab = 'preview'
    mocks.view.documentLayouts = {}
    vi.stubGlobal('navigator', { clipboard: { writeText: mocks.clipboardWrite } })
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
    mocks.getDocument.mockImplementation((id: string) => (id === 'doc-a' ? docA.promise : docB.promise))

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

  it.each([
    ['resolve', false, 'false'],
    ['reject', false, 'false'],
    ['resolve', true, 'true'],
    ['reject', true, 'true'],
  ] as const)(
    'ignores a stale retrieval %s after switching documents (current request pending: %s)',
    async (settlement, startCurrentRequest, expectedLoading) => {
      const stale = deferred<ReturnType<typeof retrievalResponse>>()
      const current = deferred<ReturnType<typeof retrievalResponse>>()
      mocks.retrievePreview.mockReturnValueOnce(stale.promise).mockReturnValueOnce(current.promise)

      await act(async () => root.render(<Probe />))
      const previousRequest = await startRetrieval('first document question')
      mocks.view.documentId = 'doc-b'
      await act(async () => root.render(<Probe />))
      const currentRequest = startCurrentRequest ? await startRetrieval('second document question') : null

      await act(async () => {
        if (settlement === 'resolve') stale.resolve(retrievalResponse('doc-a', 'old document citation'))
        else stale.reject(new Error('old document retrieval failed'))
        await previousRequest.completion
      })

      expect(retrievalSnapshot()).toEqual({ documentId: 'doc-b', loading: expectedLoading, error: '', content: '' })

      if (currentRequest) {
        await act(async () => {
          current.resolve(retrievalResponse('doc-b', 'current document citation'))
          await currentRequest.completion
        })

        expect(retrievalSnapshot()).toEqual({
          documentId: 'doc-b',
          loading: 'false',
          error: '',
          content: 'current document citation',
        })
      }
    },
  )

  it('keeps the latest retrieval result when an earlier response arrives last', async () => {
    const earlier = deferred<ReturnType<typeof retrievalResponse>>()
    const latest = deferred<ReturnType<typeof retrievalResponse>>()
    mocks.retrievePreview.mockReturnValueOnce(earlier.promise).mockReturnValueOnce(latest.promise)

    await act(async () => root.render(<Probe />))
    const earlierRequest = await startRetrieval('earlier question')
    const latestRequest = await startRetrieval('latest question')

    await act(async () => {
      latest.resolve(retrievalResponse('doc-a', 'latest citation'))
      await latestRequest.completion
    })
    await act(async () => {
      earlier.resolve(retrievalResponse('doc-a', 'earlier citation'))
      await earlierRequest.completion
    })

    expect(retrievalSnapshot()).toEqual({
      documentId: 'doc-a',
      loading: 'false',
      error: '',
      content: 'latest citation',
    })
  })

  it.each(['resolve', 'reject'] as const)('keeps retrieval cleared after a pending request %s', async (settlement) => {
    const initial = deferred<ReturnType<typeof retrievalResponse>>()
    const pending = deferred<ReturnType<typeof retrievalResponse>>()
    mocks.retrievePreview.mockReturnValueOnce(initial.promise).mockReturnValueOnce(pending.promise)

    await act(async () => root.render(<Probe />))
    const initialRequest = await startRetrieval('initial question')
    await act(async () => {
      initial.resolve(retrievalResponse('doc-a', 'previous citation'))
      await initialRequest.completion
    })

    const pendingRequest = await startRetrieval('retry question')
    act(() => viewerState.clearRetrievePreview())
    const afterClear = retrievalSnapshot()

    await act(async () => {
      if (settlement === 'resolve') pending.resolve(retrievalResponse('doc-a', 'late citation'))
      else pending.reject(new Error('cleared retrieval failed'))
      await pendingRequest.completion
    })

    expect({ afterClear, afterSettlement: retrievalSnapshot() }).toEqual({
      afterClear: { documentId: 'doc-a', loading: 'false', error: '', content: '' },
      afterSettlement: { documentId: 'doc-a', loading: 'false', error: '', content: '' },
    })
    expect(viewerState.retrieveQuery).toBe('retry question')
  })

  it.each([
    { visit: 'closing and reopening', awayDocumentId: null },
    { visit: 'leaving and returning', awayDocumentId: 'doc-b' },
  ])('rejects a previous-visit callback after $visit', async ({ awayDocumentId }) => {
    const current = deferred<ReturnType<typeof retrievalResponse>>()
    const obsolete = deferred<ReturnType<typeof retrievalResponse>>()
    mocks.retrievePreview.mockReturnValueOnce(current.promise).mockReturnValueOnce(obsolete.promise)

    await act(async () => root.render(<Probe />))
    await act(async () => viewerState.setRetrieveQuery('previous visit question'))
    const previousRunRetrieve = viewerState.runRetrievePreview
    mocks.view.documentId = awayDocumentId
    mocks.view.isOpen = awayDocumentId !== null
    await act(async () => root.render(<Probe />))
    mocks.view.documentId = 'doc-a'
    mocks.view.isOpen = true
    await act(async () => root.render(<Probe />))
    const currentRequest = await startRetrieval('current visit question')

    await act(async () => {
      const completion = previousRunRetrieve()
      obsolete.resolve(retrievalResponse('doc-a', 'previous visit citation'))
      await completion
    })

    expect(retrievalSnapshot()).toEqual({ documentId: 'doc-a', loading: 'true', error: '', content: '' })

    await act(async () => {
      current.resolve(retrievalResponse('doc-a', 'current visit citation'))
      await currentRequest.completion
    })

    expect(retrievalSnapshot()).toEqual({
      documentId: 'doc-a',
      loading: 'false',
      error: '',
      content: 'current visit citation',
    })
  })

  it('ignores a retrieval callback from the previous document when it starts after switching', async () => {
    const response = deferred<ReturnType<typeof retrievalResponse>>()
    mocks.retrievePreview.mockReturnValue(response.promise)

    await act(async () => root.render(<Probe />))
    await act(async () => viewerState.setRetrieveQuery('previous document question'))
    const previousRunRetrieve = viewerState.runRetrievePreview
    mocks.view.documentId = 'doc-b'
    await act(async () => root.render(<Probe />))

    await act(async () => {
      const completion = previousRunRetrieve()
      response.resolve(retrievalResponse('doc-a', 'old document citation'))
      await completion
    })

    expect(retrievalSnapshot()).toEqual({ documentId: 'doc-b', loading: 'false', error: '', content: '' })
  })

  it('preserves the current visit request when a previous visit clear callback is retained', async () => {
    const current = deferred<ReturnType<typeof retrievalResponse>>()
    mocks.retrievePreview.mockReturnValue(current.promise)

    await act(async () => root.render(<Probe />))
    const previousClear = viewerState.clearRetrievePreview
    mocks.view.documentId = null
    mocks.view.isOpen = false
    await act(async () => root.render(<Probe />))
    mocks.view.documentId = 'doc-a'
    mocks.view.isOpen = true
    await act(async () => root.render(<Probe />))
    const currentRequest = await startRetrieval('current visit question')

    act(() => previousClear())
    const afterPreviousClear = retrievalSnapshot()
    await act(async () => {
      current.resolve(retrievalResponse('doc-a', 'current visit citation'))
      await currentRequest.completion
    })

    expect({ afterPreviousClear, afterResponse: retrievalSnapshot() }).toEqual({
      afterPreviousClear: { documentId: 'doc-a', loading: 'true', error: '', content: '' },
      afterResponse: { documentId: 'doc-a', loading: 'false', error: '', content: 'current visit citation' },
    })
  })

  it.each(['resolve', 'reject'] as const)(
    'does not request or report from disposed preview callbacks after a late %s',
    async (settlement) => {
      const response = deferred<ReturnType<typeof retrievalResponse>>()
      mocks.retrievePreview.mockReturnValue(response.promise)

      await act(async () => root.render(<Probe />))
      const pendingRequest = await startRetrieval('question before unmount')
      const retainedRunRetrieve = viewerState.runRetrievePreview
      const retainedClear = viewerState.clearRetrievePreview
      act(() => root.unmount())

      await act(async () => {
        retainedClear()
        const retainedCompletion = retainedRunRetrieve()
        if (settlement === 'resolve') response.resolve(retrievalResponse('doc-a', 'disposed citation'))
        else response.reject(new Error('disposed retrieval failed'))
        await Promise.all([pendingRequest.completion, retainedCompletion])
      })

      expect({
        requests: mocks.retrievePreview.mock.calls.length,
        reportedErrors: mocks.reportClientError.mock.calls.length,
      }).toEqual({ requests: 1, reportedErrors: 0 })
    },
  )

  it.each([
    { action: 'create', mode: 'save_rerun', save: 'resolve', reembed: 'resolve' },
    { action: 'edit', mode: 'save_reembed', save: 'resolve', reembed: 'resolve' },
    { action: 'create', mode: 'save_rerun', save: 'reject', reembed: 'unused' },
    { action: 'edit', mode: 'save_reembed', save: 'reject', reembed: 'unused' },
    { action: 'create', mode: 'save_reembed', save: 'resolve', reembed: 'reject' },
  ] as const)(
    'isolates a new editor after $action/$save/$reembed while preserving accepted writes',
    async ({ action, mode, save, reembed }) => {
      const savedA = chunk(action === 'edit' ? 'target-a' : 'created-a')
      const saveA = deferred<DocumentChunk>()
      const saveB = deferred<DocumentChunk>()
      const reembedA = deferred<{ reembedded: number }>()
      mocks.createChunk.mockImplementation((id: string) => (id === 'doc-a' ? saveA.promise : saveB.promise))
      mocks.updateChunk.mockReturnValue(saveA.promise)
      mocks.reembedChunks.mockReturnValue(reembedA.promise)

      await act(async () => root.render(<Probe />))
      await act(async () => {
        if (action === 'edit') viewerState.openEditChunk(chunk('target-a'))
        else viewerState.openCreateChunk()
        viewerState.setChunkEditorContent('original draft')
        viewerState.setRetrieveQuery('original question')
      })
      let originalSave!: Promise<void>
      act(() => {
        originalSave = viewerState.submitChunkEditor(mode)
      })
      await switchDocument('doc-b')
      await act(async () => {
        viewerState.openCreateChunk()
        viewerState.setChunkEditorContent('new draft')
      })
      let currentSave!: Promise<void>
      act(() => {
        currentSave = viewerState.submitChunkEditor()
      })

      if (save === 'reject') {
        await act(async () => {
          saveA.reject(new Error('original save failed'))
          await originalSave
        })
        expect(mocks.reembedChunks).not.toHaveBeenCalled()
      } else {
        await act(async () => saveA.resolve(savedA))
        expect(mocks.reembedChunks).toHaveBeenCalledWith('doc-a', { chunk_ids: [savedA.id], include_disabled: false })
        await act(async () => {
          if (reembed === 'reject') reembedA.reject(new Error('original reembed failed'))
          else reembedA.resolve({ reembedded: 1 })
          await originalSave
        })
      }

      expect(mutationSnapshot()).toMatchObject({
        documentId: 'doc-b',
        chunkCount: '10',
        chunks: '',
        editorOpen: 'true',
        editorContent: 'new draft',
        editorSubmitting: 'true',
      })
      expect(mocks.view.setHighlightChunk).not.toHaveBeenCalled()
      expect(mocks.retrievePreview).not.toHaveBeenCalled()
      expect(mocks.toastSuccess).not.toHaveBeenCalled()
      expect(mocks.toastError).not.toHaveBeenCalled()
      if (save === 'reject') {
        expect(mocks.reportClientError).toHaveBeenCalledWith('Save chunk failed', expect.any(Error), {
          tags: action === 'edit' ? { document_id: 'doc-a', chunk_id: 'target-a' } : { document_id: 'doc-a' },
        })
      } else if (reembed === 'reject') {
        expect(mocks.reportClientError).toHaveBeenCalledWith('Re-embed saved chunk failed', expect.any(Error), {
          tags: { document_id: 'doc-a', chunk_id: savedA.id },
        })
      } else {
        expect(mocks.reportClientError).not.toHaveBeenCalled()
      }

      await act(async () => {
        saveB.resolve(chunk('created-b'))
        await currentSave
      })
      expect(mutationSnapshot()).toMatchObject({
        documentId: 'doc-b',
        chunkCount: '11',
        chunks: 'created-b',
        editorOpen: 'false',
        editorSubmitting: 'false',
      })
      expect(mocks.view.setHighlightChunk).toHaveBeenLastCalledWith('created-b')
    },
  )

  it.each(['resolve', 'reject'] as const)(
    'isolates a current deletion after an old deletion %s',
    async (settlement) => {
      const original = deferred<void>()
      const current = deferred<void>()
      mocks.deleteChunk.mockImplementation((id: string) => (id === 'doc-a' ? original.promise : current.promise))
      await act(async () => root.render(<Probe />))
      act(() => viewerState.handleDeleteChunk(chunk('deleted-a')))
      await switchDocument('doc-b')
      act(() => viewerState.handleDeleteChunk(chunk('deleted-b')))
      await act(async () => {
        if (settlement === 'resolve') original.resolve(undefined)
        else original.reject(new Error('original deletion failed'))
      })
      expect(mutationSnapshot()).toMatchObject({ documentId: 'doc-b', chunkCount: '10', deleting: 'deleted-b' })
      expect(mocks.toastSuccess).not.toHaveBeenCalled()
      expect(mocks.toastError).not.toHaveBeenCalled()
      if (settlement === 'reject') {
        expect(mocks.reportClientError).toHaveBeenCalledWith('Delete chunk failed', expect.any(Error), {
          tags: { document_id: 'doc-a', chunk_id: 'deleted-a' },
        })
      } else {
        expect(mocks.reportClientError).not.toHaveBeenCalled()
      }
      await act(async () => current.resolve(undefined))
      expect(mutationSnapshot()).toMatchObject({ chunkCount: '9', deleting: '' })
    },
  )

  it.each(['resolve', 'reject'] as const)(
    'isolates current Q&A generation after an old generation %s',
    async (settlement) => {
      const original = deferred<DocumentQAGenerateResponse>()
      const current = deferred<DocumentQAGenerateResponse>()
      mocks.generateQa.mockImplementation((id: string) => (id === 'doc-a' ? original.promise : current.promise))
      await act(async () => root.render(<Probe />))
      let originalGeneration!: Promise<void>
      act(() => {
        originalGeneration = viewerState.runQaGeneration()
      })
      await switchDocument('doc-b')
      act(() => viewerState.handleQaDialogOpenChange(true))
      let currentGeneration!: Promise<void>
      act(() => {
        currentGeneration = viewerState.runQaGeneration()
      })
      await act(async () => {
        if (settlement === 'resolve') original.resolve({ ...qaResponse('doc-a'), created: 2, chunk_ids: ['qa-a'] })
        else original.reject(new Error('original Q&A failed'))
        await originalGeneration
      })
      expect(mutationSnapshot()).toMatchObject({
        documentId: 'doc-b',
        chunkCount: '10',
        qaOpen: 'true',
        qaSubmitting: 'true',
        qaDocument: '',
      })
      expect(mocks.view.setHighlightChunk).not.toHaveBeenCalled()
      expect(mocks.toastSuccess).not.toHaveBeenCalled()
      expect(mocks.toastError).not.toHaveBeenCalled()
      if (settlement === 'reject') {
        expect(mocks.reportClientError).toHaveBeenCalledWith('Generate document Q&A failed', expect.any(Error), {
          tags: { document_id: 'doc-a' },
        })
      } else {
        expect(mocks.reportClientError).not.toHaveBeenCalled()
      }
      await act(async () => {
        current.resolve(qaResponse('doc-b'))
        await currentGeneration
      })
      expect(mutationSnapshot()).toMatchObject({ chunkCount: '11', qaSubmitting: 'false', qaDocument: 'doc-b' })
    },
  )

  it('starts no server or clipboard work from retained disposed mutation actions', async () => {
    await act(async () => root.render(<Probe />))
    await act(async () => {
      viewerState.openCreateChunk()
      viewerState.setChunkEditorContent('original draft')
    })
    const { submitChunkEditor, handleDeleteChunk, runQaGeneration, copyChunkContent } = viewerState
    act(() => root.unmount())
    await act(async () => {
      handleDeleteChunk(chunk('deleted-a'))
      copyChunkContent('original content')
      await Promise.all([submitChunkEditor('save_reembed'), runQaGeneration()])
    })
    expect({
      saves: mocks.createChunk.mock.calls.length,
      updates: mocks.updateChunk.mock.calls.length,
      reembeds: mocks.reembedChunks.mock.calls.length,
      deletes: mocks.deleteChunk.mock.calls.length,
      qa: mocks.generateQa.mock.calls.length,
      clipboard: mocks.clipboardWrite.mock.calls.length,
    }).toEqual({ saves: 0, updates: 0, reembeds: 0, deletes: 0, qa: 0, clipboard: 0 })
  })

  it.each(['resolve', 'reject'] as const)('does not publish a previous visit clipboard %s', async (settlement) => {
    const copy = deferred<void>()
    mocks.clipboardWrite.mockReturnValue(copy.promise)
    await act(async () => root.render(<Probe />))
    act(() => viewerState.copyChunkContent('original content'))
    await switchDocument('doc-b')
    await act(async () => {
      if (settlement === 'resolve') copy.resolve(undefined)
      else copy.reject(new Error('original clipboard failed'))
    })
    expect(mocks.clipboardWrite).toHaveBeenCalledWith('original content')
    expect(mocks.toastSuccess).not.toHaveBeenCalled()
    expect(mocks.toastError).not.toHaveBeenCalled()
    expect(mocks.reportClientError).not.toHaveBeenCalled()
  })

  it('does not report an in-flight chunk search after unmount', async () => {
    const search = deferred<{ total: number; truncated: boolean; items: [] }>()
    mocks.view.activeTab = 'chunks'
    mocks.view.highlightChunkId = 'chunk-a'
    mocks.getChunkMatches.mockReturnValue(search.promise)
    await act(async () => root.render(<Probe />))
    await act(async () => viewerState.setChunkQuery('needle'))
    await vi.waitFor(() => expect(mocks.getChunkMatches).toHaveBeenCalledOnce())
    act(() => root.unmount())
    await act(async () => search.reject(new Error('disposed chunk search failed')))
    expect(mocks.reportClientError).not.toHaveBeenCalled()
  })

  it('does not report an in-flight chunk list after unmount', async () => {
    const list = deferred<{ total: number; items: DocumentChunk[] }>()
    mocks.view.activeTab = 'chunks'
    mocks.listChunks.mockReturnValue(list.promise)
    await act(async () => root.render(<Probe />))
    act(() => root.unmount())
    await act(async () => list.reject(new Error('disposed chunk list failed')))
    expect(mocks.reportClientError).not.toHaveBeenCalled()
  })

  it('only measures queued mutation frames for the current visit', async () => {
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    })
    await act(async () => root.render(<Probe />))
    await act(async () => viewerState.handleDeleteChunk(chunk('deleted-a')))
    await switchDocument('doc-b')
    act(() => frames.splice(0).forEach((callback) => callback(0)))
    expect(mocks.measure).not.toHaveBeenCalled()
    await act(async () => viewerState.handleDeleteChunk(chunk('deleted-b')))
    act(() => frames.splice(0).forEach((callback) => callback(0)))
    expect(mocks.measure).toHaveBeenCalledOnce()
  })

  it.each([
    {
      action: 'unchanged',
      requests: ['original question', 'original question'],
      loading: 'false',
      content: 'rerun citation',
      draft: 'original question',
    },
    {
      action: 'preview',
      requests: ['original question', 'new question'],
      loading: 'true',
      content: 'prior citation',
      draft: 'new question',
    },
    { action: 'clear', requests: ['original question'], loading: 'false', content: '', draft: 'original question' },
    {
      action: 'draft',
      requests: ['original question'],
      loading: 'false',
      content: 'prior citation',
      draft: 'unsubmitted draft',
    },
  ] as const)(
    'keeps preview intent $action while the original save and reembed finish',
    async ({ action, requests, loading, content, draft }) => {
      const initial = deferred<ReturnType<typeof retrievalResponse>>()
      const manual = deferred<ReturnType<typeof retrievalResponse>>()
      const reembed = deferred<{ reembedded: number }>()
      mocks.retrievePreview
        .mockReturnValueOnce(initial.promise)
        .mockImplementation((request: { query: string }) =>
          request.query === 'new question'
            ? manual.promise
            : Promise.resolve(retrievalResponse('doc-a', 'rerun citation')),
        )
      mocks.reembedChunks.mockReturnValue(reembed.promise)

      await act(async () => root.render(<Probe />))
      const initialRequest = await startRetrieval('original question')
      await act(async () => {
        initial.resolve(retrievalResponse('doc-a', 'prior citation'))
        await initialRequest.completion
        viewerState.openCreateChunk()
        viewerState.setChunkEditorContent('accepted draft')
      })
      let save!: Promise<void>
      await act(async () => {
        save = viewerState.submitChunkEditor('save_rerun')
      })
      expect(mocks.reembedChunks).toHaveBeenCalledWith('doc-a', { chunk_ids: ['created'], include_disabled: false })
      let manualRequest: { completion: Promise<void> } | null = null
      if (action === 'preview') manualRequest = await startRetrieval('new question')
      else if (action === 'clear') act(() => viewerState.clearRetrievePreview())
      else if (action === 'draft') await act(async () => viewerState.setRetrieveQuery('unsubmitted draft'))

      await act(async () => {
        reembed.resolve({ reembedded: 1 })
        await save
      })
      expect(mocks.retrievePreview.mock.calls.map(([request]) => request.query)).toEqual(requests)
      expect(retrievalSnapshot()).toEqual({ documentId: 'doc-a', loading, error: '', content })
      expect(viewerState.retrieveQuery).toBe(draft)
      if (manualRequest) {
        await act(async () => {
          manual.resolve(retrievalResponse('doc-a', 'new question citation'))
          await manualRequest.completion
        })
        expect(retrievalSnapshot()).toEqual({
          documentId: 'doc-a',
          loading: 'false',
          error: '',
          content: 'new question citation',
        })
      }
    },
  )

  it.each([
    { settlement: 'resolve', afterFirstCount: '4', finalCount: '5' },
    { settlement: 'reject', afterFirstCount: '3', finalCount: '4' },
  ] as const)(
    'preserves a reopened same-document editor after the first save $settlement',
    async ({ settlement, afterFirstCount, finalCount }) => {
      const firstSave = deferred<DocumentChunk>()
      const secondSave = deferred<DocumentChunk>()
      const firstReembed = deferred<{ reembedded: number }>()
      const secondReembed = deferred<{ reembedded: number }>()
      mocks.createChunk.mockReturnValueOnce(firstSave.promise).mockReturnValueOnce(secondSave.promise)
      mocks.reembedChunks.mockImplementation((_id: string, payload: { chunk_ids: string[] }) =>
        payload.chunk_ids[0] === 'created-first' ? firstReembed.promise : secondReembed.promise,
      )
      mocks.retrievePreview.mockResolvedValue(retrievalResponse('doc-a', 'current editor retrieval'))
      await act(async () => root.render(<Probe />))
      await act(async () => {
        viewerState.openCreateChunk()
        viewerState.setChunkEditorContent('first draft')
        viewerState.setRetrieveQuery('current question')
      })
      let firstCompletion!: Promise<void>
      act(() => {
        firstCompletion = viewerState.submitChunkEditor('save_rerun')
      })
      act(() => viewerState.handleChunkEditorOpenChange(false))
      await act(async () => {
        viewerState.openCreateChunk()
        viewerState.setChunkEditorContent('second draft')
      })
      let secondCompletion!: Promise<void>
      act(() => {
        secondCompletion = viewerState.submitChunkEditor('save_rerun')
      })

      if (settlement === 'resolve') {
        await act(async () => firstSave.resolve(chunk('created-first')))
        expect(mocks.reembedChunks).toHaveBeenCalledWith('doc-a', {
          chunk_ids: ['created-first'],
          include_disabled: false,
        })
        await act(async () => {
          firstReembed.resolve({ reembedded: 1 })
          await firstCompletion
        })
      } else {
        await act(async () => {
          firstSave.reject(new Error('first save failed'))
          await firstCompletion
        })
        expect(mocks.reportClientError).toHaveBeenCalledWith('Save chunk failed', expect.any(Error), {
          tags: { document_id: 'doc-a' },
        })
      }
      const afterFirst = mutationSnapshot()
      const highlightsAfterFirst = mocks.view.setHighlightChunk.mock.calls.length
      const previewsAfterFirst = mocks.retrievePreview.mock.calls.length
      const errorsAfterFirst = mocks.toastError.mock.calls.length

      await act(async () => secondSave.resolve(chunk('created-second')))
      await act(async () => {
        secondReembed.resolve({ reembedded: 1 })
        await secondCompletion
      })
      expect(afterFirst).toMatchObject({
        documentId: 'doc-a',
        chunkCount: afterFirstCount,
        editorOpen: 'true',
        editorContent: 'second draft',
        editorSubmitting: 'true',
      })
      expect({ highlightsAfterFirst, previewsAfterFirst, errorsAfterFirst }).toEqual({
        highlightsAfterFirst: 0,
        previewsAfterFirst: 0,
        errorsAfterFirst: 0,
      })
      expect(mutationSnapshot()).toMatchObject({
        chunkCount: finalCount,
        editorOpen: 'false',
        editorSubmitting: 'false',
      })
      expect(mocks.view.setHighlightChunk).toHaveBeenLastCalledWith('created-second')
      expect(mocks.retrievePreview).toHaveBeenCalledOnce()
      expect(retrievalSnapshot().content).toBe('current editor retrieval')
    },
  )

  it.each([
    { settlement: 'resolve', afterFirstCount: '4', finalCount: '5' },
    { settlement: 'reject', afterFirstCount: '3', finalCount: '4' },
  ] as const)(
    'owns a reopened same-document Q&A dialog after the first generation $settlement',
    async ({ settlement, afterFirstCount, finalCount }) => {
      const first = deferred<DocumentQAGenerateResponse>()
      const second = deferred<DocumentQAGenerateResponse>()
      mocks.generateQa.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
      await act(async () => root.render(<Probe />))
      act(() => viewerState.handleQaDialogOpenChange(true))
      let firstCompletion!: Promise<void>
      act(() => {
        firstCompletion = viewerState.runQaGeneration()
      })
      act(() => viewerState.handleQaDialogOpenChange(false))
      act(() => viewerState.handleQaDialogOpenChange(true))
      const busyOnReopen = mutationSnapshot().qaSubmitting
      await act(async () => {
        if (settlement === 'resolve') first.resolve({ ...qaResponse('doc-a'), chunk_ids: ['qa-first'] })
        else first.reject(new Error('first Q&A failed'))
        await firstCompletion
      })
      const afterFirst = mutationSnapshot()
      const highlightsAfterFirst = mocks.view.setHighlightChunk.mock.calls.length
      const errorsAfterFirst = mocks.toastError.mock.calls.length
      let secondCompletion!: Promise<void>
      act(() => {
        secondCompletion = viewerState.runQaGeneration()
      })
      await act(async () => {
        second.resolve({ ...qaResponse('doc-a'), chunk_ids: ['qa-second'] })
        await secondCompletion
      })
      expect(busyOnReopen).toBe('true')
      expect(afterFirst).toMatchObject({
        documentId: 'doc-a',
        chunkCount: afterFirstCount,
        qaOpen: 'true',
        qaSubmitting: 'false',
        qaChunks: '',
      })
      expect({ highlightsAfterFirst, errorsAfterFirst }).toEqual({ highlightsAfterFirst: 0, errorsAfterFirst: 0 })
      expect(mutationSnapshot()).toMatchObject({ chunkCount: finalCount, qaSubmitting: 'false', qaChunks: 'qa-second' })
      expect(mocks.view.setHighlightChunk).toHaveBeenLastCalledWith('qa-second')
    },
  )

  it('keeps a later delete busy and a newer selection when an earlier same-document delete finishes', async () => {
    const first = deferred<void>()
    const second = deferred<void>()
    mocks.deleteChunk.mockImplementation((_id: string, chunkId: string) =>
      chunkId === 'deleted-a' ? first.promise : second.promise,
    )
    mocks.view.highlightChunkId = 'deleted-a'
    await act(async () => root.render(<Probe />))
    act(() => viewerState.handleDeleteChunk(chunk('deleted-a')))
    mocks.view.highlightChunkId = 'selected-c'
    await act(async () => root.render(<Probe />))
    act(() => viewerState.handleDeleteChunk(chunk('deleted-b')))
    await act(async () => first.resolve(undefined))
    const afterFirst = mutationSnapshot()
    const highlightsAfterFirst = mocks.view.setHighlightChunk.mock.calls.length
    await act(async () => second.resolve(undefined))
    expect(afterFirst).toMatchObject({ chunkCount: '2', deleting: 'deleted-b' })
    expect(highlightsAfterFirst).toBe(0)
    expect(mutationSnapshot()).toMatchObject({ chunkCount: '1', deleting: '' })
    expect(mocks.view.setHighlightChunk).not.toHaveBeenCalled()
  })

  it('keeps the latest retrieval failure when an earlier response arrives last', async () => {
    const earlier = deferred<ReturnType<typeof retrievalResponse>>()
    const latest = deferred<ReturnType<typeof retrievalResponse>>()
    mocks.retrievePreview.mockReturnValueOnce(earlier.promise).mockReturnValueOnce(latest.promise)

    await act(async () => root.render(<Probe />))
    const earlierRequest = await startRetrieval('earlier question')
    const latestRequest = await startRetrieval('latest question')

    await act(async () => {
      latest.reject(new Error('current retrieval failed'))
      await latestRequest.completion
    })
    await act(async () => {
      earlier.resolve(retrievalResponse('doc-a', 'earlier citation'))
      await earlierRequest.completion
    })

    expect(retrievalSnapshot()).toEqual({
      documentId: 'doc-a',
      loading: 'false',
      error: '检索测试失败，请稍后重试',
      content: '',
    })
  })
})
