import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({
  scope: 'tenant-123:user-1',
  revision: 0,
  token: 'jwt-token',
  tenantId: 'tenant-123',
  userId: 'user-1',
}))
const requests = vi.hoisted(() => ({
  authenticatedFetch: vi.fn(),
}))

vi.mock('@/lib/auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  AUTH_SESSION_CHANGED_EVENT: 'mimirq:auth-session-changed',
  getAccessToken: () => auth.token,
  getAuthSessionKey: () => JSON.stringify([auth.scope, auth.revision]),
  getStoredUserId: () => auth.userId,
  getTenantId: () => auth.tenantId,
}))
vi.mock('@/lib/authenticated-fetch', () => ({
  authenticatedFetch: requests.authenticatedFetch,
}))

import { fetchAuthAssetUrl } from './image-auth-proxy'
import { mintMarkdownImageProxyToken, resolveMarkdownImageProxyToken } from './markdown-image-proxy-token'

function streamingResponse() {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({
    start(value) {
      controller = value
    },
  })
  return {
    response: new Response(body, { status: 200 }),
    finish(content: string) {
      controller.enqueue(new TextEncoder().encode(content))
      controller.close()
    },
  }
}

describe('fetchAuthAssetUrl', () => {
  const originalCreateObjectUrl = (URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL

  beforeEach(() => {
    vi.restoreAllMocks()
    auth.scope = 'tenant-123:user-1'
    auth.revision += 1
    auth.token = 'jwt-token'
    auth.tenantId = 'tenant-123'
    auth.userId = 'user-1'
    requests.authenticatedFetch.mockReset()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    if (originalCreateObjectUrl) {
      ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = originalCreateObjectUrl
    } else {
      Object.defineProperty(URL, 'createObjectURL', {
        value: undefined,
        configurable: true,
        writable: true,
      })
    }
  })

  it('fetches protected backend asset URLs with Authorization headers and returns a blob URL', async () => {
    requests.authenticatedFetch.mockResolvedValue(new Response(new Blob(['asset-bytes']), { status: 200 }))
    const createObjectUrl = vi.fn(() => 'blob:asset-url')

    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = createObjectUrl

    const result = await fetchAuthAssetUrl('/api/v1/documents/123/download')

    expect(result).toBe('blob:asset-url')
    expect(requests.authenticatedFetch).toHaveBeenCalledWith('http://localhost:8000/api/v1/documents/123/download', {
      signal: expect.any(AbortSignal),
      headers: {
        Authorization: 'Bearer jwt-token',
        'X-Tenant-ID': 'tenant-123',
      },
    })
    expect(createObjectUrl).toHaveBeenCalledTimes(1)
  })

  it('falls back to X-User-ID headers for protected backend assets when no bearer token exists', async () => {
    auth.token = ''
    requests.authenticatedFetch.mockResolvedValue(new Response(new Blob(['asset-bytes']), { status: 200 }))
    const createObjectUrl = vi.fn(() => 'blob:asset-url')

    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = createObjectUrl

    const result = await fetchAuthAssetUrl('/api/v1/documents/321/download')

    expect(result).toBe('blob:asset-url')
    expect(requests.authenticatedFetch).toHaveBeenCalledWith('http://localhost:8000/api/v1/documents/321/download', {
      signal: expect.any(AbortSignal),
      headers: {
        'X-Tenant-ID': 'tenant-123',
        'X-User-ID': 'user-1',
      },
    })
  })

  it('does not reuse protected blobs across auth scopes', async () => {
    requests.authenticatedFetch.mockImplementation(async () => new Response(new Blob(['asset-bytes']), { status: 200 }))
    const createObjectUrl = vi.fn().mockReturnValueOnce('blob:user-1').mockReturnValueOnce('blob:user-2')

    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = createObjectUrl

    expect(await fetchAuthAssetUrl('/api/v1/documents/456/download')).toBe('blob:user-1')
    auth.scope = 'tenant-123:user-2'
    expect(await fetchAuthAssetUrl('/api/v1/documents/456/download')).toBe('blob:user-2')
    expect(requests.authenticatedFetch).toHaveBeenCalledTimes(2)
  })

  it('deduplicates concurrent protected backend asset fetches within the same auth scope', async () => {
    const body = streamingResponse()
    requests.authenticatedFetch.mockResolvedValue(body.response)
    const createObjectUrl = vi.fn(() => 'blob:shared')

    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = createObjectUrl

    const first = fetchAuthAssetUrl('/api/v1/documents/654/download')
    const second = fetchAuthAssetUrl('/api/v1/documents/654/download')
    body.finish('asset-bytes')

    await expect(Promise.all([first, second])).resolves.toEqual(['blob:shared', 'blob:shared'])
    expect(requests.authenticatedFetch).toHaveBeenCalledTimes(1)
    expect(createObjectUrl).toHaveBeenCalledTimes(1)
  })

  it('discards a protected blob that finishes after the auth scope changes', async () => {
    const body = streamingResponse()
    requests.authenticatedFetch.mockResolvedValue(body.response)
    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = vi.fn(() => 'blob:stale')
    const revokeObjectUrl = vi.spyOn(URL, 'revokeObjectURL')

    const pending = fetchAuthAssetUrl('/api/v1/documents/789/download')
    auth.scope = 'tenant-123:user-2'
    body.finish('stale-user-data')

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    expect(revokeObjectUrl).not.toHaveBeenCalledWith('blob:stale')
  })

  it('does not cache a remote proxy response after the auth scope changes', async () => {
    let resolveResponse!: (response: Response) => void
    const response = new Promise<Response>((resolve) => {
      resolveResponse = resolve
    })
    requests.authenticatedFetch.mockReturnValueOnce(response).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ src: '/api/markdown-image?token=fresh' }),
    })

    const pending = fetchAuthAssetUrl('https://example.com/private.png')
    auth.scope = 'tenant-123:user-2'
    resolveResponse(new Response(JSON.stringify({ src: '/api/markdown-image?token=stale' }), { status: 200 }))
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })

    auth.scope = 'tenant-123:user-1'
    auth.revision += 1
    await expect(fetchAuthAssetUrl('https://example.com/private.png')).resolves.toBe('/api/markdown-image?token=fresh')
    expect(requests.authenticatedFetch).toHaveBeenCalledTimes(2)
  })

  it('deduplicates concurrent remote proxy token minting within the same auth scope', async () => {
    requests.authenticatedFetch.mockResolvedValue(
      new Response(JSON.stringify({ src: '/api/markdown-image?token=shared' }), { status: 200 }),
    )

    await expect(
      Promise.all([
        fetchAuthAssetUrl('https://example.com/private-concurrent.png'),
        fetchAuthAssetUrl('https://example.com/private-concurrent.png'),
      ]),
    ).resolves.toEqual(['/api/markdown-image?token=shared', '/api/markdown-image?token=shared'])

    expect(requests.authenticatedFetch).toHaveBeenCalledTimes(1)
  })

  it('discards a remote proxy token that finishes after the auth scope changes', async () => {
    let resolvePayload!: (payload: { src: string }) => void
    const payload = new Promise<{ src: string }>((resolve) => {
      resolvePayload = resolve
    })
    requests.authenticatedFetch.mockResolvedValue({
      ok: true,
      json: () => payload,
    })

    const pending = fetchAuthAssetUrl('https://example.com/private-scope-change.png')
    auth.scope = 'tenant-456:user-2'
    resolvePayload({ src: '/api/markdown-image?token=stale' })

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('uses X-User-ID headers when minting remote proxy tokens without a bearer token', async () => {
    auth.token = ''
    requests.authenticatedFetch.mockResolvedValue(
      new Response(JSON.stringify({ src: '/api/markdown-image?token=header-mode' }), { status: 200 }),
    )

    await expect(fetchAuthAssetUrl('https://example.com/private-header-mode.png')).resolves.toBe(
      '/api/markdown-image?token=header-mode',
    )

    expect(requests.authenticatedFetch).toHaveBeenCalledWith('/api/markdown-image', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': 'tenant-123',
        'X-User-ID': 'user-1',
      },
      body: JSON.stringify({ src: 'https://example.com/private-header-mode.png' }),
      signal: expect.any(AbortSignal),
    })
  })

  it('mints a usable remote URL again after the previous opaque token has actually expired', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-15T00:00:00Z'))
    vi.stubEnv('MARKDOWN_IMAGE_PROXY_SECRET', 'asset-review-test-secret')
    const source = 'https://example.com/temporary.png'
    requests.authenticatedFetch.mockImplementation(async () => {
      const token = mintMarkdownImageProxyToken(source)
      if (token === null) throw new Error('Token fixture is not configured')
      return new Response(JSON.stringify({ src: '/api/markdown-image?token=' + token }), { status: 200 })
    })
    try {
      const first = await fetchAuthAssetUrl(source)
      const oldToken = new URL(first, 'https://frontend.example').searchParams.get('token')
      expect(resolveMarkdownImageProxyToken(oldToken)).toBe(source)
      vi.setSystemTime(new Date('2026-11-15T01:00:01Z'))
      expect(resolveMarkdownImageProxyToken(oldToken)).toBeNull()

      const fresh = await fetchAuthAssetUrl(source)
      const freshToken = new URL(fresh, 'https://frontend.example').searchParams.get('token')

      expect(resolveMarkdownImageProxyToken(freshToken)).toBe(source)
      expect(requests.authenticatedFetch).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it.each(['development', 'production'])(
    'exposes a real mint failure in %s without producing a plaintext source URL',
    async (mode) => {
      vi.stubEnv('NODE_ENV', mode)
      requests.authenticatedFetch.mockResolvedValue(new Response('unavailable', { status: 503 }))

      await expect(fetchAuthAssetUrl('https://example.com/private.png?signature=private')).rejects.toThrow('503')
      expect(requests.authenticatedFetch.mock.calls[0][0]).toBe('/api/markdown-image')
    },
  )

  it('does not expose a remote source URL when opaque token minting fails in production', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    requests.authenticatedFetch.mockResolvedValue(new Response('', { status: 500 }))

    await expect(fetchAuthAssetUrl('https://example.com/signed.png?token=secret')).rejects.toThrow('500')
  })
})
