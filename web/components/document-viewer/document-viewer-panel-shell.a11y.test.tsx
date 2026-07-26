// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  TabsList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children: React.ReactNode }) => (
    <button type="button">{children}</button>
  ),
}))
vi.mock('@/components/document-viewer/chunk-editor-dialog', () => ({
  ChunkEditorDialog: () => null,
}))
vi.mock('@/components/document-viewer/chunks-tab-panel', () => ({
  ChunksTabPanel: () => null,
}))
vi.mock('@/components/document-viewer/document-viewer-header', () => ({
  DocumentViewerHeader: () => null,
}))
vi.mock('@/components/document-viewer/floating-menu', () => ({
  FloatingMenu: () => null,
}))
vi.mock('@/components/document-viewer/preview-tab-panel', () => ({
  PreviewTabPanel: () => null,
}))
vi.mock('@/components/document-viewer/qa-generation-dialog', () => ({
  QAGenerationDialog: () => null,
}))
vi.mock('@/components/document-viewer/text-tab-panel', () => ({
  TextTabPanel: () => null,
}))

import { DocumentViewerPanelShell } from './document-viewer-panel-shell'
import type { DocumentViewerPanelState } from './use-document-viewer-panel-state'

describe('DocumentViewerPanelShell accessibility', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      writable: true,
      value: 1440,
    })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    document.body.innerHTML = ''
  })

  it('uses separator semantics and arrow keys for panel width', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 576,
      height: 800,
      top: 0,
      right: 576,
      bottom: 800,
      left: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    })
    const setPanelWidthPx = vi.fn()
    const props = {
      activeTab: 'preview',
      chunks: [],
      closeDocument: vi.fn(),
      copyChunkContent: vi.fn(),
      copyChunkLink: vi.fn(),
      doc: null,
      documentId: 'doc-a',
      downloadUrl: null,
      fileUrl: null,
      handleActiveTabChange: vi.fn(),
      handleChunkEditorOpenChange: vi.fn(),
      handleChunkSearchKeyDown: vi.fn(),
      handleDeleteChunk: vi.fn(),
      handleQaDialogOpenChange: vi.fn(),
      handleSelectTextChunkIndex: vi.fn(),
      handleTextScrollTopChange: vi.fn(),
      highlightChunk: null,
      highlightChunkId: null,
      highlightChunkLoading: false,
      highlightRange: null,
      isExpanded: false,
      isLoading: false,
      isOpen: true,
      jumpToMatch: vi.fn(),
      jumpToSource: vi.fn(),
      loadAllChunks: vi.fn(),
      matchCursor: -1,
      matchChunkIds: [],
      openCreateChunk: vi.fn(),
      openEditChunk: vi.fn(),
      panelWidthPx: null,
      parsedContent: null,
      parsedContentError: '',
      parsedContentLoading: false,
      previewAnchor: null,
      qaDialogOpen: false,
      qaLastResult: null,
      qaMaxSourceChars: 1000,
      qaNumPairs: 5,
      qaPreferLlm: false,
      qaReplaceExisting: false,
      qaSubmitting: false,
      rawFileUrl: null,
      retrieveCitations: [],
      retrieveError: '',
      retrieveLoading: false,
      retrieveQuery: '',
      rowVirtualizer: null,
      runQaGeneration: vi.fn(),
      runRetrievePreview: vi.fn(),
      serverMatchTruncated: false,
      sourceContext: null,
      setChunkEditorContent: vi.fn(),
      setChunkEditorEndChar: vi.fn(),
      setChunkEditorPageNumber: vi.fn(),
      setChunkEditorStartChar: vi.fn(),
      setChunkQuery: vi.fn(),
      setHighlightChunk: vi.fn(),
      setIsExpanded: vi.fn(),
      setLoadAllChunks: vi.fn(),
      setPanelWidthPx,
      setQaMaxSourceChars: vi.fn(),
      setQaNumPairs: vi.fn(),
      setQaPreferLlm: vi.fn(),
      setQaReplaceExisting: vi.fn(),
      setRetrieveCitations: vi.fn(),
      setRetrieveError: vi.fn(),
      setRetrieveQuery: vi.fn(),
      setTextMode: vi.fn(),
      submitChunkEditor: vi.fn(),
      textActiveChunkIndex: null,
      textChunkItems: [],
      textInitialScrollTop: 0,
      textMode: 'plain',
      textValue: '',
      canEditChunks: false,
      canInlinePreview: false,
      chunkDeleteSubmitting: false,
      chunkEditorContent: '',
      chunkEditorEndChar: null,
      chunkEditorMode: 'create',
      chunkEditorOpen: false,
      chunkEditorPageNumber: null,
      chunkEditorStartChar: null,
      chunkEditorSubmitting: false,
      chunkEditorTarget: null,
      canRerunRetrieve: false,
      chunkMatchSummary: null,
      chunkQuery: '',
      chunkSearchPlaceholder: '',
      chunkSearchRef: { current: null },
      chunksListRef: { current: null },
      chunksLoaded: false,
      chunksLoading: false,
    } as unknown as DocumentViewerPanelState

    act(() => {
      root.render(<DocumentViewerPanelShell {...props} />)
    })

    const handle = container.querySelector(
      '[data-document-viewer-resize-handle="true"]'
    ) as HTMLElement | null
    expect(handle?.getAttribute('role')).toBe('separator')
    expect(handle?.getAttribute('aria-valuenow')).toBe('576')

    act(() => {
      handle?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })
      )
      handle?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })
      )
    })

    expect(setPanelWidthPx).toHaveBeenNthCalledWith(1, 600)
    expect(setPanelWidthPx).toHaveBeenNthCalledWith(2, 552)
  })
})
