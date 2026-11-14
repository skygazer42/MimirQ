// @vitest-environment happy-dom

import type { InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAuthSession, getAccessToken, getStoredUser, setAuthSession } from '@/lib/auth-storage'
import { __resetOidcRefreshForTests } from '@/lib/oidc-session'
import type { AuthToken, UserProfile } from '@/types/backend'
import { apiClient } from './core'

const originalAdapter = apiClient.defaults.adapter
const token: AuthToken = { access_token: 'old-token', token_type: 'bearer', expires_in: 3600 }
const refreshed: AuthToken = { ...token, access_token: 'refreshed-token' }
const userA: UserProfile = {
  id: 'user-a',
  email: 'a@example.com',
  username: 'a',
  is_active: true,
  created_at: '2026-11-04T00:00:00Z',
}
const userB: UserProfile = { ...userA, id: 'user-b', email: 'b@example.com', username: 'b' }

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function unauthorized(config: InternalAxiosRequestConfig) {
  return Object.assign(new Error('unauthorized'), { config, response: { status: 401, data: {}, headers: {} } })
}

function refreshResponse(ok = true) {
  return new Response(JSON.stringify(ok ? refreshed : { error: 'refresh failed' }), {
    status: ok ? 200 : 401,
    headers: { 'Content-Type': 'application/json' },
  })
}

function sessionSnapshot() {
  return { token: getAccessToken(), userId: getStoredUser()?.id ?? null, path: window.location.pathname }
}

describe('apiClient OIDC retry', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    __resetOidcRefreshForTests()
    setAuthSession({ token, user: userA })
    window.history.replaceState({}, '', '/auth')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(refreshResponse()))
  })

  afterEach(() => {
    apiClient.defaults.adapter = originalAdapter
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('replaces the stale Authorization header after refreshing', async () => {
    const seen: string[] = []
    apiClient.defaults.adapter = vi.fn(async (config) => {
      seen.push(String(config.headers.Authorization || ''))
      if (seen.length === 1) throw unauthorized(config)
      return { config, data: { ok: true }, headers: {}, status: 200, statusText: 'OK' }
    })
    await expect(apiClient.get('/auth/me')).resolves.toMatchObject({ status: 200 })
    expect(seen).toEqual(['Bearer old-token', 'Bearer refreshed-token'])
    expect(getAccessToken()).toBe('refreshed-token')
    expect(fetch).toHaveBeenCalledOnce()
  })

  it('preserves explicit SCIM authorization and tenant headers', async () => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => ({
      config,
      data: { ok: true },
      headers: {},
      status: 200,
      statusText: 'OK',
    }))
    apiClient.defaults.adapter = adapter
    await apiClient.get('/scim/v2/Users', {
      headers: { Authorization: 'Bearer scim-token', 'X-Tenant-ID': 'scim-tenant' },
    })
    expect(adapter.mock.calls[0]?.[0].headers.Authorization).toBe('Bearer scim-token')
    expect(adapter.mock.calls[0]?.[0].headers['X-Tenant-ID']).toBe('scim-tenant')
  })

  it('does not refresh or clear the app session for a rejected SCIM token', async () => {
    apiClient.defaults.adapter = vi.fn(async (config) => {
      throw unauthorized(config)
    })
    await expect(
      apiClient.get('/scim/v2/Users', {
        headers: { Authorization: 'Bearer scim-token', 'X-Tenant-ID': 'scim-tenant' },
      }),
    ).rejects.toThrow('unauthorized')
    expect(fetch).not.toHaveBeenCalled()
    expect(sessionSnapshot()).toEqual({ token: 'old-token', userId: 'user-a', path: '/auth' })
  })

  it.each([
    { replacement: 'login-b', success: true },
    { replacement: 'login-b', success: false },
    { replacement: 'logout', success: true },
    { replacement: 'logout', success: false },
    { replacement: 'same-token-relogin', success: true },
    { replacement: 'same-token-relogin', success: false },
    { replacement: 'same-user-login', success: true },
  ])('preserves $replacement after a delayed refresh (success: $success)', async ({ replacement, success }) => {
    const refresh = deferred<Response>()
    vi.mocked(fetch).mockReturnValue(refresh.promise)
    const seen: string[] = []
    apiClient.defaults.adapter = vi.fn(async (config) => {
      seen.push(String(config.headers.Authorization))
      if (seen.length === 1) throw unauthorized(config)
      return { config, data: { ok: true }, headers: {}, status: 200, statusText: 'OK' }
    })
    const outcome = apiClient.get('/auth/me').then(
      (value) => ({ value }),
      (error) => ({ error }),
    )
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    if (replacement === 'login-b') setAuthSession({ token: { ...token, access_token: 'token-b' }, user: userB })
    else if (replacement === 'logout') clearAuthSession()
    else {
      if (replacement === 'same-token-relogin') clearAuthSession()
      setAuthSession({ token, user: userA })
    }
    const expectedSession = sessionSnapshot()
    refresh.resolve(refreshResponse(success))
    expect(await outcome).toMatchObject({ error: { message: 'unauthorized', response: { status: 401 } } })
    expect(sessionSnapshot()).toEqual(expectedSession)
    expect(seen).toEqual(['Bearer old-token'])
  })

  it('rejects an old request 401 after logout and reuse of the same token', async () => {
    const response = deferred<never>()
    let sentConfig!: InternalAxiosRequestConfig
    apiClient.defaults.adapter = vi.fn((config) => {
      sentConfig = config
      return response.promise
    })
    const outcome = apiClient.get('/auth/me').catch((error) => error)
    await vi.waitFor(() => expect(sentConfig).toBeDefined())
    clearAuthSession()
    setAuthSession({ token, user: userA })
    response.reject(unauthorized(sentConfig))
    expect(await outcome).toMatchObject({ message: 'unauthorized' })
    expect(fetch).not.toHaveBeenCalled()
    expect(sessionSnapshot()).toEqual({ token: 'old-token', userId: 'user-a', path: '/auth' })
  })

  it.each([true, false])('propagates cancellation while refresh is pending (refresh success: %s)', async (success) => {
    const refresh = deferred<Response>()
    vi.mocked(fetch).mockReturnValue(refresh.promise)
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      throw unauthorized(config)
    })
    apiClient.defaults.adapter = adapter
    const controller = new AbortController()
    const outcome = apiClient.get('/auth/me', { signal: controller.signal }).catch((error) => error)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    controller.abort()
    refresh.resolve(refreshResponse(success))
    expect(await outcome).toMatchObject({ code: 'ERR_CANCELED' })
    expect(sessionSnapshot()).toEqual({ token: 'old-token', userId: 'user-a', path: '/auth' })
    expect(adapter).toHaveBeenCalledOnce()
  })

  it('shares one refresh within a session and retries each request once', async () => {
    const refresh = deferred<Response>()
    vi.mocked(fetch).mockReturnValue(refresh.promise)
    const headers: string[] = []
    apiClient.defaults.adapter = vi.fn(async (config) => {
      const authorization = String(config.headers.Authorization)
      headers.push(authorization)
      if (authorization === 'Bearer old-token') throw unauthorized(config)
      return { config, data: { ok: true }, headers: {}, status: 200, statusText: 'OK' }
    })
    const first = apiClient.get('/auth/me')
    const second = apiClient.get('/documents')
    await vi.waitFor(() => expect(headers).toHaveLength(2))
    refresh.resolve(refreshResponse())
    expect((await Promise.all([first, second])).map((response) => response.status)).toEqual([200, 200])
    expect(fetch).toHaveBeenCalledOnce()
    expect(headers).toEqual([
      'Bearer old-token',
      'Bearer old-token',
      'Bearer refreshed-token',
      'Bearer refreshed-token',
    ])
  })

  it('clears the current session after one refreshed retry is also rejected', async () => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      throw unauthorized(config)
    })
    apiClient.defaults.adapter = adapter
    await expect(apiClient.get('/auth/me')).rejects.toThrow('unauthorized')
    expect(fetch).toHaveBeenCalledOnce()
    expect(adapter).toHaveBeenCalledTimes(2)
    expect(getAccessToken()).toBeNull()
  })

  it('keeps refresh single-flight within each session when another user signs in mid-refresh', async () => {
    const oldRefresh = deferred<Response>()
    const currentRefresh = deferred<Response>()
    vi.mocked(fetch).mockReturnValueOnce(oldRefresh.promise).mockReturnValueOnce(currentRefresh.promise)
    const seen: string[] = []
    apiClient.defaults.adapter = vi.fn(async (config) => {
      const authorization = String(config.headers.Authorization)
      seen.push(authorization)
      if (!authorization.includes('fresh-b')) throw unauthorized(config)
      return { config, data: { ok: true }, headers: {}, status: 200, statusText: 'OK' }
    })
    const oldOutcome = apiClient.get('/auth/me').catch((error) => error)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    setAuthSession({ token: { ...token, access_token: 'token-b' }, user: userB })
    const currentOutcome = apiClient.get('/auth/me')
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    currentRefresh.resolve(new Response(JSON.stringify({ ...token, access_token: 'fresh-b' }), { status: 200 }))
    await expect(currentOutcome).resolves.toMatchObject({ status: 200 })
    oldRefresh.resolve(refreshResponse())
    expect(await oldOutcome).toMatchObject({ message: 'unauthorized' })
    expect(sessionSnapshot()).toEqual({ token: 'fresh-b', userId: 'user-b', path: '/auth' })
    expect(seen).toEqual(['Bearer old-token', 'Bearer token-b', 'Bearer fresh-b'])
  })

  it('preserves the anonymous 401 contract without trying to refresh', async () => {
    clearAuthSession()
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      throw unauthorized(config)
    })
    apiClient.defaults.adapter = adapter
    await expect(apiClient.get('/health')).rejects.toThrow('unauthorized')
    expect(adapter.mock.calls[0]?.[0].headers.Authorization).toBeUndefined()
    expect(fetch).not.toHaveBeenCalled()
    expect(getAccessToken()).toBeNull()
  })

  it('preserves the current session and exact server error on a 500 response', async () => {
    let failure!: Error
    apiClient.defaults.adapter = vi.fn(async (config) => {
      failure = Object.assign(new Error('backend failed'), {
        config,
        response: { status: 500, data: { detail: 'backend failed' }, headers: {} },
      })
      throw failure
    })
    expect(await apiClient.get('/auth/me').catch((error) => error)).toBe(failure)
    expect(fetch).not.toHaveBeenCalled()
    expect(getAccessToken()).toBe('old-token')
  })

  it('does not let a cancelled caller stop a peer that shares its refresh', async () => {
    const refresh = deferred<Response>()
    vi.mocked(fetch).mockReturnValue(refresh.promise)
    const seen: string[] = []
    apiClient.defaults.adapter = vi.fn(async (config) => {
      const authorization = String(config.headers.Authorization)
      seen.push(authorization)
      if (authorization === 'Bearer old-token') throw unauthorized(config)
      return { config, data: { ok: true }, headers: {}, status: 200, statusText: 'OK' }
    })
    const controller = new AbortController()
    const cancelled = apiClient.get('/auth/me', { signal: controller.signal }).catch((error) => error)
    const peer = apiClient.get('/documents')
    await vi.waitFor(() => expect(seen).toHaveLength(2))
    controller.abort()
    refresh.resolve(refreshResponse())
    expect(await cancelled).toMatchObject({ code: 'ERR_CANCELED' })
    await expect(peer).resolves.toMatchObject({ status: 200 })
    expect(fetch).toHaveBeenCalledOnce()
    expect(seen).toEqual(['Bearer old-token', 'Bearer old-token', 'Bearer refreshed-token'])
  })

  it('does not publish a refresh into another tenant scope with the same token', async () => {
    const refresh = deferred<Response>()
    vi.mocked(fetch).mockReturnValue(refresh.promise)
    apiClient.defaults.adapter = vi.fn(async (config) => {
      throw unauthorized(config)
    })
    const outcome = apiClient.get('/auth/me').catch((error) => error)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    localStorage.setItem('mimirq_tenant_id', 'tenant-b')
    window.dispatchEvent(new StorageEvent('storage', { key: 'mimirq_tenant_id', oldValue: null, newValue: 'tenant-b' }))
    refresh.resolve(refreshResponse())
    expect(await outcome).toMatchObject({ message: 'unauthorized' })
    expect(sessionSnapshot()).toEqual({ token: 'old-token', userId: 'user-a', path: '/auth' })
    expect(localStorage.getItem('mimirq_tenant_id')).toBe('tenant-b')
  })
})
