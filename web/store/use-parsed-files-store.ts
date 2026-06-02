import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { deleteDocContentFromCache, deleteDocSourceFromCache, saveDocContentToCache } from '@/lib/doc-content-cache'
import { getClientStorage } from '@/lib/client-storage'
import { collectFolderDescendantIds } from '@/lib/folder-tree-index'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { generateRequestId } from '@/lib/request-id'
import { detachPromise } from '@/lib/utils'
import type { ParsingElement } from '@/lib/api/parsing'


export const ROOT_FOLDER_ID = 'root'

export interface FolderNode {
  id: string
  name: string
  parentId: string
  createdAt: string
}

export interface ParsedFileData {
  id: string
  filename: string
  fileType: string
  fileSize: number
  markdownContent: string
  originalMarkdownContent?: string
  parsedAt: string
  parser: string
  parserBackend?: string
  durationSec?: number
  elements?: ParsingElement[]
  folderId?: string
  datasetId?: string | null
  datasetName?: string | null
  source?: 'parsing_workspace' | 'knowledge_base'
  sourcePath?: string | null
  governanceStatus?: 'draft' | 'ready' | 'submitted'
  chunkStatus?: 'draft' | 'ready' | 'submitted'
  /**
   * UI status for the document library.
   * Note: we don't persist the original File object, only metadata + parsed markdown.
   */
  status?: 'pending' | 'parsing' | 'parsed' | 'error'
  error?: string
}

type ParsedFileUpdates = Partial<Omit<ParsedFileData, 'id'>>

const RELIABLE_SYNC_MAX_ATTEMPTS = 3
const parsedFileUpdateVersions = new Map<string, number>()

interface ParsedFilesState {
  files: ParsedFileData[]
  folders: FolderNode[]
  activeFolderId: string
  isLoaded: boolean

  // Actions
  addParsedFile: (file: Omit<ParsedFileData, 'id' | 'parsedAt'>) => string
  upsertParsedFile: (file: ParsedFileData) => void
  setParsedFiles: (files: ParsedFileData[]) => void
  getFile: (id: string) => ParsedFileData | null
  removeFile: (id: string) => void
  updateParsedFile: (id: string, updates: ParsedFileUpdates) => Promise<void>
  clearAll: () => void

  createFolder: (name: string, parentId?: string) => string
  renameFolder: (id: string, name: string) => void
  deleteFolder: (id: string) => void
  moveFolder: (id: string, parentId: string) => boolean
  setActiveFolderId: (id: string) => void

  // Internal
  setLoaded: (loaded: boolean) => void
}

const makeId = () => generateRequestId()

function getUpdatedMarkdownFields(updates: ParsedFileUpdates): {
  nextMarkdown: string | undefined
  nextOriginal: string | undefined
} {
  return {
    nextMarkdown: typeof updates.markdownContent === 'string' ? updates.markdownContent : undefined,
    nextOriginal:
      typeof updates.originalMarkdownContent === 'string' ? updates.originalMarkdownContent : undefined,
  }
}

function isIndexedDbUnavailableError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : toTrimmedPrimitiveString(error)
  const normalized = message.toLowerCase()
  return (
    normalized.includes('indexeddb') ||
    normalized.includes('private') ||
    normalized.includes('securityerror') ||
    normalized.includes('invalidstateerror')
  )
}

async function persistParsedMarkdownReliably(
  id: string,
  markdownContent: string,
  originalMarkdownContent: string
) {
  let lastError: unknown = null
  for (let attempt = 0; attempt < RELIABLE_SYNC_MAX_ATTEMPTS; attempt += 1) {
    try {
      await saveDocContentToCache({
        id,
        markdownContent,
        originalMarkdownContent,
      })
      return
    } catch (error) {
      lastError = error
    }
  }
  throw lastError
}

function registerParsedFileUpdate(id: string): number {
  const nextVersion = (parsedFileUpdateVersions.get(id) || 0) + 1
  parsedFileUpdateVersions.set(id, nextVersion)
  return nextVersion
}

function isCurrentParsedFileUpdate(id: string, version: number): boolean {
  return parsedFileUpdateVersions.get(id) === version
}

const noopStorage = {
  getItem: (_name: string) => null,
  setItem: (_name: string, _value: string) => {},
  removeItem: (_name: string) => {},
}

type UnknownRecord = Record<string, unknown>

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function isPresent<T>(value: T | null): value is T {
  return value !== null
}

function normalizePersistedFile(value: unknown): ParsedFileData | null {
  if (!isRecord(value)) return null
  const markdownContent = typeof value.markdownContent === 'string' ? value.markdownContent : ''
  const originalMarkdownContent =
    typeof value.originalMarkdownContent === 'string' ? value.originalMarkdownContent : markdownContent
  return {
    ...(value as Partial<ParsedFileData>),
    markdownContent,
    originalMarkdownContent,
    folderId: typeof value.folderId === 'string' && value.folderId ? value.folderId : ROOT_FOLDER_ID,
  } as ParsedFileData
}

function normalizePersistedFolder(value: unknown): FolderNode | null {
  if (!isRecord(value)) return null
  if (typeof value.id !== 'string' || typeof value.name !== 'string' || typeof value.parentId !== 'string') return null
  return {
    id: value.id,
    name: value.name,
    parentId: value.parentId || ROOT_FOLDER_ID,
    createdAt: typeof value.createdAt === 'string' ? value.createdAt : new Date().toISOString(),
  }
}

export const useParsedFiles = create<ParsedFilesState>()(
  persist(
    (set, get) => ({
      files: [],
      folders: [],
      activeFolderId: ROOT_FOLDER_ID,
      isLoaded: false,

      addParsedFile: (file) => {
        const newFile: ParsedFileData = {
          ...file,
          originalMarkdownContent: file.originalMarkdownContent ?? file.markdownContent,
          id: makeId(),
          parsedAt: new Date().toISOString(),
          folderId: file.folderId || ROOT_FOLDER_ID,
          status: file.status ?? 'parsed',
        }

        set((state) => ({ files: [...state.files, newFile] }))

        return newFile.id
      },

      upsertParsedFile: (file) => {
        const incoming: ParsedFileData = {
          ...file,
          id: String(file.id),
          folderId: file.folderId || ROOT_FOLDER_ID,
          status: file.status ?? 'parsed',
          parsedAt: file.parsedAt || new Date().toISOString(),
          originalMarkdownContent: file.originalMarkdownContent ?? file.markdownContent,
        }

        set((state) => {
          const exists = state.files.some((f) => f.id === incoming.id)
          return {
            files: exists
              ? state.files.map((f) => (f.id === incoming.id ? { ...f, ...incoming, id: f.id } : f))
              : [...state.files, incoming],
          }
        })
      },

      setParsedFiles: (files) => {
        const normalized = (files || []).map((file) => ({
          ...file,
          id: String(file.id),
          folderId: file.folderId || ROOT_FOLDER_ID,
          status: file.status ?? 'parsed',
          parsedAt: file.parsedAt || new Date().toISOString(),
          originalMarkdownContent: file.originalMarkdownContent ?? file.markdownContent,
        }))
        set({ files: normalized })
      },

      getFile: (id) => {
        return get().files.find((f) => f.id === id) || null
      },

      removeFile: (id) => {
        set((state) => ({
          files: state.files.filter((f) => f.id !== id),
        }))
        // Best-effort cleanup of large content cache.
        if (globalThis.window !== undefined) {
          detachPromise(deleteDocContentFromCache(id))
          detachPromise(deleteDocSourceFromCache(id))
        }
      },

      updateParsedFile: async (id, updates) => {
        const updateVersion = registerParsedFileUpdate(id)
        const applyUpdates = () =>
          set((state) => ({
            files: state.files.map((f) =>
              f.id === id ? { ...f, ...updates, id: f.id } : f
            ),
          }))

        const { nextMarkdown, nextOriginal } = getUpdatedMarkdownFields(updates)
        const shouldPersistMarkdown =
          globalThis.window !== undefined && (typeof nextMarkdown === 'string' || typeof nextOriginal === 'string')
        const shouldAwaitPersistence = shouldPersistMarkdown && updates.status === 'parsed'
        const markdownContent = nextMarkdown ?? ''
        const originalMarkdownContent = nextOriginal ?? ''

        if (!shouldPersistMarkdown) {
          applyUpdates()
          return
        }

        const persistMarkdown = () =>
          saveDocContentToCache({
            id,
            markdownContent,
            originalMarkdownContent,
          })

        if (!shouldAwaitPersistence) {
          applyUpdates()
          detachPromise(persistMarkdown())
          return
        }

        try {
          await persistParsedMarkdownReliably(id, markdownContent, originalMarkdownContent)
          if (!isCurrentParsedFileUpdate(id, updateVersion)) return
          applyUpdates()
        } catch (error) {
          const reason = isIndexedDbUnavailableError(error)
            ? 'IndexedDB unavailable, applying in-memory fallback for parsed markdown'
            : 'Failed to persist parsed markdown to IndexedDB, applying in-memory fallback'
          console.warn(reason, error)
          if (!isCurrentParsedFileUpdate(id, updateVersion)) return
          applyUpdates()
        }
      },

      clearAll: () => {
        set({ files: [], folders: [], activeFolderId: ROOT_FOLDER_ID })
        if (globalThis.window !== undefined) {
          // We don't enumerate all ids here; best-effort keeps browser storage clean, but cache may remain.
          // Users can clear site data if needed.
        }
      },

      createFolder: (name, parentId) => {
        const trimmed = name.trim()
        const newFolder: FolderNode = {
          id: makeId(),
          name: trimmed || '新建文件夹',
          parentId: parentId || get().activeFolderId || ROOT_FOLDER_ID,
          createdAt: new Date().toISOString(),
        }
        set((state) => ({ folders: [...state.folders, newFolder] }))
        return newFolder.id
      },

      renameFolder: (id, name) => {
        if (id === ROOT_FOLDER_ID) return
        const trimmed = name.trim()
        if (!trimmed) return
        set((state) => ({
          folders: state.folders.map((f) => (f.id === id ? { ...f, name: trimmed } : f)),
        }))
      },

      deleteFolder: (id) => {
        if (id === ROOT_FOLDER_ID) return

        const folders = get().folders
        const idsToDelete = new Set([id, ...collectFolderDescendantIds(folders, id)])
        const fileIdsToDelete = get()
          .files
          .filter((file) => Boolean(file.folderId) && idsToDelete.has(String(file.folderId)))
          .map((file) => file.id)

        set((state) => ({
          folders: state.folders.filter((f) => !idsToDelete.has(f.id)),
          files: state.files.filter((file) =>
            !(file.folderId && idsToDelete.has(file.folderId))
          ),
          activeFolderId: idsToDelete.has(state.activeFolderId) ? ROOT_FOLDER_ID : state.activeFolderId,
        }))

        if (globalThis.window !== undefined && fileIdsToDelete.length > 0) {
          for (const fileId of fileIdsToDelete) {
            detachPromise(deleteDocContentFromCache(fileId))
            detachPromise(deleteDocSourceFromCache(fileId))
          }
        }
      },

      moveFolder: (id, parentId) => {
        if (!id || id === ROOT_FOLDER_ID) return false

        const folders = get().folders
        const byId = new Map(folders.map((f) => [f.id, f]))
        if (!byId.has(id)) return false
        const normalizedParentId =
          parentId && parentId !== id && (parentId === ROOT_FOLDER_ID || byId.has(parentId)) ? parentId : ROOT_FOLDER_ID

        // Prevent cycles: cannot move a folder into itself or its descendants
        let current = normalizedParentId
        while (current && current !== ROOT_FOLDER_ID) {
          if (current === id) return false
          current = byId.get(current)?.parentId || ROOT_FOLDER_ID
        }

        const prevParentId = byId.get(id)?.parentId || ROOT_FOLDER_ID
        if ((prevParentId || ROOT_FOLDER_ID) === (normalizedParentId || ROOT_FOLDER_ID)) return false

        set((state) => ({
          folders: state.folders.map((f) => (f.id === id ? { ...f, parentId: normalizedParentId } : f)),
        }))
        return true
      },

      setActiveFolderId: (id) => {
        set({ activeFolderId: id || ROOT_FOLDER_ID })
      },

      setLoaded: (loaded) => set({ isLoaded: loaded }),
    }),
    {
      name: 'mimirq_parsed_files',
      storage: createJSONStorage(() => getClientStorage() ?? noopStorage),
      partialize: (state) => ({
        files: state.files.map((f) => ({
          ...f,
          markdownContent: '', // Exclude large content from persisted JSON to prevent quota crashes.
          originalMarkdownContent: '',
        })),
        folders: state.folders,
        activeFolderId: state.activeFolderId,
      }),
      onRehydrateStorage: () => (state) => {
        if (globalThis.window !== undefined) {
          state?.setLoaded(true)
        }
      },
      migrate: (persistedState: unknown, _version) => {
        // Handle migration from legacy React State hook (raw array)
        if (Array.isArray(persistedState)) {
          const migrated = persistedState.map(normalizePersistedFile).filter(isPresent)
          return {
            files: migrated,
            folders: [],
            activeFolderId: ROOT_FOLDER_ID,
            isLoaded: true,
          }
        }

        const normalized = isRecord(persistedState) ? persistedState : {}
        const normalizedFiles = Array.isArray(normalized.files)
          ? normalized.files.map(normalizePersistedFile).filter(isPresent)
          : []

        const normalizedFolders = Array.isArray(normalized.folders)
          ? normalized.folders.map(normalizePersistedFolder).filter(isPresent)
          : []

        return {
          ...(normalized as Partial<ParsedFilesState>),
          files: normalizedFiles,
          folders: normalizedFolders,
          activeFolderId: typeof normalized.activeFolderId === 'string' && normalized.activeFolderId ? normalized.activeFolderId : ROOT_FOLDER_ID,
          isLoaded: true,
        }
      }
    }
  )
)
