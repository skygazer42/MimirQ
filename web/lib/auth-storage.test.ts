// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AUTH_SCOPE_CHANGED_EVENT,
  clearAuthSession,
  getAuthCacheScope,
  getTenantId,
  setAuthSession,
} from './auth-storage'

const token = { access_token: 'token', token_type: 'bearer', expires_in: 3600 }

describe('auth storage scope', () => {
  beforeEach(() => {
    localStorage.clear()
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

  it('bridges only effective cross-tab tenant scope changes', () => {
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
})
