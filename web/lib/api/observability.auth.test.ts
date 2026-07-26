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
vi.mock('@/lib/auth-headers', () => ({
  getAuthHeaders: () => ({ Authorization: `Bearer ${auth.token}` }),
}))
vi.mock('@/lib/oidc-session', () => ({
  tryRefreshOidcAccessToken: oidc.refresh,
}))

import { observabilityApi } from './observability'

const originalFetch = globalThis.fetch

describe('observabilityApi auth handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.token = 'session-token'
    oidc.refresh.mockResolvedValue(null)
    window.history.replaceState({}, '', '/dashboard')
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('does not clear the app session or redirect on a telemetry 401', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('', { status: 401 })) as typeof fetch

    await expect(
      observabilityApi.reportFrontendVital({ id: 'web-vital-1', name: 'LCP', value: 123 })
    ).rejects.toThrow('Frontend vital report failed (HTTP 401)')

    expect(oidc.refresh).toHaveBeenCalledTimes(1)
    expect(auth.clear).not.toHaveBeenCalled()
    expect(window.location.pathname).toBe('/dashboard')
  })
})
