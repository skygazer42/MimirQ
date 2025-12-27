export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const API_V1_BASE_URL = `${API_BASE_URL}/api/v1`

export function toAbsoluteBackendUrl(path: string): string {
  if (!path) return API_BASE_URL
  if (/^https?:\/\//i.test(path)) return path
  return path.startsWith('/') ? `${API_BASE_URL}${path}` : `${API_BASE_URL}/${path}`
}
