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
type HeaderLike = Record<string, unknown> & {
  get?: (name: string) => unknown
}
type AxiosErrorLike = {
  code?: unknown
  message?: unknown
  requestId?: unknown
  request_id?: unknown
  response?: {
    status?: unknown
    data?: unknown
    headers?: unknown
  }
  config?: {
    headers?: unknown
  }
}

function looksLikeHtmlDocument(value: string): boolean {
  const trimmed = (value || '').trimStart().slice(0, 200).toLowerCase()
  return trimmed.startsWith('<!doctype html') || trimmed.startsWith('<html')
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
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

function parseJsonObjectString(value: string): ErrorResponseLike | undefined {
  const trimmed = value.trim()
  if (!trimmed?.startsWith('{')) return undefined
  try {
    const parsed = JSON.parse(trimmed)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as ErrorResponseLike)
      : undefined
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
  if (typeof data === 'string') {
    const parsed = parseJsonObjectString(data)
    return parsed ? extractBackendRequestId(parsed) : undefined
  }

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

    const parsed = parseJsonObjectString(data)
    if (parsed) return extractBackendMessage(parsed)

    return asNonEmptyString(data)
  }

  if (typeof data === 'object') {
    const payload = data as ErrorResponseLike
    const detail = isRecord(payload.detail) ? payload.detail : null
    return (
      asNonEmptyString(payload.message) ||
      asNonEmptyString(payload.detail) ||
      // FastAPI default: {"detail":[{...},{...}]}
      (Array.isArray(payload.detail) ? 'Validation error' : undefined) ||
      (detail
        ? asNonEmptyString(detail.message) || safeJson(payload.detail)
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

function extractHeaderRequestId(headers: unknown): string | undefined {
  if (!headers) return undefined
  const record = headers as HeaderLike
  const raw =
    record['x-request-id'] ??
    record['X-Request-ID'] ??
    record['x-request-id'.toLowerCase()] ??
    record['X-Request-ID'.toLowerCase()]
  if (raw == null) return undefined
  return asNonEmptyString(String(raw))
}

function extractHeaderRetryAfterSec(headers: unknown): number | undefined {
  if (!headers) return undefined
  const record = headers as HeaderLike
  const raw =
    record['retry-after'] ??
    record['Retry-After'] ??
    record['retry-after'.toLowerCase()] ??
    record['Retry-After'.toLowerCase()]
  if (raw == null) return undefined
  const parsed = asFiniteNumber(raw)
  if (parsed == null) return undefined
  return Math.max(0, Math.round(parsed))
}

function extractConfigRequestId(headers: unknown): string | undefined {
  if (!headers) return undefined
  const record = headers as HeaderLike
  try {
    if (typeof record.get === 'function') {
      return asNonEmptyString(record.get('X-Request-ID') || record.get('x-request-id'))
    }
  } catch {
    // ignore
  }
  const raw = record['X-Request-ID'] ?? record['x-request-id']
  return raw == null ? undefined : asNonEmptyString(String(raw))
}

export function extractAxiosRequestId(err: unknown): string | undefined {
  const maybeError = err as AxiosErrorLike

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

  const maybeError = err as AxiosErrorLike
  const axiosResponse = maybeError?.response
  const status = typeof axiosResponse?.status === 'number' ? axiosResponse.status : undefined
  const data = axiosResponse?.data

  let message =
    extractBackendMessage(data) ||
    (maybeError?.message ? String(maybeError.message) : '') ||
    fallbackMessage
  const requestId = extractAxiosRequestId(err)
  const normalizedMessage = String(message || '').trim().toLowerCase()
  const code = String(maybeError?.code || '').trim().toUpperCase()

  if (
    !axiosResponse &&
    (code === 'ECONNABORTED' ||
      code === 'ETIMEDOUT' ||
      normalizedMessage.includes('timeout') ||
      normalizedMessage.includes('exceeded'))
  ) {
    message = `${fallbackMessage}：请求超时，后端可能仍在处理。请稍后刷新列表确认结果，或缩小本次操作范围后重试`
  }

  if (!axiosResponse && (normalizedMessage === 'network error' || normalizedMessage === 'failed to fetch')) {
    message = `${fallbackMessage}：无法连接后端 API，请确认后端服务已启动，或检查 NEXT_PUBLIC_API_URL / 反向代理配置`
  }

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
