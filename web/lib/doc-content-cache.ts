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
