// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
}))

vi.mock('@/lib/env', () => ({
  API_V1_BASE_URL: 'https://api.example.com/api/v1',
}))
vi.mock('server-only', () => ({}))

import { POST } from './route'

function makeRequest(cookie = 'mimirq_saml_bridge=bridge-code') {
  return new NextRequest('https://app.example.com/api/saml/session', {
    method: 'POST',
    headers: {
      origin: 'https://app.example.com',
      cookie,
    },
  })
}

describe('SAML session bridge route', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', mocks.fetch)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('redeems the bridge code once and clears the cookie', async () => {
    mocks.fetch.mockResolvedValue(
      Response.json({
        return_to: '/datasets/123',
        user: { id: 'user-1' },
        token: { access_token: 'jwt-token', token_type: 'bearer', expires_in: 3600 },
      })
    )

    const response = await POST(makeRequest())

    expect(response.status).toBe(200)
    expect(await response.json()).toMatchObject({
      return_to: '/datasets/123',
      token: { access_token: 'jwt-token' },
    })
    expect(mocks.fetch).toHaveBeenCalledWith(
      'https://api.example.com/api/v1/auth/saml/bridge/consume',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ code: 'bridge-code' }),
      })
    )
    const cookie = response.headers.get('set-cookie')
    expect(cookie).toContain('mimirq_saml_bridge=')
    expect(cookie).toContain('Max-Age=0')
  })
})
