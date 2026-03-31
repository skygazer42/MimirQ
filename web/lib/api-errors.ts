type ErrorResponseLike = {
  error?: unknown
  message?: unknown
  detail?: unknown
  request_id?: unknown
}

type RateLimitDetailLike = {
  retry_after_sec?: unknown
  limit?: unknown
  scope?: unknown
}

function looksLikeHtmlDocument(value: string): boolean {
  const trimmed = (value || '').trimStart().slice(0, 200).toLowerCase()
  return trimmed.startsWith('<!doctype html') || trimmed.startsWith('<html')
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function asNonEmptyString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed || undefined
}

function safeJson(value: unknown): string | undefined {
  try {
    return JSON.stringify(value)
  } catch {
    return undefined
  }
}

function asFiniteNumber(value: unknown): number | undefined {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  if (!trimmed) return undefined
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : undefined
}

export function extractRateLimitDetail(data: unknown): { retryAfterSec?: number; limit?: number; scope?: string } | undefined {
  if (!data || typeof data !== 'object') return undefined
  const detail = (data as ErrorResponseLike).detail
  if (!detail || typeof detail !== 'object') return undefined
  const maybe = detail as RateLimitDetailLike

  const retryAfterSec = asFiniteNumber(maybe.retry_after_sec)
  const limit = asFiniteNumber(maybe.limit)
  const scope = asNonEmptyString(maybe.scope)

  if (retryAfterSec == null && limit == null && !scope) return undefined
  return {
    retryAfterSec: retryAfterSec == null ? undefined : Math.max(0, Math.round(retryAfterSec)),
    limit,
    scope,
  }
}

export function extractBackendRequestId(data: unknown): string | undefined {
  if (!data || typeof data !== 'object') return undefined
  const maybe = (data as ErrorResponseLike).request_id
  return asNonEmptyString(maybe)
}

export function extractBackendMessage(data: unknown): string | undefined {
  if (!data) return undefined
  if (typeof data === 'string') {
    if (looksLikeHtmlDocument(data)) {
      return 'Backend returned HTML (可能 API 地址配错了；请检查 NEXT_PUBLIC_API_URL / 反向代理配置)'
    }
    return asNonEmptyString(data)
  }

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

function extractHeaderRetryAfterSec(headers: any): number | undefined {
  if (!headers) return undefined
  const raw =
    headers['retry-after'] ??
    headers['Retry-After'] ??
    headers['retry-after'.toLowerCase()] ??
    headers['Retry-After'.toLowerCase()]
  if (raw == null) return undefined
  const parsed = asFiniteNumber(raw)
  if (parsed == null) return undefined
  return Math.max(0, Math.round(parsed))
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

const REQUEST_ID_IN_TEXT_PATTERN = /\brequest_id=([A-Za-z0-9._:-]+)\b/

export function extractRequestIdFromError(err: unknown): string | undefined {
  const direct = extractAxiosRequestId(err)
  if (direct) return direct

  if (isNonEmptyString(err)) {
    return REQUEST_ID_IN_TEXT_PATTERN.exec(err.trim())?.[1]
  }

  const maybeError = err as { message?: unknown }
  const message = asNonEmptyString(maybeError?.message)
  if (!message) return undefined
  return REQUEST_ID_IN_TEXT_PATTERN.exec(message)?.[1]
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

  let message = extractBackendMessage(data) || (maybeError?.message && String(maybeError.message)) || fallbackMessage
  const requestId = extractAxiosRequestId(err)

  if (status === 429) {
    const meta = extractRateLimitDetail(data)
    const retryAfterSec = meta?.retryAfterSec ?? extractHeaderRetryAfterSec(axiosResponse?.headers)
    if (typeof retryAfterSec === 'number' && retryAfterSec > 0) {
      const suffixBits: string[] = []
      if (meta?.scope) suffixBits.push(`scope=${meta.scope}`)
      if (typeof meta?.limit === 'number' && Number.isFinite(meta.limit) && meta.limit > 0) suffixBits.push(`limit=${meta.limit}`)
      const suffix = suffixBits.length ? `（${suffixBits.join('，')}）` : ''
      message = `请求过于频繁，请在 ${retryAfterSec} 秒后重试${suffix}`
    }
  }

  return { message, requestId, status }
}
