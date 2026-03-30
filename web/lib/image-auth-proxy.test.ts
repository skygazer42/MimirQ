import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchAuthAssetUrl, needsAuthAssetProxy } from './image-auth-proxy'

describe('image auth proxy', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('treats external HTTP images as needing a same-origin proxy hop', () => {
    expect(needsAuthAssetProxy('https://example.com/image.png')).toBe(true)
  })

  it('mints opaque proxy URLs for external images before rendering them', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ src: '/api/markdown-image?token=opaque-token' }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
        },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchAuthAssetUrl('https://example.com/image.png')).resolves.toBe(
      '/api/markdown-image?token=opaque-token'
    )
    expect(fetchMock).toHaveBeenCalledWith('/api/markdown-image', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        src: 'https://example.com/image.png',
      }),
    })
  })

  it('falls back to the legacy query proxy if token minting fails', async () => {
    const rawUrl = 'https://fallback.example.com/image.png'

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: 'proxy_secret_unavailable' }), {
          status: 503,
          headers: {
            'Content-Type': 'application/json',
          },
        }),
      ),
    )

    await expect(fetchAuthAssetUrl(rawUrl)).resolves.toBe(
      '/api/markdown-image?src=https%3A%2F%2Ffallback.example.com%2Fimage.png'
    )
  })
})
