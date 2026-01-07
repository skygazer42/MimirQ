import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export interface ParsedFileData {
  id: string
  filename: string
  fileType: string
  fileSize: number
  markdownContent: string
  originalMarkdownContent?: string
  parsedAt: string
  parser: string
}

interface ParsedFilesState {
  files: ParsedFileData[]
  isLoaded: boolean

  // Actions
  addParsedFile: (file: Omit<ParsedFileData, 'id' | 'parsedAt'>) => string
  getFile: (id: string) => ParsedFileData | null
  removeFile: (id: string) => void
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => void
  clearAll: () => void

  // Internal
  setLoaded: (loaded: boolean) => void
}

export const useParsedFiles = create<ParsedFilesState>()(
  persist(
    (set, get) => ({
      files: [],
      isLoaded: false,

      addParsedFile: (file) => {
        const newFile: ParsedFileData = {
          ...file,
          originalMarkdownContent: file.originalMarkdownContent ?? file.markdownContent,
          id: Math.random().toString(36).substring(2, 15),
          parsedAt: new Date().toISOString(),
        }

        set((state) => ({ files: [...state.files, newFile] }))

        return newFile.id
      },

      getFile: (id) => {
        return get().files.find((f) => f.id === id) || null
      },

      removeFile: (id) => {
        set((state) => ({
          files: state.files.filter((f) => f.id !== id),
        }))
      },

      updateParsedFile: (id, updates) => {
        set((state) => ({
          files: state.files.map((f) =>
            f.id === id ? { ...f, ...updates, id: f.id } : f
          ),
        }))
      },

      clearAll: () => {
        set({ files: [] })
      },

      setLoaded: (loaded) => set({ isLoaded: loaded }),
    }),
    {
      name: 'mimirq_parsed_files',
      storage: createJSONStorage(() => localStorage),
      onRehydrateStorage: () => (state) => {
        state?.setLoaded(true)
      },
      migrate: (persistedState: any, version) => {
        // Handle migration from legacy React State hook (raw array)
        if (Array.isArray(persistedState)) {
           const migrated = persistedState
            .filter((f) => f && typeof f === 'object')
            .map((f: any) => {
              const markdownContent = typeof f.markdownContent === 'string' ? f.markdownContent : ''
              const originalMarkdownContent =
                typeof f.originalMarkdownContent === 'string' ? f.originalMarkdownContent : markdownContent
              return {
                ...f,
                markdownContent,
                originalMarkdownContent,
              } as ParsedFileData
            })
           return {
             files: migrated,
             isLoaded: true
           } as any
        }
        return persistedState as ParsedFilesState
      }
    }
  )
)
