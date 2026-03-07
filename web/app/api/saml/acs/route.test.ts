import { afterEach, describe, expect, it, vi } from 'vitest'

const COOKIE_NAME = 'mimirq_saml_bridge'

describe('SAML ACS route', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('returns 404 when SAML is disabled', async () => {
    vi.stubEnv('SAML_ENABLED', '')
    const { POST } = await import('./route')

    const req = new Request('https://app.example.com/api/saml/acs', {
      method: 'POST',
      body: new URLSearchParams({ SAMLResponse: 'base64-response' }),
    }) as any

    const res = await POST(req)
    expect(res.status).toBe(404)
    expect(res.headers.get('cache-control')).toContain('no-store')
    expect(await res.json()).toEqual({ error: 'saml_disabled' })
  })

  it('forwards the assertion to backend exchange and redirects to the callback on success', async () => {
    vi.stubEnv('SAML_ENABLED', 'true')
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          user: {
            id: '00000000-0000-0000-0000-000000000001',
            email: 'alice@example.com',
            username: 'alice',
            is_active: true,
            created_at: '2026-03-07T00:00:00Z',
            last_login_at: null,
          },
          token: {
            access_token: 'jwt-token',
            token_type: 'bearer',
            expires_in: 3600,
          },
          return_to: '/datasets/123',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { POST } = await import('./route')
    const req = new Request('https://app.example.com/api/saml/acs?provider_id=default', {
      method: 'POST',
      body: new URLSearchParams({
        SAMLResponse: 'base64-response',
        RelayState: '/datasets/123',
      }),
    }) as any

    const res = await POST(req)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/api/v1/auth/saml/exchange')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(String(init.body))).toEqual({
      provider_id: 'default',
      saml_response: 'base64-response',
      relay_state: '/datasets/123',
      acs_url: 'https://app.example.com/api/saml/acs',
    })

    expect(res.status).toBe(303)
    expect(res.headers.get('location')).toBe('https://app.example.com/auth/saml/callback')
    expect(res.headers.get('set-cookie')).toContain(COOKIE_NAME)
    expect(res.headers.get('set-cookie')).toContain('/auth/saml/callback')
    expect(res.headers.get('cache-control')).toContain('no-store')
  })

  it('redirects to the callback with an error bridge cookie when backend exchange fails', async () => {
    vi.stubEnv('SAML_ENABLED', 'true')
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Invalid SAML signature' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { POST } = await import('./route')
    const req = new Request('https://app.example.com/api/saml/acs', {
      method: 'POST',
      body: new URLSearchParams({ SAMLResponse: 'base64-response' }),
    }) as any

    const res = await POST(req)
    expect(res.status).toBe(303)
    expect(res.headers.get('location')).toBe('https://app.example.com/auth/saml/callback')
    expect(res.headers.get('set-cookie')).toContain(COOKIE_NAME)
    expect(res.headers.get('cache-control')).toContain('no-store')
  })
})
