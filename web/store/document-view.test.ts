import { afterEach, describe, expect, it, vi } from 'vitest'

const STORAGE_KEY = 'mimirq_document_view_v1'

function createLocalStorage(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial))
  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, String(value))
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key)
    }),
    clear: vi.fn(() => {
      store.clear()
    }),
  }
}

async function loadStore(localStorage = createLocalStorage()) {
  vi.resetModules()
  vi.stubGlobal('window', { localStorage })
  const mod = await import('./document-view')
  await mod.useDocumentView.persist.rehydrate()
  return { useDocumentView: mod.useDocumentView, localStorage }
}

afterEach(() => {
  vi.resetModules()
  vi.unstubAllGlobals()
})

describe('document view store persistence', () => {
  it('reuses the last saved tab when reopening a document without an explicit location', async () => {
    const { useDocumentView } = await loadStore()

    useDocumentView.getState().setDocumentLayout('doc-1', {
      activeTab: 'chunks',
      textMode: 'original',
    })

    useDocumentView.getState().openDocument('doc-1')
    expect(useDocumentView.getState().activeTab).toBe('chunks')

    useDocumentView.getState().openDocument('doc-1', 'chunk-1', { start: 4, end: 12 })
    expect(useDocumentView.getState().activeTab).toBe('text')
  })

  it('respects an explicit preview tab override when opening a cited document context', async () => {
    const { useDocumentView } = await loadStore()

    useDocumentView.getState().openDocument(
      'doc-preview',
      'chunk-3',
      { start: 18, end: 44 },
      {
        activeTab: 'preview',
        previewAnchor: { pageNumber: 2, searchText: 'retention period' },
      }
    )

    expect(useDocumentView.getState().isOpen).toBe(true)
    expect(useDocumentView.getState().documentId).toBe('doc-preview')
    expect(useDocumentView.getState().highlightChunkId).toBe('chunk-3')
    expect(useDocumentView.getState().highlightRange).toEqual({ start: 18, end: 44 })
    expect(useDocumentView.getState().activeTab).toBe('preview')
    expect(useDocumentView.getState().lastOpenedTarget).toMatchObject({
      documentId: 'doc-preview',
      chunkId: 'chunk-3',
      activeTab: 'preview',
      previewAnchor: { pageNumber: 2, searchText: 'retention period' },
    })
  })

  it('persists the viewer session and per-document layout across refresh hydration', async () => {
    const localStorage = createLocalStorage()
    let { useDocumentView } = await loadStore(localStorage)

    useDocumentView.getState().setDocumentLayout('doc-42', {
      activeTab: 'chunks',
      isExpanded: true,
      textMode: 'original',
      chunksScrollTop: 128,
      textScrollTop: 512,
      panelWidthPx: 860,
    })
    useDocumentView.getState().openDocument('doc-42')

    const raw = localStorage.getItem(STORAGE_KEY)
    expect(raw).toContain('"documentId":"doc-42"')
    expect(raw).toContain('"activeTab":"chunks"')
    expect(raw).toContain('"isExpanded":true')
    expect(raw).toContain('"textScrollTop":512')
    expect(raw).toContain('"panelWidthPx":860')

    ;({ useDocumentView } = await loadStore(localStorage))

    expect(useDocumentView.getState().isOpen).toBe(true)
    expect(useDocumentView.getState().documentId).toBe('doc-42')
    expect(useDocumentView.getState().activeTab).toBe('chunks')
    expect(useDocumentView.getState().getDocumentLayout('doc-42')).toMatchObject({
      activeTab: 'chunks',
      isExpanded: true,
      textMode: 'original',
      chunksScrollTop: 128,
      textScrollTop: 512,
      panelWidthPx: 860,
    })
  })

  it('sanitizes persisted document viewer panel width', async () => {
    const { useDocumentView } = await loadStore()

    useDocumentView.getState().setDocumentLayout('doc-width', {
      panelWidthPx: 600.8,
    })
    useDocumentView.getState().setDocumentLayout('doc-bad-width', {
      panelWidthPx: 120,
    })

    expect(useDocumentView.getState().getDocumentLayout('doc-width')).toMatchObject({
      panelWidthPx: 601,
    })
    expect(useDocumentView.getState().getDocumentLayout('doc-bad-width')).toBeNull()
  })


  it('opening a new URL document replaces a hydrated viewer target from a previous session', async () => {
    const localStorage = createLocalStorage()
    let { useDocumentView } = await loadStore(localStorage)

    useDocumentView.getState().openDocument('old-doc')

    ;({ useDocumentView } = await loadStore(localStorage))
    useDocumentView.getState().openDocument('new-doc')

    expect(useDocumentView.getState().isOpen).toBe(true)
    expect(useDocumentView.getState().documentId).toBe('new-doc')
  })

  it('keeps the last opened target after closing and can reopen the same context', async () => {
    const { useDocumentView } = await loadStore()

    useDocumentView.getState().openDocument(
      'doc-7',
      'chunk-9',
      { start: 15, end: 45 },
      { previewAnchor: { pageNumber: 6, searchText: 'policy clause' } }
    )
    useDocumentView.getState().setActiveTab('chunks')
    useDocumentView.getState().closeDocument()

    expect(useDocumentView.getState().isOpen).toBe(false)
    expect(useDocumentView.getState().lastOpenedTarget).toEqual({
      documentId: 'doc-7',
      chunkId: 'chunk-9',
      highlightRange: { start: 15, end: 45 },
      previewAnchor: { pageNumber: 6, searchText: 'policy clause' },
      activeTab: 'chunks',
    })

    useDocumentView.getState().reopenLastDocument()

    expect(useDocumentView.getState().isOpen).toBe(true)
    expect(useDocumentView.getState().documentId).toBe('doc-7')
    expect(useDocumentView.getState().highlightChunkId).toBe('chunk-9')
    expect(useDocumentView.getState().highlightRange).toEqual({ start: 15, end: 45 })
    expect(useDocumentView.getState().previewAnchor).toEqual({ pageNumber: 6, searchText: 'policy clause' })
    expect(useDocumentView.getState().activeTab).toBe('chunks')
  })

  it('persists chat citation source context so the viewer can jump back to the originating message', async () => {
    const { useDocumentView } = await loadStore()

    useDocumentView.getState().openDocument(
      'doc-chat',
      'chunk-chat',
      { start: 21, end: 63 },
      {
        activeTab: 'preview',
        previewAnchor: { pageNumber: 3, searchText: 'retention window' },
        sourceContext: {
          kind: 'chat-citation',
          messageId: 'msg-42',
          documentId: 'doc-chat',
          chunkId: 'chunk-chat',
        },
      }
    )
    useDocumentView.getState().closeDocument()
    useDocumentView.getState().reopenLastDocument()

    expect(useDocumentView.getState().sourceContext).toEqual({
      kind: 'chat-citation',
      messageId: 'msg-42',
      documentId: 'doc-chat',
      chunkId: 'chunk-chat',
    })
    expect(useDocumentView.getState().lastOpenedTarget).toMatchObject({
      sourceContext: {
        kind: 'chat-citation',
        messageId: 'msg-42',
        documentId: 'doc-chat',
        chunkId: 'chunk-chat',
      },
    })
  })
})
