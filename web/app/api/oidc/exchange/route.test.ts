// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

const oidc = vi.hoisted(() => ({
  providers: [
    {
      id: 'default',
      issuer: 'https://issuer.example.com',
      client_id: 'client-id',
      client_secret: 'client-secret',
      client_auth_method: 'basic' as const,
    },
  ],
  fetch: vi.fn(),
}))

vi.mock('@/lib/oidc-providers', () => ({
  getOidcServerProvidersFromEnv: () => oidc.providers,
  resolveOidcServerProvider: () => oidc.providers[0],
}))
vi.mock('server-only', () => ({}))

import { POST } from './route'

function makeRequest({
  origin = 'https://app.example.com',
  body = {
    code: 'auth-code',
    code_verifier: 'verifier',
    provider_id: 'default',
    redirect_uri: 'https://app.example.com/auth/oidc/callback',
  },
}: {
  origin?: string
  body?: Record<string, string>
} = {}) {
  return new NextRequest('https://app.example.com/api/oidc/exchange', {
    method: 'POST',
    headers: { origin, 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
}

describe('OIDC exchange route', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', oidc.fetch)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('rejects cross-origin exchange requests without touching the upstream provider', async () => {
    const response = await POST(makeRequest({ origin: 'https://evil.example.com' }))

    expect(response.status).toBe(403)
    expect(await response.json()).toEqual({ error: 'oidc_invalid_origin' })
    expect(response.headers.get('cache-control')).toBe('no-store')
    expect(oidc.fetch).not.toHaveBeenCalled()
  })

  it('returns no-store JSON and stores refresh/provider cookies on success', async () => {
    oidc.fetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/.well-known/openid-configuration')) {
        return Response.json({ token_endpoint: 'https://issuer.example.com/token' })
      }
      if (url === 'https://issuer.example.com/token') {
        return Response.json({
          access_token: 'access-token',
          token_type: 'Bearer',
          expires_in: 1800,
          refresh_token: 'refresh-token',
          id_token: 'id-token',
        })
      }
      throw new Error(`unexpected fetch: ${url}`)
    })

    const response = await POST(makeRequest())

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({
      access_token: 'access-token',
      token_type: 'bearer',
      expires_in: 1800,
      id_token: 'id-token',
    })
    expect(response.headers.get('cache-control')).toBe('no-store')
    const cookie = response.headers.get('set-cookie')
    expect(cookie).toContain('mimirq_oidc_refresh_token=refresh-token')
    expect(cookie).toContain('mimirq_oidc_provider_id=default')
    expect(cookie).toContain('HttpOnly')
    expect(cookie).toContain('Path=/api/oidc')
    expect(cookie).toContain('SameSite=lax')
  })
})
