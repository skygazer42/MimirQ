import { create } from 'zustand'
import { persist, type PersistStorage } from 'zustand/middleware'
import { z } from 'zod'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthCacheScope } from '@/lib/auth-storage'
import {
  clearDocCachesForScope,
  deleteDocContentFromCache,
  deleteDocSourceFromCache,
  getDocCacheScopeGuard,
  invalidateDocCacheScopeWrites,
  isDocCacheScopeGuardCurrent,
  updateDocContentInCache,
  type DocContentCacheUpdate,
} from '@/lib/doc-content-cache'
import { getClientStorage } from '@/lib/client-storage'
import { collectFolderDescendantIds } from '@/lib/folder-tree-index'
import { generateRequestId } from '@/lib/request-id'
import { isParsingElement } from '@/lib/parsing-elements'
import type { ParsingContentResponse, ParsingElement } from '@/lib/api/parsing'

export const ROOT_FOLDER_ID = 'root'
const PARSED_FILES_STORAGE_KEY = 'mimirq_parsed_files'

export type FolderNode = {
  id: string
  name: string
  parentId: string
  createdAt: string
}

export type ParsedFileData = {
  id: string
  filename: string
  fileType: string
  fileSize: number
  markdownContent: string
  originalMarkdownContent?: string
  /** Session content is loaded even when both Markdown fields are empty. */
  contentLoaded?: true
  contentEdited?: boolean
  parsedAt: string
  parser: string
  parserBackend?: string
  durationSec?: number
  elements?: ParsingElement[]
  pdfQuality?: ParsingContentResponse['pdf_quality']
  qualityGate?: ParsingContentResponse['quality_gate']
  folderId?: string
  datasetId?: string | null
  datasetName?: string | null
  source?: 'parsing_workspace' | 'knowledge_base'
  sourcePath?: string | null
  governanceStatus?: 'draft' | 'ready' | 'submitted'
  /** Review metadata for the saved Markdown; drafts remain in the governance workspace. */
  governanceReview?: {
    qualityScore: number | null
    issues: Array<{
      id: string
      type: 'error' | 'warning' | 'info'
      message: string
      position?: { start: number; end: number }
    }>
    annotations: Array<{
      id: string
      text: string
      type: 'entity' | 'keyword' | 'sensitive' | 'custom'
      label: string
      start: number
      end: number
    }>
    tags: string[]
    category: string | null
  }
  chunkStatus?: 'draft' | 'ready' | 'submitted'
  /**
   * UI status for the document library.
   * Note: we don't persist the original File object, only metadata + parsed markdown.
   */
  status?: 'pending' | 'parsing' | 'parsed' | 'error'
  error?: string
}

type ParsedFileUpdates = Partial<Omit<ParsedFileData, 'id'>>
type PendingParsedFileUpdate = {
  controller: AbortController
  content: DocContentCacheUpdate
  appliedContent?: DocContentCacheUpdate
  isApplied: boolean
}

const pendingParsedFileUpdates = new Map<string, PendingParsedFileUpdate>()
let isSwitchingParsedFilesScope = false
let isUpdatingParsedFilesViewState = false
let parsedFilesScopeSwitchGeneration = 0

function updateParsedFilesViewState(update: () => void) {
  const wasUpdatingViewState = isUpdatingParsedFilesViewState
  isUpdatingParsedFilesViewState = true
  try {
    update()
  } finally {
    isUpdatingParsedFilesViewState = wasUpdatingViewState
  }
}

function updateParsedFilesIndex(update: () => void) {
  const previous = useParsedFiles.getState()
  try {
    update()
  } catch (error) {
    updateParsedFilesViewState(() => useParsedFiles.setState(previous, true))
    throw error
  }
}

function assertParsedFilesWritable(requirePersistence = false) {
  const loadError = useParsedFiles.getState().loadError
  if (loadError !== undefined) throw loadError
  if (requirePersistence && getClientStorage() === null) {
    throw new Error('当前浏览器无法保存本地文档，请允许浏览器存储后重试')
  }
}

function getParsedFileUpdateKey(scope: string, id: string): string {
  return `${scope}:${id}`
}

function cancelParsedFileUpdatesForScope(scope: string) {
  const scopedPrefix = `${scope}:`
  for (const [key, update] of pendingParsedFileUpdates) {
    if (key.startsWith(scopedPrefix)) {
      update.controller.abort()
      pendingParsedFileUpdates.delete(key)
    }
  }
}

function cancelParsedFileUpdate(scope: string, id: string) {
  const key = getParsedFileUpdateKey(scope, id)
  pendingParsedFileUpdates.get(key)?.controller.abort()
  pendingParsedFileUpdates.delete(key)
}

function beginParsedFileUpdate(scope: string, content: DocContentCacheUpdate): PendingParsedFileUpdate {
  const key = getParsedFileUpdateKey(scope, content.id)
  const previous = pendingParsedFileUpdates.get(key)
  const appliedContent = previous?.appliedContent
  cancelParsedFileUpdate(scope, content.id)
  const update = {
    controller: new AbortController(),
    content: {
      id: content.id,
      markdownContent: content.markdownContent ?? appliedContent?.markdownContent,
      originalMarkdownContent: content.originalMarkdownContent ?? appliedContent?.originalMarkdownContent,
    },
    appliedContent,
    isApplied: false,
  }
  pendingParsedFileUpdates.set(key, update)
  return update
}

function finishParsedFileUpdate(scope: string, id: string, controller: AbortController) {
  const key = getParsedFileUpdateKey(scope, id)
  if (pendingParsedFileUpdates.get(key)?.controller === controller) pendingParsedFileUpdates.delete(key)
}

function persistAppliedParsedFileUpdate(scope: string, update: PendingParsedFileUpdate) {
  update.isApplied = true
  update.appliedContent = update.content
  void updateDocContentInCache(update.content, scope, update.controller.signal)
    .catch((error) => {
      if (update.controller.signal.aborted || getAuthCacheScope() !== scope) return
      console.warn('Failed to cache the parsed file working copy', error)
    })
    .finally(() => finishParsedFileUpdate(scope, update.content.id, update.controller))
}

function deleteParsedFileCaches(id: string, scope: string) {
  void Promise.all([deleteDocContentFromCache(id, scope), deleteDocSourceFromCache(id, scope)]).catch((error) => {
    console.warn('Failed to delete parsed file browser caches', error)
  })
}

type ParsedFilesState = {
  files: ParsedFileData[]
  folders: FolderNode[]
  activeFolderId: string
  isLoaded: boolean
  loadError: unknown

  // Actions
  addParsedFile: (file: Omit<ParsedFileData, 'id' | 'parsedAt'>, options?: { signal?: AbortSignal }) => Promise<string>
  upsertParsedFile: (file: ParsedFileData) => void
  replaceParsedFile: (id: string, file: ParsedFileData) => void
  setParsedFiles: (files: ParsedFileData[]) => void
  getFile: (id: string) => ParsedFileData | null
  removeFile: (id: string) => void
  updateParsedFile: (
    id: string,
    updates: ParsedFileUpdates,
    options?: { requirePersistence?: boolean },
  ) => Promise<void>
  clearAll: () => void

  createFolder: (name: string, parentId?: string) => string
  renameFolder: (id: string, name: string) => void
  deleteFolder: (id: string) => void
  moveFolder: (id: string, parentId: string) => boolean
  setActiveFolderId: (id: string) => void

  // Internal
  finishHydration: (error: unknown) => void
}

function getParsedFilesStorageKey(scope = getAuthCacheScope()): string {
  return `${PARSED_FILES_STORAGE_KEY}:${scope}`
}

const parsedFilesPersistStorage: PersistStorage<unknown> = {
  // Settle restoration after Store creation so initial failures can update its state.
  getItem: async (name) => {
    const storage = getClientStorage()
    if (!storage) return null

    const scopedKey = getParsedFilesStorageKey()
    const scopedValue = storage.getItem(scopedKey)
    storage.removeItem(name)
    if (scopedValue === null) return null
    const snapshot: unknown = JSON.parse(scopedValue)
    if (!isRecord(snapshot) || !Object.prototype.hasOwnProperty.call(snapshot, 'state')) {
      throw new Error('本地文档记录格式不正确')
    }
    if (snapshot.version !== undefined && typeof snapshot.version !== 'number') {
      throw new Error('本地文档记录版本格式不正确')
    }
    return { state: snapshot.state, version: snapshot.version }
  },
  setItem: (_name, value) => {
    if (isSwitchingParsedFilesScope || isUpdatingParsedFilesViewState) return
    assertParsedFilesWritable()
    const storage = getClientStorage()
    if (!storage) return
    storage.removeItem(PARSED_FILES_STORAGE_KEY)
    storage.setItem(getParsedFilesStorageKey(), JSON.stringify(value))
  },
  removeItem: (name) => {
    const storage = getClientStorage()
    if (!storage) return
    storage.removeItem(getParsedFilesStorageKey())
    storage.removeItem(name)
  },
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isPresent<T>(value: T | null): value is T {
  return value !== null
}

const governanceReviewSchema = z.looseObject({
  qualityScore: z.number().nullable(),
  category: z.string().nullable(),
  tags: z.array(z.string()),
  issues: z.array(
    z.looseObject({
      id: z.string(),
      type: z.enum(['error', 'warning', 'info']),
      message: z.string(),
      position: z.looseObject({ start: z.number(), end: z.number() }).optional(),
    }),
  ),
  annotations: z.array(
    z.looseObject({
      id: z.string(),
      type: z.enum(['entity', 'keyword', 'sensitive', 'custom']),
      text: z.string(),
      label: z.string(),
      start: z.number(),
      end: z.number(),
    }),
  ),
}) satisfies z.ZodType<NonNullable<ParsedFileData['governanceReview']>>

const workflowStatusSchema = z.enum(['draft', 'ready', 'submitted']).optional()
const persistedParsedFileSchema = z.looseObject({
  id: z.string(),
  filename: z.string(),
  fileType: z.string(),
  fileSize: z.number(),
  parsedAt: z.string(),
  parser: z.string(),
  markdownContent: z.string().optional(),
  originalMarkdownContent: z.string().optional(),
  parserBackend: z.string().optional(),
  folderId: z.string().optional(),
  error: z.string().optional(),
  datasetId: z.string().nullish(),
  datasetName: z.string().nullish(),
  sourcePath: z.string().nullish(),
  durationSec: z.number().optional(),
  contentEdited: z.boolean().optional(),
  source: z.enum(['parsing_workspace', 'knowledge_base']).optional(),
  governanceStatus: workflowStatusSchema,
  chunkStatus: workflowStatusSchema,
  status: z.enum(['pending', 'parsing', 'parsed', 'error']).optional(),
  elements: z.array(z.custom<ParsingElement>(isParsingElement)).optional(),
  governanceReview: governanceReviewSchema.optional(),
})

function normalizePersistedFile(value: unknown): ParsedFileData | null {
  const result = persistedParsedFileSchema.safeParse(value)
  if (!result.success) return null

  const file = result.data
  const markdownContent = file.markdownContent ?? ''
  return {
    ...file,
    markdownContent,
    originalMarkdownContent: file.originalMarkdownContent ?? markdownContent,
    contentLoaded: undefined,
    folderId: file.folderId === undefined || file.folderId === '' ? ROOT_FOLDER_ID : file.folderId,
  }
}

function normalizePersistedFolder(value: unknown): FolderNode | null {
  if (!isRecord(value)) return null
  if (typeof value.id !== 'string' || typeof value.name !== 'string' || typeof value.parentId !== 'string') return null
  if (typeof value.createdAt !== 'string') return null
  return {
    id: value.id,
    name: value.name,
    parentId: value.parentId === '' ? ROOT_FOLDER_ID : value.parentId,
    createdAt: value.createdAt,
  }
}

function validateFolderHierarchy(folders: FolderNode[]) {
  const byId = new Map<string, FolderNode>()
  for (const folder of folders) {
    if (folder.id === ROOT_FOLDER_ID || byId.has(folder.id))
      throw new Error(`本地文件夹身份重复或与根目录冲突：${folder.name}`)
    byId.set(folder.id, folder)
  }
  const validatedIds = new Set([ROOT_FOLDER_ID])
  for (const folder of folders) {
    const ancestors = new Set<string>()
    let currentId = folder.id
    while (!validatedIds.has(currentId)) {
      if (ancestors.has(currentId)) throw new Error(`本地文件夹层级存在循环引用：${folder.name}`)
      const current = byId.get(currentId)
      if (current === undefined) throw new Error(`本地文件夹「${folder.name}」的父级不存在`)
      ancestors.add(currentId)
      currentId = current.parentId
    }
    for (const id of ancestors) validatedIds.add(id)
  }
}

function restoreParsedFilesState(persisted: unknown): Pick<ParsedFilesState, 'files' | 'folders' | 'activeFolderId'> {
  const saved = Array.isArray(persisted) ? { files: persisted } : persisted
  if (!isRecord(saved) || !Array.isArray(saved.files)) throw new Error('本地文档列表格式不正确')
  if (saved.folders !== undefined && !Array.isArray(saved.folders)) throw new Error('本地文件夹列表格式不正确')
  const folders = saved.folders === undefined ? [] : saved.folders.map(normalizePersistedFolder).filter(isPresent)
  validateFolderHierarchy(folders)
  const activeFolderId = saved.activeFolderId

  return {
    files: saved.files.map(normalizePersistedFile).filter(isPresent),
    folders,
    activeFolderId:
      typeof activeFolderId === 'string' && folders.some((folder) => folder.id === activeFolderId)
        ? activeFolderId
        : ROOT_FOLDER_ID,
  }
}

export const useParsedFiles = create<ParsedFilesState>()(
  persist(
    (set, get) => ({
      files: [],
      folders: [],
      activeFolderId: ROOT_FOLDER_ID,
      isLoaded: false,
      loadError: undefined,

      addParsedFile: async (file, { signal } = {}) => {
        assertParsedFilesWritable(true)
        const scope = getAuthCacheScope()
        const guard = getDocCacheScopeGuard(scope)
        const newFile: ParsedFileData = {
          ...file,
          contentLoaded: true,
          originalMarkdownContent: file.originalMarkdownContent ?? file.markdownContent,
          id: generateRequestId(),
          parsedAt: new Date().toISOString(),
          folderId: file.folderId || ROOT_FOLDER_ID,
          status: file.status ?? 'parsed',
        }
        await updateDocContentInCache(
          {
            id: newFile.id,
            markdownContent: newFile.markdownContent,
            originalMarkdownContent: newFile.originalMarkdownContent,
          },
          scope,
          signal,
        )
        try {
          if (signal?.aborted || !isDocCacheScopeGuardCurrent(guard)) {
            throw new DOMException('文档导入已取消，请重试', 'AbortError')
          }
          assertParsedFilesWritable(true)
          updateParsedFilesIndex(() => set((state) => ({ files: [...state.files, newFile] })))
        } catch (error) {
          await deleteDocContentFromCache(newFile.id, scope).catch((cleanupError) => {
            console.warn('Failed to remove an unpublished imported body', cleanupError)
          })
          throw error
        }

        return newFile.id
      },

      upsertParsedFile: (file) => {
        assertParsedFilesWritable()
        const incoming: ParsedFileData = {
          ...file,
          folderId: file.folderId || ROOT_FOLDER_ID,
          status: file.status ?? 'parsed',
          originalMarkdownContent: file.originalMarkdownContent ?? file.markdownContent,
        }

        updateParsedFilesIndex(() =>
          set((state) => {
            const exists = state.files.some((file) => file.id === incoming.id)
            return {
              files: exists
                ? state.files.map((file) => (file.id === incoming.id ? { ...file, ...incoming, id: file.id } : file))
                : [...state.files, incoming],
            }
          }),
        )
      },

      replaceParsedFile: (id, file) => {
        assertParsedFilesWritable(true)
        const previousFiles = get().files
        if (!previousFiles.some((entry) => entry.id === id)) throw new Error('原文档已移除，请重新选择')
        const scope = getAuthCacheScope()
        updateParsedFilesIndex(() =>
          set({
            files: previousFiles
              .filter((entry) => entry.id === id || entry.id !== file.id)
              .map((entry) => (entry.id === id ? { ...entry, ...file, folderId: entry.folderId } : entry)),
          }),
        )
        persistAppliedParsedFileUpdate(scope, beginParsedFileUpdate(scope, file))
        if (id !== file.id) {
          cancelParsedFileUpdate(scope, id)
          deleteParsedFileCaches(id, scope)
        }
      },

      setParsedFiles: (files) => {
        assertParsedFilesWritable()
        const normalized = files.map((file) => ({
          ...file,
          folderId: file.folderId || ROOT_FOLDER_ID,
          status: file.status ?? 'parsed',
          originalMarkdownContent: file.originalMarkdownContent ?? file.markdownContent,
        }))
        updateParsedFilesIndex(() => set({ files: normalized }))
      },

      getFile: (id) => {
        return get().files.find((file) => file.id === id) ?? null
      },

      removeFile: (id) => {
        assertParsedFilesWritable()
        const scope = getAuthCacheScope()
        updateParsedFilesIndex(() =>
          set((state) => ({
            files: state.files.filter((file) => file.id !== id),
          })),
        )
        cancelParsedFileUpdate(scope, id)
        deleteParsedFileCaches(id, scope)
      },

      updateParsedFile: async (id, updates, { requirePersistence = false } = {}) => {
        const updateScope = getAuthCacheScope()
        const { markdownContent, originalMarkdownContent, ...metadataUpdates } = updates
        if (
          markdownContent === undefined &&
          originalMarkdownContent === undefined &&
          Object.keys(metadataUpdates).length === 0
        )
          return
        assertParsedFilesWritable(requirePersistence)
        const applyUpdates = () => {
          assertParsedFilesWritable(requirePersistence)
          if (requirePersistence && !get().files.some((file) => file.id === id)) {
            throw new Error('文档已移除，请重新选择')
          }
          updateParsedFilesIndex(() =>
            set((state) => ({
              files: state.files.map((file) =>
                file.id === id
                  ? {
                      ...file,
                      ...metadataUpdates,
                      id: file.id,
                      markdownContent: markdownContent ?? file.markdownContent,
                      originalMarkdownContent: originalMarkdownContent ?? file.originalMarkdownContent,
                      contentLoaded:
                        markdownContent !== undefined || originalMarkdownContent !== undefined
                          ? true
                          : file.contentLoaded,
                    }
                  : file,
              ),
            })),
          )
        }

        if (markdownContent === undefined && originalMarkdownContent === undefined) {
          const pending = pendingParsedFileUpdates.get(getParsedFileUpdateKey(updateScope, id))
          const supersedesContent =
            (metadataUpdates.status !== undefined && metadataUpdates.status !== 'parsed') ||
            ('source' in metadataUpdates &&
              metadataUpdates.source !== get().files.find((file) => file.id === id)?.source) ||
            metadataUpdates.governanceStatus !== undefined ||
            metadataUpdates.chunkStatus !== undefined
          applyUpdates()
          // Independent metadata does not invalidate a body awaiting persistence.
          if (pending !== undefined && !pending.isApplied && supersedesContent) {
            cancelParsedFileUpdate(updateScope, id)
            if (pending.appliedContent !== undefined) {
              persistAppliedParsedFileUpdate(updateScope, beginParsedFileUpdate(updateScope, pending.appliedContent))
            }
          }
          return
        }

        if (globalThis.window === undefined) {
          applyUpdates()
          return
        }

        if (updates.status !== 'parsed' && !requirePersistence) {
          applyUpdates()
          const pendingUpdate = beginParsedFileUpdate(updateScope, { id, markdownContent, originalMarkdownContent })
          persistAppliedParsedFileUpdate(updateScope, pendingUpdate)
          return
        }

        const pendingUpdate = beginParsedFileUpdate(updateScope, { id, markdownContent, originalMarkdownContent })
        const { signal } = pendingUpdate.controller
        try {
          const restoreContent = await updateDocContentInCache(pendingUpdate.content, updateScope, signal).catch(
            (error) => {
              if (requirePersistence) throw error
              if (signal.aborted || getAuthCacheScope() !== updateScope) return
              console.warn('Failed to persist parsed markdown to IndexedDB, applying in-memory fallback', error)
            },
          )
          if (signal.aborted || getAuthCacheScope() !== updateScope) {
            if (requirePersistence) throw new DOMException('文档保存已取消，请重试', 'AbortError')
            return
          }
          try {
            applyUpdates()
          } catch (indexError) {
            await restoreContent?.().catch((restoreError) => {
              throw new AggregateError([indexError, restoreError], '无法保存文档目录，也无法恢复原正文')
            })
            throw indexError
          }
        } finally {
          finishParsedFileUpdate(updateScope, id, pendingUpdate.controller)
        }
      },

      clearAll: () => {
        assertParsedFilesWritable()
        const scope = getAuthCacheScope()
        updateParsedFilesIndex(() => set({ files: [], folders: [], activeFolderId: ROOT_FOLDER_ID }))
        cancelParsedFileUpdatesForScope(scope)
        invalidateDocCacheScopeWrites(scope)
        void clearDocCachesForScope(scope).catch((error) => {
          console.warn('Failed to clear parsed file browser cache for auth scope', error)
        })
      },

      createFolder: (name, parentId) => {
        assertParsedFilesWritable()
        const trimmed = name.trim()
        const parent = parentId ?? get().activeFolderId
        if (parent !== ROOT_FOLDER_ID && !get().folders.some((folder) => folder.id === parent))
          throw new Error('父文件夹不存在，请重新选择')
        const newFolder: FolderNode = {
          id: generateRequestId(),
          name: trimmed || '新建文件夹',
          parentId: parent,
          createdAt: new Date().toISOString(),
        }
        updateParsedFilesIndex(() => set((state) => ({ folders: [...state.folders, newFolder] })))
        return newFolder.id
      },

      renameFolder: (id, name) => {
        if (id === ROOT_FOLDER_ID) return
        const trimmed = name.trim()
        if (!trimmed) return
        assertParsedFilesWritable()
        updateParsedFilesIndex(() =>
          set((state) => ({
            folders: state.folders.map((folder) => (folder.id === id ? { ...folder, name: trimmed } : folder)),
          })),
        )
      },

      deleteFolder: (id) => {
        if (id === ROOT_FOLDER_ID) return
        assertParsedFilesWritable()

        const scope = getAuthCacheScope()
        const folders = get().folders
        const idsToDelete = new Set([id, ...collectFolderDescendantIds(folders, id)])
        const fileIdsToDelete = get()
          .files.filter((file) => file.folderId && idsToDelete.has(file.folderId))
          .map((file) => file.id)
        updateParsedFilesIndex(() =>
          set((state) => ({
            folders: state.folders.filter((folder) => !idsToDelete.has(folder.id)),
            files: state.files.filter((file) => !(file.folderId && idsToDelete.has(file.folderId))),
            activeFolderId: idsToDelete.has(state.activeFolderId) ? ROOT_FOLDER_ID : state.activeFolderId,
          })),
        )

        for (const fileId of fileIdsToDelete) cancelParsedFileUpdate(scope, fileId)
        for (const fileId of fileIdsToDelete) deleteParsedFileCaches(fileId, scope)
      },

      moveFolder: (id, parentId) => {
        if (id === ROOT_FOLDER_ID || id === parentId) return false

        const folders = get().folders
        const byId = new Map(folders.map((folder) => [folder.id, folder]))
        const folder = byId.get(id)
        if (folder === undefined) return false
        if (parentId !== ROOT_FOLDER_ID && !byId.has(parentId)) return false

        const ancestors = new Set<string>()
        let current = parentId
        while (current !== ROOT_FOLDER_ID) {
          if (current === id || ancestors.has(current)) return false
          ancestors.add(current)
          const ancestor = byId.get(current)
          if (ancestor === undefined) return false
          current = ancestor.parentId
        }

        if (folder.parentId === parentId) return false

        assertParsedFilesWritable()
        updateParsedFilesIndex(() =>
          set((state) => ({
            folders: state.folders.map((folder) => (folder.id === id ? { ...folder, parentId } : folder)),
          })),
        )
        return true
      },

      setActiveFolderId: (id) => {
        if (get().loadError !== undefined) {
          updateParsedFilesViewState(() => set({ activeFolderId: id || ROOT_FOLDER_ID }))
          return
        }
        updateParsedFilesIndex(() => set({ activeFolderId: id || ROOT_FOLDER_ID }))
      },

      finishHydration: (error) => {
        updateParsedFilesViewState(() => set({ isLoaded: error === undefined, loadError: error }))
      },
    }),
    {
      name: PARSED_FILES_STORAGE_KEY,
      storage: parsedFilesPersistStorage,
      partialize: (state) => ({
        files: state.files.map((file) => ({
          ...file,
          markdownContent: '', // Exclude large content from persisted JSON to prevent quota crashes.
          originalMarkdownContent: '',
          contentLoaded: undefined,
        })),
        folders: state.folders,
        activeFolderId: state.activeFolderId,
      }),
      onRehydrateStorage: (state) => {
        const previousReadError =
          state.loadError !== undefined && getClientStorage() === null ? state.loadError : undefined
        return (_restored, error) => {
          if (globalThis.window !== undefined) {
            state.finishHydration(error === undefined ? previousReadError : error)
          }
        }
      },
      migrate: restoreParsedFilesState,
      merge: (persisted, current) =>
        persisted === undefined ? current : { ...current, ...restoreParsedFilesState(persisted), loadError: undefined },
    },
  ),
)

globalThis.window?.addEventListener(AUTH_SCOPE_CHANGED_EVENT, () => {
  const switchGeneration = ++parsedFilesScopeSwitchGeneration
  isSwitchingParsedFilesScope = true
  for (const update of pendingParsedFileUpdates.values()) update.controller.abort()
  pendingParsedFileUpdates.clear()
  useParsedFiles.setState({
    files: [],
    folders: [],
    activeFolderId: ROOT_FOLDER_ID,
    isLoaded: false,
    loadError: undefined,
  })
  void (async () => {
    try {
      await useParsedFiles.persist.rehydrate()
    } finally {
      if (parsedFilesScopeSwitchGeneration === switchGeneration) {
        isSwitchingParsedFilesScope = false
      }
    }
  })().catch((error) => {
    console.warn('Failed to restore the parsed file workspace after a scope change', error)
  })
})
