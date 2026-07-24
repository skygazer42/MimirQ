// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
}))

vi.mock('@/lib/env', () => ({
  API_V1_BASE_URL: 'https://api.example.com/api/v1',
}))

import { POST } from './route'

function makeRequest() {
  const form = new FormData()
  form.set('SAMLResponse', 'base64-response')
  form.set('RelayState', '/datasets/123')
  return new NextRequest('https://app.example.com/api/saml/acs?provider_id=default', {
    method: 'POST',
    body: form,
  })
}

describe('SAML ACS route', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', mocks.fetch)
    process.env.SAML_ENABLED = 'true'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    delete process.env.SAML_ENABLED
  })

  it('stores only an opaque bridge code in an httpOnly cookie', async () => {
    mocks.fetch.mockResolvedValue(
      Response.json({
        bridge_code: 'bridge-code',
        return_to: '/datasets/123',
        user: { id: 'user-1' },
        token: { access_token: 'jwt-token', token_type: 'bearer', expires_in: 3600 },
      })
    )

    const response = await POST(makeRequest())

    expect(response.status).toBe(303)
    expect(response.headers.get('location')).toBe('https://app.example.com/auth/saml/callback')
    expect(mocks.fetch).toHaveBeenCalledWith(
      'https://api.example.com/api/v1/auth/saml/exchange',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(String),
      })
    )
    const [, requestInit] = mocks.fetch.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(requestInit.body))).toEqual({
      provider_id: 'default',
      saml_response: 'base64-response',
      relay_state: '/datasets/123',
      bridge_mode: true,
    })
    const cookie = response.headers.get('set-cookie')
    expect(cookie).toContain('mimirq_saml_bridge=bridge-code')
    expect(cookie).toContain('HttpOnly')
    expect(cookie).toContain('Path=/api/saml')
    expect(cookie).not.toContain('jwt-token')
  })

  it('clears the bridge cookie and redirects with an opaque code when exchange fails', async () => {
    mocks.fetch.mockResolvedValue(
      Response.json(
        { detail: 'Invalid SAML signature' },
        { status: 401 }
      )
    )

    const response = await POST(makeRequest())

    expect(response.status).toBe(303)
    expect(response.headers.get('location')).toBe(
      'https://app.example.com/auth/saml/callback?error=saml_invalid_response'
    )
    expect(response.headers.get('location')).not.toContain('Invalid+SAML+signature')
    const cookie = response.headers.get('set-cookie')
    expect(cookie).toContain('mimirq_saml_bridge=')
    expect(cookie).toContain('Max-Age=0')
  })
})
