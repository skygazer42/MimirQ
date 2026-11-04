// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authenticatedFetch } from './authenticated-fetch'
import { clearAuthSession, getAccessToken, getStoredUser, setAuthSession } from './auth-storage'
import { __resetOidcRefreshForTests } from './oidc-session'
import type { AuthToken, UserProfile } from '@/types/backend'

const token: AuthToken = { access_token: 'session-token', token_type: 'bearer', expires_in: 3600 }
const user: UserProfile = {
  id: 'user-a',
  email: 'a@example.com',
  username: 'a',
  is_active: true,
  created_at: '2026-11-04T00:00:00Z',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function refreshedResponse(ok = true) {
  return new Response(JSON.stringify(ok ? { ...token, access_token: 'fresh-token' } : { error: 'refresh failed' }), {
    status: ok ? 200 : 401,
  })
}

function sessionSnapshot() {
  return { token: getAccessToken(), userId: getStoredUser()?.id ?? null, path: window.location.pathname }
}

describe('authenticatedFetch', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    __resetOidcRefreshForTests()
    setAuthSession({ token, user })
    window.history.replaceState({}, '', '/auth')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('does not refresh or clear the app session for a non-session token 401', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('denied', { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)
    const response = await authenticatedFetch('/scim/v2/Users', { headers: { Authorization: 'Bearer scim-token' } })
    expect(response.status).toBe(401)
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(getAccessToken()).toBe('session-token')
  })

  it('clears a rejected app session when refresh fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('denied', { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)
    expect(
      (await authenticatedFetch('/api/v1/chat/stream', { headers: { Authorization: 'Bearer session-token' } })).status,
    ).toBe(401)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(getAccessToken()).toBeNull()
  })

  it('shares one real OIDC refresh across concurrent session-token 401 responses', async () => {
    const refresh = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/oidc/refresh') return refresh.promise
      return Promise.resolve(
        new Response('result', {
          status: new Headers(init?.headers).get('Authorization') === 'Bearer fresh-token' ? 200 : 401,
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const first = authenticatedFetch('/api/v1/documents/1/download', {
      headers: { Authorization: 'Bearer session-token' },
    })
    const second = authenticatedFetch('/api/v1/documents/2/download', {
      headers: { Authorization: 'Bearer session-token' },
    })
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === '/api/oidc/refresh')).toHaveLength(1),
    )
    refresh.resolve(refreshedResponse())
    expect((await Promise.all([first, second])).map((response) => response.status)).toEqual([200, 200])
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === '/api/oidc/refresh')).toHaveLength(1)
    expect(getAccessToken()).toBe('fresh-token')
  })

  it.each([
    { replacement: 'login-b', success: true },
    { replacement: 'login-b', success: false },
    { replacement: 'logout', success: true },
    { replacement: 'logout', success: false },
    { replacement: 'same-token-relogin', success: true },
    { replacement: 'same-token-relogin', success: false },
  ])('keeps $replacement when the previous refresh settles (success: $success)', async ({ replacement, success }) => {
    const refresh = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL) =>
      String(input) === '/api/oidc/refresh'
        ? refresh.promise
        : Promise.resolve(new Response('denied', { status: 401 })),
    )
    vi.stubGlobal('fetch', fetchMock)
    const pending = authenticatedFetch('/api/v1/chat/stream', { headers: { Authorization: 'Bearer session-token' } })
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    if (replacement === 'login-b')
      setAuthSession({ token: { ...token, access_token: 'token-b' }, user: { ...user, id: 'user-b' } })
    else {
      clearAuthSession()
      if (replacement === 'same-token-relogin') setAuthSession({ token, user })
    }
    const expected = sessionSnapshot()
    refresh.resolve(refreshedResponse(success))
    expect((await pending).status).toBe(401)
    expect(sessionSnapshot()).toEqual(expected)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not use an old request 401 to refresh a new session with the same token', async () => {
    const original = deferred<Response>()
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(original.promise)
      .mockResolvedValue(new Response('denied', { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)
    const pending = authenticatedFetch('/api/v1/documents/1/download', {
      headers: { Authorization: 'Bearer session-token' },
    })
    clearAuthSession()
    setAuthSession({ token, user })
    original.resolve(new Response('denied', { status: 401 }))
    expect((await pending).status).toBe(401)
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(getAccessToken()).toBe('session-token')
  })

  it.each([true, false])('propagates caller abort while refresh is pending (success: %s)', async (success) => {
    const refresh = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL) =>
      String(input) === '/api/oidc/refresh'
        ? refresh.promise
        : Promise.resolve(new Response('denied', { status: 401 })),
    )
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const outcome = authenticatedFetch('/api/v1/chat/stream', {
      headers: { Authorization: 'Bearer session-token' },
      signal: controller.signal,
    }).catch((error) => error)
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    controller.abort()
    refresh.resolve(refreshedResponse(success))
    expect(await outcome).toMatchObject({ name: 'AbortError' })
    expect(getAccessToken()).toBe('session-token')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('keeps telemetry unauthorized handling from logging out the current session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('denied', { status: 401 })))
    const response = await authenticatedFetch('/api/v1/observability/frontend-vitals', {
      headers: { Authorization: 'Bearer session-token' },
      allowSessionLogoutOnUnauthorized: false,
    })
    expect(response.status).toBe(401)
    expect(getAccessToken()).toBe('session-token')
  })
})
