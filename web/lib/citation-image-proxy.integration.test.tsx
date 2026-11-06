// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ fetch: vi.fn(), createObjectURL: vi.fn(), revokeObjectURL: vi.fn() }))
vi.mock('next/image', () => ({
  default: ({ src, alt }: { src: string; alt: string }) => React.createElement('img', { src, alt }),
}))

const cleanup: Array<() => void> = []
const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL

async function load(mode: 'development' | 'production', base = 'http://localhost:8000') {
  vi.stubEnv('NODE_ENV', mode)
  vi.stubEnv('NEXT_PUBLIC_API_URL', base)
  vi.stubEnv('API_INTERNAL_URL', '')
  vi.stubEnv('NEXT_PUBLIC_TENANT_ID', 'image-test-tenant')
  vi.resetModules()
  const auth = await import('@/lib/auth-storage')
  auth.setAuthSession({
    token: { access_token: 'image-review-token', token_type: 'bearer', expires_in: 3600 },
    user: {
      id: 'image-review-user',
      username: 'image-review-user',
      email: 'image@example.com',
      is_active: true,
      created_at: '2026-11-05T00:00:00Z',
    },
  })
  const env = await import('@/lib/env')
  const citation = await import('@/lib/citation-images')
  const assets = await import('@/lib/image-auth-proxy')
  const { AuthImage } = await import('@/components/auth-image')
  return { ...env, ...citation, ...assets, AuthImage }
}

async function mountImage(AuthImage: Awaited<ReturnType<typeof load>>['AuthImage'], src: string | null) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  cleanup.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  await act(async () => root.render(<AuthImage src={src} alt="citation" width={100} height={100} unoptimized />))
  return container
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  vi.stubGlobal('BroadcastChannel', undefined)
  vi.stubGlobal('fetch', transport.fetch)
  localStorage.clear()
  sessionStorage.clear()
  transport.createObjectURL.mockReturnValue('blob:authenticated-image')
  URL.createObjectURL = transport.createObjectURL
  URL.revokeObjectURL = transport.revokeObjectURL
  transport.fetch.mockImplementation(async () => new Response(new Blob(['protected image bytes']), { status: 200 }))
})

afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  URL.createObjectURL = originalCreateObjectURL
  URL.revokeObjectURL = originalRevokeObjectURL
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('citation image authenticated consumer', () => {
  it.each([
    ['development', 'http://localhost:8000'],
    ['production', 'https://api.example.com'],
    ['production', 'https://api.example.com/gateway'],
  ] as const)(
    'renders %s / %s citations only after the actual authenticated transport returns a blob',
    async (mode, base) => {
      const { API_BASE_URL, resolveSafeCitationImageUrl, needsAuthAssetProxy, AuthImage } = await load(mode, base)
      const src = resolveSafeCitationImageUrl('/api/v1/documents/image/image-a')
      if (mode === 'development') {
        expect(API_BASE_URL).toBe('')
        expect(src).toBe(`${window.location.origin}/api/v1/documents/image/image-a`)
      }
      expect.soft(needsAuthAssetProxy(src)).toBe(true)
      const container = await mountImage(AuthImage, src)

      expect.soft(transport.fetch).toHaveBeenCalledWith(src, {
        headers: { Authorization: 'Bearer image-review-token', 'X-Tenant-ID': 'image-test-tenant' },
      })
      expect(container.querySelector('img')?.getAttribute('src')).toBe('blob:authenticated-image')
      expect(transport.createObjectURL).toHaveBeenCalledOnce()
    },
  )

  it('does not emit a raw protected img when the real transport refuses the development asset', async () => {
    transport.fetch.mockResolvedValue(new Response('', { status: 403 }))
    const { resolveSafeCitationImageUrl, AuthImage } = await load('development')
    const src = resolveSafeCitationImageUrl('/api/v1/documents/image/image-a')
    const container = await mountImage(AuthImage, src)

    expect(transport.fetch).toHaveBeenCalledOnce()
    expect(container.querySelector('img')).toBeNull()
    expect(transport.createObjectURL).not.toHaveBeenCalled()
  })

  it.each([
    '/api/v1/documents/image/image-a',
    'api/v1/documents/image-url/image-a',
    '/api/v1/documents/document-a/download',
  ])('authenticates the internal relative asset %s in browser development', async (src) => {
    const { fetchAuthAssetUrl, needsAuthAssetProxy } = await load('development')

    expect(needsAuthAssetProxy(src)).toBe(true)
    expect(await fetchAuthAssetUrl(src)).toBe('blob:authenticated-image')
    expect(transport.fetch).toHaveBeenCalledWith(src.startsWith('/') ? src : `/${src}`, {
      headers: { Authorization: 'Bearer image-review-token', 'X-Tenant-ID': 'image-test-tenant' },
    })
  })

  it('keeps external credentials on the frontend opaque-proxy request', async () => {
    transport.fetch.mockResolvedValue(
      new Response(JSON.stringify({ src: '/api/markdown-image?token=opaque' }), { status: 200 }),
    )
    const { fetchAuthAssetUrl, needsAuthAssetProxy } = await load('development')
    const external = 'https://external.example/api/v1/documents/image/image-a?signature=private'

    expect(needsAuthAssetProxy(external)).toBe(true)
    expect(await fetchAuthAssetUrl(external)).toBe('/api/markdown-image?token=opaque')
    expect(transport.fetch).toHaveBeenCalledExactlyOnceWith('/api/markdown-image', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer image-review-token',
        'X-Tenant-ID': 'image-test-tenant',
      },
      body: JSON.stringify({ src: external }),
    })
  })

  it('rejects external citation images before AuthImage can request them', async () => {
    const { resolveSafeCitationImageUrl, AuthImage } = await load('development')
    const container = await mountImage(
      AuthImage,
      resolveSafeCitationImageUrl('https://external.example/api/v1/documents/image/image-a'),
    )

    expect(transport.fetch).not.toHaveBeenCalled()
    expect(container.querySelector('img')).toBeNull()
  })

  it.each(['/public.png?next=/api/v1/documents/image/image-a', '/api/v1/documents/document-a/download/extra'])(
    'keeps unrelated path-only assets outside auth fetching: %s',
    async (src) => {
      const { fetchAuthAssetUrl, needsAuthAssetProxy } = await load('development')

      expect(needsAuthAssetProxy(src)).toBe(false)
      expect(await fetchAuthAssetUrl(src)).toBe(src)
      expect(transport.fetch).not.toHaveBeenCalled()
    },
  )

  it('keeps server and browser initial protected-image markup deterministic without inventing a server origin', async () => {
    const browserWindow = window
    vi.stubGlobal('window', undefined)
    const server = await load('development')
    expect(server.API_BASE_URL).toBe('http://localhost:8000')
    const serverMarkup = renderToStaticMarkup(
      <server.AuthImage src="/api/v1/documents/image/image-a" alt="citation" width={100} height={100} />,
    )
    vi.stubGlobal('window', browserWindow)
    const browser = await load('development')
    expect(browser.API_BASE_URL).toBe('')
    const browserMarkup = renderToStaticMarkup(
      <browser.AuthImage src="/api/v1/documents/image/image-a" alt="citation" width={100} height={100} />,
    )

    expect(serverMarkup).toBe('')
    expect(browserMarkup).toBe(serverMarkup)
    expect(transport.fetch).not.toHaveBeenCalled()
  })
})
