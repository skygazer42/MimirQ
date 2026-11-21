// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DOCUMENT_VIEW_STORAGE_KEY, getAuthCacheScope } from '@/lib/auth-storage'
import { useDocumentView } from './document-view'

vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))

async function restoreDocumentView(state: unknown) {
  localStorage.setItem(DOCUMENT_VIEW_STORAGE_KEY, JSON.stringify({ state, version: 0 }))
  await useDocumentView.persist.rehydrate()
}

beforeEach(() => {
  useDocumentView.setState(useDocumentView.getInitialState(), true)
  localStorage.clear()
})

afterEach(() => {
  useDocumentView.setState(useDocumentView.getInitialState(), true)
  localStorage.clear()
})

describe('document view restoration', () => {
  it('does not round fractional citation positions or restore an invalid character range', async () => {
    await restoreDocumentView({
      authScope: getAuthCacheScope(),
      documentId: 'document-a',
      isOpen: true,
      highlightRange: { start: 1.5, end: 3.5 },
      sourceContext: {
        kind: 'chat-citation',
        messageId: 'message-a',
        documentId: 'document-a',
        chunkId: 'chunk-a',
        chunkContent: '  source\n\n',
        chunkIndex: 1.5,
        pageNumber: 2.5,
      },
    })
    expect(useDocumentView.getState().highlightRange).toBeNull()
    expect(useDocumentView.getState().sourceContext).toMatchObject({
      chunkIndex: null,
      pageNumber: null,
      chunkContent: '  source\n\n',
    })
    useDocumentView.getState().openDocument('document-a', 'chunk-a', { start: -1, end: 4 })
    expect(useDocumentView.getState().highlightRange).toBeNull()
  })

  it.each(['  Citation text\n\n', ''])(
    'preserves exact citation content %j through open and persistence restoration',
    async (chunkContent) => {
      useDocumentView.getState().openDocument('document-a', 'chunk-a', undefined, {
        sourceContext: {
          kind: 'chat-citation',
          messageId: 'message-a',
          documentId: 'document-a',
          chunkId: 'chunk-a',
          chunkContent,
        },
      })
      expect(useDocumentView.getState().sourceContext?.chunkContent).toBe(chunkContent)
      await useDocumentView.persist.rehydrate()
      expect(useDocumentView.getState().sourceContext?.chunkContent).toBe(chunkContent)
    },
  )

  it('restores saved data without replacing actions or loading unrelated fields', async () => {
    await restoreDocumentView({
      authScope: getAuthCacheScope(),
      isOpen: true,
      documentId: 'document-a',
      closeDocument: 'stored data',
      setActiveTab: null,
      unrelated: 'not view state',
    })

    expect(useDocumentView.getState().closeDocument).toBeTypeOf('function')
    expect(useDocumentView.getState().setActiveTab).toBeTypeOf('function')
    expect(useDocumentView.getState()).not.toHaveProperty('unrelated')
    useDocumentView.getState().closeDocument()
    expect(useDocumentView.getState().isOpen).toBe(false)
  })

  it('keeps citation context on its own document when opening or restoring a view', async () => {
    const sourceContext = {
      kind: 'chat-citation',
      messageId: 'message-a',
      documentId: 'document-b',
      chunkContent: 'Citation from another document',
    } as const
    useDocumentView.getState().openDocument('document-a', undefined, undefined, { sourceContext })
    expect(useDocumentView.getState().sourceContext).toBeNull()

    await restoreDocumentView({
      authScope: getAuthCacheScope(),
      documentId: 'document-a',
      isOpen: true,
      sourceContext,
      lastOpenedTarget: { documentId: 'document-a', sourceContext },
    })
    expect(useDocumentView.getState().sourceContext).toBeNull()
    expect(useDocumentView.getState().lastOpenedTarget).not.toHaveProperty('sourceContext')
  })

  it('restores layout values including false and zero, and uses the saved tab when resuming', async () => {
    await restoreDocumentView({
      authScope: getAuthCacheScope(),
      documentLayouts: {
        'document-a': {
          activeTab: 'chunks',
          isExpanded: false,
          panelWidthPx: 480.4,
          textMode: 'original',
          chunksScrollTop: 0,
          textScrollTop: 0,
          unrelated: 'not layout data',
        },
        invalid: null,
      },
      lastOpenedTarget: {
        documentId: 'document-a',
        chunkId: 'chunk-a',
        highlightRange: { start: 0, end: 4 },
      },
    })

    expect(useDocumentView.getState().getDocumentLayout('document-a')).toEqual({
      activeTab: 'chunks',
      isExpanded: false,
      panelWidthPx: 480,
      textMode: 'original',
      chunksScrollTop: 0,
      textScrollTop: 0,
    })
    expect(useDocumentView.getState().getDocumentLayout('invalid')).toBeNull()
    useDocumentView.getState().reopenLastDocument()
    expect(useDocumentView.getState()).toMatchObject({
      isOpen: true,
      documentId: 'document-a',
      highlightChunkId: 'chunk-a',
      highlightRange: { start: 0, end: 4 },
      activeTab: 'chunks',
    })
  })

  it('ignores invalid layout containers so a document can still be opened', async () => {
    await restoreDocumentView({ authScope: getAuthCacheScope(), documentLayouts: null })

    useDocumentView.getState().openDocument('document-a')

    expect(useDocumentView.getState().documentId).toBe('document-a')
  })

  it('restores validated preview anchors and citation context without losing zero indices', async () => {
    await restoreDocumentView({
      authScope: getAuthCacheScope(),
      documentId: 'document-a',
      isOpen: true,
      previewAnchor: {
        pageNumber: 2,
        bbox: { x0: 0, y0: 0, x1: 100, y1: 50 },
      },
      sourceContext: {
        kind: 'chat-citation',
        messageId: 'message-a',
        documentId: 'document-a',
        chunkIndex: 0,
        pageNumber: 0,
      },
    })

    expect(useDocumentView.getState().previewAnchor).toEqual({
      pageNumber: 2,
      bboxPageNumber: 2,
      bbox: { x0: 0, y0: 0, x1: 100, y1: 50 },
    })
    expect(useDocumentView.getState().sourceContext).toMatchObject({
      kind: 'chat-citation',
      messageId: 'message-a',
      documentId: 'document-a',
      chunkIndex: 0,
      pageNumber: 0,
    })
  })

  it.each([null, 42, false, ' '])('does not restore an open viewer without a valid document id: %s', async (id) => {
    await restoreDocumentView({ authScope: getAuthCacheScope(), isOpen: true, documentId: id })

    expect(useDocumentView.getState()).toMatchObject({ isOpen: false, documentId: null })
  })

  it('keeps a normalized selection unchanged through closing and resuming', () => {
    useDocumentView.getState().openDocument(' document-a ', ' chunk-a ', { start: 0, end: 5 })
    expect(useDocumentView.getState()).toMatchObject({
      documentId: 'document-a',
      highlightChunkId: 'chunk-a',
      highlightRange: { start: 0, end: 5 },
    })

    useDocumentView.getState().setHighlightChunk(' chunk-b ')
    useDocumentView.getState().closeDocument()
    useDocumentView.getState().reopenLastDocument()

    expect(useDocumentView.getState()).toMatchObject({ documentId: 'document-a', highlightChunkId: 'chunk-b' })
  })
})
