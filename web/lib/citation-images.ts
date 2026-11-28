'use client'

import { API_BASE_URL, toAbsoluteBackendUrl } from '@/lib/env'

export function resolveSafeCitationImageUrl(rawUrl: string | null | undefined): string | null {
  if (typeof rawUrl !== 'string') return null
  const imageUrl = rawUrl.trim()
  if (imageUrl === '') return null

  const backendBaseUrl = API_BASE_URL === '' ? globalThis.window?.location.origin : API_BASE_URL
  if (backendBaseUrl === undefined) return null

  let parsed: URL
  let backend: URL
  try {
    backend = new URL(backendBaseUrl)
    parsed = new URL(toAbsoluteBackendUrl(imageUrl), backend)
  } catch {
    return null
  }

  // Safety: never render thumbnails from a non-backend origin (prevents accidental token leakage / tracking).
  if (parsed.origin !== backend.origin) return null

  // Only allow the dedicated backend image routes for citations.
  const documentsPath = `${backend.pathname.replace(/\/$/, '')}/api/v1/documents/`
  const isCitationImageRoute =
    parsed.pathname.startsWith(`${documentsPath}image/`) || parsed.pathname.startsWith(`${documentsPath}image-url/`)
  if (!isCitationImageRoute) return null

  return parsed.toString()
}
