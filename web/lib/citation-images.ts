'use client'

import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'

export function resolveSafeCitationImageUrl(rawUrl: string | null | undefined): string | null {
  const raw = String(rawUrl || '').trim()
  if (!raw) return null

  let parsed: URL
  let backend: URL
  try {
    backend = new URL(API_BASE_URL || globalThis.window?.location.origin || '')
    parsed = new URL(toAbsoluteBackendUrl(raw), backend)
  } catch {
    return null
  }

  // Safety: never render thumbnails from a non-backend origin (prevents accidental token leakage / tracking).
  if (parsed.origin !== backend.origin) return null

  // Only allow the dedicated backend image routes for citations.
  const path = parsed.pathname || ''
  const documentsPath = `${backend.pathname.replace(/\/$/, '')}/api/v1/documents/`
  const ok = path.startsWith(`${documentsPath}image/`) || path.startsWith(`${documentsPath}image-url/`)
  if (!ok) return null

  return parsed.toString()
}
