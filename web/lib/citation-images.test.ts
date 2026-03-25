import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resolveSafeCitationImageUrl } from './citation-images'

function createLocalStorageMock() {
  const store = new Map<string, string>()
  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, String(value))
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key)
    }),
    clear: vi.fn(() => {
      store.clear()
    }),
  }
}

describe('resolveSafeCitationImageUrl', () => {
  beforeEach(() => {
    const localStorage = createLocalStorageMock()
    vi.stubGlobal('window', { localStorage })
    localStorage.setItem('mimirq_access_token', 'secret-token')
    localStorage.setItem('mimirq_tenant_id', 'tenant-1')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps backend image URLs free of auth query parameters', () => {
    const url = resolveSafeCitationImageUrl('/api/v1/documents/image/doc-1')

    expect(url).toContain('/api/v1/documents/image/doc-1')
    expect(url).not.toContain('token=')
    expect(url).not.toContain('access_token=')
    expect(url).not.toContain('tenant_id=')
  })

  it('rejects non-backend origins', () => {
    expect(resolveSafeCitationImageUrl('https://example.com/track.png')).toBeNull()
  })
})
