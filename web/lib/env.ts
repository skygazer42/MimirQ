function resolveApiBaseUrl(): string {
  const publicUrl = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim()
  const internalUrl = (process.env.API_INTERNAL_URL || '').trim()

  // In Docker, the browser should call the host-mapped backend (usually http://localhost:8000),
  // but the Next.js server (SSR) must call the backend via container-to-container DNS.
  const chosen = typeof window === 'undefined' && internalUrl ? internalUrl : publicUrl
  return chosen.replace(/\/+$/, '')
}

export const API_BASE_URL = resolveApiBaseUrl()

export const API_V1_BASE_URL = `${API_BASE_URL}/api/v1`

const rawTimeout = (process.env.NEXT_PUBLIC_API_TIMEOUT_MS || '').trim()
const parsedTimeout = rawTimeout ? Number(rawTimeout) : NaN
export const API_TIMEOUT_MS = Number.isFinite(parsedTimeout) ? parsedTimeout : 60_000

// Some endpoints (document parsing / chunk preview) can take much longer than chat/CRUD calls.
const rawLongTimeout = (process.env.NEXT_PUBLIC_API_LONG_TIMEOUT_MS || '').trim()
const parsedLongTimeout = rawLongTimeout ? Number(rawLongTimeout) : NaN
export const API_LONG_TIMEOUT_MS = Number.isFinite(parsedLongTimeout) ? parsedLongTimeout : 10 * 60_000

export function toAbsoluteBackendUrl(path: string): string {
  if (!path) return API_BASE_URL
  if (/^https?:\/\//i.test(path)) return path
  return path.startsWith('/') ? `${API_BASE_URL}${path}` : `${API_BASE_URL}/${path}`
}
