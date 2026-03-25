'use client'

import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'

let BACKEND_ORIGIN = ''
try {
  BACKEND_ORIGIN = new URL(API_BASE_URL).origin
} catch {
  BACKEND_ORIGIN = ''
}

export function resolveSafeCitationImageUrl(rawUrl: string | null | undefined): string | null {
  const raw = String(rawUrl || '').trim()
  if (!raw) return null

  const resolved =
    /^https?:\/\//i.test(raw) || /^data:/i.test(raw) || /^blob:/i.test(raw)
      ? raw
      : toAbsoluteBackendUrl(raw)

  let parsed: URL
  try {
    parsed = new URL(resolved, API_BASE_URL)
  } catch {
    return null
  }

  // Safety: never render thumbnails from a non-backend origin (prevents accidental token leakage / tracking).
  if (BACKEND_ORIGIN && parsed.origin !== BACKEND_ORIGIN) return null

  // Only allow the dedicated backend image routes for citations.
  const path = parsed.pathname || ''
  const ok =
    path.includes('/api/v1/documents/image/') || path.includes('/api/v1/documents/image-url/')
  if (!ok) return null

  return parsed.toString()
}
