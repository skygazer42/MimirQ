// @vitest-environment jsdom

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
})
