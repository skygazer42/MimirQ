export type DocContentCacheRecord = {
  id: string
  markdownContent: string
  originalMarkdownContent?: string
  updatedAt: number
}

const DB_NAME = 'mimirq'
const DB_VERSION = 1
const STORE = 'doc_contents'

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function withStore<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return new Promise(async (resolve, reject) => {
    try {
      const db = await openDb()
      const tx = db.transaction(STORE, mode)
      const store = tx.objectStore(STORE)
      const req = fn(store)
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error)
      tx.onabort = () => reject(tx.error)
      tx.oncomplete = () => db.close()
    } catch (e) {
      reject(e)
    }
  })
}

export async function saveDocContentToCache(record: Omit<DocContentCacheRecord, 'updatedAt'> & { updatedAt?: number }) {
  if (typeof window === 'undefined') return
  if (!record?.id) return
  await withStore('readwrite', (store) =>
    store.put({
      id: record.id,
      markdownContent: record.markdownContent || '',
      originalMarkdownContent: record.originalMarkdownContent || '',
      updatedAt: record.updatedAt ?? Date.now(),
    })
  )
}

export async function getDocContentFromCache(id: string): Promise<DocContentCacheRecord | null> {
  if (typeof window === 'undefined') return null
  if (!id) return null
  const res = await withStore('readonly', (store) => store.get(id))
  return res ? (res as DocContentCacheRecord) : null
}

export async function deleteDocContentFromCache(id: string) {
  if (typeof window === 'undefined') return
  if (!id) return
  await withStore('readwrite', (store) => store.delete(id))
}


