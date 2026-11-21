// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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
  const successListeners = new Set<() => void>()
  const request = {
    result: undefined as T,
    error: null,
    onsuccess: null as ((event?: Event) => void) | null,
    onerror: null as (() => void) | null,
    addEventListener: (type: string, listener: () => void) => {
      if (type === 'success') successListeners.add(listener)
    },
    succeed: (event?: Event) => {
      for (const listener of successListeners) listener()
      request.onsuccess?.(event)
    },
  }
  return request
}

function createIndexedDbHarness() {
  const stores = new Map<string, Map<string, Record<string, unknown>>>()
  let deferredOpenCount = 0
  let deferredWriteCount = 0
  let deferredWriteCompletionCount = 0
  let nextPutError: Error | null = null
  let nextTransactionError: Error | null = null
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
      if (nextTransactionError !== null) {
        const error = nextTransactionError
        nextTransactionError = null
        throw error
      }
      let aborted = false
      let pendingRequests = 0
      const finishRequest = () => {
        pendingRequests -= 1
        if (!aborted && pendingRequests === 0) tx.oncomplete?.()
      }
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
              if (nextPutError !== null) {
                const error = nextPutError
                nextPutError = null
                throw error
              }
              pendingRequests += 1
              const req = createRequest<Record<string, unknown>>()
              const execute = () => {
                if (aborted) return
                req.result = value
                req.succeed()
                if (aborted) return
                const finalize = () => {
                  if (aborted) return
                  ensureStore().set(String(value.id), { ...value })
                  finishRequest()
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
              pendingRequests += 1
              const req = createRequest<Record<string, unknown> | undefined>()
              queueMicrotask(() => {
                const value = ensureStore().get(key)
                req.result = value ? { ...value } : undefined
                req.succeed()
                finishRequest()
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
              const entries = Array.from(ensureStore().values())
              let index = 0
              const emit = () => {
                if (index >= entries.length) {
                  req.result = null
                  req.succeed({ target: req } as unknown as Event)
                  tx.oncomplete?.()
                  return
                }
                const current = entries[index] as Record<string, unknown> & { id: string }
                req.result = {
                  primaryKey: current.id,
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
                req.succeed({ target: req } as unknown as Event)
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
    pendingWriteCompletions: () => pendingWriteCompletionResolvers.length,
    failNextPut: (error: Error) => {
      nextPutError = error
    },
    failNextTransaction: (error: Error) => {
      nextTransactionError = error
    },
    seedRecord: (storeName: string, record: { id: string } & Record<string, unknown>) => {
      const records = stores.get(storeName) ?? new Map<string, Record<string, unknown>>()
      records.set(record.id, record)
      stores.set(storeName, records)
    },
    closeDatabase: database.close,
    listStoreKeys,
  }
}

describe('document content cache auth scope writes', () => {
  afterEach(() => vi.restoreAllMocks())
  beforeEach(() => {
    vi.resetModules()
    authMock.scope = 'tenant-a:user-a'
    localStorage.clear()
    sessionStorage.clear()
  })

  it('publishes an imported preview only after its body commits and restores it after reload', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { getDocContentFromCache } = await import('./doc-content-cache')
    const { useParsedFiles } = await import('@/store/use-parsed-files-store')
    await useParsedFiles.persist.rehydrate()
    harness.deferNextWriteCompletion()
    const importing = useParsedFiles.getState().addParsedFile({
      filename: 'imported.md',
      fileType: 'md',
      fileSize: 6,
      markdownContent: 'Saved imported body',
      parser: 'text',
    })
    await vi.waitFor(() => expect(harness.pendingWriteCompletions()).toBe(1))
    expect(useParsedFiles.getState().files).toEqual([])
    harness.flushPendingWriteCompletions()
    const id = await importing
    const key = 'mimirq_parsed_files:tenant-a:user-a'
    const snapshot = localStorage.getItem(key)!
    expect(snapshot).not.toContain('Saved imported body')
    useParsedFiles.setState({ files: [] })
    localStorage.setItem(key, snapshot)
    await useParsedFiles.persist.rehydrate()
    expect(useParsedFiles.getState().getFile(id)).toMatchObject({ id, markdownContent: '' })
    expect(await getDocContentFromCache(id)).toMatchObject({
      markdownContent: 'Saved imported body',
      originalMarkdownContent: 'Saved imported body',
    })
  })

  it('does not publish an imported document when its required body write fails', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { useParsedFiles } = await import('@/store/use-parsed-files-store')
    await useParsedFiles.persist.rehydrate()
    harness.failNextPut(new Error('Import body write denied'))
    await expect(
      useParsedFiles.getState().addParsedFile({
        filename: 'failed.md',
        fileType: 'md',
        fileSize: 6,
        markdownContent: 'Keep source',
        parser: 'text',
      }),
    ).rejects.toThrow('Import body write denied')
    expect(useParsedFiles.getState().files).toEqual([])
    expect(harness.listStoreKeys('doc_contents')).toEqual([])
  })

  it('does not publish or retain a preview cancelled while its body commit is pending', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { useParsedFiles } = await import('@/store/use-parsed-files-store')
    await useParsedFiles.persist.rehydrate()
    harness.deferNextWriteCompletion()
    const controller = new AbortController()
    const importing = useParsedFiles.getState().addParsedFile(
      {
        filename: 'cancelled.md',
        fileType: 'md',
        fileSize: 6,
        markdownContent: 'Cancelled body',
        parser: 'text',
      },
      { signal: controller.signal },
    )
    const rejected = expect(importing).rejects.toMatchObject({ name: 'AbortError' })
    await vi.waitFor(() => expect(harness.pendingWriteCompletions()).toBe(1))
    controller.abort()
    harness.flushPendingWriteCompletions()
    await rejected
    expect(useParsedFiles.getState().files).toEqual([])
    expect(harness.listStoreKeys('doc_contents')).toEqual([])
  })

  it.each([
    { markdownContent: 42, originalMarkdownContent: 'Raw', updatedAt: 0 },
    { markdownContent: 'Body', originalMarkdownContent: false, updatedAt: 0 },
    { markdownContent: 'Body', originalMarkdownContent: 'Raw', updatedAt: 'invalid time' },
  ])('rejects malformed persisted content instead of returning it as text: %j', async (fields) => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    harness.seedRecord('doc_contents', { id: 'tenant-a:user-a:invalid', ...fields })
    const { getDocContentFromCache } = await import('./doc-content-cache')
    await expect(getDocContentFromCache('invalid')).rejects.toThrow('正文缓存格式不正确')
    expect(harness.listStoreKeys('doc_contents')).toEqual(['tenant-a:user-a:invalid'])
  })

  it.each([{ blob: 'not a Blob' }, { filename: 12 }, { lastModified: null }])(
    'rejects a malformed persisted source instead of declaring it available: %j',
    async (fields) => {
      const harness = createIndexedDbHarness()
      vi.stubGlobal('indexedDB', harness.indexedDB)
      harness.seedRecord('doc_sources', {
        id: 'tenant-a:user-a:invalid',
        filename: '',
        mimeType: '',
        size: 0,
        lastModified: 0,
        updatedAt: 0,
        blob: new Blob([]),
        ...fields,
      })
      const { getDocSourceFromCache } = await import('./doc-content-cache')
      await expect(getDocSourceFromCache('invalid')).rejects.toThrow('原文件缓存格式不正确')
      expect(harness.listStoreKeys('doc_sources')).toEqual(['tenant-a:user-a:invalid'])
    },
  )

  it('rejects a partial write that would inherit malformed persisted text but allows a complete replacement', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    harness.seedRecord('doc_contents', {
      id: 'tenant-a:user-a:invalid',
      markdownContent: 42,
      originalMarkdownContent: 'Old raw',
      updatedAt: 0,
    })
    const { updateDocContentInCache, getDocContentFromCache } = await import('./doc-content-cache')
    await expect(updateDocContentInCache({ id: 'invalid', originalMarkdownContent: 'New raw' })).rejects.toThrow(
      '正文缓存格式不正确',
    )
    await updateDocContentInCache({ id: 'invalid', markdownContent: '', originalMarkdownContent: '' })
    expect(await getDocContentFromCache('invalid')).toMatchObject({ markdownContent: '', originalMarkdownContent: '' })
  })

  it.each(['Approved new body', ''])(
    'does not overwrite an accepted working copy %j when an older preview fills the cache later',
    async (body) => {
      const harness = createIndexedDbHarness()
      vi.stubGlobal('indexedDB', harness.indexedDB)
      const { cacheDocContentIfMissing, updateDocContentInCache, getDocContentFromCache } =
        await import('./doc-content-cache')
      await updateDocContentInCache({
        id: 'working-copy',
        markdownContent: body,
        originalMarkdownContent: 'Approved raw',
      })
      await cacheDocContentIfMissing({
        id: 'working-copy',
        markdownContent: 'Old server body',
        originalMarkdownContent: 'Old raw',
      })
      expect(await getDocContentFromCache('working-copy')).toMatchObject({
        markdownContent: body,
        originalMarkdownContent: 'Approved raw',
      })
    },
  )

  it.each(['content-read', 'source-read', 'content-write', 'source-write', 'content-delete', 'source-delete'] as const)(
    'rejects an empty document identity at the actual cache boundary for %s',
    async (operation) => {
      const harness = createIndexedDbHarness()
      vi.stubGlobal('indexedDB', harness.indexedDB)
      const cache = await import('./doc-content-cache')
      const request = () => {
        if (operation === 'content-read') return cache.getDocContentFromCache('')
        if (operation === 'source-read') return cache.getDocSourceFromCache('')
        if (operation === 'content-write') return cache.cacheDocContentIfMissing({ id: '', markdownContent: '' })
        if (operation === 'source-write') return cache.saveDocSourceToCache({ id: '', file: new File([], '') })
        if (operation === 'content-delete') return cache.deleteDocContentFromCache('')
        return cache.deleteDocSourceFromCache('')
      }
      await expect(request()).rejects.toThrow('文档 ID 不能为空')
      expect(harness.indexedDB.open).not.toHaveBeenCalled()
    },
  )

  it('closes both opened connections when a scoped clear cannot start one transaction', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const failure = new Error('Clear transaction cannot start')
    harness.failNextTransaction(failure)
    const { clearDocCachesForScope } = await import('./doc-content-cache')
    await expect(clearDocCachesForScope()).rejects.toBe(failure)
    await vi.waitFor(() => expect(harness.closeDatabase).toHaveBeenCalledTimes(2))
  })

  it('clears every target-scope key including malformed payloads while retaining other scopes', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    for (const store of ['doc_contents', 'doc_sources']) {
      for (const id of ['a', 'b', 'c']) harness.seedRecord(store, { id: `tenant-a:user-a:${id}`, payload: false })
      harness.seedRecord(store, { id: 'tenant-b:user-b:keep', payload: false })
    }
    const { clearDocCachesForScope } = await import('./doc-content-cache')
    await expect(clearDocCachesForScope()).resolves.toEqual({ contentDeleted: 3, sourceDeleted: 3, totalDeleted: 6 })
    expect(harness.listStoreKeys('doc_contents')).toEqual(['tenant-b:user-b:keep'])
    expect(harness.listStoreKeys('doc_sources')).toEqual(['tenant-b:user-b:keep'])
  })

  it.each(['markdownContent', 'originalMarkdownContent'] as const)(
    'keeps the other cached text variant when updating only %s and supports explicit clearing',
    async (field) => {
      const harness = createIndexedDbHarness()
      vi.stubGlobal('indexedDB', harness.indexedDB)
      const { getDocContentFromCache, cacheDocContentIfMissing } = await import('./doc-content-cache')
      const { useParsedFiles } = await import('@/store/use-parsed-files-store')
      const id = await useParsedFiles.getState().addParsedFile({
        filename: 'cached.md',
        fileType: 'md',
        fileSize: 0,
        markdownContent: 'cleaned old',
        originalMarkdownContent: 'original old',
        parser: 'test',
      })
      const previous = { id, markdownContent: 'cleaned old', originalMarkdownContent: 'original old' }
      await cacheDocContentIfMissing(previous)

      await useParsedFiles.getState().updateParsedFile(id, { [field]: 'changed', status: 'parsed' })
      expect(await getDocContentFromCache(id)).toMatchObject({ ...previous, [field]: 'changed' })

      await useParsedFiles.getState().updateParsedFile(id, { [field]: '', status: 'parsed' })
      expect(await getDocContentFromCache(id)).toMatchObject({ ...previous, [field]: '' })
    },
  )

  it.each(['folder', 'parser', 'parserBackend', 'completedStatus'] as const)(
    'retains an awaited body when independent %s metadata changes',
    async (kind) => {
      const harness = createIndexedDbHarness()
      vi.stubGlobal('indexedDB', harness.indexedDB)
      const { getDocContentFromCache, cacheDocContentIfMissing } = await import('./doc-content-cache')
      const { useParsedFiles } = await import('@/store/use-parsed-files-store')
      const id = await useParsedFiles.getState().addParsedFile({
        filename: 'pending.md',
        fileType: 'md',
        fileSize: 0,
        markdownContent: 'before',
        originalMarkdownContent: 'original',
        parser: 'test',
      })
      await cacheDocContentIfMissing({ id, markdownContent: 'before', originalMarkdownContent: 'original' })
      harness.deferNextWriteCompletion()
      const pending = useParsedFiles
        .getState()
        .updateParsedFile(id, { markdownContent: 'latest body', status: 'parsed' })
      await vi.waitFor(() => expect(harness.pendingWriteCompletions()).toBe(1))
      const updates =
        kind === 'folder'
          ? { folderId: useParsedFiles.getState().createFolder('Moved') }
          : kind === 'parser'
            ? { parser: 'updated' }
            : kind === 'parserBackend'
              ? { parserBackend: 'marker' }
              : { status: 'parsed' as const }
      await useParsedFiles.getState().updateParsedFile(id, updates)
      harness.flushPendingWriteCompletions()
      await pending
      expect(useParsedFiles.getState().getFile(id)).toMatchObject({ ...updates, markdownContent: 'latest body' })
      expect(await getDocContentFromCache(id)).toMatchObject({
        markdownContent: 'latest body',
        originalMarkdownContent: 'original',
      })
    },
  )

  it('does not recreate a source cache record removed while its database open was pending', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { saveDocSourceToCache, deleteDocSourceFromCache, getDocSourceFromCache } =
      await import('./doc-content-cache')
    harness.deferNextOpen()
    const write = saveDocSourceToCache({ id: 'deleted-source', file: new File(['Deleted source'], 'deleted.md') })
    await Promise.resolve()
    await deleteDocSourceFromCache('deleted-source')
    harness.flushPendingOpens()
    await write
    expect(await getDocSourceFromCache('deleted-source')).toBeNull()
  })

  it('cancels an obsolete source write before a newer local association is cached', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { getDocSourceFromCache, saveDocSourceToCache } = await import('./doc-content-cache')
    const controller = new AbortController()
    harness.deferNextOpen()
    const older = saveDocSourceToCache(
      { id: 'source-a', file: new File(['Old'], 'old.md') },
      authMock.scope,
      controller.signal,
    )
    await Promise.resolve()
    controller.abort()
    await saveDocSourceToCache({ id: 'source-a', file: new File(['New'], 'new.md') }, authMock.scope)
    harness.flushPendingOpens()
    await older
    expect(await getDocSourceFromCache('source-a')).toMatchObject({ filename: 'new.md' })
  })

  it('preserves genuine empty File metadata and epoch-zero lastModified in the source cache', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { getDocSourceFromCache, saveDocSourceToCache } = await import('./doc-content-cache')
    const file = new File([], '', { lastModified: 0 })
    Object.defineProperty(file, 'lastModified', { value: 0 })
    await saveDocSourceToCache({ id: 'source-empty', file })
    expect(await getDocSourceFromCache('source-empty')).toMatchObject({
      filename: '',
      mimeType: '',
      size: 0,
      lastModified: 0,
    })
  })

  it('does not commit pending parsed content after a newer parse starts', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { getDocContentFromCache, cacheDocContentIfMissing } = await import('./doc-content-cache')
    const { useParsedFiles } = await import('@/store/use-parsed-files-store')
    const id = await useParsedFiles.getState().addParsedFile({
      filename: 'pending.md',
      fileType: 'md',
      fileSize: 0,
      markdownContent: 'before',
      originalMarkdownContent: 'original',
      parser: 'test',
    })
    await cacheDocContentIfMissing({ id, markdownContent: 'before', originalMarkdownContent: 'original' })
    harness.deferNextWriteCompletion()
    const pending = useParsedFiles.getState().updateParsedFile(id, { markdownContent: 'obsolete', status: 'parsed' })
    await vi.waitFor(() => expect(harness.pendingWriteCompletions()).toBe(1))

    await useParsedFiles.getState().updateParsedFile(id, { status: 'parsing' })
    harness.flushPendingWriteCompletions()
    await pending

    expect(useParsedFiles.getState().getFile(id)).toMatchObject({ status: 'parsing', markdownContent: 'before' })
    expect(await getDocContentFromCache(id)).toMatchObject({
      markdownContent: 'before',
      originalMarkdownContent: 'original',
    })
  })

  it('rejects a failed compound write and closes its connection', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { updateDocContentInCache } = await import('./doc-content-cache')
    harness.failNextPut(new Error('write request cannot start'))

    await expect(updateDocContentInCache({ id: 'document-a', markdownContent: 'content' })).rejects.toThrow(
      'write request cannot start',
    )
    expect(harness.closeDatabase).toHaveBeenCalledOnce()
  })

  it.each(['metadata', 'originalMarkdownContent'] as const)(
    'persists an already applied background edit when the next update changes only %s',
    async (nextUpdate) => {
      const harness = createIndexedDbHarness()
      vi.stubGlobal('indexedDB', harness.indexedDB)
      const { getDocContentFromCache, cacheDocContentIfMissing } = await import('./doc-content-cache')
      const { useParsedFiles } = await import('@/store/use-parsed-files-store')
      const id = await useParsedFiles.getState().addParsedFile({
        filename: 'background.md',
        fileType: 'md',
        fileSize: 0,
        markdownContent: 'before',
        originalMarkdownContent: 'original',
        parser: 'test',
      })
      await cacheDocContentIfMissing({ id, markdownContent: 'before', originalMarkdownContent: 'original' })
      harness.deferNextWriteCompletion()
      await useParsedFiles.getState().updateParsedFile(id, { markdownContent: 'applied edit' })
      await vi.waitFor(() => expect(harness.pendingWriteCompletions()).toBe(1))
      expect(useParsedFiles.getState().getFile(id)?.markdownContent).toBe('applied edit')

      await useParsedFiles
        .getState()
        .updateParsedFile(
          id,
          nextUpdate === 'metadata' ? { parser: 'updated' } : { originalMarkdownContent: 'source edit' },
        )
      harness.flushPendingWriteCompletions()

      await vi.waitFor(async () => {
        expect(await getDocContentFromCache(id)).toMatchObject({
          markdownContent: 'applied edit',
          originalMarkdownContent: nextUpdate === 'metadata' ? 'original' : 'source edit',
        })
      })
    },
  )

  it.each([
    { acceptedMarkdown: 'applied edit', nextUpdate: 'metadata' },
    { acceptedMarkdown: '', nextUpdate: 'metadata' },
    { acceptedMarkdown: 'applied edit', nextUpdate: 'originalMarkdownContent' },
  ])(
    'retains accepted $acceptedMarkdown through a pending update and $nextUpdate',
    async ({ acceptedMarkdown, nextUpdate }) => {
      const harness = createIndexedDbHarness()
      vi.stubGlobal('indexedDB', harness.indexedDB)
      const { getDocContentFromCache, cacheDocContentIfMissing } = await import('./doc-content-cache')
      const { useParsedFiles } = await import('@/store/use-parsed-files-store')
      const id = await useParsedFiles.getState().addParsedFile({
        filename: 'successive.md',
        fileType: 'md',
        fileSize: 0,
        markdownContent: 'before',
        originalMarkdownContent: 'original',
        parser: 'test',
      })
      await cacheDocContentIfMissing({ id, markdownContent: 'before', originalMarkdownContent: 'original' })
      harness.deferNextOpen()
      await useParsedFiles.getState().updateParsedFile(id, { markdownContent: acceptedMarkdown })
      harness.deferNextOpen()
      const pending = useParsedFiles.getState().updateParsedFile(id, {
        originalMarkdownContent: 'unapplied source',
        status: 'parsed',
      })

      await useParsedFiles
        .getState()
        .updateParsedFile(
          id,
          nextUpdate === 'metadata' ? { parser: 'updated' } : { originalMarkdownContent: 'latest source' },
        )
      harness.flushPendingOpens()
      await pending

      expect(useParsedFiles.getState().getFile(id)?.markdownContent).toBe(acceptedMarkdown)
      await vi.waitFor(async () => {
        expect(await getDocContentFromCache(id)).toMatchObject({
          markdownContent: acceptedMarkdown,
          originalMarkdownContent: nextUpdate === 'metadata' ? 'unapplied source' : 'latest source',
        })
      })
    },
  )

  it('does not cancel a pending write for an update containing no content or metadata changes', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { useParsedFiles } = await import('@/store/use-parsed-files-store')
    const id = await useParsedFiles.getState().addParsedFile({
      filename: 'unchanged.md',
      fileType: 'md',
      fileSize: 0,
      markdownContent: 'before',
      parser: 'test',
    })
    harness.deferNextWriteCompletion()
    const pending = useParsedFiles.getState().updateParsedFile(id, { markdownContent: 'after', status: 'parsed' })
    await vi.waitFor(() => expect(harness.pendingWriteCompletions()).toBe(1))

    await useParsedFiles.getState().updateParsedFile(id, { markdownContent: undefined })
    harness.flushPendingWriteCompletions()
    await pending

    expect(useParsedFiles.getState().getFile(id)?.markdownContent).toBe('after')
  })

  it('does not retry applying a metadata storage failure as an IndexedDB failure', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)
    const { useParsedFiles } = await import('@/store/use-parsed-files-store')
    const id = await useParsedFiles.getState().addParsedFile({
      filename: 'quota.md',
      fileType: 'md',
      fileSize: 0,
      markdownContent: 'before',
      parser: 'test',
    })
    const storage = window.localStorage
    let metadataWriteAttempts = 0
    vi.spyOn(window, 'localStorage', 'get').mockReturnValue({
      get length() {
        return storage.length
      },
      key: storage.key.bind(storage),
      clear: storage.clear.bind(storage),
      getItem: storage.getItem.bind(storage),
      removeItem: storage.removeItem.bind(storage),
      setItem: (key, value) => {
        if (key.startsWith('mimirq_parsed_files:')) {
          metadataWriteAttempts += 1
          throw new Error('metadata quota reached')
        }
        storage.setItem(key, value)
      },
    })
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    await expect(
      useParsedFiles.getState().updateParsedFile(id, { markdownContent: 'after', status: 'parsed' }),
    ).rejects.toThrow('metadata quota reached')

    expect(metadataWriteAttempts).toBe(1)
    expect(warn).not.toHaveBeenCalled()
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

    const { cacheDocContentIfMissing } = await import('./doc-content-cache')
    const pendingWrite = cacheDocContentIfMissing(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a',
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
      cacheDocContentIfMissing,
      saveDocSourceToCache,
    } = await import('./doc-content-cache')

    await cacheDocContentIfMissing(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a',
    )
    authMock.scope = 'tenant-b:user-b'
    await cacheDocContentIfMissing(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-b-safe',
        originalMarkdownContent: 'tenant-b-safe',
      },
      'tenant-b:user-b',
    )
    authMock.scope = 'tenant-a:user-a'
    await saveDocSourceToCache(
      {
        id: 'shared-document-id',
        file: new File(['a'], 'tenant-a.md', { type: 'text/markdown' }),
      },
      'tenant-a:user-a',
    )
    authMock.scope = 'tenant-b:user-b'
    await saveDocSourceToCache(
      {
        id: 'shared-document-id',
        file: new File(['b'], 'tenant-b.md', { type: 'text/markdown' }),
      },
      'tenant-b:user-b',
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

    const { clearDocCachesForScope, getDocContentFromCache, invalidateDocCacheScopeWrites, cacheDocContentIfMissing } =
      await import('./doc-content-cache')

    authMock.scope = 'tenant-a:user-a'
    harness.deferNextOpen()
    const staleWrite = cacheDocContentIfMissing(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a',
    )
    await Promise.resolve()
    await Promise.resolve()

    invalidateDocCacheScopeWrites('tenant-a:user-a')
    await clearDocCachesForScope('tenant-a:user-a')

    authMock.scope = 'tenant-b:user-b'
    await cacheDocContentIfMissing(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-b-safe',
        originalMarkdownContent: 'tenant-b-safe',
      },
      'tenant-b:user-b',
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

    const { getDocContentFromCache, invalidateDocCacheScopeWrites, cacheDocContentIfMissing } =
      await import('./doc-content-cache')

    authMock.scope = 'tenant-a:user-a'
    harness.deferNextWrite()
    const staleWrite = cacheDocContentIfMissing(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a',
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

    const { getDocContentFromCache, invalidateDocCacheScopeWrites, cacheDocContentIfMissing } =
      await import('./doc-content-cache')

    authMock.scope = 'tenant-a:user-a'
    harness.deferNextWriteCompletion()
    const staleWrite = cacheDocContentIfMissing(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a',
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
    const staleWrite = initialModule.cacheDocContentIfMissing(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-secret',
        originalMarkdownContent: 'tenant-a-secret',
      },
      'tenant-a:user-a',
    )
    await Promise.resolve()
    await Promise.resolve()

    vi.resetModules()
    const reloadedModule = await import('./doc-content-cache')
    reloadedModule.invalidateDocCacheScopeWrites('tenant-a:user-a')

    harness.flushPendingWrites()
    await staleWrite

    await expect(reloadedModule.getDocContentFromCache('shared-document-id', 'tenant-a:user-a')).resolves.toBeNull()
    expect(harness.listStoreKeys('doc_contents')).toEqual([])
  })

  it('keeps current-scope cache readable after module reload resets in-memory generations', async () => {
    const harness = createIndexedDbHarness()
    vi.stubGlobal('indexedDB', harness.indexedDB)

    const initialModule = await import('./doc-content-cache')
    authMock.scope = 'tenant-a:user-a'
    initialModule.invalidateDocCacheScopeWrites('tenant-a:user-a')
    await initialModule.clearDocCachesForScope('tenant-a:user-a')
    await initialModule.cacheDocContentIfMissing(
      {
        id: 'shared-document-id',
        markdownContent: 'tenant-a-safe',
        originalMarkdownContent: 'tenant-a-safe',
      },
      'tenant-a:user-a',
    )

    await expect(initialModule.getDocContentFromCache('shared-document-id', 'tenant-a:user-a')).resolves.toMatchObject({
      markdownContent: 'tenant-a-safe',
      originalMarkdownContent: 'tenant-a-safe',
    })

    vi.resetModules()
    const reloadedModule = await import('./doc-content-cache')

    await expect(reloadedModule.getDocContentFromCache('shared-document-id', 'tenant-a:user-a')).resolves.toMatchObject(
      {
        markdownContent: 'tenant-a-safe',
        originalMarkdownContent: 'tenant-a-safe',
      },
    )
  })
})
