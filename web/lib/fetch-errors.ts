import { extractBackendMessage, extractBackendRequestId, withRequestId } from '@/lib/api-errors'
import { clearAuthSession, getAccessToken } from '@/lib/auth-storage'

export async function buildFetchError(response: Response, fallbackMessage: string): Promise<Error> {
  let requestId = response.headers.get('X-Request-ID') || undefined
  let message = `${fallbackMessage} (HTTP ${response.status})`

  // Match axios behaviour: if a stored JWT token is rejected, clear it so the UI can recover.
  if (response.status === 401) {
    const token = getAccessToken()
    if (token) {
      clearAuthSession()
      if (typeof window !== 'undefined') {
        const path = String(window.location?.pathname || '')
        if (!path.startsWith('/auth')) {
          window.location.href = '/auth'
        }
      }
    }
  }

  try {
    const raw = await response.text()
    const trimmed = (raw || '').trim()
    if (trimmed) {
      try {
        const data = JSON.parse(trimmed)
        requestId = extractBackendRequestId(data) || requestId
        message = extractBackendMessage(data) || message
      } catch {
        message = extractBackendMessage(trimmed) || message
      }
    }
  } catch {
    // ignore
  }

  return new Error(withRequestId(message, requestId))
}
