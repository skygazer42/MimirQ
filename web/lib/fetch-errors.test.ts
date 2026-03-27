import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildFetchError } from './fetch-errors'

function createLocalStorage(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial))
  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key)
    }),
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('buildFetchError', () => {
  it('prefers backend json message and request_id over header', async () => {
    const response = new Response(JSON.stringify({ detail: 'bad request', request_id: 'rid-body' }), {
      status: 422,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-ID': 'rid-header',
      },
    })

    const err = await buildFetchError(response, 'fallback')
    expect(err.message).toContain('bad request')
    expect(err.message).toContain('request_id=rid-body')
  })

  it('falls back to header request id when body is not json', async () => {
    const response = new Response('oops', {
      status: 500,
      headers: {
        'X-Request-ID': 'rid-header',
      },
    })

    const err = await buildFetchError(response, 'fallback')
    expect(err.message).toContain('oops')
    expect(err.message).toContain('request_id=rid-header')
  })

  it('clears the auth session and redirects to /auth when a protected request is rejected', async () => {
    const location = { pathname: '/chat', href: '/chat' }
    const localStorage = createLocalStorage({
      mimirq_access_token: 'jwt-token',
      mimirq_user_profile: '{"id":"user-1"}',
      mimirq_user_id: 'user-1',
    })
    vi.stubGlobal('window', { localStorage, location })

    const response = new Response(JSON.stringify({ detail: 'expired token' }), {
      status: 401,
      headers: {
        'Content-Type': 'application/json',
      },
    })

    const err = await buildFetchError(response, 'fallback')

    expect(err.message).toContain('expired token')
    expect(localStorage.removeItem).toHaveBeenCalledWith('mimirq_access_token')
    expect(localStorage.removeItem).toHaveBeenCalledWith('mimirq_user_profile')
    expect(location.href).toBe('/auth')
  })

  it('clears the auth session without redirecting again on auth routes', async () => {
    const location = { pathname: '/auth/login', href: '/auth/login' }
    const localStorage = createLocalStorage({
      mimirq_access_token: 'jwt-token',
    })
    vi.stubGlobal('window', { localStorage, location })

    const response = new Response('unauthorized', { status: 401 })

    await buildFetchError(response, 'fallback')

    expect(localStorage.removeItem).toHaveBeenCalledWith('mimirq_access_token')
    expect(location.href).toBe('/auth/login')
  })

  it('does not clear or redirect when no stored token exists', async () => {
    const location = { pathname: '/chat', href: '/chat' }
    const localStorage = createLocalStorage()
    vi.stubGlobal('window', { localStorage, location })

    const response = new Response('unauthorized', { status: 401 })

    await buildFetchError(response, 'fallback')

    expect(localStorage.removeItem).not.toHaveBeenCalled()
    expect(location.href).toBe('/chat')
  })
})
