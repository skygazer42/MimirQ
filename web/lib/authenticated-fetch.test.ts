// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({
  clear: vi.fn(),
  token: 'session-token',
}))
const oidc = vi.hoisted(() => ({
  refresh: vi.fn(),
}))

vi.mock('@/lib/auth-storage', () => ({
  clearAuthSession: auth.clear,
  getAccessToken: () => auth.token,
  setAccessToken: (token: { access_token: string }) => {
    auth.token = token.access_token
  },
}))
vi.mock('@/lib/oidc-session', () => ({
  tryRefreshOidcAccessToken: oidc.refresh,
}))

import { authenticatedFetch } from './authenticated-fetch'

const originalFetch = globalThis.fetch

describe('authenticatedFetch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.token = 'session-token'
    oidc.refresh.mockResolvedValue(null)
    window.history.replaceState({}, '', '/workspace')
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('does not refresh or clear the app session for a non-session token 401', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('denied', { status: 401 })) as typeof fetch

    const response = await authenticatedFetch('/scim/v2/Users', {
      headers: { Authorization: 'Bearer scim-token' },
    })

    expect(response.status).toBe(401)
    expect(oidc.refresh).not.toHaveBeenCalled()
    expect(auth.clear).not.toHaveBeenCalled()
    expect(window.location.pathname).toBe('/workspace')
  })

  it('clears a rejected app session when refresh fails', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('denied', { status: 401 })) as typeof fetch
    window.history.replaceState({}, '', '/auth')

    await authenticatedFetch('/api/v1/chat/stream', {
      headers: { Authorization: 'Bearer session-token' },
    })

    expect(oidc.refresh).toHaveBeenCalledOnce()
    expect(auth.clear).toHaveBeenCalledOnce()
  })

  it('shares one refresh attempt across concurrent session-token 401 responses', async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response('denied', { status: 401 }))
      .mockResolvedValueOnce(new Response('denied', { status: 401 }))
      .mockResolvedValue(new Response('ok', { status: 200 })) as typeof fetch

    let resolveRefresh!: (value: { access_token: string; expires_in: number; token_type: string }) => void
    oidc.refresh.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRefresh = resolve
      })
    )

    const first = authenticatedFetch('/api/v1/documents/1/download', {
      headers: { Authorization: 'Bearer session-token' },
    })
    const second = authenticatedFetch('/api/v1/documents/2/download', {
      headers: { Authorization: 'Bearer session-token' },
    })

    resolveRefresh({
      access_token: 'fresh-token',
      expires_in: 3600,
      token_type: 'bearer',
    })

    const [firstResponse, secondResponse] = await Promise.all([first, second])

    expect(firstResponse.status).toBe(200)
    expect(secondResponse.status).toBe(200)
    expect(oidc.refresh).toHaveBeenCalledTimes(1)
  })

  it('does not apply a stale refresh result after the session token changes', async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response('denied', { status: 401 }))
      .mockResolvedValue(new Response('ok', { status: 200 })) as typeof fetch

    let resolveRefresh!: (value: { access_token: string; expires_in: number; token_type: string }) => void
    oidc.refresh.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRefresh = resolve
      })
    )

    const pending = authenticatedFetch('/api/v1/documents/1/download', {
      headers: { Authorization: 'Bearer session-token' },
    })

    auth.token = 'new-session-token'
    resolveRefresh({
      access_token: 'stale-refresh-token',
      expires_in: 3600,
      token_type: 'bearer',
    })

    const response = await pending

    expect(response.status).toBe(401)
    expect(auth.token).toBe('new-session-token')
    expect(auth.clear).not.toHaveBeenCalled()
  })
})
