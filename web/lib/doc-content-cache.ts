import { z } from 'zod'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthCacheScope } from './auth-storage'
import { generateRequestId } from './request-id'

const docContentCacheSchema = z.object({
  id: z.string(),
  markdownContent: z.string(),
  originalMarkdownContent: z.string().optional(),
  updatedAt: z.number(),
})

export type DocContentCacheRecord = z.infer<typeof docContentCacheSchema>

export type DocContentCacheUpdate = Pick<DocContentCacheRecord, 'id'> &
  Partial<Pick<DocContentCacheRecord, 'markdownContent' | 'originalMarkdownContent'>>

const docSourceCacheSchema = z.object({
  id: z.string(),
  filename: z.string(),
  mimeType: z.string(),
  size: z.number().int().nonnegative(),
  lastModified: z.number(),
  blob: z.instanceof(Blob),
  updatedAt: z.number(),
})

export type DocSourceCacheRecord = z.infer<typeof docSourceCacheSchema>

const DB_NAME = 'mimirq'
const DB_VERSION = 2
const CONTENT_STORE = 'doc_contents'
const SOURCE_STORE = 'doc_sources'
const pendingSourceWrites = new Map<string, AbortController>()

type DocCacheScopeGuard = {
  scope: string
  authGeneration: number
  scopeWriteGeneration: number
}

type DocCacheWriteState = {
  authScopeGeneration: number
  authScopeListenerInstalled: boolean
  invalidationListeners: Set<() => void>
  scopeWriteGenerations: Map<string, number>
}

const DOC_CACHE_WRITE_STATE_KEY = '__mimirqDocCacheWriteState__'

function getDocCacheWriteState(): DocCacheWriteState {
  const globalScope = globalThis as typeof globalThis & {
    [DOC_CACHE_WRITE_STATE_KEY]?: DocCacheWriteState
  }
  let writeState = globalScope[DOC_CACHE_WRITE_STATE_KEY]
  if (writeState === undefined) {
    writeState = {
      authScopeGeneration: 0,
      authScopeListenerInstalled: false,
      invalidationListeners: new Set<() => void>(),
      scopeWriteGenerations: new Map<string, number>(),
    }
    globalScope[DOC_CACHE_WRITE_STATE_KEY] = writeState
  }
  return writeState
}

function getAuthScopeGeneration(): number {
  return getDocCacheWriteState().authScopeGeneration
}

function getDocCacheScopeWriteGeneration(scope: string): number {
  return getDocCacheWriteState().scopeWriteGenerations.get(scope) ?? 0
}

function notifyDocCacheInvalidationListeners() {
  const listeners = Array.from(getDocCacheWriteState().invalidationListeners)
  for (const listener of listeners) {
    listener()
  }
}

function subscribeToDocCacheInvalidation(listener: () => void): () => void {
  const writeState = getDocCacheWriteState()
  writeState.invalidationListeners.add(listener)
  return () => {
    writeState.invalidationListeners.delete(listener)
  }
}

function scopedRecordId(id: string, scope: string = getAuthCacheScope()): string {
  if (id.length === 0) throw new Error('缓存文档 ID 不能为空')
  if (scope.length === 0) throw new Error('缓存作用域不能为空')
  return `${scope}:${id}`
}

function parseDocContentCacheRecord(value: unknown): DocContentCacheRecord {
  const result = docContentCacheSchema.safeParse(value)
  if (!result.success) throw new Error('本地正文缓存格式不正确，原记录已保留')
  return result.data
}

function toError(reason: unknown, fallbackMessage: string): Error {
  if (reason instanceof Error) return reason
  if (typeof reason === 'string' && reason) return new Error(reason)
  return new Error(fallbackMessage)
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(CONTENT_STORE)) {
        db.createObjectStore(CONTENT_STORE, { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains(SOURCE_STORE)) {
        db.createObjectStore(SOURCE_STORE, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(toError(req.error, `Failed to open IndexedDB "${DB_NAME}"`))
  })
}

function withStore<T>(
  storeName: string,
  mode: IDBTransactionMode,
  runRequest: (store: IDBObjectStore, checkCommit: () => boolean, onError: (error: unknown) => void) => IDBRequest<T>,
  shouldStart?: () => boolean,
  shouldCommit?: () => boolean,
  signal?: AbortSignal,
): Promise<T | undefined> {
  return new Promise((resolve, reject) => {
    void openDb()
      .then((db) => {
        if (signal?.aborted || (shouldStart && !shouldStart())) {
          db.close()
          resolve(undefined)
          return
        }
        let tx: IDBTransaction
        try {
          tx = db.transaction(storeName, mode)
        } catch (error) {
          db.close()
          reject(toError(error, `Failed to start IndexedDB transaction for "${storeName}"`))
          return
        }
        const store = tx.objectStore(storeName)
        let settled = false
        let abortedForGuard = false
        let unsubscribeInvalidationListener: () => void = () => {}
        const cleanup = () => {
          unsubscribeInvalidationListener()
          signal?.removeEventListener('abort', abortForGuard)
          db.close()
        }
        const resolveOnce = (value: T | undefined) => {
          if (settled) return
          settled = true
          cleanup()
          resolve(value)
        }
        const rejectOnce = (reason: unknown, fallbackMessage: string) => {
          if (settled) return
          settled = true
          cleanup()
          reject(toError(reason, fallbackMessage))
        }
        const abortForGuard = () => {
          if (settled || abortedForGuard) return
          abortedForGuard = true
          try {
            tx.abort()
          } catch {
            abortedForGuard = false
          }
        }
        const checkCommit = () => {
          if (settled) return false
          if (mode === 'readwrite' && (signal?.aborted || (shouldCommit && !shouldCommit()))) {
            abortForGuard()
            return false
          }
          return true
        }
        const failRequest = (error: unknown) => {
          try {
            tx.abort()
          } catch {
            // The initiating error is still reported if the transaction already ended.
          } finally {
            rejectOnce(error, `IndexedDB request failed for "${storeName}"`)
          }
        }
        if (mode === 'readwrite' && shouldCommit) {
          unsubscribeInvalidationListener = subscribeToDocCacheInvalidation(checkCommit)
        }
        signal?.addEventListener('abort', abortForGuard)
        tx.onabort = () => {
          if (abortedForGuard) {
            resolveOnce(undefined)
            return
          }
          rejectOnce(tx.error, `IndexedDB transaction aborted for "${storeName}"`)
        }
        tx.onerror = () => rejectOnce(tx.error, `IndexedDB transaction failed for "${storeName}"`)
        if (mode === 'readwrite') tx.oncomplete = () => resolveOnce(undefined)

        let req: IDBRequest<T>
        try {
          req = runRequest(store, checkCommit, failRequest)
        } catch (error) {
          failRequest(error)
          return
        }
        req.onsuccess = () => {
          if (!checkCommit()) return
          if (mode !== 'readwrite') resolveOnce(req.result)
        }
        req.onerror = () => rejectOnce(req.error, `IndexedDB request failed for "${storeName}"`)
      })
      .catch((error) => {
        reject(toError(error, `Failed to access IndexedDB store "${storeName}"`))
      })
  })
}

export function invalidateDocCacheScopeWrites(scope: string = getAuthCacheScope()): number {
  const nextGeneration = getDocCacheScopeWriteGeneration(scope) + 1
  getDocCacheWriteState().scopeWriteGenerations.set(scope, nextGeneration)
  notifyDocCacheInvalidationListeners()
  return nextGeneration
}

export function getDocCacheScopeGuard(scope: string = getAuthCacheScope()): DocCacheScopeGuard {
  return {
    scope,
    authGeneration: getAuthScopeGeneration(),
    scopeWriteGeneration: getDocCacheScopeWriteGeneration(scope),
  }
}

export function isDocCacheScopeGuardCurrent(scopeGuard: DocCacheScopeGuard): boolean {
  return (
    getAuthScopeGeneration() === scopeGuard.authGeneration &&
    getAuthCacheScope() === scopeGuard.scope &&
    getDocCacheScopeWriteGeneration(scopeGuard.scope) === scopeGuard.scopeWriteGeneration
  )
}

export async function cacheDocContentIfMissing(
  record: Omit<DocContentCacheRecord, 'updatedAt'> & { updatedAt?: number },
  scopeOrGuard: string | DocCacheScopeGuard = getAuthCacheScope(),
) {
  if (globalThis.window === undefined) return
  const scopeGuard = typeof scopeOrGuard === 'string' ? getDocCacheScopeGuard(scopeOrGuard) : scopeOrGuard
  const scopedId = scopedRecordId(record.id, scopeGuard.scope)
  await withStore(
    CONTENT_STORE,
    'readwrite',
    (store, checkCommit, onError) => {
      const request: IDBRequest<unknown> = store.get(scopedId)
      request.addEventListener('success', () => {
        if (!checkCommit() || request.result !== undefined) return
        try {
          const write = store.put({
            id: scopedId,
            markdownContent: record.markdownContent,
            originalMarkdownContent: record.originalMarkdownContent ?? '',
            updatedAt: record.updatedAt ?? Date.now(),
          })
          write.addEventListener('success', checkCommit)
        } catch (error) {
          onError(error)
        }
      })
      return request
    },
    () => isDocCacheScopeGuardCurrent(scopeGuard),
    () => isDocCacheScopeGuardCurrent(scopeGuard),
  )
}

export async function updateDocContentInCache(
  update: DocContentCacheUpdate,
  scopeOrGuard: string | DocCacheScopeGuard = getAuthCacheScope(),
  signal?: AbortSignal,
): Promise<void | (() => Promise<unknown>)> {
  if (globalThis.window === undefined || signal?.aborted) return
  const { markdownContent, originalMarkdownContent } = update
  if (markdownContent === undefined && originalMarkdownContent === undefined) return
  const scopeGuard = typeof scopeOrGuard === 'string' ? getDocCacheScopeGuard(scopeOrGuard) : scopeOrGuard
  const scopedId = scopedRecordId(update.id, scopeGuard.scope)
  const writeId = generateRequestId()
  const isCurrentScope = () => isDocCacheScopeGuardCurrent(scopeGuard)
  let previousRecord: unknown
  await withStore(
    CONTENT_STORE,
    'readwrite',
    (store, checkCommit, onError) => {
      const request: IDBRequest<unknown> = store.get(scopedId)
      request.addEventListener('success', () => {
        if (!checkCommit()) return
        try {
          previousRecord = request.result
          let current: DocContentCacheRecord | undefined
          const needsSavedContent = markdownContent === undefined || originalMarkdownContent === undefined
          if (needsSavedContent && previousRecord !== undefined) current = parseDocContentCacheRecord(previousRecord)
          const write = store.put({
            id: scopedId,
            writeId,
            markdownContent: markdownContent ?? current?.markdownContent ?? '',
            originalMarkdownContent: originalMarkdownContent ?? current?.originalMarkdownContent ?? '',
            updatedAt: Date.now(),
          })
          write.addEventListener('success', checkCommit)
        } catch (error) {
          onError(error)
        }
      })
      return request
    },
    isCurrentScope,
    isCurrentScope,
    signal,
  )
  if (signal?.aborted || !isCurrentScope()) return

  return () =>
    withStore(
      CONTENT_STORE,
      'readwrite',
      (store, checkCommit, onError) => {
        const request: IDBRequest<unknown> = store.get(scopedId)
        request.addEventListener('success', () => {
          if (!checkCommit()) return
          const current = request.result
          if (typeof current !== 'object' || current === null || !('writeId' in current) || current.writeId !== writeId)
            return
          try {
            const restore = previousRecord === undefined ? store.delete(scopedId) : store.put(previousRecord)
            restore.addEventListener('success', checkCommit)
          } catch (error) {
            onError(error)
          }
        })
        return request
      },
      isCurrentScope,
      isCurrentScope,
    )
}

export async function getDocContentFromCache(
  id: string,
  scope: string = getAuthCacheScope(),
): Promise<DocContentCacheRecord | null> {
  if (globalThis.window === undefined) return null
  const scopedId = scopedRecordId(id, scope)
  const res: unknown = await withStore(CONTENT_STORE, 'readonly', (store) => store.get(scopedId))
  return res === undefined ? null : { ...parseDocContentCacheRecord(res), id }
}

export async function deleteDocContentFromCache(id: string, scope: string = getAuthCacheScope()) {
  if (globalThis.window === undefined) return
  const scopedId = scopedRecordId(id, scope)
  await withStore(CONTENT_STORE, 'readwrite', (store) => store.delete(scopedId))
}

export async function saveDocSourceToCache(
  record: { id: string; file: File; updatedAt?: number },
  scopeOrGuard: string | DocCacheScopeGuard = getAuthCacheScope(),
  signal?: AbortSignal,
) {
  if (globalThis.window === undefined) return

  const scopeGuard = typeof scopeOrGuard === 'string' ? getDocCacheScopeGuard(scopeOrGuard) : scopeOrGuard
  const scopedId = scopedRecordId(record.id, scopeGuard.scope)
  pendingSourceWrites.get(scopedId)?.abort()
  const controller = new AbortController()
  pendingSourceWrites.set(scopedId, controller)
  const cancelWrite = () => controller.abort()
  signal?.addEventListener('abort', cancelWrite, { once: true })
  if (signal?.aborted) controller.abort()
  try {
    await withStore(
      SOURCE_STORE,
      'readwrite',
      (store) =>
        store.put({
          id: scopedId,
          filename: record.file.name,
          mimeType: record.file.type,
          size: record.file.size,
          lastModified: record.file.lastModified,
          blob: record.file,
          updatedAt: record.updatedAt ?? Date.now(),
        } satisfies DocSourceCacheRecord),
      () => isDocCacheScopeGuardCurrent(scopeGuard),
      () => isDocCacheScopeGuardCurrent(scopeGuard),
      controller.signal,
    )
  } finally {
    signal?.removeEventListener('abort', cancelWrite)
    if (pendingSourceWrites.get(scopedId) === controller) pendingSourceWrites.delete(scopedId)
  }
}

export async function getDocSourceFromCache(
  id: string,
  scope: string = getAuthCacheScope(),
): Promise<DocSourceCacheRecord | null> {
  if (globalThis.window === undefined) return null
  const scopedId = scopedRecordId(id, scope)
  const res: unknown = await withStore(SOURCE_STORE, 'readonly', (store) => store.get(scopedId))
  if (res === undefined) return null
  const record = docSourceCacheSchema.safeParse(res)
  if (!record.success) throw new Error('本地原文件缓存格式不正确，请重新关联该文档')
  return { ...record.data, id }
}

export async function deleteDocSourceFromCache(id: string, scope: string = getAuthCacheScope()) {
  if (globalThis.window === undefined) return
  const scopedId = scopedRecordId(id, scope)
  pendingSourceWrites.get(scopedId)?.abort()
  await withStore(SOURCE_STORE, 'readwrite', (store) => store.delete(scopedId))
}

async function clearStoreForScope(storeName: string, scope: string): Promise<number> {
  if (globalThis.window === undefined) return 0
  if (scope.length === 0) throw new Error('缓存作用域不能为空')
  const scopedPrefix = `${scope}:`
  let deletedCount = 0
  await withStore(storeName, 'readwrite', (store, checkCommit, onError) => {
    const request = store.openCursor()
    request.addEventListener('success', () => {
      if (!checkCommit()) return
      const cursor = request.result
      if (cursor === null) return
      try {
        const recordId = cursor.primaryKey
        if (typeof recordId === 'string' && recordId.startsWith(scopedPrefix)) {
          cursor.delete()
          deletedCount += 1
        }
        cursor.continue()
      } catch (error) {
        onError(error)
      }
    })
    return request
  })
  return deletedCount
}

export async function clearDocCachesForScope(scope: string = getAuthCacheScope()) {
  const [contentDeleted, sourceDeleted] = await Promise.all([
    clearStoreForScope(CONTENT_STORE, scope),
    clearStoreForScope(SOURCE_STORE, scope),
  ])
  return {
    contentDeleted,
    sourceDeleted,
    totalDeleted: contentDeleted + sourceDeleted,
  }
}

if (globalThis.window !== undefined) {
  const writeState = getDocCacheWriteState()
  if (!writeState.authScopeListenerInstalled) {
    globalThis.window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, () => {
      getDocCacheWriteState().authScopeGeneration += 1
      notifyDocCacheInvalidationListeners()
    })
    writeState.authScopeListenerInstalled = true
  }
}
