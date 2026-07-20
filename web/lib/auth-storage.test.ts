// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AUTH_SCOPE_CHANGED_EVENT,
  clearAuthSession,
  getAuthCacheScope,
  setAuthSession,
} from './auth-storage'

const token = { access_token: 'token', token_type: 'bearer', expires_in: 3600 }

describe('auth storage scope', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('isolates cache keys and notifies listeners when the user changes or logs out', () => {
    localStorage.setItem('mimirq_tenant_id', 'tenant-a')
    const listener = vi.fn()
    const notifiedScopes: string[] = []
    const captureScope = () => notifiedScopes.push(getAuthCacheScope())
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, captureScope)

    setAuthSession({ token, user: { id: 'user-a' } as never })
    expect(getAuthCacheScope()).toBe('tenant-a:user-a')

    localStorage.setItem('mimirq_document_view_v1', '{"private":true}')
    setAuthSession({ token, user: { id: 'user-b' } as never })
    expect(getAuthCacheScope()).toBe('tenant-a:user-b')
    expect(localStorage.getItem('mimirq_document_view_v1')).toBeNull()
    expect(listener).toHaveBeenCalledTimes(1)
    expect(notifiedScopes).toEqual(['tenant-a:user-b'])

    clearAuthSession()
    expect(getAuthCacheScope()).toBe('tenant-a:anonymous')
    expect(listener).toHaveBeenCalledTimes(2)
    expect(notifiedScopes).toEqual(['tenant-a:user-b', 'tenant-a:anonymous'])

    window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)
    window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, captureScope)
  })

  it('bridges a cross-tab user scope change to the local auth event', () => {
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

    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, listener)
  })
})
