import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('server-only', () => ({}))

import { buildMarkdownImageResponseHeaders } from './response-headers'

describe('markdown image proxy', () => {
  afterEach(() => {
    vi.resetModules()
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('requires an opaque token for production GET requests', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    const { GET } = await import('./route')
    const request = new NextRequest(
      'http://localhost/api/markdown-image?src=https%3A%2F%2Fexample.com%2Fsigned.png%3Ftoken%3Dsecret',
    )

    const response = await GET(request)

    expect(response.status).toBe(400)
    await expect(response.json()).resolves.toEqual({ error: 'image_token_required' })
  })

  it('uses private no-store caching for served image responses', () => {
    const headers = buildMarkdownImageResponseHeaders('image/png', {
      etag: '"abc123"',
      'last-modified': 'Wed, 21 Oct 2015 07:28:00 GMT',
    })

    expect(headers.get('Content-Type')).toBe('image/png')
    expect(headers.get('Cache-Control')).toBe('private, no-store')
    expect(headers.get('Pragma')).toBe('no-cache')
    expect(headers.get('X-Content-Type-Options')).toBe('nosniff')
    expect(headers.get('ETag')).toBe('"abc123"')
    expect(headers.get('Last-Modified')).toBe('Wed, 21 Oct 2015 07:28:00 GMT')
  })

  it('requires an authenticated same-origin request to mint production tokens', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    const { POST } = await import('./route')
    const request = new NextRequest('http://localhost/api/markdown-image', {
      method: 'POST',
      headers: { origin: 'http://localhost', 'content-type': 'application/json' },
      body: JSON.stringify({ src: 'https://example.com/image.png' }),
    })

    const response = await POST(request)

    expect(response.status).toBe(401)
    await expect(response.json()).resolves.toEqual({ error: 'image_proxy_unauthorized' })
  })

  it('mints an opaque production token after backend authentication', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('MARKDOWN_IMAGE_PROXY_SECRET', 'test-proxy-secret')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 200 })))
    const { POST } = await import('./route')
    const request = new NextRequest('http://web:3000/api/markdown-image', {
      method: 'POST',
      headers: {
        origin: 'https://app.example.com',
        authorization: 'Bearer valid-token',
        'content-type': 'application/json',
        'x-forwarded-host': 'app.example.com',
        'x-forwarded-proto': 'https',
      },
      body: JSON.stringify({ src: 'https://example.com/image.png' }),
    })

    const response = await POST(request)

    expect(response.status).toBe(200)
    await expect(response.json()).resolves.toEqual({
      src: expect.stringMatching(/^\/api\/markdown-image\?token=v1\./),
    })
  })

  it('accepts production header-mode auth when backend /auth/me validates it', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('MARKDOWN_IMAGE_PROXY_SECRET', 'test-proxy-secret')
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const { POST } = await import('./route')
    const request = new NextRequest('http://web:3000/api/markdown-image', {
      method: 'POST',
      headers: {
        origin: 'https://app.example.com',
        'content-type': 'application/json',
        'x-forwarded-host': 'app.example.com',
        'x-forwarded-proto': 'https',
        'x-tenant-id': 'tenant-123',
        'x-user-id': 'user-1',
      },
      body: JSON.stringify({ src: 'https://example.com/image.png' }),
    })

    const response = await POST(request)

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/auth\/me$/),
      expect.objectContaining({
        cache: 'no-store',
        headers: {
          'X-Tenant-ID': 'tenant-123',
          'X-User-ID': 'user-1',
        },
      }),
    )
    expect(response.status).toBe(200)
    await expect(response.json()).resolves.toEqual({
      src: expect.stringMatching(/^\/api\/markdown-image\?token=v1\./),
    })
  })
})
