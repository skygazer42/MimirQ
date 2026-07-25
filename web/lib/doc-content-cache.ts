import { AUTH_SCOPE_CHANGED_EVENT, getAuthCacheScope } from './auth-storage'

export type DocContentCacheRecord = {
  id: string
  markdownContent: string
  originalMarkdownContent?: string
  updatedAt: number
}

export type DocSourceCacheRecord = {
  id: string
  filename: string
  mimeType: string
  size: number
  lastModified: number
  blob: Blob
  updatedAt: number
}

export type DocContentCacheStats = {
  entries: number
  totalBytes: number
  lastUpdatedAt: number | null
}

export type DocSourceCacheStats = {
  entries: number
  totalBytes: number
  lastUpdatedAt: number | null
}

export type CachePressureLevel = 'low' | 'moderate' | 'high'

export type CachePressureClassification = {
  level: CachePressureLevel
  storageUsageRatio: number | null
  cacheShareOfUsage: number | null
  totalCacheBytes: number
  reasons: string[]
  hasStorageEstimate: boolean
}

const DB_NAME = 'mimirq'
const DB_VERSION = 2
const CONTENT_STORE = 'doc_contents'
const SOURCE_STORE = 'doc_sources'
const MB = 1024 * 1024
const DEFAULT_STALE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000
let authScopeGeneration = 0

function scopedRecordId(id: string, scope: string = getAuthCacheScope()): string {
  return `${scope}:${id}`
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
  fn: (store: IDBObjectStore) => IDBRequest<T>,
  shouldStart?: () => boolean
): Promise<T> {
  return new Promise((resolve, reject) => {
    void openDb()
      .then((db) => {
        if (shouldStart && !shouldStart()) {
          db.close()
          resolve(undefined as T)
          return
        }
        const tx = db.transaction(storeName, mode)
        const store = tx.objectStore(storeName)
        const req = fn(store)
        let settled = false

        const closeDb = () => db.close()
        const resolveOnce = (value: T) => {
          if (settled) return
          settled = true
          resolve(value)
        }
        const rejectOnce = (reason: unknown, fallbackMessage: string) => {
          if (settled) return
          settled = true
          closeDb()
          reject(toError(reason, fallbackMessage))
        }

        req.onsuccess = () => resolveOnce(req.result)
        req.onerror = () => rejectOnce(req.error, `IndexedDB request failed for "${storeName}"`)
        tx.onabort = () => rejectOnce(tx.error, `IndexedDB transaction aborted for "${storeName}"`)
        tx.onerror = () => rejectOnce(tx.error, `IndexedDB transaction failed for "${storeName}"`)
        tx.oncomplete = closeDb
      })
      .catch((error) => {
        reject(toError(error, `Failed to access IndexedDB store "${storeName}"`))
      })
  })
}

const textEncoder =
  typeof TextEncoder === 'undefined' ? null : new TextEncoder()

function measureStringBytes(value: string | undefined | null): number {
  if (!value) return 0
  if (textEncoder) return textEncoder.encode(value).length
  return value.length * 2
}

function normalizeFiniteNumber(input: unknown): number | null {
  const value = Number(input)
  if (!Number.isFinite(value) || value < 0) return null
  return value
}

export function isRecordStaleByUpdatedAt(updatedAt: number | null | undefined, staleBefore: number): boolean {
  return Number.isFinite(updatedAt) && Number(updatedAt) < staleBefore
}

export function classifyStoragePressure(input: {
  storageEstimate: Pick<StorageEstimate, 'usage' | 'quota'> | null | undefined
  cacheStats:
    | {
        content?: Pick<DocContentCacheStats, 'totalBytes'>
        source?: Pick<DocSourceCacheStats, 'totalBytes'>
      }
    | null
    | undefined
}): CachePressureClassification {
  const usage = normalizeFiniteNumber(input.storageEstimate?.usage)
  const quota = normalizeFiniteNumber(input.storageEstimate?.quota)
  const contentBytes = normalizeFiniteNumber(input.cacheStats?.content?.totalBytes) ?? 0
  const sourceBytes = normalizeFiniteNumber(input.cacheStats?.source?.totalBytes) ?? 0
  const totalCacheBytes = contentBytes + sourceBytes
  const storageUsageRatio = usage != null && quota && quota > 0 ? usage / quota : null
  const cacheShareOfUsage = usage != null && usage > 0 ? totalCacheBytes / usage : null
  const reasons: string[] = []

  if (storageUsageRatio != null && storageUsageRatio >= 0.85) {
    reasons.push('storage usage is near quota')
  }
  if (cacheShareOfUsage != null && cacheShareOfUsage >= 0.7 && totalCacheBytes >= 20 * MB) {
    reasons.push('cache footprint dominates storage usage')
  }
  if (storageUsageRatio != null && storageUsageRatio >= 0.7) {
    reasons.push('storage usage is elevated')
  }
  if (cacheShareOfUsage != null && cacheShareOfUsage >= 0.45 && totalCacheBytes >= 10 * MB) {
    reasons.push('cache footprint is a large share of storage usage')
  }
  if (storageUsageRatio == null && totalCacheBytes >= 250 * MB) {
    reasons.push('cache footprint is large and storage estimate is unavailable')
  } else if (storageUsageRatio == null && totalCacheBytes >= 100 * MB) {
    reasons.push('cache footprint is moderate and storage estimate is unavailable')
  }

  let level: CachePressureLevel = 'low'
  if (reasons.some((reason) => reason.includes('near quota') || reason.includes('dominates') || reason.includes('large'))) {
    level = 'high'
  } else if (reasons.length > 0) {
    level = 'moderate'
  }

  return {
    level,
    storageUsageRatio,
    cacheShareOfUsage,
    totalCacheBytes,
    reasons,
    hasStorageEstimate: usage != null && quota != null,
  }
}

async function collectStoreRecords<T>(
  storeName: string,
  handler: (entry: T) => void
): Promise<void> {
  if (globalThis.window === undefined) return
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly')
    const store = tx.objectStore(storeName)
    const request = store.openCursor()
    let settled = false

    const close = () => {
      db.close()
    }

    const resolveOnce = () => {
      if (settled) return
      settled = true
      close()
      resolve()
    }

    const rejectOnce = (reason: unknown, message: string) => {
      if (!settled) {
        settled = true
        close()
        reject(toError(reason, message))
      }
    }

    request.onsuccess = (event) => {
      const cursor = (event.target as IDBRequest).result
      if (!cursor) return
      handler(cursor.value as T)
      cursor.continue()
    }
    request.onerror = () => rejectOnce(request.error, `IndexedDB cursor failed for "${storeName}"`)
    tx.oncomplete = resolveOnce
    tx.onabort = () => rejectOnce(tx.error, `IndexedDB transaction aborted for "${storeName}"`)
    tx.onerror = () => rejectOnce(tx.error, `IndexedDB transaction failed for "${storeName}"`)
  })
}

export async function saveDocContentToCache(
  record: Omit<DocContentCacheRecord, 'updatedAt'> & { updatedAt?: number },
  scope: string = getAuthCacheScope()
) {
  if (globalThis.window === undefined) return
  if (!record?.id) return
  const scopedId = scopedRecordId(record.id, scope)
  const writeGeneration = authScopeGeneration
  await withStore(CONTENT_STORE, 'readwrite', (store) =>
    store.put({
      id: scopedId,
      markdownContent: record.markdownContent || '',
      originalMarkdownContent: record.originalMarkdownContent || '',
      updatedAt: record.updatedAt ?? Date.now(),
    }),
    () => authScopeGeneration === writeGeneration && getAuthCacheScope() === scope
  )
}

export async function getDocContentFromCache(
  id: string,
  scope: string = getAuthCacheScope()
): Promise<DocContentCacheRecord | null> {
  if (globalThis.window === undefined) return null
  if (!id) return null
  const scopedId = scopedRecordId(id, scope)
  const res = await withStore(CONTENT_STORE, 'readonly', (store) => store.get(scopedId))
  return res ? { ...(res as DocContentCacheRecord), id } : null
}

export async function deleteDocContentFromCache(id: string, scope: string = getAuthCacheScope()) {
  if (globalThis.window === undefined) return
  if (!id) return
  const scopedId = scopedRecordId(id, scope)
  await withStore(CONTENT_STORE, 'readwrite', (store) => store.delete(scopedId))
}

export async function saveDocSourceToCache(
  record: { id: string; file: File; updatedAt?: number },
  scope: string = getAuthCacheScope()
) {
  if (globalThis.window === undefined) return
  if (!record?.id) return
  if (!record.file) return

  const scopedId = scopedRecordId(record.id, scope)
  const writeGeneration = authScopeGeneration
  await withStore(SOURCE_STORE, 'readwrite', (store) =>
    store.put({
      id: scopedId,
      filename: record.file.name || 'document',
      mimeType: record.file.type || 'application/octet-stream',
      size: record.file.size || 0,
      lastModified: record.file.lastModified || Date.now(),
      blob: record.file,
      updatedAt: record.updatedAt ?? Date.now(),
    } satisfies DocSourceCacheRecord),
    () => authScopeGeneration === writeGeneration && getAuthCacheScope() === scope
  )
}

export async function getDocSourceFromCache(
  id: string,
  scope: string = getAuthCacheScope()
): Promise<DocSourceCacheRecord | null> {
  if (globalThis.window === undefined) return null
  if (!id) return null
  const scopedId = scopedRecordId(id, scope)
  const res = await withStore(SOURCE_STORE, 'readonly', (store) => store.get(scopedId))
  return res ? { ...(res as DocSourceCacheRecord), id } : null
}

export async function deleteDocSourceFromCache(id: string, scope: string = getAuthCacheScope()) {
  if (globalThis.window === undefined) return
  if (!id) return
  const scopedId = scopedRecordId(id, scope)
  await withStore(SOURCE_STORE, 'readwrite', (store) => store.delete(scopedId))
}

export async function getDocContentCacheStats(): Promise<DocContentCacheStats> {
  if (globalThis.window === undefined) {
    return { entries: 0, totalBytes: 0, lastUpdatedAt: null }
  }
  const stats: DocContentCacheStats = { entries: 0, totalBytes: 0, lastUpdatedAt: null }
  await collectStoreRecords<DocContentCacheRecord>(CONTENT_STORE, (entry) => {
    stats.entries += 1
    stats.totalBytes += measureStringBytes(entry.markdownContent)
    if (entry.originalMarkdownContent) {
      stats.totalBytes += measureStringBytes(entry.originalMarkdownContent)
    }
    if (entry.updatedAt && (stats.lastUpdatedAt === null || entry.updatedAt > stats.lastUpdatedAt)) {
      stats.lastUpdatedAt = entry.updatedAt
    }
  })
  return stats
}

export async function getDocSourceCacheStats(): Promise<DocSourceCacheStats> {
  if (globalThis.window === undefined) {
    return { entries: 0, totalBytes: 0, lastUpdatedAt: null }
  }
  const stats: DocSourceCacheStats = { entries: 0, totalBytes: 0, lastUpdatedAt: null }
  await collectStoreRecords<DocSourceCacheRecord>(SOURCE_STORE, (entry) => {
    stats.entries += 1
    stats.totalBytes += Number(entry.size || 0)
    if (entry.updatedAt && (stats.lastUpdatedAt === null || entry.updatedAt > stats.lastUpdatedAt)) {
      stats.lastUpdatedAt = entry.updatedAt
    }
  })
  return stats
}

export async function clearDocContentCache() {
  if (globalThis.window === undefined) return
  await withStore(CONTENT_STORE, 'readwrite', (store) => store.clear())
}

export async function clearDocSourceCache() {
  if (globalThis.window === undefined) return
  await withStore(SOURCE_STORE, 'readwrite', (store) => store.clear())
}

if (globalThis.window !== undefined) {
  globalThis.window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, () => {
    authScopeGeneration += 1
    void Promise.all([clearDocContentCache(), clearDocSourceCache()]).catch(() => undefined)
  })
}

async function pruneStoreByUpdatedAt(
  storeName: string,
  maxAgeMs: number,
  nowMs: number
): Promise<number> {
  if (globalThis.window === undefined) return 0
  const normalizedMaxAgeMs =
    Number.isFinite(maxAgeMs) && maxAgeMs >= 0 ? Math.trunc(maxAgeMs) : DEFAULT_STALE_MAX_AGE_MS
  const staleBefore = nowMs - normalizedMaxAgeMs
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite')
    const store = tx.objectStore(storeName)
    const request = store.openCursor()
    let deletedCount = 0
    let settled = false

    const close = () => {
      db.close()
    }

    const resolveOnce = (value: number) => {
      if (settled) return
      settled = true
      close()
      resolve(value)
    }

    const rejectOnce = (reason: unknown, message: string) => {
      if (settled) return
      settled = true
      close()
      reject(toError(reason, message))
    }

    request.onsuccess = (event) => {
      const cursor = (event.target as IDBRequest<IDBCursorWithValue | null>).result
      if (!cursor) return
      const updatedAt = normalizeFiniteNumber((cursor.value as { updatedAt?: number })?.updatedAt)
      if (isRecordStaleByUpdatedAt(updatedAt, staleBefore)) {
        cursor.delete()
        deletedCount += 1
      }
      cursor.continue()
    }
    request.onerror = () => rejectOnce(request.error, `IndexedDB cursor failed for "${storeName}"`)
    tx.oncomplete = () => resolveOnce(deletedCount)
    tx.onabort = () => rejectOnce(tx.error, `IndexedDB transaction aborted for "${storeName}"`)
    tx.onerror = () => rejectOnce(tx.error, `IndexedDB transaction failed for "${storeName}"`)
  })
}

export async function pruneStaleDocContentCache(maxAgeMs = DEFAULT_STALE_MAX_AGE_MS, nowMs = Date.now()) {
  return pruneStoreByUpdatedAt(CONTENT_STORE, maxAgeMs, nowMs)
}

export async function pruneStaleDocSourceCache(maxAgeMs = DEFAULT_STALE_MAX_AGE_MS, nowMs = Date.now()) {
  return pruneStoreByUpdatedAt(SOURCE_STORE, maxAgeMs, nowMs)
}

export async function pruneStaleDocCaches(maxAgeMs = DEFAULT_STALE_MAX_AGE_MS, nowMs = Date.now()) {
  const [contentDeleted, sourceDeleted] = await Promise.all([
    pruneStaleDocContentCache(maxAgeMs, nowMs),
    pruneStaleDocSourceCache(maxAgeMs, nowMs),
  ])
  return {
    contentDeleted,
    sourceDeleted,
    totalDeleted: contentDeleted + sourceDeleted,
  }
}
