import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export type HighlightRange = { start: number; end: number }
export type DocumentViewTab = 'preview' | 'text' | 'chunks'
export type DocumentTextMode = 'cleaned' | 'original'

export type DocumentViewLayout = {
  activeTab?: DocumentViewTab
  isExpanded?: boolean
  textMode?: DocumentTextMode
  chunksScrollTop?: number
  textScrollTop?: number
}

interface DocumentViewState {
  isOpen: boolean
  documentId: string | null
  highlightChunkId: string | null
  highlightRange: HighlightRange | null
  activeTab: DocumentViewTab
  documentLayouts: Record<string, DocumentViewLayout>

  openDocument: (documentId: string, chunkId?: string, range?: Partial<HighlightRange>) => void
  closeDocument: () => void
  setHighlightChunk: (chunkId: string | null) => void
  setHighlightRange: (range: HighlightRange | null) => void
  setActiveTab: (tab: DocumentViewTab) => void
  getDocumentLayout: (documentId: string | null | undefined) => DocumentViewLayout | null
  setDocumentLayout: (documentId: string, patch: Partial<DocumentViewLayout>) => void
}

const STORAGE_KEY = 'mimirq_document_view_v1'
const DEFAULT_ACTIVE_TAB: DocumentViewTab = 'preview'
const VALID_TABS: DocumentViewTab[] = ['preview', 'text', 'chunks']
const VALID_TEXT_MODES: DocumentTextMode[] = ['cleaned', 'original']

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

function sanitizeHighlightRange(range: Partial<HighlightRange> | HighlightRange | null | undefined): HighlightRange | null {
  const startRaw = range?.start
  const endRaw = range?.end
  const start = typeof startRaw === 'number' && Number.isFinite(startRaw) ? Math.trunc(startRaw) : null
  const end = typeof endRaw === 'number' && Number.isFinite(endRaw) ? Math.trunc(endRaw) : null
  return start != null && end != null && end > start ? ({ start, end } satisfies HighlightRange) : null
}

function sanitizeDocumentLayoutPatch(patch: Partial<DocumentViewLayout>): Partial<DocumentViewLayout> {
  const next: Partial<DocumentViewLayout> = {}

  if (patch.activeTab && VALID_TABS.includes(patch.activeTab)) next.activeTab = patch.activeTab
  if (typeof patch.isExpanded === 'boolean') next.isExpanded = patch.isExpanded
  if (patch.textMode && VALID_TEXT_MODES.includes(patch.textMode)) next.textMode = patch.textMode

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
  const next = {
    ...(current || {}),
    ...sanitizeDocumentLayoutPatch(patch),
  }

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
      activeTab: DEFAULT_ACTIVE_TAB,
      documentLayouts: {},

      openDocument: (rawDocumentId, chunkId, range) =>
        set((state) => {
          const documentId = normalizeDocumentId(rawDocumentId)
          if (!documentId) return state

          const highlightRange = sanitizeHighlightRange(range)
          const savedLayout = state.documentLayouts[documentId]
          const activeTab = chunkId || highlightRange ? 'text' : savedLayout?.activeTab || DEFAULT_ACTIVE_TAB

          return {
            isOpen: true,
            documentId,
            highlightChunkId: chunkId || null,
            highlightRange,
            activeTab,
            documentLayouts: persistActiveTabForDocument(documentId, state.documentLayouts, activeTab),
          }
        }),

      closeDocument: () =>
        set({
          isOpen: false,
          documentId: null,
          highlightChunkId: null,
          highlightRange: null,
        }),

      setHighlightChunk: (chunkId) => set({ highlightChunkId: chunkId, highlightRange: null }),

      setHighlightRange: (range) => set({ highlightRange: sanitizeHighlightRange(range) }),

      setActiveTab: (tab) =>
        set((state) => ({
          activeTab: tab,
          documentLayouts: persistActiveTabForDocument(state.documentId, state.documentLayouts, tab),
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
      storage: createJSONStorage(() => (globalThis.window === undefined ? noopStorage : globalThis.window.localStorage)),
      partialize: (state) => ({
        isOpen: state.isOpen,
        documentId: state.documentId,
        highlightChunkId: state.highlightChunkId,
        highlightRange: state.highlightRange,
        activeTab: state.activeTab,
        documentLayouts: state.documentLayouts,
      }),
    }
  )
)
