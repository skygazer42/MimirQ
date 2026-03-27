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

const DB_NAME = 'mimirq'
const DB_VERSION = 2
const CONTENT_STORE = 'doc_contents'
const SOURCE_STORE = 'doc_sources'

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
  fn: (store: IDBObjectStore) => IDBRequest<T>
): Promise<T> {
  return new Promise((resolve, reject) => {
    void openDb()
      .then((db) => {
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
  typeof TextEncoder !== 'undefined' ? new TextEncoder() : null

function measureStringBytes(value: string | undefined | null): number {
  if (!value) return 0
  if (textEncoder) return textEncoder.encode(value).length
  return value.length * 2
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
      if (settled) return
      settled = true
      close()
      reject(toError(reason, message))
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

export async function saveDocContentToCache(record: Omit<DocContentCacheRecord, 'updatedAt'> & { updatedAt?: number }) {
  if (globalThis.window === undefined) return
  if (!record?.id) return
  await withStore(CONTENT_STORE, 'readwrite', (store) =>
    store.put({
      id: record.id,
      markdownContent: record.markdownContent || '',
      originalMarkdownContent: record.originalMarkdownContent || '',
      updatedAt: record.updatedAt ?? Date.now(),
    })
  )
}

export async function getDocContentFromCache(id: string): Promise<DocContentCacheRecord | null> {
  if (globalThis.window === undefined) return null
  if (!id) return null
  const res = await withStore(CONTENT_STORE, 'readonly', (store) => store.get(id))
  return res ? (res as DocContentCacheRecord) : null
}

export async function deleteDocContentFromCache(id: string) {
  if (globalThis.window === undefined) return
  if (!id) return
  await withStore(CONTENT_STORE, 'readwrite', (store) => store.delete(id))
}

export async function saveDocSourceToCache(record: { id: string; file: File; updatedAt?: number }) {
  if (globalThis.window === undefined) return
  if (!record?.id) return
  if (!record.file) return

  await withStore(SOURCE_STORE, 'readwrite', (store) =>
    store.put({
      id: record.id,
      filename: record.file.name || 'document',
      mimeType: record.file.type || 'application/octet-stream',
      size: record.file.size || 0,
      lastModified: record.file.lastModified || Date.now(),
      blob: record.file,
      updatedAt: record.updatedAt ?? Date.now(),
    } satisfies DocSourceCacheRecord)
  )
}

export async function getDocSourceFromCache(id: string): Promise<DocSourceCacheRecord | null> {
  if (globalThis.window === undefined) return null
  if (!id) return null
  const res = await withStore(SOURCE_STORE, 'readonly', (store) => store.get(id))
  return res ? (res as DocSourceCacheRecord) : null
}

export async function deleteDocSourceFromCache(id: string) {
  if (globalThis.window === undefined) return
  if (!id) return
  await withStore(SOURCE_STORE, 'readwrite', (store) => store.delete(id))
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
