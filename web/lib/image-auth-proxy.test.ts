import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/auth-storage', () => ({
  getAccessToken: () => 'jwt-token',
  getTenantId: () => 'tenant-123',
}))

import { fetchAuthAssetUrl } from './image-auth-proxy'

describe('fetchAuthAssetUrl', () => {
  const originalFetch = global.fetch
  const originalCreateObjectUrl = (URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    global.fetch = originalFetch
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
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi.fn().mockResolvedValue(new Blob(['asset-bytes'])),
    })
    const createObjectUrl = vi.fn(() => 'blob:asset-url')

    global.fetch = fetchMock as typeof fetch
    ;(URL as typeof URL & { createObjectURL?: typeof URL.createObjectURL }).createObjectURL = createObjectUrl

    const result = await fetchAuthAssetUrl('/api/v1/documents/123/download')

    expect(result).toBe('blob:asset-url')
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8000/api/v1/documents/123/download', {
      headers: {
        Authorization: 'Bearer jwt-token',
        'X-Tenant-ID': 'tenant-123',
      },
    })
    expect(createObjectUrl).toHaveBeenCalledTimes(1)
  })
})
