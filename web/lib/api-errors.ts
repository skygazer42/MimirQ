type ErrorResponseLike = {
  error?: unknown
  message?: unknown
  detail?: unknown
  request_id?: unknown
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function asNonEmptyString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed ? trimmed : undefined
}

function safeJson(value: unknown): string | undefined {
  try {
    return JSON.stringify(value)
  } catch {
    return undefined
  }
}

export function extractBackendRequestId(data: unknown): string | undefined {
  if (!data || typeof data !== 'object') return undefined
  const maybe = (data as ErrorResponseLike).request_id
  return asNonEmptyString(maybe)
}

export function extractBackendMessage(data: unknown): string | undefined {
  if (!data) return undefined
  if (typeof data === 'string') return asNonEmptyString(data)

  if (typeof data === 'object') {
    const payload = data as ErrorResponseLike
    return (
      asNonEmptyString(payload.message) ||
      asNonEmptyString(payload.detail) ||
      // FastAPI default: {"detail":[{...},{...}]}
      (Array.isArray(payload.detail) ? 'Validation error' : undefined) ||
      (typeof payload.detail === 'object'
        ? asNonEmptyString((payload.detail as any)?.message) || safeJson(payload.detail)
        : undefined)
    )
  }

  return undefined
}

export function withRequestId(message: string, requestId?: string): string {
  const rid = (requestId || '').trim()
  if (!rid) return message
  if (/\brequest_id=/.test(message)) return message
  return `${message} (request_id=${rid})`
}

export function formatApiError(err: unknown, fallbackMessage: string): string {
  if (isNonEmptyString(err)) return err.trim()

  const maybeError = err as any
  const axiosResponse = maybeError?.response

  if (axiosResponse) {
    const data = axiosResponse.data
    const headerRequestId = axiosResponse.headers?.['x-request-id']
    const requestId = extractBackendRequestId(data) || (headerRequestId ? String(headerRequestId) : undefined)
    const msg = extractBackendMessage(data) || maybeError?.message || fallbackMessage
    return withRequestId(msg, requestId)
  }

  const message = (maybeError?.message && String(maybeError.message)) || fallbackMessage
  return message
}
