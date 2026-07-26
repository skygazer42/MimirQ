'use client'

import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'
import {
  AUTH_SCOPE_CHANGED_EVENT,
  getAuthCacheScope,
} from '@/lib/auth-storage'
import { getAuthHeaders } from '@/lib/auth-headers'
import { buildMarkdownImageProxyUrl } from '@/lib/markdown-image-proxy'

const DOCUMENT_DOWNLOAD_PATH_RE = /^\/api\/v1\/documents\/[^/]+\/download\/?$/

let BACKEND_ORIGIN = ''
try {
  BACKEND_ORIGIN = new URL(API_BASE_URL).origin
} catch {
  BACKEND_ORIGIN = ''
}

const blobCache = new Map<string, string>()
const proxiedRemoteUrlCache = new Map<string, string>()
const inflightBlobFetches = new Map<string, Promise<string | null>>()
const inflightRemoteProxyFetches = new Map<string, Promise<string | null>>()

function cacheKey(url: string): string {
  return `${getAuthCacheScope()}:${url}`
}

function clearAssetCaches() {
  for (const blobUrl of blobCache.values()) URL.revokeObjectURL(blobUrl)
  blobCache.clear()
  proxiedRemoteUrlCache.clear()
  inflightBlobFetches.clear()
  inflightRemoteProxyFetches.clear()
}

globalThis.window?.addEventListener(AUTH_SCOPE_CHANGED_EVENT, clearAssetCaches)

export function normalizeAssetUrl(rawUrl: string | null | undefined): string | null {
  const raw = String(rawUrl || '').trim()
  if (!raw) return null
  if (/^https?:\/\//i.test(raw) || /^data:/i.test(raw) || /^blob:/i.test(raw)) return raw
  return toAbsoluteBackendUrl(raw)
}

export function needsAuthAssetProxy(rawUrl: string | null | undefined): boolean {
  const resolved = normalizeAssetUrl(rawUrl)
  if (!resolved || /^data:/i.test(resolved) || /^blob:/i.test(resolved)) return false

  try {
    const parsed = new URL(resolved, API_BASE_URL)
    if (BACKEND_ORIGIN && parsed.origin !== BACKEND_ORIGIN) return /^https?:$/i.test(parsed.protocol)

    const path = parsed.pathname || ''
    return (
      path.includes('/api/v1/documents/image/') ||
      path.includes('/api/v1/documents/image-url/') ||
      DOCUMENT_DOWNLOAD_PATH_RE.test(path)
    )
  } catch {
    return false
  }
}

async function mintOpaqueRemoteImageUrl(rawUrl: string): Promise<string | null> {
  const key = cacheKey(rawUrl)
  const cached = proxiedRemoteUrlCache.get(key)
  if (cached) return cached
  const inflight = inflightRemoteProxyFetches.get(key)
  if (inflight) return inflight

  const pending = (async () => {
    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      }
      Object.assign(headers, getAuthHeaders())
      const response = await fetch('/api/markdown-image', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          src: rawUrl,
        }),
      })

      if (response.ok) {
        const payload = await response.json() as { src?: unknown }
        const nextUrl = typeof payload?.src === 'string' ? payload.src.trim() : ''
        if (nextUrl) {
          if (key !== cacheKey(rawUrl)) return null
          proxiedRemoteUrlCache.set(key, nextUrl)
          return nextUrl
        }
      }
    } catch {
      // Fall through to the legacy query proxy below.
    }

    if (process.env.NODE_ENV === 'production') return null

    const fallbackUrl = buildMarkdownImageProxyUrl(rawUrl)
    if (key !== cacheKey(rawUrl)) return null
    proxiedRemoteUrlCache.set(key, fallbackUrl)
    return fallbackUrl
  })()

  inflightRemoteProxyFetches.set(key, pending)
  try {
    return await pending
  } finally {
    if (inflightRemoteProxyFetches.get(key) === pending) {
      inflightRemoteProxyFetches.delete(key)
    }
  }
}

export async function fetchAuthAssetUrl(rawUrl: string | null | undefined): Promise<string | null> {
  const resolved = normalizeAssetUrl(rawUrl)
  if (!resolved) return null
  if (!needsAuthAssetProxy(resolved)) return resolved

  try {
    const parsed = new URL(resolved, API_BASE_URL)
    if (BACKEND_ORIGIN && parsed.origin !== BACKEND_ORIGIN) {
      return await mintOpaqueRemoteImageUrl(resolved)
    }
  } catch {
    return null
  }

  const key = cacheKey(resolved)
  const cached = blobCache.get(key)
  if (cached) return cached
  const inflight = inflightBlobFetches.get(key)
  if (inflight) return inflight

  const pending = (async () => {
    const response = await fetch(resolved, { headers: getAuthHeaders() })
    if (!response.ok) return null

    const blobUrl = URL.createObjectURL(await response.blob())
    if (key !== cacheKey(resolved)) {
      URL.revokeObjectURL(blobUrl)
      return null
    }
    blobCache.set(key, blobUrl)
    return blobUrl
  })()

  inflightBlobFetches.set(key, pending)
  try {
    return await pending
  } finally {
    if (inflightBlobFetches.get(key) === pending) {
      inflightBlobFetches.delete(key)
    }
  }
}
