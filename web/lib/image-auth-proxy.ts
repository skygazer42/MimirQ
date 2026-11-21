'use client'

import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'
import { AUTH_SCOPE_CHANGED_EVENT, AUTH_SESSION_CHANGED_EVENT, getAuthSessionKey } from '@/lib/auth-storage'
import { getAuthHeaders } from '@/lib/auth-headers'
import { authenticatedFetch } from '@/lib/authenticated-fetch'

const DOCUMENT_DOWNLOAD_PATH_RE = /^\/api\/v1\/documents\/[^/]+\/download\/?$/

type AuthAssetCache = Readonly<{
  scope: string
  controller: AbortController
  blobUrls: Map<string, string>
  allocatedUrls: Set<string>
  pending: Map<string, Promise<string>>
}>

let assetCache: AuthAssetCache | null = null

function releaseAssetCache() {
  const cache = assetCache
  assetCache = null
  if (cache === null) return
  cache.controller.abort()
  for (const url of cache.allocatedUrls) URL.revokeObjectURL(url)
  cache.allocatedUrls.clear()
  cache.blobUrls.clear()
  cache.pending.clear()
}

function invalidateAssetCache() {
  if (assetCache?.scope === getAuthSessionKey()) return
  releaseAssetCache()
}

globalThis.window?.addEventListener(AUTH_SCOPE_CHANGED_EVENT, invalidateAssetCache)
globalThis.window?.addEventListener(AUTH_SESSION_CHANGED_EVENT, invalidateAssetCache)

/** Stop reuse; issued URLs remain available to their consumers until the scope ends. */
export function invalidateAuthAssetUrl(url: string, scope: string): void {
  const cache = assetCache
  if (cache === null || cache.scope !== scope || scope !== getAuthSessionKey()) return
  for (const [key, cachedUrl] of cache.blobUrls) {
    if (cachedUrl !== url) continue
    cache.blobUrls.delete(key)
    return
  }
}

function getAssetCache(): AuthAssetCache {
  const scope = getAuthSessionKey()
  if (assetCache === null || assetCache.scope !== scope) {
    releaseAssetCache()
    assetCache = {
      scope,
      controller: new AbortController(),
      blobUrls: new Map(),
      allocatedUrls: new Set(),
      pending: new Map(),
    }
  }
  return assetCache
}

function assertCurrentAssetCache(cache: AuthAssetCache) {
  cache.controller.signal.throwIfAborted()
  if (assetCache !== cache || cache.scope !== getAuthSessionKey()) {
    throw new DOMException('资源读取已失效', 'AbortError')
  }
}

export function normalizeAssetUrl(rawUrl: string | null | undefined): string | null {
  if (rawUrl === null || rawUrl === undefined) return null
  const source = rawUrl.trim()
  if (source.length === 0) return null
  if (/^(https?:\/\/|data:|blob:)/i.test(source)) return source
  return toAbsoluteBackendUrl(source)
}

function isProtectedBackendAsset(url: URL, backend: URL): boolean {
  const basePath = backend.pathname.replace(/\/+$/, '')
  if (!url.pathname.startsWith(basePath + '/')) return false
  const path = url.pathname.slice(basePath.length)
  return (
    path.startsWith('/api/v1/documents/image/') ||
    path.startsWith('/api/v1/documents/image-url/') ||
    DOCUMENT_DOWNLOAD_PATH_RE.test(path)
  )
}

async function loadAssetUrl(source: string, url: URL, backend: URL, cache: AuthAssetCache): Promise<string> {
  const signal = cache.controller.signal
  if (url.origin !== backend.origin) {
    const response = await authenticatedFetch('/api/markdown-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ src: source }),
      signal,
    })
    if (!response.ok) throw new Error(`图片代理请求失败（HTTP ${response.status}）`)
    const payload: unknown = await response.json()
    assertCurrentAssetCache(cache)
    if (
      typeof payload !== 'object' ||
      payload === null ||
      !('src' in payload) ||
      typeof payload.src !== 'string' ||
      payload.src.trim().length === 0
    ) {
      throw new Error('图片代理未返回有效地址')
    }
    return payload.src.trim()
  }

  const response = await authenticatedFetch(source, { headers: getAuthHeaders(), signal })
  if (!response.ok) throw new Error(`资源读取失败（HTTP ${response.status}）`)
  const blob = await response.blob()
  assertCurrentAssetCache(cache)
  const blobUrl = URL.createObjectURL(blob)
  cache.allocatedUrls.add(blobUrl)
  cache.blobUrls.set(url.href, blobUrl)
  return blobUrl
}

export async function fetchAuthAssetUrl(rawUrl: string): Promise<string> {
  const source = normalizeAssetUrl(rawUrl)
  if (source === null) throw new Error('资源地址为空')
  const backend = new URL(API_BASE_URL.length === 0 ? globalThis.window.location.origin : API_BASE_URL)
  const url = new URL(source, backend)
  if (url.protocol === 'data:' || url.protocol === 'blob:') return source
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('资源地址不支持此协议')
  if (url.origin === backend.origin && !isProtectedBackendAsset(url, backend)) return source

  const cache = getAssetCache()
  const cached = cache.blobUrls.get(url.href)
  if (cached !== undefined) return cached
  const existing = cache.pending.get(url.href)
  if (existing !== undefined) return existing

  const pending = loadAssetUrl(source, url, backend, cache)
  cache.pending.set(url.href, pending)
  try {
    return await pending
  } finally {
    if (cache.pending.get(url.href) === pending) cache.pending.delete(url.href)
  }
}
