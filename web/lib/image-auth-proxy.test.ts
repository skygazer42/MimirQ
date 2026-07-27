import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({
  scope: 'tenant-123:user-1',
  token: 'jwt-token',
  tenantId: 'tenant-123',
  userId: 'user-1',
}))
const requests = vi.hoisted(() => ({
  authenticatedFetch: vi.fn(),
}))

vi.mock('@/lib/auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  getAccessToken: () => auth.token,
  getAuthCacheScope: () => auth.scope,
  getStoredUserId: () => auth.userId,
  getTenantId: () => auth.tenantId,
}))
vi.mock('@/lib/authenticated-fetch', () => ({
  authenticatedFetch: requests.authenticatedFetch,
}))

import { fetchAuthAssetUrl } from './image-auth-proxy'

describe('fetchAuthAssetUrl', () => {
  const originalCreateObjectUrl = (URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL

  beforeEach(() => {
    vi.restoreAllMocks()
    auth.scope = 'tenant-123:user-1'
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
    requests.authenticatedFetch.mockResolvedValue(
      new Response(new Blob(['asset-bytes']), { status: 200 })
    )
    const createObjectUrl = vi.fn(() => 'blob:asset-url')

    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = createObjectUrl

    const result = await fetchAuthAssetUrl('/api/v1/documents/123/download')

    expect(result).toBe('blob:asset-url')
    expect(requests.authenticatedFetch).toHaveBeenCalledWith('http://localhost:8000/api/v1/documents/123/download', {
      headers: {
        Authorization: 'Bearer jwt-token',
        'X-Tenant-ID': 'tenant-123',
      },
    })
    expect(createObjectUrl).toHaveBeenCalledTimes(1)
  })

  it('falls back to X-User-ID headers for protected backend assets when no bearer token exists', async () => {
    auth.token = ''
    requests.authenticatedFetch.mockResolvedValue(
      new Response(new Blob(['asset-bytes']), { status: 200 })
    )
    const createObjectUrl = vi.fn(() => 'blob:asset-url')

    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = createObjectUrl

    const result = await fetchAuthAssetUrl('/api/v1/documents/321/download')

    expect(result).toBe('blob:asset-url')
    expect(requests.authenticatedFetch).toHaveBeenCalledWith('http://localhost:8000/api/v1/documents/321/download', {
      headers: {
        'X-Tenant-ID': 'tenant-123',
        'X-User-ID': 'user-1',
      },
    })
  })

  it('does not reuse protected blobs across auth scopes', async () => {
    requests.authenticatedFetch.mockImplementation(
      async () => new Response(new Blob(['asset-bytes']), { status: 200 })
    )
    const createObjectUrl = vi.fn()
      .mockReturnValueOnce('blob:user-1')
      .mockReturnValueOnce('blob:user-2')

    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = createObjectUrl

    expect(await fetchAuthAssetUrl('/api/v1/documents/456/download')).toBe('blob:user-1')
    auth.scope = 'tenant-123:user-2'
    expect(await fetchAuthAssetUrl('/api/v1/documents/456/download')).toBe('blob:user-2')
    expect(requests.authenticatedFetch).toHaveBeenCalledTimes(2)
  })

  it('deduplicates concurrent protected backend asset fetches within the same auth scope', async () => {
    let resolveBlob!: (blob: Blob) => void
    const blob = new Promise<Blob>((resolve) => {
      resolveBlob = resolve
    })
    requests.authenticatedFetch.mockResolvedValue(
      new Response(blob as unknown as BodyInit, { status: 200 })
    )
    const createObjectUrl = vi.fn(() => 'blob:shared')

    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = createObjectUrl

    const first = fetchAuthAssetUrl('/api/v1/documents/654/download')
    const second = fetchAuthAssetUrl('/api/v1/documents/654/download')
    resolveBlob(new Blob(['asset-bytes']))

    await expect(Promise.all([first, second])).resolves.toEqual(['blob:shared', 'blob:shared'])
    expect(requests.authenticatedFetch).toHaveBeenCalledTimes(1)
    expect(createObjectUrl).toHaveBeenCalledTimes(1)
  })

  it('discards a protected blob that finishes after the auth scope changes', async () => {
    let resolveBlob!: (blob: Blob) => void
    const blob = new Promise<Blob>((resolve) => {
      resolveBlob = resolve
    })
    requests.authenticatedFetch.mockResolvedValue(
      new Response(blob as unknown as BodyInit, { status: 200 })
    )
    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = vi.fn(() => 'blob:stale')
    const revokeObjectUrl = vi.spyOn(URL, 'revokeObjectURL')

    const pending = fetchAuthAssetUrl('/api/v1/documents/789/download')
    auth.scope = 'tenant-123:user-2'
    resolveBlob(new Blob(['stale-user-data']))

    await expect(pending).resolves.toBeNull()
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:stale')
  })

  it('does not cache a remote proxy response after the auth scope changes', async () => {
    let resolveResponse!: (response: Response) => void
    const response = new Promise<Response>((resolve) => {
      resolveResponse = resolve
    })
    requests.authenticatedFetch
      .mockReturnValueOnce(response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ src: '/api/markdown-image?token=fresh' }),
      })

    const pending = fetchAuthAssetUrl('https://example.com/private.png')
    auth.scope = 'tenant-123:user-2'
    resolveResponse(new Response(JSON.stringify({ src: '/api/markdown-image?token=stale' }), { status: 200 }))
    await pending

    auth.scope = 'tenant-123:user-1'
    await expect(fetchAuthAssetUrl('https://example.com/private.png'))
      .resolves.toBe('/api/markdown-image?token=fresh')
    expect(requests.authenticatedFetch).toHaveBeenCalledTimes(2)
  })

  it('deduplicates concurrent remote proxy token minting within the same auth scope', async () => {
    requests.authenticatedFetch.mockResolvedValue(
      new Response(JSON.stringify({ src: '/api/markdown-image?token=shared' }), { status: 200 })
    )

    await expect(Promise.all([
      fetchAuthAssetUrl('https://example.com/private-concurrent.png'),
      fetchAuthAssetUrl('https://example.com/private-concurrent.png'),
    ])).resolves.toEqual([
      '/api/markdown-image?token=shared',
      '/api/markdown-image?token=shared',
    ])

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

    await expect(pending).resolves.toBeNull()
  })

  it('uses X-User-ID headers when minting remote proxy tokens without a bearer token', async () => {
    auth.token = ''
    requests.authenticatedFetch.mockResolvedValue(
      new Response(JSON.stringify({ src: '/api/markdown-image?token=header-mode' }), { status: 200 })
    )

    await expect(fetchAuthAssetUrl('https://example.com/private-header-mode.png'))
      .resolves.toBe('/api/markdown-image?token=header-mode')

    expect(requests.authenticatedFetch).toHaveBeenCalledWith('/api/markdown-image', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': 'tenant-123',
        'X-User-ID': 'user-1',
      },
      body: JSON.stringify({ src: 'https://example.com/private-header-mode.png' }),
    })
  })

  it('does not expose a remote source URL when opaque token minting fails in production', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    requests.authenticatedFetch.mockResolvedValue(new Response('', { status: 500 }))

    await expect(fetchAuthAssetUrl('https://example.com/signed.png?token=secret'))
      .resolves.toBeNull()
  })
})
