const rawApiBaseUrl = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').trim()

export const API_BASE_URL = rawApiBaseUrl.replace(/\/+$/, '')

export const API_V1_BASE_URL = `${API_BASE_URL}/api/v1`

const rawTimeout = (process.env.NEXT_PUBLIC_API_TIMEOUT_MS || '').trim()
const parsedTimeout = rawTimeout ? Number(rawTimeout) : NaN
export const API_TIMEOUT_MS = Number.isFinite(parsedTimeout) ? parsedTimeout : 60_000

export function toAbsoluteBackendUrl(path: string): string {
  if (!path) return API_BASE_URL
  if (/^https?:\/\//i.test(path)) return path
  return path.startsWith('/') ? `${API_BASE_URL}${path}` : `${API_BASE_URL}/${path}`
}
