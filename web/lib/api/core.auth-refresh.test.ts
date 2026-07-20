// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ clear: vi.fn(), token: 'old-token' }))

vi.mock('@/lib/auth-storage', () => ({
  clearAuthSession: auth.clear,
  getAccessToken: () => auth.token,
  setAccessToken: (token: { access_token: string }) => {
    auth.token = token.access_token
  },
}))
vi.mock('@/lib/auth-headers', () => ({
  getAuthHeaders: () => ({
    Authorization: `Bearer ${auth.token}`,
    'X-Tenant-ID': 'default-tenant',
  }),
}))
vi.mock('@/lib/oidc-session', () => ({
  tryRefreshOidcAccessToken: vi.fn().mockResolvedValue({
    access_token: 'new-token',
    token_type: 'bearer',
    expires_in: 3600,
  }),
}))

import { apiClient } from './core'
import { tryRefreshOidcAccessToken } from '@/lib/oidc-session'

describe('apiClient OIDC retry', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.token = 'old-token'
  })

  it('replaces the stale Authorization header after refreshing', async () => {
    const seen: string[] = []
    apiClient.defaults.adapter = vi.fn(async (config) => {
      seen.push(String(config.headers.Authorization || ''))
      if (seen.length === 1) {
        throw Object.assign(new Error('unauthorized'), {
          config,
          response: { status: 401, data: {}, headers: {} },
        })
      }
      return { config, data: { ok: true }, headers: {}, status: 200, statusText: 'OK' }
    })

    await expect(apiClient.get('/auth/me')).resolves.toMatchObject({ status: 200 })
    expect(seen).toEqual(['Bearer old-token', 'Bearer new-token'])
  })

  it('preserves explicit SCIM authorization and tenant headers', async () => {
    const adapter = vi.fn(async (config) => ({
      config,
      data: { ok: true },
      headers: {},
      status: 200,
      statusText: 'OK',
    }))
    apiClient.defaults.adapter = adapter

    await apiClient.get('/scim/v2/Users', {
      headers: {
        Authorization: 'Bearer scim-token',
        'X-Tenant-ID': 'scim-tenant',
      },
    })

    expect(adapter.mock.calls[0]?.[0].headers.Authorization).toBe('Bearer scim-token')
    expect(adapter.mock.calls[0]?.[0].headers['X-Tenant-ID']).toBe('scim-tenant')
  })

  it('does not refresh or clear the app session for a rejected SCIM token', async () => {
    apiClient.defaults.adapter = vi.fn(async (config) => {
      throw Object.assign(new Error('unauthorized'), {
        config,
        response: { status: 401, data: {}, headers: {} },
      })
    })

    await expect(apiClient.get('/scim/v2/Users', {
      headers: { Authorization: 'Bearer scim-token', 'X-Tenant-ID': 'scim-tenant' },
    })).rejects.toThrow('unauthorized')
    expect(tryRefreshOidcAccessToken).not.toHaveBeenCalled()
    expect(auth.clear).not.toHaveBeenCalled()
  })
})
