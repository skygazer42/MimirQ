// @vitest-environment jsdom

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
    requests[0]?.onsuccess?.()
    await pendingWrite

    expect(transaction).not.toHaveBeenCalled()
  })
})
