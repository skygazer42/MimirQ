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

export type ApiErrorInfo = {
  message: string
  requestId?: string
  status?: number
}

function extractHeaderRequestId(headers: any): string | undefined {
  if (!headers) return undefined
  const raw =
    headers['x-request-id'] ??
    headers['X-Request-ID'] ??
    headers['x-request-id'.toLowerCase()] ??
    headers['X-Request-ID'.toLowerCase()]
  if (raw == null) return undefined
  return asNonEmptyString(String(raw))
}

function extractConfigRequestId(headers: any): string | undefined {
  if (!headers) return undefined
  try {
    if (typeof headers.get === 'function') {
      return asNonEmptyString(headers.get('X-Request-ID') || headers.get('x-request-id'))
    }
  } catch {
    // ignore
  }
  const raw = headers['X-Request-ID'] ?? headers['x-request-id']
  return raw == null ? undefined : asNonEmptyString(String(raw))
}

export function extractAxiosRequestId(err: unknown): string | undefined {
  const maybeError = err as any

  // If upstream already attached a request id, trust it first.
  const direct = asNonEmptyString(maybeError?.requestId) || asNonEmptyString(maybeError?.request_id)
  if (direct) return direct

  const axiosResponse = maybeError?.response
  const data = axiosResponse?.data
  const fromBody = extractBackendRequestId(data)
  if (fromBody) return fromBody

  const fromHeader = extractHeaderRequestId(axiosResponse?.headers)
  if (fromHeader) return fromHeader

  const fromConfig = extractConfigRequestId(maybeError?.config?.headers)
  if (fromConfig) return fromConfig

  return undefined
}

export function withRequestId(message: string, requestId?: string): string {
  const label = formatRequestId(requestId)
  if (!label) return message
  if (/\brequest_id=/.test(message)) return message
  return `${message} (${label})`
}

export function formatRequestId(requestId?: string): string | undefined {
  const rid = (requestId || '').trim()
  return rid ? `request_id=${rid}` : undefined
}

export function formatApiError(err: unknown, fallbackMessage: string): string {
  const info = toApiErrorInfo(err, fallbackMessage)
  return withRequestId(info.message, info.requestId)
}

export function toApiErrorInfo(err: unknown, fallbackMessage: string): ApiErrorInfo {
  if (isNonEmptyString(err)) return { message: err.trim() }

  const maybeError = err as any
  const axiosResponse = maybeError?.response
  const status = typeof axiosResponse?.status === 'number' ? axiosResponse.status : undefined
  const data = axiosResponse?.data

  const message = extractBackendMessage(data) || (maybeError?.message && String(maybeError.message)) || fallbackMessage
  const requestId = extractAxiosRequestId(err)

  return { message, requestId, status }
}
