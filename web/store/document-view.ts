import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { getClientStorage } from '@/lib/client-storage'
import type { DocumentPreviewAnchor } from '@/lib/document-preview-anchor'
import { sanitizeDocumentPreviewAnchor } from '@/lib/document-preview-anchor'

export type HighlightRange = { start: number; end: number }
export type DocumentViewTab = 'preview' | 'text' | 'chunks'
export type DocumentTextMode = 'cleaned' | 'original'
export type DocumentViewSourceContext = {
  kind: 'chat-citation'
  messageId: string
  documentId: string
  chunkId?: string | null
}
export type DocumentViewResumeTarget = {
  documentId: string
  chunkId?: string | null
  highlightRange?: HighlightRange | null
  previewAnchor?: DocumentPreviewAnchor | null
  activeTab?: DocumentViewTab
  sourceContext?: DocumentViewSourceContext | null
}

export type DocumentViewLayout = {
  activeTab?: DocumentViewTab
  isExpanded?: boolean
  panelWidthPx?: number
  textMode?: DocumentTextMode
  chunksScrollTop?: number
  textScrollTop?: number
}

interface DocumentViewState {
  isOpen: boolean
  documentId: string | null
  highlightChunkId: string | null
  highlightRange: HighlightRange | null
  previewAnchor: DocumentPreviewAnchor | null
  sourceContext: DocumentViewSourceContext | null
  activeTab: DocumentViewTab
  documentLayouts: Record<string, DocumentViewLayout>
  lastOpenedTarget: DocumentViewResumeTarget | null

  openDocument: (
    documentId: string,
    chunkId?: string,
    range?: Partial<HighlightRange>,
    options?: {
      previewAnchor?: Partial<DocumentPreviewAnchor> | null
      activeTab?: DocumentViewTab
      sourceContext?: DocumentViewSourceContext | null
    }
  ) => void
  closeDocument: () => void
  reopenLastDocument: () => void
  setHighlightChunk: (chunkId: string | null) => void
  setHighlightRange: (range: HighlightRange | null) => void
  setActiveTab: (tab: DocumentViewTab) => void
  getDocumentLayout: (documentId: string | null | undefined) => DocumentViewLayout | null
  setDocumentLayout: (documentId: string, patch: Partial<DocumentViewLayout>) => void
}

const STORAGE_KEY = 'mimirq_document_view_v1'
const DEFAULT_ACTIVE_TAB: DocumentViewTab = 'preview'
const VALID_TABS = new Set<string>(['preview', 'text', 'chunks'])
const VALID_TEXT_MODES = new Set<string>(['cleaned', 'original'])

const noopStorage = {
  getItem: (_name: string) => null,
  setItem: (_name: string, _value: string) => {},
  removeItem: (_name: string) => {},
}

function normalizeDocumentId(documentId: string | null | undefined): string | null {
  const normalized = String(documentId || '').trim()
  return normalized || null
}

function sanitizeScrollTop(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  return Math.max(0, value)
}

function sanitizePanelWidthPx(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  const width = Math.round(value)
  return width >= 360 && width <= 1800 ? width : undefined
}

function sanitizeHighlightRange(range: Partial<HighlightRange> | HighlightRange | null | undefined): HighlightRange | null {
  const startRaw = range?.start
  const endRaw = range?.end
  const start = typeof startRaw === 'number' && Number.isFinite(startRaw) ? Math.trunc(startRaw) : null
  const end = typeof endRaw === 'number' && Number.isFinite(endRaw) ? Math.trunc(endRaw) : null
  return start != null && end != null && end > start ? ({ start, end } satisfies HighlightRange) : null
}

function normalizeChunkId(chunkId: string | null | undefined): string | null {
  const normalized = String(chunkId || '').trim()
  return normalized || null
}

function isDocumentViewTab(tab: unknown): tab is DocumentViewTab {
  return typeof tab === 'string' && VALID_TABS.has(tab)
}

function sanitizeDocumentViewTab(tab: unknown): DocumentViewTab | undefined {
  return isDocumentViewTab(tab) ? tab : undefined
}

function sanitizeSourceContext(sourceContext: DocumentViewSourceContext | null | undefined): DocumentViewSourceContext | null {
  if (sourceContext?.kind !== 'chat-citation') return null

  const messageId = String(sourceContext.messageId || '').trim()
  const documentId = normalizeDocumentId(sourceContext.documentId)
  if (!messageId || !documentId) return null

  return {
    kind: 'chat-citation',
    messageId,
    documentId,
    chunkId: normalizeChunkId(sourceContext.chunkId),
  }
}

function buildResumeTarget(
  rawDocumentId: string | null | undefined,
  activeTab: DocumentViewTab,
  rawChunkId?: string | null,
  range?: Partial<HighlightRange> | HighlightRange | null,
  previewAnchor?: Partial<DocumentPreviewAnchor> | DocumentPreviewAnchor | null,
  sourceContext?: DocumentViewSourceContext | null
): DocumentViewResumeTarget | null {
  const documentId = normalizeDocumentId(rawDocumentId)
  if (!documentId) return null

  const chunkId = normalizeChunkId(rawChunkId)
  const highlightRange = sanitizeHighlightRange(range)
  const sanitizedPreviewAnchor = sanitizeDocumentPreviewAnchor(previewAnchor)
  const sanitizedSourceContext = sanitizeSourceContext(sourceContext)
  return {
    documentId,
    chunkId,
    highlightRange,
    previewAnchor: sanitizedPreviewAnchor,
    activeTab,
    ...(sanitizedSourceContext ? { sourceContext: sanitizedSourceContext } : {}),
  }
}

function sanitizeResumeTarget(target: DocumentViewResumeTarget | null | undefined): DocumentViewResumeTarget | null {
  if (!target) return null

  const documentId = normalizeDocumentId(target.documentId)
  if (!documentId) return null
  const sourceContext = sanitizeSourceContext(target.sourceContext)

  return {
    documentId,
    chunkId: normalizeChunkId(target.chunkId),
    highlightRange: sanitizeHighlightRange(target.highlightRange),
    previewAnchor: sanitizeDocumentPreviewAnchor(target.previewAnchor),
    activeTab: sanitizeDocumentViewTab(target.activeTab),
    ...(sourceContext ? { sourceContext } : {}),
  }
}

function sanitizeDocumentLayoutPatch(patch: Partial<DocumentViewLayout>): Partial<DocumentViewLayout> {
  const next: Partial<DocumentViewLayout> = {}

  if (patch.activeTab && VALID_TABS.has(patch.activeTab)) next.activeTab = patch.activeTab
  if (typeof patch.isExpanded === 'boolean') next.isExpanded = patch.isExpanded
  const panelWidthPx = sanitizePanelWidthPx(patch.panelWidthPx)
  if (panelWidthPx !== undefined) next.panelWidthPx = panelWidthPx
  if (patch.textMode && VALID_TEXT_MODES.has(patch.textMode)) next.textMode = patch.textMode

  const chunksScrollTop = sanitizeScrollTop(patch.chunksScrollTop)
  if (chunksScrollTop !== undefined) next.chunksScrollTop = chunksScrollTop

  const textScrollTop = sanitizeScrollTop(patch.textScrollTop)
  if (textScrollTop !== undefined) next.textScrollTop = textScrollTop

  return next
}

function mergeDocumentLayout(
  current: DocumentViewLayout | undefined,
  patch: Partial<DocumentViewLayout>
): DocumentViewLayout | null {
  const sanitizedPatch = sanitizeDocumentLayoutPatch(patch)
  const next = current ? { ...current, ...sanitizedPatch } : { ...sanitizedPatch }

  return Object.keys(next).length > 0 ? next : null
}

function persistActiveTabForDocument(
  documentId: string | null,
  documentLayouts: Record<string, DocumentViewLayout>,
  activeTab: DocumentViewTab
) {
  if (!documentId) return documentLayouts

  const nextLayouts = { ...documentLayouts }
  const nextLayout = mergeDocumentLayout(nextLayouts[documentId], { activeTab })
  if (nextLayout) nextLayouts[documentId] = nextLayout
  else delete nextLayouts[documentId]
  return nextLayouts
}

export const useDocumentView = create<DocumentViewState>()(
  persist(
    (set, get) => ({
      isOpen: false,
      documentId: null,
      highlightChunkId: null,
      highlightRange: null,
      previewAnchor: null,
      sourceContext: null,
      activeTab: DEFAULT_ACTIVE_TAB,
      documentLayouts: {},
      lastOpenedTarget: null,

      openDocument: (rawDocumentId, chunkId, range, options) =>
        set((state) => {
          const documentId = normalizeDocumentId(rawDocumentId)
          if (!documentId) return state

          const highlightRange = sanitizeHighlightRange(range)
          const previewAnchor = sanitizeDocumentPreviewAnchor(options?.previewAnchor)
          const sourceContext = sanitizeSourceContext(options?.sourceContext)
          const preferredActiveTab = sanitizeDocumentViewTab(options?.activeTab)
          const savedLayout = state.documentLayouts[documentId]
          const activeTab =
            preferredActiveTab || (chunkId || highlightRange ? 'text' : savedLayout?.activeTab || DEFAULT_ACTIVE_TAB)
          const lastOpenedTarget = buildResumeTarget(
            documentId,
            activeTab,
            chunkId || null,
            highlightRange,
            previewAnchor,
            sourceContext
          )

          return {
            isOpen: true,
            documentId,
            highlightChunkId: chunkId || null,
            highlightRange,
            previewAnchor,
            sourceContext,
            activeTab,
            documentLayouts: persistActiveTabForDocument(documentId, state.documentLayouts, activeTab),
            lastOpenedTarget,
          }
        }),

      closeDocument: () =>
        set({
          isOpen: false,
          documentId: null,
          highlightChunkId: null,
          highlightRange: null,
          previewAnchor: null,
          sourceContext: null,
        }),

      reopenLastDocument: () =>
        set((state) => {
          const lastOpenedTarget = sanitizeResumeTarget(state.lastOpenedTarget)
          if (!lastOpenedTarget) return state

          const savedLayout = state.documentLayouts[lastOpenedTarget.documentId]
          const activeTab =
            lastOpenedTarget.activeTab || savedLayout?.activeTab || DEFAULT_ACTIVE_TAB

          return {
            isOpen: true,
            documentId: lastOpenedTarget.documentId,
            highlightChunkId: lastOpenedTarget.chunkId || null,
            highlightRange: lastOpenedTarget.highlightRange || null,
            previewAnchor: lastOpenedTarget.previewAnchor || null,
            sourceContext: lastOpenedTarget.sourceContext || null,
            activeTab,
            documentLayouts: persistActiveTabForDocument(
              lastOpenedTarget.documentId,
              state.documentLayouts,
              activeTab
            ),
            lastOpenedTarget: {
              ...lastOpenedTarget,
              activeTab,
            },
          }
        }),

      setHighlightChunk: (chunkId) =>
        set((state) => ({
          highlightChunkId: chunkId,
          highlightRange: null,
          lastOpenedTarget:
            buildResumeTarget(state.documentId, state.activeTab, chunkId, null, state.previewAnchor, state.sourceContext) ||
            state.lastOpenedTarget,
        })),

      setHighlightRange: (range) =>
        set((state) => ({
          highlightRange: sanitizeHighlightRange(range),
          lastOpenedTarget:
            buildResumeTarget(
              state.documentId,
              state.activeTab,
              state.highlightChunkId,
              range,
              state.previewAnchor,
              state.sourceContext
            ) ||
            state.lastOpenedTarget,
        })),

      setActiveTab: (tab) =>
        set((state) => ({
          activeTab: tab,
          documentLayouts: persistActiveTabForDocument(state.documentId, state.documentLayouts, tab),
          lastOpenedTarget:
            buildResumeTarget(
              state.documentId,
              tab,
              state.highlightChunkId,
              state.highlightRange,
              state.previewAnchor,
              state.sourceContext
            ) ||
            state.lastOpenedTarget,
        })),

      getDocumentLayout: (documentId) => {
        const id = normalizeDocumentId(documentId)
        if (!id) return null
        return get().documentLayouts[id] || null
      },

      setDocumentLayout: (documentId, patch) =>
        set((state) => {
          const id = normalizeDocumentId(documentId)
          if (!id) return state

          const nextLayouts = { ...state.documentLayouts }
          const nextLayout = mergeDocumentLayout(nextLayouts[id], patch)
          if (nextLayout) nextLayouts[id] = nextLayout
          else delete nextLayouts[id]

          return { documentLayouts: nextLayouts }
        }),
    }),
    {
      name: STORAGE_KEY,
      storage: createJSONStorage(() => getClientStorage() ?? noopStorage),
      partialize: (state) => ({
        isOpen: state.isOpen,
        documentId: state.documentId,
        highlightChunkId: state.highlightChunkId,
        highlightRange: state.highlightRange,
        previewAnchor: state.previewAnchor,
        sourceContext: state.sourceContext,
        activeTab: state.activeTab,
        documentLayouts: state.documentLayouts,
        lastOpenedTarget: state.lastOpenedTarget,
      }),
    }
  )
)
