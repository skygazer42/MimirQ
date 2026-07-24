import { extractBackendMessage, extractBackendRequestId, withRequestId } from '@/lib/api-errors'

export async function buildFetchError(response: Response, fallbackMessage: string): Promise<Error> {
  let requestId = response.headers.get('X-Request-ID') || undefined
  let message = `${fallbackMessage} (HTTP ${response.status})`

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
