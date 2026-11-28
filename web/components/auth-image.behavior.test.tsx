// @vitest-environment happy-dom

import React, { act, useLayoutEffect } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ scope: 'asset-scope-a', revision: 0 }))
const transport = vi.hoisted(() => ({
  fetch: vi.fn(),
  createObjectURL: vi.fn(),
  revokeObjectURL: vi.fn(),
}))
vi.mock('next/image', () => ({
  default: ({
    src,
    alt,
    onError,
  }: {
    src: string
    alt: string
    onError?: React.ReactEventHandler<HTMLImageElement>
  }) => <img src={src} alt={alt} onError={onError} />,
}))
vi.mock('@/lib/env', () => ({
  API_BASE_URL: 'http://localhost:8000',
  toAbsoluteBackendUrl: (path: string) => new URL(path, 'http://localhost:8000').href,
}))
vi.mock('@/lib/auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  AUTH_SESSION_CHANGED_EVENT: 'mimirq:auth-session-changed',
  getAuthSessionKey: () => JSON.stringify([auth.scope, auth.revision]),
  subscribeAuthSession: (listener: () => void) => {
    window.addEventListener('mimirq:auth-scope-changed', listener)
    window.addEventListener('mimirq:auth-session-changed', listener)
    return () => {
      window.removeEventListener('mimirq:auth-scope-changed', listener)
      window.removeEventListener('mimirq:auth-session-changed', listener)
    }
  },
}))
vi.mock('@/lib/auth-headers', () => ({ getAuthHeaders: () => ({ Authorization: 'Bearer asset-test-token' }) }))
vi.mock('@/lib/authenticated-fetch', () => ({ authenticatedFetch: transport.fetch }))

import { AuthImage, AuthImageLink } from './auth-image'
import { fetchAuthAssetUrl } from '@/lib/image-auth-proxy'

const roots = new Set<Root>()
const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function mount(src: string, linked = false) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.add(root)
  const committedSources: Array<string | null> = []
  function CommitProbe() {
    useLayoutEffect(() => {
      committedSources.push(
        container.querySelector(linked ? 'a' : 'img')?.getAttribute(linked ? 'href' : 'src') ?? null,
      )
    })
    return null
  }
  async function render(nextSource: string) {
    await act(async () =>
      root.render(
        <>
          {linked ? (
            <AuthImageLink src={nextSource} alt="引用图片" title="查看引用图片" />
          ) : (
            <AuthImage src={nextSource} alt="引用图片" width={100} height={100} unoptimized />
          )}
          <CommitProbe />
        </>,
      ),
    )
  }
  return { container, render, committedSources, initialSource: src }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  auth.scope = 'asset-scope-a'
  auth.revision += 1
  window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
  vi.clearAllMocks()
  transport.fetch.mockReset()
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: transport.createObjectURL })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: transport.revokeObjectURL })
  transport.createObjectURL.mockReturnValue('blob:source-a')
  transport.fetch.mockImplementation(async () => new Response(new Blob(['source-a']), { status: 200 }))
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots.clear()
  document.body.replaceChildren()
  if (originalCreateObjectURL === undefined) Reflect.deleteProperty(URL, 'createObjectURL')
  else Object.defineProperty(URL, 'createObjectURL', originalCreateObjectURL)
  if (originalRevokeObjectURL === undefined) Reflect.deleteProperty(URL, 'revokeObjectURL')
  else Object.defineProperty(URL, 'revokeObjectURL', originalRevokeObjectURL)
})

describe('actual authenticated asset ownership', () => {
  it.each([false, true])('hides the previous asset in the first new-source commit, linked=%s', async (linked) => {
    const view = mount('/api/v1/documents/image/source-a', linked)
    await view.render(view.initialSource)
    expect(view.container.querySelector(linked ? 'a' : 'img')?.getAttribute(linked ? 'href' : 'src')).toBe(
      'blob:source-a',
    )
    view.committedSources.length = 0
    const response = deferred<Response>()
    transport.fetch.mockReturnValueOnce(response.promise)

    try {
      await view.render('/api/v1/documents/image/source-b')

      expect(view.committedSources[0]).toBeNull()
    } finally {
      await act(async () => response.resolve(new Response(new Blob(['source-b']), { status: 200 })))
    }
  })

  it('keeps a real asset failure visible and lets the user retry it', async () => {
    transport.fetch.mockResolvedValueOnce(new Response('not available', { status: 503 }))
    const view = mount('/api/v1/documents/image/unavailable', true)
    await view.render(view.initialSource)

    expect(view.container.textContent).toContain('503')
    const retry = view.container.querySelector<HTMLButtonElement>('button')!
    expect(retry.textContent).toContain('重试')
    await act(async () => retry.click())

    expect(view.container.querySelector('a')?.getAttribute('href')).toBe('blob:source-a')
    expect(transport.fetch).toHaveBeenCalledTimes(2)
  })

  it('does not publish a retired asset when the same auth scope is revisited', async () => {
    const response = deferred<Response>()
    transport.fetch.mockReturnValueOnce(response.promise)
    const pending = fetchAuthAssetUrl('/api/v1/documents/image/retired')
    const observed = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    auth.scope = 'asset-scope-b'
    auth.revision += 1
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    auth.scope = 'asset-scope-a'
    auth.revision += 1
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))

    response.resolve(new Response(new Blob(['old-private-bytes']), { status: 200 }))

    await observed
  })

  it('reports a native image failure after a remote URL was prepared and retries the image', async () => {
    transport.fetch.mockImplementation(
      async () => new Response(JSON.stringify({ src: '/api/markdown-image?token=opaque' }), { status: 200 }),
    )
    const view = mount('https://remote.example/image.png')
    await view.render(view.initialSource)
    const image = view.container.querySelector('img')!

    act(() => image.dispatchEvent(new Event('error')))

    expect(view.container.querySelector('[role="alert"]')?.textContent).toContain('图片')
    const retry = view.container.querySelector<HTMLButtonElement>('button')!
    await act(async () => retry.click())
    expect(transport.fetch).toHaveBeenCalledTimes(2)
    expect(view.container.querySelector('img')).not.toBeNull()
  })

  it.each(['button', 'a'] as const)('keeps recovery valid inside an existing %s action', async (tag) => {
    transport.fetch.mockResolvedValueOnce(new Response('not available', { status: 503 }))
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    roots.add(root)
    const action = vi.fn((event: React.MouseEvent) => event.preventDefault())
    await act(async () =>
      root.render(
        React.createElement(
          tag,
          { onClick: action, ...(tag === 'a' ? { href: '/source' } : { type: 'button' }) },
          <AuthImage src="/api/v1/documents/image/nested" alt="嵌入图片" width={100} height={100} unoptimized />,
        ),
      ),
    )
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('503')
    expect(container.querySelectorAll('button, a')).toHaveLength(1)
    const parent = container.querySelector<HTMLElement>(tag)!

    await act(async () => parent.click())

    expect(action).toHaveBeenCalledOnce()
    expect(transport.fetch).toHaveBeenCalledTimes(2)
    expect(container.querySelector('img')).not.toBeNull()
  })

  it('keeps another consumer URL alive during retry and releases both URLs when the scope ends', async () => {
    let sequence = 0
    transport.createObjectURL.mockImplementation(() => 'blob:shared-resource-' + ++sequence)
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    roots.add(root)
    await act(async () =>
      root.render(
        <>
          <AuthImageLink src="/api/v1/documents/image/shared" alt="第一张" />
          <AuthImageLink src="/api/v1/documents/image/shared" alt="第二张" />
        </>,
      ),
    )
    const firstImage = container.querySelector<HTMLImageElement>('img[alt="第一张"]')!
    const secondLink = container.querySelector('img[alt="第二张"]')!.closest('a')!
    const originalUrl = secondLink.getAttribute('href')

    act(() => firstImage.dispatchEvent(new Event('error')))
    await act(async () => container.querySelector<HTMLButtonElement>('button')!.click())

    expect(secondLink.getAttribute('href')).toBe(originalUrl)
    expect(transport.revokeObjectURL).not.toHaveBeenCalledWith(originalUrl)
    const retriedUrl = container.querySelector('img[alt="第一张"]')!.closest('a')!.getAttribute('href')
    expect(retriedUrl).not.toBe(originalUrl)
    expect(transport.fetch).toHaveBeenCalledTimes(2)

    await act(async () => {
      auth.scope = 'another-scope'
      auth.revision += 1
      window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    })

    expect(transport.revokeObjectURL).toHaveBeenCalledWith(originalUrl)
    expect(transport.revokeObjectURL).toHaveBeenCalledWith(retriedUrl)
  })
})
