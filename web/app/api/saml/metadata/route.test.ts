import { afterEach, describe, expect, it, vi } from 'vitest'

describe('SAML metadata route', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('returns 404 when SAML is disabled', async () => {
    vi.stubEnv('SAML_ENABLED', '')
    const { GET } = await import('./route')

    const req = {
      nextUrl: new URL('https://app.example.com/api/saml/metadata'),
    } as any

    const res = await GET(req)
    expect(res.status).toBe(404)
    expect(res.headers.get('cache-control')).toContain('no-store')
    expect(res.headers.get('content-type')).toContain('application/samlmetadata+xml')
  })

  it('proxies backend metadata when SAML is enabled', async () => {
    vi.stubEnv('SAML_ENABLED', 'true')
    const xml = `<?xml version="1.0" encoding="UTF-8"?><EntityDescriptor />`
    const fetchMock = vi.fn().mockResolvedValue(new Response(xml, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const { GET } = await import('./route')
    const req = {
      nextUrl: new URL('https://app.example.com/api/saml/metadata?provider_id=default'),
    } as any

    const res = await GET(req)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [any, RequestInit]
    expect(String(url)).toContain('/api/v1/auth/saml/metadata')
    expect(String(url)).toContain('provider_id=default')
    expect(init.method).toBe('GET')
    expect(init.cache).toBe('no-store')

    expect(res.status).toBe(200)
    expect(res.headers.get('cache-control')).toContain('no-store')
    expect(res.headers.get('content-type')).toContain('application/samlmetadata+xml')
    expect(await res.text()).toBe(xml)
  })
})

