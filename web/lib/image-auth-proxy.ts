'use client'

import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'
import { getAccessToken, getTenantId } from '@/lib/auth-storage'

const DOCUMENT_DOWNLOAD_PATH_RE = /^\/api\/v1\/documents\/[^/]+\/download\/?$/

let BACKEND_ORIGIN = ''
try {
  BACKEND_ORIGIN = new URL(API_BASE_URL).origin
} catch {
  BACKEND_ORIGIN = ''
}

const blobCache = new Map<string, string>()

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
    if (BACKEND_ORIGIN && parsed.origin !== BACKEND_ORIGIN) return false

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

export async function fetchAuthAssetUrl(rawUrl: string | null | undefined): Promise<string | null> {
  const resolved = normalizeAssetUrl(rawUrl)
  if (!resolved) return null
  if (!needsAuthAssetProxy(resolved)) return resolved

  const cached = blobCache.get(resolved)
  if (cached) return cached

  const headers: Record<string, string> = {}
  const token = getAccessToken()
  const tenantId = getTenantId()

  if (token) headers.Authorization = `Bearer ${token}`
  if (tenantId) headers['X-Tenant-ID'] = tenantId

  const response = await fetch(resolved, { headers })
  if (!response.ok) return null

  const blobUrl = URL.createObjectURL(await response.blob())
  blobCache.set(resolved, blobUrl)
  return blobUrl
}
