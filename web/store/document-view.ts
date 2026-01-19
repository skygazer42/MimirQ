import { create } from 'zustand'

interface DocumentViewState {
  isOpen: boolean
  documentId: string | null
  highlightChunkId: string | null
  activeTab: 'preview' | 'chunks'
  
  openDocument: (documentId: string, chunkId?: string) => void
  closeDocument: () => void
  setHighlightChunk: (chunkId: string | null) => void
  setActiveTab: (tab: 'preview' | 'chunks') => void
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
    activeTab: chunkId ? 'chunks' : 'preview' 
  }),
  
  closeDocument: () => set({ 
    isOpen: false, 
    documentId: null, 
    highlightChunkId: null 
  }),
  
  setHighlightChunk: (chunkId) => set({ highlightChunkId: chunkId }),
  
  setActiveTab: (tab) => set({ activeTab: tab })
}))
