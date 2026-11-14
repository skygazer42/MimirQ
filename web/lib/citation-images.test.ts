// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

async function load(mode: 'development' | 'production', base: string) {
  vi.stubEnv('NODE_ENV', mode)
  vi.stubEnv('NEXT_PUBLIC_API_URL', base)
  vi.stubEnv('API_INTERNAL_URL', '')
  vi.resetModules()
  return import('./citation-images')
}

describe('citation image route boundary', () => {
  it('resolves backend images through the supported same-origin development API base', async () => {
    const { resolveSafeCitationImageUrl } = await load('development', 'http://localhost:8000')
    const { API_BASE_URL } = await import('./env')
    expect(API_BASE_URL).toBe('')

    expect(resolveSafeCitationImageUrl('/api/v1/documents/image/image-a')).toBe(
      `${window.location.origin}/api/v1/documents/image/image-a`,
    )
    expect(resolveSafeCitationImageUrl('api/v1/documents/image-url/image-a')).toBe(
      `${window.location.origin}/api/v1/documents/image-url/image-a`,
    )
    expect(resolveSafeCitationImageUrl('https://external.example/api/v1/documents/image/image-a')).toBeNull()
  })

  it('preserves a configured backend path and only accepts its dedicated image routes', async () => {
    const { resolveSafeCitationImageUrl } = await load('production', 'https://api.example.com/gateway')

    expect(resolveSafeCitationImageUrl('/api/v1/documents/image/image-a?version=2')).toBe(
      'https://api.example.com/gateway/api/v1/documents/image/image-a?version=2',
    )
    expect(resolveSafeCitationImageUrl('https://api.example.com/gateway/api/v1/documents/image-url/image-a')).toBe(
      'https://api.example.com/gateway/api/v1/documents/image-url/image-a',
    )
    expect(resolveSafeCitationImageUrl('https://api.example.com/other/api/v1/documents/image/image-a')).toBeNull()
    expect(resolveSafeCitationImageUrl('/uploads/api/v1/documents/image/image-a')).toBeNull()
    expect(resolveSafeCitationImageUrl('/api/v1/documents/document-a/download')).toBeNull()
    expect(resolveSafeCitationImageUrl('https://external.example/gateway/api/v1/documents/image/image-a')).toBeNull()
    expect(resolveSafeCitationImageUrl('data:image/png;base64,AA==')).toBeNull()
    expect(resolveSafeCitationImageUrl('blob:https://api.example.com/image-a')).toBeNull()
    expect(resolveSafeCitationImageUrl('javascript:alert(1)')).toBeNull()
  })
})
