import { create } from 'zustand'

type HighlightRange = { start: number; end: number }

interface DocumentViewState {
  isOpen: boolean
  documentId: string | null
  highlightChunkId: string | null
  highlightRange: HighlightRange | null
  activeTab: 'preview' | 'text' | 'chunks'
  
  openDocument: (documentId: string, chunkId?: string, range?: Partial<HighlightRange>) => void
  closeDocument: () => void
  setHighlightChunk: (chunkId: string | null) => void
  setHighlightRange: (range: HighlightRange | null) => void
  setActiveTab: (tab: 'preview' | 'text' | 'chunks') => void
}

export const useDocumentView = create<DocumentViewState>((set) => ({
  isOpen: false,
  documentId: null,
  highlightChunkId: null,
  highlightRange: null,
  activeTab: 'preview',

  openDocument: (documentId, chunkId, range) =>
    set(() => {
      const startRaw = range?.start
      const endRaw = range?.end
      const start = typeof startRaw === 'number' && Number.isFinite(startRaw) ? Math.trunc(startRaw) : null
      const end = typeof endRaw === 'number' && Number.isFinite(endRaw) ? Math.trunc(endRaw) : null
      const highlightRange =
        start != null && end != null && end > start ? ({ start, end } satisfies HighlightRange) : null

      return {
        isOpen: true,
        documentId,
        highlightChunkId: chunkId || null,
        highlightRange,
        // When we have a concrete location (chunk or range), jump to "text" view.
        activeTab: chunkId || highlightRange ? 'text' : 'preview',
      }
    }),
  
  closeDocument: () => set({ 
    isOpen: false, 
    documentId: null, 
    highlightChunkId: null,
    highlightRange: null,
  }),
  
  setHighlightChunk: (chunkId) => set({ highlightChunkId: chunkId, highlightRange: null }),

  setHighlightRange: (range) => set({ highlightRange: range }),
  
  setActiveTab: (tab) => set({ activeTab: tab })
}))
