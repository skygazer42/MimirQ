// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AUTH_SCOPE_CHANGED_EVENT,
  clearAuthSession,
  getAuthCacheScope,
  getAccessToken,
  getStoredUser,
  getTenantId,
  setAuthSession,
  setAccessToken,
} from './auth-storage'

const token = { access_token: 'token', token_type: 'bearer', expires_in: 3600 }

describe('auth storage scope', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('preserves an explicitly selected tenant for the first login only', () => {
    localStorage.setItem('mimirq_tenant_id', 'tenant-a')

    setAuthSession({ token, user: { id: 'user-a' } as never })

    expect(getTenantId()).toBe('tenant-a')
    expect(getAuthCacheScope()).toBe('tenant-a:user-a')
  })

  it('clears a stale tenant exactly once when switching to another user and on logout', () => {
    localStorage.setItem('mimirq_tenant_id', 'tenant-a')
    const listener = vi.fn()
    const notifiedScopes: string[] = []
    const captureScope = () => notifiedScopes.push(getAuthCacheScope())
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, captureScope)

    setAuthSession({ token, user: { id: 'user-a' } as never })
    expect(getAuthCacheScope()).toBe('tenant-a:user-a')
    expect(listener).toHaveBeenCalledTimes(1)
    expect(notifiedScopes).toEqual(['tenant-a:user-a'])

    localStorage.setItem('mimirq_document_view_v1', '{"private":true}')
    setAuthSession({ token, user: { id: 'user-b' } as never })
    expect(getTenantId()).toBeNull()
    expect(getAuthCacheScope()).toBe('default:user-b')
    expect(localStorage.getItem('mimirq_document_view_v1')).toBeNull()
    expect(listener).toHaveBeenCalledTimes(2)
    expect(notifiedScopes).toEqual(['tenant-a:user-a', 'default:user-b'])

    clearAuthSession()
    expect(getTenantId()).toBeNull()
    expect(getAuthCacheScope()).toBe('default:anonymous')
    expect(listener).toHaveBeenCalledTimes(3)
    expect(notifiedScopes).toEqual(['tenant-a:user-a', 'default:user-b', 'default:anonymous'])

    window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)
    window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, captureScope)
  })

  it('keeps the tenant when refreshing the same user session', () => {
    localStorage.setItem('mimirq_tenant_id', 'tenant-a')

    setAuthSession({ token, user: { id: 'user-a' } as never })
    setAuthSession({ token: { ...token, access_token: 'token-2' }, user: { id: 'user-a' } as never })

    expect(getTenantId()).toBe('tenant-a')
    expect(getAuthCacheScope()).toBe('tenant-a:user-a')
  })

  it('stores the access token in sessionStorage instead of localStorage', () => {
    setAuthSession({ token, user: { id: 'user-a' } as never })

    expect(sessionStorage.getItem('mimirq_access_token')).toBe('token')
    expect(localStorage.getItem('mimirq_access_token')).toBeNull()
    expect(sessionStorage.getItem('mimirq_token_expires_at')).toBeTruthy()
    expect(localStorage.getItem('mimirq_token_expires_at')).toBeNull()
  })

  it('migrates a legacy localStorage access token into sessionStorage on read', () => {
    localStorage.setItem('mimirq_access_token', 'legacy-token')
    localStorage.setItem('mimirq_token_expires_at', '123')
    localStorage.setItem('mimirq_user_profile', JSON.stringify({ id: 'legacy-user' }))
    localStorage.setItem('mimirq_user_id', 'legacy-user')

    expect(getAccessToken()).toBe('legacy-token')
    expect(sessionStorage.getItem('mimirq_access_token')).toBe('legacy-token')
    expect(sessionStorage.getItem('mimirq_token_expires_at')).toBe('123')
    expect(getStoredUser()).toEqual({ id: 'legacy-user' })
    expect(localStorage.getItem('mimirq_access_token')).toBeNull()
    expect(localStorage.getItem('mimirq_token_expires_at')).toBeNull()
  })

  it('keeps the legacy token when sessionStorage is unavailable during migration', () => {
    localStorage.setItem('mimirq_access_token', 'legacy-token')
    localStorage.setItem('mimirq_token_expires_at', '123')
    localStorage.setItem('mimirq_user_profile', JSON.stringify({ id: 'legacy-user' }))
    localStorage.setItem('mimirq_user_id', 'legacy-user')

    const sessionStorageGetter = vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => {
      throw new Error('blocked')
    })

    try {
      expect(getAccessToken()).toBe('legacy-token')
      expect(getStoredUser()).toEqual({ id: 'legacy-user' })
      expect(localStorage.getItem('mimirq_access_token')).toBe('legacy-token')
      expect(localStorage.getItem('mimirq_token_expires_at')).toBe('123')
    } finally {
      sessionStorageGetter.mockRestore()
    }
  })

  it('keeps the legacy token when sessionStorage writes fail during migration', () => {
    localStorage.setItem('mimirq_access_token', 'legacy-token')
    localStorage.setItem('mimirq_token_expires_at', '123')

    const originalSessionStorage = window.sessionStorage
    const blockedSessionStorage = {
      getItem: originalSessionStorage.getItem.bind(originalSessionStorage),
      setItem: vi.fn(() => {
        throw new Error('blocked')
      }),
      removeItem: originalSessionStorage.removeItem.bind(originalSessionStorage),
      clear: originalSessionStorage.clear.bind(originalSessionStorage),
      key: originalSessionStorage.key.bind(originalSessionStorage),
      get length() {
        return originalSessionStorage.length
      },
    } as Storage
    const sessionStorageGetter = vi.spyOn(window, 'sessionStorage', 'get').mockReturnValue(blockedSessionStorage)

    try {
      expect(getAccessToken()).toBe('legacy-token')
      expect(localStorage.getItem('mimirq_access_token')).toBe('legacy-token')
      expect(localStorage.getItem('mimirq_token_expires_at')).toBe('123')
    } finally {
      sessionStorageGetter.mockRestore()
    }
  })

  it('clears legacy and session token storage on logout', () => {
    localStorage.setItem('mimirq_access_token', 'legacy-token')
    localStorage.setItem('mimirq_token_expires_at', '123')
    setAccessToken(token)

    clearAuthSession()

    expect(sessionStorage.getItem('mimirq_access_token')).toBeNull()
    expect(sessionStorage.getItem('mimirq_token_expires_at')).toBeNull()
    expect(localStorage.getItem('mimirq_access_token')).toBeNull()
    expect(localStorage.getItem('mimirq_token_expires_at')).toBeNull()
  })

  it('does not notify when writing or clearing the same auth scope', () => {
    const listener = vi.fn()
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)

    setAuthSession({ token, user: { id: 'user-a' } as never })
    setAuthSession({ token, user: { id: 'user-a' } as never })
    clearAuthSession()
    clearAuthSession()

    expect(listener).toHaveBeenCalledTimes(2)
    window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)
  })

  it('does not expose a persisted user profile or authenticated scope without a token', () => {
    localStorage.setItem('mimirq_user_profile', JSON.stringify({ id: 'user-a', email: 'user@example.com' }))
    localStorage.setItem('mimirq_user_id', 'user-a')
    localStorage.setItem('mimirq_tenant_id', 'tenant-a')

    expect(getStoredUser()).toBeNull()
    expect(getAuthCacheScope()).toBe('default:anonymous')
  })

  it('invalidates the current tab token when another tab changes user', () => {
    setAccessToken(token)
    localStorage.setItem('mimirq_user_id', 'user-b')
    const listener = vi.fn()
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'mimirq_user_id',
        oldValue: 'user-a',
        newValue: 'user-b',
      })
    )

    expect(getAccessToken()).toBeNull()
    expect(getAuthCacheScope()).toBe('default:anonymous')
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)
  })

  it('bridges only effective cross-tab tenant scope changes', () => {
    setAccessToken(token)
    localStorage.setItem('mimirq_user_id', 'user-a')
    localStorage.setItem('mimirq_tenant_id', 'tenant-b')
    const listener = vi.fn()
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'mimirq_tenant_id',
        oldValue: 'tenant-a',
        newValue: 'tenant-b',
      })
    )
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'mimirq_tenant_id',
        oldValue: 'tenant-b',
        newValue: 'tenant-b',
      })
    )

    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)
  })

  it('clears the current tab session token when another tab broadcasts a logout fallback event', () => {
    setAuthSession({ token, user: { id: 'user-a', email: 'user@example.com' } as never })
    const listener = vi.fn()
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'mimirq_auth_sync',
        newValue: JSON.stringify({
          id: 'clear-1',
          source: 'tab:remote',
          type: 'session-cleared',
        }),
      })
    )

    expect(getAccessToken()).toBeNull()
    expect(getStoredUser()).toBeNull()
    expect(getAuthCacheScope()).toBe('default:anonymous')
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)
  })

  it('drops a stale tenant when a different user logs in after a remote logout', () => {
    localStorage.setItem('mimirq_tenant_id', 'tenant-a')
    setAuthSession({ token, user: { id: 'user-a' } as never })

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'mimirq_auth_sync',
        newValue: JSON.stringify({
          id: 'clear-before-new-login',
          source: 'tab:remote',
          type: 'session-cleared',
        }),
      })
    )
    setAuthSession({ token: { ...token, access_token: 'token-b' }, user: { id: 'user-b' } as never })

    expect(getTenantId()).toBeNull()
    expect(getAuthCacheScope()).toBe('default:user-b')
  })

  it('closes the broadcast channel on pagehide and recreates it on the next auth write', async () => {
    class MockBroadcastChannel {
      static instances: MockBroadcastChannel[] = []
      static reset() {
        MockBroadcastChannel.instances = []
      }

      close = vi.fn()
      listeners = new Set<(event: MessageEvent) => void>()

      constructor(public readonly name: string) {
        MockBroadcastChannel.instances.push(this)
      }

      addEventListener(_type: 'message', listener: (event: MessageEvent) => void) {
        this.listeners.add(listener)
      }

      postMessage(_message: unknown) {}
    }

    MockBroadcastChannel.reset()
    vi.resetModules()
    vi.stubGlobal('BroadcastChannel', MockBroadcastChannel)

    const authStorage = await import('./auth-storage')
    expect(MockBroadcastChannel.instances).toHaveLength(1)

    window.dispatchEvent(new Event('pagehide'))
    expect(MockBroadcastChannel.instances[0]?.close).toHaveBeenCalledOnce()

    authStorage.setAccessToken(token)
    authStorage.clearAuthSession()

    expect(MockBroadcastChannel.instances).toHaveLength(2)
    vi.unstubAllGlobals()
  })
})
