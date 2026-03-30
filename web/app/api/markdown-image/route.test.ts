import { afterEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

describe('markdown image proxy route', () => {
  afterEach(() => {
    delete process.env.MARKDOWN_IMAGE_PROXY_SECRET
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('mints opaque proxy URLs instead of exposing the raw remote image URL', async () => {
    process.env.MARKDOWN_IMAGE_PROXY_SECRET = 'test-secret'

    const { POST } = await import('./route')
    const req = new NextRequest('https://app.example.com/api/markdown-image', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        src: 'https://example.com/image.png',
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    expect(res.headers.get('cache-control')).toContain('no-store')

    const body = await res.json()
    expect(body).toEqual({
      src: expect.stringContaining('/api/markdown-image?token='),
    })
    expect(String(body.src)).not.toContain('src=')
    expect(String(body.src)).not.toContain('example.com/image.png')
  })

  it('rejects loopback and private image targets', async () => {
    const { GET } = await import('./route')
    const req = new NextRequest('https://app.example.com/api/markdown-image?src=http%3A%2F%2F127.0.0.1%3A8000%2Fsecret.png')

    const res = await GET(req)
    expect(res.status).toBe(400)
    expect(res.headers.get('cache-control')).toContain('no-store')
    expect(await res.json()).toEqual({ error: 'invalid_image_src' })
  })

  it('streams safe remote images with cache and nosniff headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('png-bytes', {
        status: 200,
        headers: {
          'Content-Type': 'image/png',
          'Content-Length': '9',
          ETag: '"etag-1"',
        },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { GET } = await import('./route')
    const req = new NextRequest('https://app.example.com/api/markdown-image?src=https%3A%2F%2Fexample.com%2Fimage.png')

    const res = await GET(req)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith('https://example.com/image.png', {
      headers: { Accept: 'image/*' },
      redirect: 'manual',
    })
    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toBe('image/png')
    expect(res.headers.get('cache-control')).toContain('max-age=300')
    expect(res.headers.get('x-content-type-options')).toBe('nosniff')
    expect(await res.text()).toBe('png-bytes')
  })

  it('accepts opaque proxy tokens for image fetches', async () => {
    process.env.MARKDOWN_IMAGE_PROXY_SECRET = 'test-secret'

    const fetchMock = vi.fn().mockResolvedValue(
      new Response('png-bytes', {
        status: 200,
        headers: {
          'Content-Type': 'image/png',
          'Content-Length': '9',
          ETag: '"etag-1"',
        },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { GET, POST } = await import('./route')
    const mintReq = new NextRequest('https://app.example.com/api/markdown-image', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        src: 'https://example.com/image.png',
      }),
    })
    const mintRes = await POST(mintReq)
    const { src } = await mintRes.json()

    const res = await GET(new NextRequest(`https://app.example.com${src}`))
    expect(fetchMock).toHaveBeenCalledWith('https://example.com/image.png', {
      headers: { Accept: 'image/*' },
      redirect: 'manual',
    })
    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toBe('image/png')
    expect(await res.text()).toBe('png-bytes')
  })

  it('rejects non-image upstream responses', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('<html>tracker</html>', {
        status: 200,
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
        },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { GET } = await import('./route')
    const req = new NextRequest('https://app.example.com/api/markdown-image?src=https%3A%2F%2Fexample.com%2Ftracker')

    const res = await GET(req)
    expect(res.status).toBe(415)
    expect(res.headers.get('cache-control')).toContain('no-store')
    expect(await res.json()).toEqual({ error: 'image_content_type_invalid' })
  })

  it('rejects invalid opaque image tokens', async () => {
    process.env.MARKDOWN_IMAGE_PROXY_SECRET = 'test-secret'

    const { GET } = await import('./route')
    const req = new NextRequest('https://app.example.com/api/markdown-image?token=invalid-token')

    const res = await GET(req)
    expect(res.status).toBe(400)
    expect(res.headers.get('cache-control')).toContain('no-store')
    expect(await res.json()).toEqual({ error: 'invalid_image_token' })
  })
})
