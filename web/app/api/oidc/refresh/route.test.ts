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

function makeRequest() {
  return new NextRequest('https://app.example.com/api/oidc/refresh', {
    method: 'POST',
    headers: {
      origin: 'https://app.example.com',
      cookie: 'mimirq_oidc_refresh_token=refresh-token; mimirq_oidc_provider_id=default',
    },
  })
}

function setTokenResponse(status: number, body: Record<string, unknown>) {
  oidc.fetch.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/.well-known/openid-configuration')) {
      return Response.json({
        token_endpoint: 'https://issuer.example.com/token',
      })
    }
    if (url === 'https://issuer.example.com/token') {
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    throw new Error(`unexpected fetch: ${url}`)
  })
}

describe('OIDC refresh route', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', oidc.fetch)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('clears refresh cookies only for terminal invalid_grant responses', async () => {
    setTokenResponse(400, {
      error: 'invalid_grant',
      error_description: 'refresh token expired',
    })

    const response = await POST(makeRequest())

    expect(response.status).toBe(400)
    expect(response.headers.get('set-cookie')).toContain('mimirq_oidc_refresh_token=')
    expect(response.headers.get('set-cookie')).toContain('Max-Age=0')
    expect(response.headers.get('set-cookie')).toContain('mimirq_oidc_provider_id=')
  })

  it('keeps cookies for non-terminal invalid_client responses', async () => {
    setTokenResponse(400, {
      error: 'invalid_client',
      error_description: 'bad client credentials',
    })

    const response = await POST(makeRequest())

    expect(response.status).toBe(400)
    expect(response.headers.get('set-cookie')).toBeNull()
  })

  it('keeps cookies and preserves 429 for temporary upstream throttling', async () => {
    setTokenResponse(429, {
      error: 'slow_down',
      error_description: 'rate limited',
    })

    const response = await POST(makeRequest())

    expect(response.status).toBe(429)
    expect(response.headers.get('set-cookie')).toBeNull()
  })

  it('keeps cookies and preserves 5xx for temporary upstream failures', async () => {
    setTokenResponse(503, {
      error: 'temporarily_unavailable',
      error_description: 'upstream unavailable',
    })

    const response = await POST(makeRequest())

    expect(response.status).toBe(503)
    expect(response.headers.get('set-cookie')).toBeNull()
  })
})
