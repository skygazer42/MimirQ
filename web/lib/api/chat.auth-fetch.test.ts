// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createChatStreamFixture } from '@/test/chat-stream-fixture'

const auth = vi.hoisted(() => ({
  clear: vi.fn(),
  token: 'old-token',
}))
const oidc = vi.hoisted(() => ({
  refresh: vi.fn(),
}))

vi.mock('@/lib/auth-storage', () => ({
  clearAuthSession: auth.clear,
  getAccessToken: () => auth.token,
  getAuthSessionKey: () => 'default:user-a',
  getAuthSessionRevision: () => 0,
  getAuthCacheScope: () => 'default:user-a',
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

import { chatApi } from './chat'

const originalFetch = globalThis.fetch

describe('chatApi.streamChat auth retry', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.token = 'old-token'
    oidc.refresh.mockResolvedValue({
      access_token: 'new-token',
      token_type: 'bearer',
      expires_in: 3600,
    })
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('refreshes and retries once after a session JWT 401', async () => {
    const run = createChatStreamFixture({ requestId: 'req-stream-401' })
    const expectedEvents: string[] = []
    run.start((event) => expectedEvents.push(event))
    run.finish((event) => expectedEvents.push(event))
    const body = expectedEvents.map((event) => `data: ${event}\n\n`).join('')

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('unauthorized', { status: 401 }))
      .mockResolvedValueOnce(
        new Response(body, {
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream',
            'X-Request-ID': 'req-stream-401',
          },
        }),
      )
    globalThis.fetch = fetchMock as typeof fetch

    const events: string[] = []
    const result = await chatApi.streamChat({ message: 'hello', stream: true }, (json) => events.push(json))

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get('Authorization')).toBe('Bearer old-token')
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get('Authorization')).toBe('Bearer new-token')
    expect(oidc.refresh).toHaveBeenCalledTimes(1)
    expect(auth.clear).not.toHaveBeenCalled()
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(fetchMock.mock.calls[1]?.[1]?.body)
    expect(events).toEqual(expectedEvents)
    expect(result).toMatchObject({
      requestId: 'req-stream-401',
      conversationId: expect.any(String),
      runId: expect.any(String),
    })
  })
})
