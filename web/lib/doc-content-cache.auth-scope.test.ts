// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest'

const authMock = vi.hoisted(() => ({
  scope: 'tenant-a:user-a',
}))

vi.mock('./auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  getAuthCacheScope: () => authMock.scope,
}))

type DeferredOpenRequest = {
  result: IDBDatabase
  error: null
  onupgradeneeded: (() => void) | null
  onsuccess: (() => void) | null
  onerror: (() => void) | null
}

function createRequest<T>() {
  return {
    result: undefined as T,
    error: null,
    onsuccess: null as ((event?: Event) => void) | null,
    onerror: null as (() => void) | null,
  }
}

function createIndexedDbHarness() {
  const stores = new Map<string, Map<string, Record<string, unknown>>>()
  let deferredOpenCount = 0
  let deferredWriteCount = 0
  let deferredWriteCompletionCount = 0
  const pendingOpenRequests: DeferredOpenRequest[] = []
  const pendingWriteResolvers: Array<() => void> = []
  const pendingWriteCompletionResolvers: Array<() => void> = []

  const deferNextOpen = () => {
    deferredOpenCount += 1
  }

  const deferNextWrite = () => {
    deferredWriteCount += 1
  }

  const deferNextWriteCompletion = () => {
    deferredWriteCompletionCount += 1
  }

  const flushPendingOpens = () => {
    const requests = pendingOpenRequests.splice(0, pendingOpenRequests.length)
    for (const request of requests) {
      queueMicrotask(() => {
        request.onupgradeneeded?.()
        request.onsuccess?.()
      })
    }
  }

  const flushPendingWrites = () => {
    const resolvers = pendingWriteResolvers.splice(0, pendingWriteResolvers.length)
    for (const resolve of resolvers) {
      queueMicrotask(resolve)
    }
  }

  const flushPendingWriteCompletions = () => {
    const resolvers = pendingWriteCompletionResolvers.splice(0, pendingWriteCompletionResolvers.length)
    for (const resolve of resolvers) {
      queueMicrotask(resolve)
    }
  }

  const listStoreKeys = (storeName: string) => Array.from((stores.get(storeName) || new Map()).keys())

  const database = {
    objectStoreNames: {
      contains: (name: string) => stores.has(name),
    },
    createObjectStore: (name: string) => {
      if (!stores.has(name)) {
        stores.set(name, new Map())
      }
      return {}
    },
    transaction: (storeName: string) => {
      let aborted = false
      const tx = {
        onabort: null as (() => void) | null,
        onerror: null as (() => void) | null,
        oncomplete: null as (() => void) | null,
        abort: () => {
          if (aborted) return
          aborted = true
          queueMicrotask(() => {
            tx.onabort?.()
          })
        },
        objectStore: () => {
          const ensureStore = () => {
            if (!stores.has(storeName)) {
              stores.set(storeName, new Map())
            }
            return stores.get(storeName) as Map<string, Record<string, unknown>>
          }

          return {
            put: (value: Record<string, unknown>) => {
              const req = createRequest<Record<string, unknown>>()
              const execute = () => {
                if (aborted) return
                req.result = value
                req.onsuccess?.()
                if (aborted) return
                const finalize = () => {
                  if (aborted) return
                  ensureStore().set(String(value.id), { ...value })
                  tx.oncomplete?.()
                }
                if (deferredWriteCompletionCount > 0) {
                  deferredWriteCompletionCount -= 1
                  pendingWriteCompletionResolvers.push(finalize)
                } else {
                  queueMicrotask(finalize)
                }
              }
              if (deferredWriteCount > 0) {
                deferredWriteCount -= 1
                pendingWriteResolvers.push(execute)
              } else {
                queueMicrotask(execute)
              }
              return req as unknown as IDBRequest<Record<string, unknown>>
            },
            get: (key: string) => {
              const req = createRequest<Record<string, unknown> | undefined>()
              queueMicrotask(() => {
                const value = ensureStore().get(key)
                req.result = value ? { ...value } : undefined
                req.onsuccess?.()
                tx.oncomplete?.()
              })
              return req as unknown as IDBRequest<Record<string, unknown> | undefined>
            },
            delete: (key: string) => {
              const req = createRequest<undefined>()
              queueMicrotask(() => {
                ensureStore().delete(key)
                req.result = undefined
                req.onsuccess?.()
                tx.oncomplete?.()
              })
              return req as unknown as IDBRequest<undefined>
            },
            clear: () => {
              const req = createRequest<undefined>()
              queueMicrotask(() => {
                ensureStore().clear()
                req.result = undefined
                req.onsuccess?.()
                tx.oncomplete?.()
              })
              return req as unknown as IDBRequest<undefined>
            },
            openCursor: () => {
              const req = createRequest<IDBCursorWithValue | null>()
              const entries = () => Array.from(ensureStore().values())
              let index = 0
              const emit = () => {
                const snapshot = entries()
                if (index >= snapshot.length) {
                  req.result = null
                  req.onsuccess?.({ target: req } as unknown as Event)
                  tx.oncomplete?.()
                  return
                }
                const current = snapshot[index] as Record<string, unknown> & { id: string }
                req.result = {
                  value: { ...current },
                  continue: () => {
                    index += 1
                    queueMicrotask(emit)
                  },
                  delete: () => {
                    ensureStore().delete(String(current.id))
                    return createRequest<undefined>() as unknown as IDBRequest<undefined>
                  },
                } as IDBCursorWithValue
                req.onsuccess?.({ target: req } as unknown as Event)
              }
              queueMicrotask(emit)
              return req as unknown as IDBRequest<IDBCursorWithValue | null>
            },
          } as unknown as IDBObjectStore
        },
      }
      return tx as unknown as IDBTransaction
    },
    close: vi.fn(),
  } as unknown as IDBDatabase

  return {
    indexedDB: {
      open: vi.fn(() => {
        const request: DeferredOpenRequest = {
          result: database,
          error: null,
          onupgradeneeded: null,
          onsuccess: null,
          onerror: null,
        }
        if (deferredOpenCount > 0) {
          deferredOpenCount -= 1
          pendingOpenRequests.push(request)
        } else {
          queueMicrotask(() => {
            request.onupgradeneeded?.()
            request.onsuccess?.()
          })
        }
        return request
      }),
    },
    deferNextOpen,
    deferNextWrite,
    deferNextWriteCompletion,
    flushPendingOpens,
    flushPendingWrites,
    flushPendingWriteCompletions,
    listStoreKeys,
  }
}

describe('document content cache auth scope writes', () => {
  beforeEach(() => {
    vi.resetModules()
    authMock.scope = 'tenant-a:user-a'
  })

  it('does not start a delayed IndexedDB write after the auth scope changes', async () => {
    const requests: DeferredOpenRequest[] = []
    const transaction = vi.fn()
    const database = {
      close: vi.fn(),
      transaction,
    } as unknown as IDBDatabase
    const indexedDb = {
      open: vi.fn(() => {
        const request: DeferredOpenRequest = {
          result: database,
          error: null,
          onupgradeneeded: null,
          onsuccess: null,
          onerror: null,
        }
        requests.push(request)
        return request
      }),
    }
    vi.stubGlobal('indexedDB', indexedDb)

    const { saveDocContentToCache } = await import('./doc-content-cache')
    const pendingWrite = saveDocContentToCache(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a'
    )
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    authMock.scope = 'tenant-b:user-b'
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    expect(requests).toHaveLength(1)
    requests[0]?.onsuccess?.()
    await pendingWrite

    expect(transaction).not.toHaveBeenCalled()
  })

  it('clears only records for the requested auth scope', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)

    const {
      clearDocCachesForScope,
      getDocContentFromCache,
      getDocSourceFromCache,
      saveDocContentToCache,
      saveDocSourceToCache,
    } = await import('./doc-content-cache')

    await saveDocContentToCache(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a'
    )
    authMock.scope = 'tenant-b:user-b'
    await saveDocContentToCache(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-b-safe',
        originalMarkdownContent: 'tenant-b-safe',
      },
      'tenant-b:user-b'
    )
    authMock.scope = 'tenant-a:user-a'
    await saveDocSourceToCache(
      {
        id: 'shared-document-id',
        file: new File(['a'], 'tenant-a.md', { type: 'text/markdown' }),
      },
      'tenant-a:user-a'
    )
    authMock.scope = 'tenant-b:user-b'
    await saveDocSourceToCache(
      {
        id: 'shared-document-id',
        file: new File(['b'], 'tenant-b.md', { type: 'text/markdown' }),
      },
      'tenant-b:user-b'
    )

    await expect(clearDocCachesForScope('tenant-a:user-a')).resolves.toMatchObject({
      contentDeleted: 1,
      sourceDeleted: 1,
      totalDeleted: 2,
    })

    await expect(getDocContentFromCache('shared-document-id', 'tenant-a:user-a')).resolves.toBeNull()
    await expect(getDocSourceFromCache('shared-document-id', 'tenant-a:user-a')).resolves.toBeNull()
    await expect(getDocContentFromCache('shared-document-id', 'tenant-b:user-b')).resolves.toMatchObject({
      markdownContent: 'tenant-b-safe',
      originalMarkdownContent: 'tenant-b-safe',
    })
    await expect(getDocSourceFromCache('shared-document-id', 'tenant-b:user-b')).resolves.toMatchObject({
      filename: 'tenant-b.md',
    })
  })

  it('drops a late same-scope write after invalidation while preserving other scopes', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)

    const {
      clearDocCachesForScope,
      getDocContentFromCache,
      invalidateDocCacheScopeWrites,
      saveDocContentToCache,
    } = await import('./doc-content-cache')

    authMock.scope = 'tenant-a:user-a'
    harness.deferNextOpen()
    const staleWrite = saveDocContentToCache(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a'
    )
    await Promise.resolve()
    await Promise.resolve()

    invalidateDocCacheScopeWrites('tenant-a:user-a')
    await clearDocCachesForScope('tenant-a:user-a')

    authMock.scope = 'tenant-b:user-b'
    await saveDocContentToCache(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-b-safe',
        originalMarkdownContent: 'tenant-b-safe',
      },
      'tenant-b:user-b'
    )

    harness.flushPendingOpens()
    await staleWrite

    await expect(getDocContentFromCache('shared-document-id', 'tenant-a:user-a')).resolves.toBeNull()
    await expect(getDocContentFromCache('shared-document-id', 'tenant-b:user-b')).resolves.toMatchObject({
      markdownContent: 'tenant-b-safe',
      originalMarkdownContent: 'tenant-b-safe',
    })
    expect(harness.listStoreKeys('doc_contents')).toEqual(['tenant-b:user-b:shared-document-id'])
  })

  it('aborts a write that started before same-scope invalidation once the transaction is already open', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)

    const {
      getDocContentFromCache,
      invalidateDocCacheScopeWrites,
      saveDocContentToCache,
    } = await import('./doc-content-cache')

    authMock.scope = 'tenant-a:user-a'
    harness.deferNextWrite()
    const staleWrite = saveDocContentToCache(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a'
    )
    await Promise.resolve()
    await Promise.resolve()

    invalidateDocCacheScopeWrites('tenant-a:user-a')
    harness.flushPendingWrites()
    await staleWrite

    await expect(getDocContentFromCache('shared-document-id', 'tenant-a:user-a')).resolves.toBeNull()
    expect(harness.listStoreKeys('doc_contents')).toEqual([])
  })

  it('aborts a write if same-scope invalidation happens after request success but before transaction completion', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)

    const {
      getDocContentFromCache,
      invalidateDocCacheScopeWrites,
      saveDocContentToCache,
    } = await import('./doc-content-cache')

    authMock.scope = 'tenant-a:user-a'
    harness.deferNextWriteCompletion()
    const staleWrite = saveDocContentToCache(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a'
    )
    await Promise.resolve()
    await Promise.resolve()

    invalidateDocCacheScopeWrites('tenant-a:user-a')
    harness.flushPendingWriteCompletions()
    await staleWrite

    await expect(getDocContentFromCache('shared-document-id', 'tenant-a:user-a')).resolves.toBeNull()
    expect(harness.listStoreKeys('doc_contents')).toEqual([])
  })

  it('shares scope generations across module reloads so stale writes cannot commit afterward', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)

    authMock.scope = 'tenant-a:user-a'
    const initialModule = await import('./doc-content-cache')
    harness.deferNextWrite()
    const staleWrite = initialModule.saveDocContentToCache(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a'
    )
    await Promise.resolve()
    await Promise.resolve()

    vi.resetModules()
    const reloadedModule = await import('./doc-content-cache')
    reloadedModule.invalidateDocCacheScopeWrites('tenant-a:user-a')

    harness.flushPendingWrites()
    await staleWrite

    await expect(
      reloadedModule.getDocContentFromCache('shared-document-id', 'tenant-a:user-a')
    ).resolves.toBeNull()
    expect(harness.listStoreKeys('doc_contents')).toEqual([])
  })

  it('keeps current-scope cache readable after module reload resets in-memory generations', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)

    const initialModule = await import('./doc-content-cache')
    authMock.scope = 'tenant-a:user-a'
    initialModule.invalidateDocCacheScopeWrites('tenant-a:user-a')
    await initialModule.clearDocCachesForScope('tenant-a:user-a')
    await initialModule.saveDocContentToCache(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-safe',
        originalMarkdownContent: 'tenant-a-safe',
      },
      'tenant-a:user-a'
    )

    await expect(
      initialModule.getDocContentFromCache('shared-document-id', 'tenant-a:user-a')
    ).resolves.toMatchObject({
      markdownContent: 'tenant-a-safe',
      originalMarkdownContent: 'tenant-a-safe',
    })

    vi.resetModules()
    const reloadedModule = await import('./doc-content-cache')

    await expect(
      reloadedModule.getDocContentFromCache('shared-document-id', 'tenant-a:user-a')
    ).resolves.toMatchObject({
      markdownContent: 'tenant-a-safe',
      originalMarkdownContent: 'tenant-a-safe',
    })
  })
})
