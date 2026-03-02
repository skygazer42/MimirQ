import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { __resetOidcRefreshForTests, tryRefreshOidcAccessToken } from './oidc-session'

describe('oidc-session refresh', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    __resetOidcRefreshForTests()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    __resetOidcRefreshForTests()
  })

  it('returns null when refresh endpoint fails', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ error: 'invalid_grant' }),
    }) as any

    const token = await tryRefreshOidcAccessToken()
    expect(token).toBeNull()
  })

  it('dedupes concurrent refresh calls (single in-flight request)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: 't1', token_type: 'Bearer', expires_in: 3600 }),
    })
    globalThis.fetch = fetchMock as any

    const [a, b] = await Promise.all([tryRefreshOidcAccessToken(), tryRefreshOidcAccessToken()])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(a?.access_token).toBe('t1')
    expect(b?.access_token).toBe('t1')
    expect(a?.token_type).toBe('bearer')
  })
})

