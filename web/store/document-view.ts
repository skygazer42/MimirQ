import { create } from 'zustand'

interface DocumentViewState {
  isOpen: boolean
  documentId: string | null
  highlightChunkId: string | null
  activeTab: 'preview' | 'text' | 'chunks'
  
  openDocument: (documentId: string, chunkId?: string) => void
  closeDocument: () => void
  setHighlightChunk: (chunkId: string | null) => void
  setActiveTab: (tab: 'preview' | 'text' | 'chunks') => void
}

export const useDocumentView = create<DocumentViewState>((set) => ({
  isOpen: false,
  documentId: null,
  highlightChunkId: null,
  activeTab: 'preview',

  openDocument: (documentId, chunkId) => set({ 
    isOpen: true, 
    documentId, 
    highlightChunkId: chunkId || null,
    // Enterprise UX: when we know the chunk id, jump directly to "text location" view.
    activeTab: chunkId ? 'text' : 'preview' 
  }),
  
  closeDocument: () => set({ 
    isOpen: false, 
    documentId: null, 
    highlightChunkId: null 
  }),
  
  setHighlightChunk: (chunkId) => set({ highlightChunkId: chunkId }),
  
  setActiveTab: (tab) => set({ activeTab: tab })
}))
