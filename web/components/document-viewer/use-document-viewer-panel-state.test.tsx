// @vitest-environment happy-dom

import { act, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DocumentChunk, DocumentQAGenerateResponse } from '@/types/backend'
import type { DocumentViewLayout, DocumentViewSourceContext, HighlightRange } from '@/store/document-view'

const mocks = vi.hoisted(() => ({
  getDocument: vi.fn(),
  getParsedContent: vi.fn(),
  getCachedContent: vi.fn(),
  cacheContent: vi.fn(),
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
  downloadDocument: vi.fn(),
  downloadBlob: vi.fn(),
  sessionKey: 'download-session-a',
  sessionListeners: new Set<() => void>(),
  virtualizerOptions: null as { count: number; getItemKey?: (index: number) => string | number | bigint } | null,
  view: {
    authScope: 'test-scope',
    isOpen: true,
    documentId: 'doc-a' as string | null,
    highlightChunkId: null as string | null,
    highlightRange: null as HighlightRange | null,
    previewAnchor: null,
    sourceContext: null as DocumentViewSourceContext | null,
    activeTab: 'preview',
    documentLayouts: {},
    getDocumentLayout: vi.fn<(documentId: string | null | undefined) => DocumentViewLayout | null>(() => null),
    closeDocument: vi.fn(),
    setActiveTab: vi.fn(),
    setDocumentLayout: vi.fn(),
    setHighlightChunk: vi.fn(),
  },
}))

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: (options: NonNullable<typeof mocks.virtualizerOptions>) => {
    mocks.virtualizerOptions = options
    return { getVirtualItems: () => [], getTotalSize: () => 0, measure: mocks.measure, scrollToIndex: vi.fn() }
  },
}))
vi.mock('sonner', () => ({
  toast: { error: mocks.toastError, success: mocks.toastSuccess, message: mocks.toastMessage },
}))
vi.mock('@/lib/download', () => ({ downloadBlob: mocks.downloadBlob }))
vi.mock('@/lib/auth-storage', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/auth-storage')>()),
  getAuthSessionKey: () => mocks.sessionKey,
  subscribeAuthSession: (listener: () => void) => {
    mocks.sessionListeners.add(listener)
    return () => {
      mocks.sessionListeners.delete(listener)
    }
  },
}))
vi.mock('@/lib/api', () => ({
  documentApi: {
    download: mocks.downloadDocument,
    get: mocks.getDocument,
    getParsedContent: mocks.getParsedContent,
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
  getDocContentFromCache: mocks.getCachedContent,
  cacheDocContentIfMissing: mocks.cacheContent,
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
    mocks.downloadDocument.mockReset().mockResolvedValue(new Blob(['actual-document']))
    mocks.downloadBlob.mockReset()
    mocks.sessionKey = 'download-session-a'
    mocks.getDocument.mockImplementation(async (id: string) => ({
      id,
      status: 'completed',
      filename: id + '.pdf',
      chunk_count: id === 'doc-a' ? 3 : 10,
    }))
    mocks.retrievePreview.mockReset()
    mocks.getParsedContent.mockReset().mockResolvedValue({ available: false })
    mocks.getCachedContent.mockReset().mockResolvedValue(null)
    mocks.cacheContent.mockReset().mockResolvedValue(undefined)
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
    mocks.virtualizerOptions = null
    mocks.view.setHighlightChunk.mockClear()
    mocks.view.getDocumentLayout.mockReset()
    mocks.view.getDocumentLayout.mockReturnValue(null)
    mocks.view.setDocumentLayout.mockReset()
    mocks.view.isOpen = true
    mocks.view.authScope = 'test-scope'
    mocks.view.documentId = 'doc-a'
    mocks.view.highlightChunkId = null
    mocks.view.highlightRange = null
    mocks.view.sourceContext = null
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

  it('prepares downloads on demand from any tab and starts one browser download for repeated input', async () => {
    mocks.view.activeTab = 'text'
    await act(async () => root.render(<Probe />))
    expect(mocks.downloadDocument).not.toHaveBeenCalled()
    const pending = deferred<Blob>()
    mocks.downloadDocument.mockReturnValueOnce(pending.promise)
    let first!: Promise<void>
    let second!: Promise<void>
    act(() => {
      first = viewerState.downloadOriginalFile()
      second = viewerState.downloadOriginalFile()
    })
    expect(viewerState.downloadLoading).toBe(true)
    expect(mocks.downloadBlob).not.toHaveBeenCalled()
    const blob = new Blob(['actual-document'])
    await act(async () => {
      pending.resolve(blob)
      await Promise.all([first, second])
    })
    expect(mocks.downloadDocument).toHaveBeenCalledExactlyOnceWith('doc-a', { inline: false })
    expect(mocks.downloadBlob).toHaveBeenCalledExactlyOnceWith('doc-a.pdf', blob)
    expect(viewerState.downloadLoading).toBe(false)
  })

  it('keeps download failure separate from a missing file and retries the current document', async () => {
    await act(async () => root.render(<Probe />))
    mocks.downloadDocument.mockRejectedValueOnce(new Error('503'))
    await act(async () => viewerState.downloadOriginalFile())
    expect(viewerState.downloadError).toBe('error')
    expect(viewerState.downloadLoading).toBe(false)
    expect(mocks.downloadBlob).not.toHaveBeenCalled()
    await act(async () => viewerState.downloadOriginalFile())
    expect(viewerState.downloadError).toBeNull()
    expect(mocks.downloadBlob).toHaveBeenCalledOnce()
  })

  it('does not download the previous document or clear the new document operation', async () => {
    await act(async () => root.render(<Probe />))
    const first = deferred<Blob>()
    const second = deferred<Blob>()
    mocks.downloadDocument.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    let firstOperation!: Promise<void>
    act(() => {
      firstOperation = viewerState.downloadOriginalFile()
    })
    await switchDocument('doc-b')
    let secondOperation!: Promise<void>
    act(() => {
      secondOperation = viewerState.downloadOriginalFile()
    })
    await act(async () => {
      first.resolve(new Blob(['old-document']))
      await firstOperation
    })
    expect(mocks.downloadBlob).not.toHaveBeenCalled()
    expect(viewerState.downloadLoading).toBe(true)
    const blob = new Blob([])
    await act(async () => {
      second.resolve(blob)
      await secondOperation
    })
    expect(mocks.downloadBlob).toHaveBeenCalledExactlyOnceWith('doc-b.pdf', blob)
    expect(viewerState.downloadLoading).toBe(false)
  })

  it('allows the new session to download while the previous session request is still pending', async () => {
    await act(async () => root.render(<Probe />))
    const previous = deferred<Blob>()
    const current = deferred<Blob>()
    mocks.downloadDocument.mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    let previousOperation!: Promise<void>
    act(() => {
      previousOperation = viewerState.downloadOriginalFile()
    })
    act(() => {
      mocks.sessionKey = 'download-session-b'
      for (const notify of mocks.sessionListeners) notify()
    })
    expect(viewerState.downloadLoading).toBe(false)
    let currentOperation!: Promise<void>
    act(() => {
      currentOperation = viewerState.downloadOriginalFile()
    })

    await act(async () => {
      previous.resolve(new Blob(['previous-session']))
      await previousOperation
    })

    expect(mocks.downloadBlob).not.toHaveBeenCalled()
    expect(viewerState.downloadLoading).toBe(true)
    const blob = new Blob(['current-session'])
    await act(async () => {
      current.resolve(blob)
      await currentOperation
    })
    expect(mocks.downloadBlob).toHaveBeenCalledExactlyOnceWith('doc-a.pdf', blob)
  })

  it('keeps actual virtual row identities when a preceding server chunk is removed', async () => {
    const { Virtualizer } = await vi.importActual<typeof import('@tanstack/react-virtual')>('@tanstack/react-virtual')
    mocks.view.activeTab = 'chunks'
    mocks.listChunks.mockResolvedValue({ total: 2, items: [chunk('chunk-a'), chunk('chunk-b')] })
    await act(async () => root.render(<Probe />))
    function keys() {
      const options = mocks.virtualizerOptions!
      const virtualizer = new Virtualizer({
        count: options.count,
        getItemKey: options.getItemKey,
        getScrollElement: () => null,
        estimateSize: () => 100,
        initialRect: { width: 500, height: 500 },
        initialOffset: 0,
        observeElementRect: () => undefined,
        observeElementOffset: () => undefined,
        scrollToFn: () => undefined,
      })
      return virtualizer.getVirtualItems().map((item) => item.key)
    }
    expect(keys()).toEqual(['chunk-a', 'chunk-b'])
    await act(async () => viewerState.handleDeleteChunk(chunk('chunk-a')))
    expect(keys()).toEqual(['chunk-b'])
  })

  it('sends exact chunk editor content while validating nonempty text separately', async () => {
    await act(async () => root.render(<Probe />))
    act(() => {
      viewerState.openCreateChunk()
      viewerState.setChunkEditorContent('  const value = 1\n\n')
    })
    await act(async () => viewerState.submitChunkEditor())
    expect(mocks.createChunk).toHaveBeenCalledWith(
      'doc-a',
      expect.objectContaining({ content: '  const value = 1\n\n' }),
    )
  })

  it.each([
    { page: '-1', start: '', end: '' },
    { page: '1.5', start: '', end: '' },
    { page: 'abc', start: '', end: '' },
    { page: '100001', start: '', end: '' },
    { page: '', start: '-1', end: '' },
    { page: '', start: '2.5', end: '' },
    { page: '', start: 'invalid', end: '' },
    { page: '', start: '', end: '10000001' },
  ])(
    'keeps invalid position input $page/$start/$end instead of silently correcting it',
    async ({ page, start, end }) => {
      await act(async () => root.render(<Probe />))
      act(() => {
        viewerState.openCreateChunk()
        viewerState.setChunkEditorContent('Draft text')
        viewerState.setChunkEditorPageNumber(page)
        viewerState.setChunkEditorStartChar(start)
        viewerState.setChunkEditorEndChar(end)
      })
      await act(async () => viewerState.submitChunkEditor())
      expect(mocks.createChunk).not.toHaveBeenCalled()
      expect(viewerState.chunkEditorOpen).toBe(true)
      expect(viewerState.chunkEditorPageNumber).toBe(page)
      expect(viewerState.chunkEditorStartChar).toBe(start)
      expect(viewerState.chunkEditorEndChar).toBe(end)
      expect(mocks.toastError).toHaveBeenCalled()
    },
  )

  it('preserves zero positions and omits only truly blank optional fields', async () => {
    await act(async () => root.render(<Probe />))
    act(() => {
      viewerState.openCreateChunk()
      viewerState.setChunkEditorContent('Draft')
      viewerState.setChunkEditorPageNumber('0')
      viewerState.setChunkEditorStartChar('0')
      viewerState.setChunkEditorEndChar('2')
    })
    await act(async () => viewerState.submitChunkEditor())
    expect(mocks.createChunk).toHaveBeenCalledWith(
      'doc-a',
      expect.objectContaining({ page_number: 0, start_char: 0, end_char: 2 }),
    )
  })

  it.each(['update', 'delete', 'create'] as const)(
    'keeps an accepted %s when a previous page request returns later',
    async (operation) => {
      let serverItems = Array.from({ length: 2001 }, (_, index) => ({ ...chunk(`page-${index}`), chunk_index: index }))
      const oldLastPage = deferred<{ total: number; items: DocumentChunk[] }>()
      let held = false
      mocks.view.activeTab = 'chunks'
      mocks.view.highlightChunkId = 'page-1'
      mocks.listChunks.mockImplementation(async (_id: string, { skip, limit }: { skip: number; limit: number }) => {
        if (skip === 2000 && !held) {
          held = true
          return oldLastPage.promise
        }
        return { total: serverItems.length, items: serverItems.slice(skip, skip + limit) }
      })
      mocks.updateChunk.mockImplementation(async () => {
        const updated = { ...serverItems[0], content: 'Approved update' }
        serverItems = [updated, ...serverItems.slice(1)]
        return updated
      })
      mocks.deleteChunk.mockImplementation(async () => {
        serverItems = serverItems.slice(1)
      })
      mocks.createChunk.mockImplementation(async () => {
        const created = { ...chunk('approved-create'), chunk_index: serverItems.length }
        serverItems = [...serverItems, created]
        return created
      })
      await act(async () => root.render(<Probe />))
      await act(async () => viewerState.setLoadAllChunks(true))
      expect(held).toBe(true)
      const before = serverItems
      if (operation === 'delete') await act(async () => viewerState.handleDeleteChunk(before[0]))
      else {
        act(() => {
          if (operation === 'create') viewerState.openCreateChunk()
          else viewerState.openEditChunk(before[0])
          viewerState.setChunkEditorContent('Approved update')
        })
        await act(async () => viewerState.submitChunkEditor())
      }
      await act(async () => oldLastPage.resolve({ total: before.length, items: before.slice(2000) }))
      expect(viewerState.chunks.map((item) => [item.id, item.content])).toEqual(
        serverItems.map((item) => [item.id, item.content]),
      )
      expect(viewerState.chunksLoaded).toBe(true)
    },
  )

  it.each([
    { pairs: '', chars: '12000' },
    { pairs: '0', chars: '12000' },
    { pairs: '1.5', chars: '12000' },
    { pairs: '201', chars: '12000' },
    { pairs: 'abc', chars: '12000' },
    { pairs: '20', chars: '' },
    { pairs: '20', chars: '499' },
    { pairs: '20', chars: '200001' },
  ])('preserves invalid Q&A settings $pairs/$chars instead of clamping them', async ({ pairs, chars }) => {
    await act(async () => root.render(<Probe />))
    act(() => {
      viewerState.setQaNumPairsInput(pairs)
      viewerState.setQaMaxSourceCharsInput(chars)
    })
    await act(async () => viewerState.runQaGeneration())
    expect(mocks.generateQa).not.toHaveBeenCalled()
    expect(viewerState.qaNumPairsInput).toBe(pairs)
    expect(viewerState.qaMaxSourceCharsInput).toBe(chars)
    expect(mocks.toastError).toHaveBeenCalled()
  })

  it('passes validated Q&A integers and genuine false flags unchanged', async () => {
    await act(async () => root.render(<Probe />))
    act(() => {
      viewerState.setQaNumPairsInput('1')
      viewerState.setQaMaxSourceCharsInput('500')
      viewerState.setQaReplaceExisting(false)
      viewerState.setQaPreferLlm(false)
    })
    await act(async () => viewerState.runQaGeneration())
    expect(mocks.generateQa).toHaveBeenCalledWith(
      'doc-a',
      expect.objectContaining({ num_pairs: 1, max_source_chars: 500, replace_existing: false, prefer_llm: false }),
    )
  })

  it.each(['', '  \n\n'])('allows an explicitly valid update body %j without normalizing it', async (content) => {
    await act(async () => root.render(<Probe />))
    act(() => {
      viewerState.openEditChunk(chunk('target'))
      viewerState.setChunkEditorContent(content)
    })
    await act(async () => viewerState.submitChunkEditor())
    expect(mocks.updateChunk).toHaveBeenCalledWith('doc-a', 'target', expect.objectContaining({ content }))
  })

  it('retains the latest accepted entity response when saves of one chunk finish out of order', async () => {
    const first = deferred<DocumentChunk>()
    const second = deferred<DocumentChunk>()
    mocks.view.activeTab = 'chunks'
    mocks.listChunks.mockResolvedValue({ total: 1, items: [chunk('target')] })
    mocks.updateChunk.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    await act(async () => root.render(<Probe />))
    act(() => {
      viewerState.openEditChunk(chunk('target'))
      viewerState.setChunkEditorContent('First edit')
    })
    let firstSave!: Promise<void>
    act(() => {
      firstSave = viewerState.submitChunkEditor()
    })
    act(() => {
      viewerState.openEditChunk(chunk('target'))
      viewerState.setChunkEditorContent('Second edit')
    })
    let secondSave!: Promise<void>
    act(() => {
      secondSave = viewerState.submitChunkEditor()
    })
    await act(async () => {
      second.resolve(chunk('target', 'Second edit'))
      await secondSave
    })
    await act(async () => {
      first.resolve(chunk('target', 'First edit'))
      await firstSave
    })
    expect(viewerState.chunks[0].content).toBe('Second edit')
  })

  it('does not let an earlier highlight read replace a confirmed edit from a loaded row', async () => {
    const read = deferred<DocumentChunk>()
    mocks.view.activeTab = 'chunks'
    mocks.view.highlightChunkId = 'target'
    mocks.getChunk.mockReturnValue(read.promise)
    mocks.listChunks.mockResolvedValue({ total: 1, items: [chunk('target', 'Original')] })
    mocks.updateChunk.mockResolvedValue(chunk('target', 'Approved edit'))
    await act(async () => root.render(<Probe />))
    await act(async () => viewerState.setLoadAllChunks(true))
    act(() => {
      viewerState.openEditChunk(viewerState.chunks[0])
      viewerState.setChunkEditorContent('Approved edit')
    })
    await act(async () => viewerState.submitChunkEditor())
    await act(async () => read.resolve(chunk('target', 'Original')))
    expect(viewerState.highlightContent).toMatchObject({ kind: 'chunk', chunk: { content: 'Approved edit' } })
    expect(viewerState.highlightChunkLoading).toBe(false)
  })

  it('does not expose another selected chunk while the current chunk is loading', async () => {
    const pending = deferred<DocumentChunk>()
    mocks.view.highlightChunkId = 'chunk-a'
    await act(async () => root.render(<Probe />))
    expect(viewerState.highlightContent).toMatchObject({ kind: 'chunk', chunk: { id: 'chunk-a' } })
    mocks.getChunk.mockReturnValue(pending.promise)
    mocks.view.highlightChunkId = 'chunk-b'
    await act(async () => root.render(<Probe />))
    expect(viewerState.highlightContent).toBeNull()
    await act(async () => pending.resolve(chunk('chunk-b')))
    expect(viewerState.highlightContent).toMatchObject({ kind: 'chunk', chunk: { id: 'chunk-b' } })
  })

  it('reports a failed selected-chunk read without relabeling an unrelated citation', async () => {
    mocks.view.highlightChunkId = 'chunk-b'
    mocks.view.sourceContext = {
      kind: 'chat-citation',
      messageId: 'message-a',
      documentId: 'doc-a',
      chunkId: 'chunk-a',
      chunkContent: 'Citation A text',
      pageNumber: 2,
    }
    mocks.getChunk.mockRejectedValueOnce(new Error('Selected chunk denied')).mockResolvedValue(chunk('chunk-b'))
    await act(async () => root.render(<Probe />))
    expect(viewerState.highlightContent).toBeNull()
    expect(viewerState.highlightChunkError).toBe('error')
    await act(async () => viewerState.retryHighlightedChunk())
    expect(viewerState.highlightContent).toMatchObject({ kind: 'chunk', chunk: { id: 'chunk-b' } })
    expect(viewerState.highlightChunkError).toBeNull()
  })

  it('retains a matching citation excerpt while exposing its actual read failure', async () => {
    mocks.view.highlightChunkId = 'chunk-a'
    mocks.view.sourceContext = {
      kind: 'chat-citation',
      messageId: 'message-a',
      documentId: 'doc-a',
      chunkId: 'chunk-a',
      chunkContent: 'Matching citation text',
      pageNumber: 2,
    }
    mocks.getChunk.mockRejectedValue(new Error('Selected chunk denied'))
    await act(async () => root.render(<Probe />))
    expect(viewerState.highlightContent).toMatchObject({
      kind: 'citation',
      snapshot: { content: 'Matching citation text' },
    })
    expect(viewerState.highlightChunkError).toBe('error')
    expect(mocks.reportClientError).toHaveBeenCalled()
  })

  it.each([undefined, 0])(
    'keeps citation snapshot positions without inventing a server chunk: %s',
    async (position) => {
      mocks.view.highlightChunkId = 'citation-target'
      mocks.view.sourceContext = {
        kind: 'chat-citation',
        messageId: 'message-a',
        documentId: 'doc-a',
        chunkId: 'citation-target',
        chunkContent: '  quoted text\n\n',
        chunkIndex: position,
        pageNumber: position,
      }
      mocks.getChunk.mockRejectedValue(new Error('Chunk unavailable'))
      await act(async () => root.render(<Probe />))
      expect(viewerState.highlightContent).toMatchObject({
        kind: 'citation',
        snapshot: {
          chunkId: 'citation-target',
          content: '  quoted text\n\n',
          chunkIndex: position,
          pageNumber: position,
        },
      })
      expect(viewerState.highlightChunkError).not.toBeNull()
    },
  )

  it('retains an actual empty citation excerpt after its server chunk read fails', async () => {
    mocks.view.highlightChunkId = 'empty-citation'
    mocks.view.sourceContext = {
      kind: 'chat-citation',
      messageId: 'message-a',
      documentId: 'doc-a',
      chunkId: 'empty-citation',
      chunkContent: '',
    }
    mocks.getChunk.mockRejectedValue(new Error('Chunk unavailable'))
    await act(async () => root.render(<Probe />))
    expect(viewerState.highlightContent).toMatchObject({
      kind: 'citation',
      snapshot: { chunkId: 'empty-citation', content: '' },
    })
    expect(viewerState.highlightChunkError).not.toBeNull()
  })

  it('converts only the text-view range while keeping the original API link coordinates', async () => {
    mocks.view.activeTab = 'text'
    mocks.view.highlightRange = { start: 1, end: 3 }
    mocks.getParsedContent.mockResolvedValue({
      document_id: 'doc-a',
      available: true,
      markdown_content: '😀AB',
      original_markdown_content: '😀AB',
      markdown_truncated: false,
      original_markdown_truncated: false,
    })
    await act(async () => root.render(<Probe />))
    expect(viewerState.textHighlightRange).toEqual({ start: 2, end: 4 })
    expect(mocks.view.highlightRange).toEqual({ start: 1, end: 3 })
    await act(async () => viewerState.copyChunkLink({ ...chunk('source-unit'), start_char: 1, end_char: 3 }))
    const link = new URL(mocks.clipboardWrite.mock.calls[0][0])
    expect(link.searchParams.get('start')).toBe('1')
    expect(link.searchParams.get('end')).toBe('3')
  })

  it('does not let delayed cached text replace a completed server response', async () => {
    const cached = deferred<{
      id: string
      markdownContent: string
      originalMarkdownContent: string
      updatedAt: number
    }>()
    const response = {
      document_id: 'doc-a',
      available: true,
      markdown_content: 'Fresh server body',
      original_markdown_content: '',
      markdown_truncated: false,
      original_markdown_truncated: false,
      max_chars: 200_000,
      persisted_meta: {},
    }
    mocks.view.activeTab = 'text'
    mocks.getCachedContent.mockReturnValue(cached.promise)
    mocks.getParsedContent.mockResolvedValue(response)
    await act(async () => root.render(<Probe />))
    await act(async () =>
      cached.resolve({
        id: 'doc-a',
        markdownContent: 'Old cached body',
        originalMarkdownContent: 'Old raw',
        updatedAt: 0,
      }),
    )
    expect(viewerState.parsedContent).toBe(response)
  })

  it('reports document-read failure and retries without clearing an existing draft', async () => {
    mocks.getDocument.mockRejectedValueOnce(new Error('Document read denied'))
    await act(async () => root.render(<Probe />))
    expect(viewerState.documentError).toBe('error')
    act(() => viewerState.setChunkEditorContent('Unsubmitted draft'))
    await act(async () => viewerState.retryDocument())
    expect(viewerState.doc?.id).toBe('doc-a')
    expect(viewerState.documentError).toBeNull()
    expect(viewerState.chunkEditorContent).toBe('Unsubmitted draft')
  })

  it('reports a failed chunk load and completes a real retry', async () => {
    mocks.view.activeTab = 'chunks'
    mocks.listChunks
      .mockRejectedValueOnce(new Error('Chunk read denied'))
      .mockResolvedValue({ total: 1, items: [chunk('recovered')] })
    await act(async () => root.render(<Probe />))
    expect(viewerState.chunksError).toBe('error')
    expect(viewerState.chunksLoaded).toBe(false)
    await act(async () => viewerState.retryChunks())
    expect(viewerState.chunks.map((item) => item.id)).toEqual(['recovered'])
    expect(viewerState.chunksError).toBeNull()
    expect(viewerState.chunksLoaded).toBe(true)
  })

  it('shows failed search rather than zero results and retries the same query', async () => {
    mocks.view.activeTab = 'chunks'
    mocks.view.highlightChunkId = 'chunk-a'
    mocks.getChunkMatches
      .mockRejectedValueOnce(new Error('Search read denied'))
      .mockResolvedValue({ total: 1, truncated: false, items: [{ id: 'matched' }] })
    await act(async () => root.render(<Probe />))
    await act(async () => viewerState.setChunkQuery('needle'))
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 280))
    })
    expect(viewerState.chunkMatchSummary).toBe('搜索失败')
    expect(viewerState.serverMatchError).toBe('error')
    await act(async () => viewerState.retryChunkSearch())
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 280))
    })
    expect(viewerState.matchChunkIds).toEqual(['matched'])
    expect(viewerState.chunkMatchSummary).toBe('1/1')
  })

  it('loads every page when the document has more than fifty thousand chunks', async () => {
    const items = Array.from({ length: 50_001 }, (_, index) => chunk(`chunk-${index}`))
    mocks.view.activeTab = 'chunks'
    mocks.listChunks.mockImplementation(async (_id: string, { skip, limit }: { skip: number; limit: number }) => ({
      total: items.length,
      items: items.slice(skip, skip + limit),
    }))
    await act(async () => root.render(<Probe />))
    expect(viewerState.chunks).toHaveLength(items.length)
    expect(viewerState.chunksLoaded).toBe(true)
  })

  it('copies exact chunk content including indentation and blank lines', async () => {
    await act(async () => root.render(<Probe />))
    await act(async () => viewerState.copyChunkContent('  const value = 1\n\n'))
    expect(mocks.clipboardWrite).toHaveBeenCalledWith('  const value = 1\n\n')
  })

  it('copies the current document link with a legitimate zero start offset', async () => {
    await act(async () => root.render(<Probe />))
    await act(async () => viewerState.copyChunkLink({ ...chunk('selected'), start_char: 0, end_char: 5 }))
    const link = new URL(mocks.clipboardWrite.mock.calls[0][0])
    expect(link.origin).toBe(window.location.origin)
    expect(link.pathname).toBe('/')
    expect(Object.fromEntries(link.searchParams)).toEqual({ doc: 'doc-a', chunk: 'selected', start: '0', end: '5' })
    expect(mocks.toastSuccess).toHaveBeenCalledWith('已复制定位链接')
  })

  it('reports a failed clipboard write without claiming the link was copied', async () => {
    const failure = new Error('Clipboard permission denied')
    mocks.clipboardWrite.mockRejectedValue(failure)
    await act(async () => root.render(<Probe />))
    await act(async () => viewerState.copyChunkLink(chunk('selected')))
    expect(mocks.toastSuccess).not.toHaveBeenCalled()
    expect(mocks.toastError).toHaveBeenCalledWith('复制失败')
    expect(mocks.reportClientError).toHaveBeenCalledWith('Copy document viewer text failed', failure)
  })

  it.each(['markdown_truncated', 'original_markdown_truncated'] as const)(
    'shows the preview while excluding %s content from the complete cache',
    async (field) => {
      const content = {
        document_id: 'doc-a',
        available: true,
        markdown_content: 'Short preview',
        original_markdown_content: 'Short original',
        markdown_truncated: false,
        original_markdown_truncated: false,
        [field]: true,
        max_chars: 200_000,
        persisted_meta: {},
      }
      mocks.view.activeTab = 'text'
      mocks.getParsedContent.mockResolvedValue(content)
      await act(async () => root.render(<Probe />))
      expect(viewerState.parsedContent).toBe(content)
      expect(mocks.cacheContent).not.toHaveBeenCalled()
    },
  )

  it('keeps complete viewer content when its optional browser cache write fails', async () => {
    const content = {
      document_id: 'doc-a',
      available: true,
      markdown_content: '',
      original_markdown_content: '',
      markdown_truncated: false,
      original_markdown_truncated: false,
      max_chars: 200_000,
      persisted_meta: {},
    }
    const error = new Error('Optional cache write denied')
    mocks.view.activeTab = 'text'
    mocks.getParsedContent.mockResolvedValue(content)
    mocks.cacheContent.mockRejectedValue(error)
    await act(async () => root.render(<Probe />))
    expect(mocks.cacheContent).toHaveBeenCalledWith({ id: 'doc-a', markdownContent: '', originalMarkdownContent: '' })
    expect(viewerState.parsedContent).toBe(content)
    expect(viewerState.parsedContentError).toBeNull()
    expect(mocks.reportClientError).toHaveBeenCalledWith('Cache parsed document content failed', error)
  })

  it('reports a failed optional cache warmup without blocking document loading', async () => {
    const error = new Error('Cached content unreadable')
    mocks.getCachedContent.mockRejectedValue(error)
    await act(async () => root.render(<Probe />))
    expect(viewerState.doc?.id).toBe('doc-a')
    expect(mocks.reportClientError).toHaveBeenCalledWith('Read cached document content failed', error)
    expect(viewerState.parsedContentError).toBeNull()
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

  it('restores saved layout in StrictMode and keeps actual document preferences separate', async () => {
    const { useDocumentView } = await vi.importActual<typeof import('@/store/document-view')>('@/store/document-view')
    const savedLayouts = useDocumentView.getState().documentLayouts
    useDocumentView.setState({
      documentLayouts: {
        'doc-a': { isExpanded: true, textMode: 'original', textScrollTop: 0 },
        'doc-b': { isExpanded: false, textMode: 'cleaned', panelWidthPx: 720 },
      },
    })
    mocks.view.getDocumentLayout.mockImplementation(useDocumentView.getState().getDocumentLayout)
    mocks.view.setDocumentLayout.mockImplementation(useDocumentView.getState().setDocumentLayout)
    try {
      await act(async () =>
        root.render(
          <StrictMode>
            <Probe />
          </StrictMode>,
        ),
      )
      expect(viewerState.isExpanded).toBe(true)
      expect(viewerState.textMode).toBe('original')
      expect(useDocumentView.getState().getDocumentLayout('doc-a')).toMatchObject({
        isExpanded: true,
        textMode: 'original',
        textScrollTop: 0,
      })
      act(() => {
        viewerState.setIsExpanded(false)
        viewerState.setTextMode('cleaned')
      })
      await act(async () =>
        root.render(
          <StrictMode>
            <Probe />
          </StrictMode>,
        ),
      )
      expect(viewerState.isExpanded).toBe(false)
      expect(viewerState.textMode).toBe('cleaned')
      const oldSetPanelWidth = viewerState.setPanelWidthPx
      act(() => viewerState.handleTextScrollTopChange(125))
      expect(useDocumentView.getState().getDocumentLayout('doc-a')?.textScrollTop).toBe(0)
      mocks.view.documentId = 'doc-b'
      await act(async () =>
        root.render(
          <StrictMode>
            <Probe />
          </StrictMode>,
        ),
      )
      act(() => oldSetPanelWidth(999))
      expect(viewerState.isExpanded).toBe(false)
      expect(viewerState.textMode).toBe('cleaned')
      expect(viewerState.panelWidthPx).toBe(720)
      expect(useDocumentView.getState().getDocumentLayout('doc-a')).toMatchObject({
        isExpanded: false,
        textMode: 'cleaned',
        textScrollTop: 125,
      })
    } finally {
      useDocumentView.setState({ documentLayouts: savedLayouts })
    }
  })

  it('keeps absent citation positions absent and preserves actual zeros and source text', async () => {
    const citation = retrievalResponse('doc-a', '  raw text\n\n').citations[0]
    mocks.retrievePreview.mockResolvedValue({
      citations: [
        { ...citation, page_number: null, chunk_index: null, start_char: null, end_char: null },
        { ...citation, relevance_score: 0, page_number: 0, chunk_index: 0, start_char: 0, end_char: 0 },
      ],
    })
    await act(async () => root.render(<Probe />))
    const request = await startRetrieval('current question')
    await act(async () => request.completion)
    expect(viewerState.retrieveCitations[0]).toMatchObject({ chunk_content: '  raw text\n\n' })
    for (const field of ['page_number', 'chunk_index', 'start_char', 'end_char'] as const) {
      expect(viewerState.retrieveCitations[0][field]).toBeUndefined()
      expect(viewerState.retrieveCitations[1][field]).toBe(0)
    }
    expect(viewerState.retrieveCitations[1].relevance_score).toBe(0)
  })

  it('discards a pending layout patch after the real Store changes auth scope', async () => {
    const { useDocumentView } = await vi.importActual<typeof import('@/store/document-view')>('@/store/document-view')
    const authStorage = await import('@/lib/auth-storage')
    const original = useDocumentView.getState()
    const nextScope = vi.spyOn(authStorage, 'getAuthCacheScope')
    useDocumentView.setState({ documentLayouts: {} })
    mocks.view.authScope = original.authScope
    mocks.view.getDocumentLayout.mockImplementation(useDocumentView.getState().getDocumentLayout)
    mocks.view.setDocumentLayout.mockImplementation(useDocumentView.getState().setDocumentLayout)
    try {
      await act(async () => root.render(<Probe />))
      act(() => viewerState.handleTextScrollTopChange(250))
      nextScope.mockReturnValue('another-account')
      await act(async () => {
        window.dispatchEvent(new Event(authStorage.AUTH_SCOPE_CHANGED_EVENT))
        mocks.view.authScope = useDocumentView.getState().authScope
        mocks.view.documentId = useDocumentView.getState().documentId
        root.render(<Probe />)
      })
      expect(useDocumentView.getState().authScope).toBe('another-account')
      expect(useDocumentView.getState().documentLayouts).toEqual({})
      const persisted = await useDocumentView.persist
        .getOptions()
        .storage!.getItem(authStorage.DOCUMENT_VIEW_STORAGE_KEY)
      expect(persisted).toBeNull()
    } finally {
      nextScope.mockRestore()
      useDocumentView.setState(original, true)
    }
  })

  it('keeps the last successful retrieval with its actual query when refresh fails', async () => {
    mocks.retrievePreview
      .mockResolvedValueOnce(retrievalResponse('doc-a', 'Previous matched text'))
      .mockRejectedValueOnce(new Error('Refresh failed'))
    await act(async () => root.render(<Probe />))
    const first = await startRetrieval('First question')
    await act(async () => first.completion)
    const refresh = await startRetrieval('Second question')
    await act(async () => refresh.completion)
    expect(viewerState.retrieveCitations).toMatchObject([{ chunk_content: 'Previous matched text' }])
    expect(viewerState.retrieveResultQuery).toBe('First question')
    expect(viewerState.retrieveFailedQuery).toBe('Second question')
    expect(viewerState.retrieveQuery).toBe('Second question')
    expect(viewerState.retrieveError).not.toBeNull()
  })

  it.each([
    { citations: null },
    { citations: {} },
    { citations: [{ document_id: 'doc-a', document_name: 'Document', relevance_score: 1 }] },
    { citations: [{ document_id: 'doc-a', document_name: 'Document', chunk_content: 'Text' }] },
    { citations: [{ document_id: 'doc-a', document_name: 'Document', chunk_content: 'Text', relevance_score: null }] },
  ])(
    'reports an invalid retrieval response as failure instead of an empty or fabricated result: %j',
    async (response) => {
      mocks.retrievePreview.mockResolvedValue(response)
      await act(async () => root.render(<Probe />))
      const request = await startRetrieval('current question')
      await act(async () => request.completion)
      expect(viewerState.retrieveError).not.toBeNull()
      expect(viewerState.retrieveCitations).toEqual([])
      expect(viewerState.retrieveLoading).toBe(false)
      expect(mocks.reportClientError).toHaveBeenCalledWith('Run retrieve preview failed', expect.any(Error))
    },
  )

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
      act(() => {
        void viewerState.handleDeleteChunk(chunk('deleted-a'))
      })
      await switchDocument('doc-b')
      act(() => {
        void viewerState.handleDeleteChunk(chunk('deleted-b'))
      })
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
    let copying!: Promise<void>
    act(() => {
      copying = viewerState.copyChunkContent('original content')
    })
    await switchDocument('doc-b')
    await act(async () => {
      if (settlement === 'resolve') copy.resolve(undefined)
      else copy.reject(new Error('original clipboard failed'))
      await copying
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
    act(() => {
      void viewerState.handleDeleteChunk(chunk('deleted-a'))
    })
    mocks.view.highlightChunkId = 'selected-c'
    await act(async () => root.render(<Probe />))
    act(() => {
      void viewerState.handleDeleteChunk(chunk('deleted-b'))
    })
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
