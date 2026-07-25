// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getAuthHeaders } from './auth-headers'
import { getAccessToken, setAuthSession, setAccessToken } from './auth-storage'

const token = { access_token: 'token', token_type: 'bearer', expires_in: 3600 }

describe('getAuthHeaders', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.unstubAllEnvs()
  })

  it('prefers bearer auth and includes tenant context', () => {
    localStorage.setItem('mimirq_tenant_id', 'tenant-1')
    setAuthSession({ token, user: { id: 'user-1' } as never })

    expect(getAuthHeaders()).toEqual({ Authorization: 'Bearer token', 'X-Tenant-ID': 'tenant-1' })
  })

  it('falls back to env-backed header auth without a token', () => {
    vi.stubEnv('NEXT_PUBLIC_USER_ID', 'user-1')
    vi.stubEnv('NEXT_PUBLIC_TENANT_ID', 'tenant-1')

    expect(getAuthHeaders()).toEqual({ 'X-User-ID': 'user-1', 'X-Tenant-ID': 'tenant-1' })
  })

  it('does not emit shared auth metadata after another tab broadcasts logout', () => {
    localStorage.setItem('mimirq_tenant_id', 'tenant-1')
    setAuthSession({ token, user: { id: 'user-1' } as never })

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
    expect(localStorage.getItem('mimirq_user_id')).toBe('user-1')
    expect(localStorage.getItem('mimirq_tenant_id')).toBe('tenant-1')
    expect(getAuthHeaders()).toEqual({})
  })

  it('does not emit shared auth metadata after another tab switches users', () => {
    setAccessToken(token)
    localStorage.setItem('mimirq_user_id', 'user-a')
    localStorage.setItem('mimirq_tenant_id', 'tenant-a')
    localStorage.setItem('mimirq_user_id', 'user-b')

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'mimirq_user_id',
        oldValue: 'user-a',
        newValue: 'user-b',
      })
    )

    expect(getAccessToken()).toBeNull()
    expect(localStorage.getItem('mimirq_user_id')).toBe('user-b')
    expect(localStorage.getItem('mimirq_tenant_id')).toBe('tenant-a')
    expect(getAuthHeaders()).toEqual({})
  })
})
