import { readNonEmptyString } from '@/lib/primitive-text'

const REQUEST_ID_IN_TEXT_PATTERN = /\brequest_id=([A-Za-z0-9._:-]+)\b/

export const HTML_API_ERROR_MESSAGE =
  'Backend returned HTML (可能 API 地址配错了；请检查 NEXT_PUBLIC_API_URL / 反向代理配置)'

export type ApiErrorInfo = {
  message: string
  requestId?: string
  status?: number
}

export type RateLimitInfo = {
  retryAfterSec?: number
  limit?: number
  scope?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readFiniteNumber(value: unknown): number | undefined {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined
  const text = readNonEmptyString(value)
  if (text === undefined) return undefined
  const number = Number(text)
  return Number.isFinite(number) ? number : undefined
}

function readBackendPayload(data: unknown): unknown {
  if (typeof data !== 'string') return data
  const text = data.trim()
  if (!text.startsWith('{')) return text
  try {
    const payload: unknown = JSON.parse(text)
    return payload
  } catch {
    return text
  }
}

function readHeaderValue(headers: unknown, name: string): unknown {
  if (!isRecord(headers)) return undefined
  if (typeof headers.get === 'function') return headers.get(name)
  const key = Object.keys(headers).find((key) => key.toLowerCase() === name.toLowerCase())
  return key === undefined ? undefined : headers[key]
}

function readRetryAfterSeconds(value: unknown): number | undefined {
  const seconds = readFiniteNumber(value)
  if (seconds === undefined || seconds < 0) return undefined
  return Math.ceil(seconds)
}

export function extractRateLimitInfo(data: unknown, headers: unknown): RateLimitInfo | undefined {
  const payload = readBackendPayload(data)
  const detail = isRecord(payload) && isRecord(payload.detail) ? payload.detail : undefined
  const bodySeconds = readRetryAfterSeconds(detail?.retry_after_sec)
  const retryAfterSec = bodySeconds === undefined ? extractHeaderRetryAfterSeconds(headers) : bodySeconds
  const limit = readFiniteNumber(detail?.limit)
  const scope = readNonEmptyString(detail?.scope)
  if (retryAfterSec === undefined && limit === undefined && scope === undefined) return undefined
  return { retryAfterSec, limit, scope }
}

function extractBackendRequestId(data: unknown): string | undefined {
  const payload = readBackendPayload(data)
  if (!isRecord(payload)) return undefined
  return readNonEmptyString(payload.request_id)
}

export function isHtmlApiResponse(data: unknown, headers: unknown): boolean {
  if (typeof data !== 'string') return false
  const contentType = readHeaderValue(headers, 'content-type')
  if (typeof contentType === 'string' && contentType.split(';', 1)[0].trim().toLowerCase() === 'text/html') return true
  const text = data.trimStart().slice(0, 200).toLowerCase()
  return text.startsWith('<!doctype html') || text.startsWith('<html')
}

export function extractBackendMessage(data: unknown, headers: unknown): string | undefined {
  if (isHtmlApiResponse(data, headers)) return HTML_API_ERROR_MESSAGE
  const payload = readBackendPayload(data)
  if (typeof payload === 'string') return readNonEmptyString(payload)
  if (!isRecord(payload)) return undefined

  const detail = payload.detail
  if (payload.error === 'VALIDATION_ERROR' && isRecord(detail) && Array.isArray(detail.errors)) {
    for (const issue of detail.errors) {
      if (!isRecord(issue)) continue
      const issueMessage = readNonEmptyString(issue.msg)
      if (issueMessage === undefined) continue
      const field = Array.isArray(issue.loc)
        ? issue.loc.filter((part) => typeof part === 'string' || typeof part === 'number').join('.')
        : undefined
      return field ? `${field} · ${issueMessage}` : issueMessage
    }
  }

  const message = readNonEmptyString(payload.message)
  if (message !== undefined) return message
  const detailMessage = readNonEmptyString(detail)
  if (detailMessage !== undefined) return detailMessage
  if (isRecord(detail)) return readNonEmptyString(detail.message)
  return undefined
}

export function extractHeaderRequestId(headers: unknown): string | undefined {
  const value = readHeaderValue(headers, 'x-request-id')
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return readNonEmptyString(value)
}

function extractHeaderRetryAfterSeconds(headers: unknown): number | undefined {
  return readRetryAfterSeconds(readHeaderValue(headers, 'retry-after'))
}

export function extractRequestIdFromError(error: unknown): string | undefined {
  if (typeof error === 'string') return REQUEST_ID_IN_TEXT_PATTERN.exec(error)?.[1]
  if (!isRecord(error)) return undefined

  const direct = readNonEmptyString(error.requestId) ?? readNonEmptyString(error.request_id)
  if (direct !== undefined) return direct
  const response = isRecord(error.response) ? error.response : undefined
  const bodyId = extractBackendRequestId(response?.data)
  if (bodyId !== undefined) return bodyId
  const headerId = extractHeaderRequestId(response?.headers)
  if (headerId !== undefined) return headerId
  const config = isRecord(error.config) ? error.config : undefined
  const configId = extractHeaderRequestId(config?.headers)
  if (configId !== undefined) return configId
  const message = readNonEmptyString(error.message)
  return message === undefined ? undefined : REQUEST_ID_IN_TEXT_PATTERN.exec(message)?.[1]
}

function formatRequestId(requestId?: string): string | undefined {
  if (requestId === undefined) return undefined
  const text = requestId.trim()
  return text.length === 0 ? undefined : `request_id=${text}`
}

export function withRequestId(message: string, requestId?: string): string {
  const label = formatRequestId(requestId)
  if (label === undefined || REQUEST_ID_IN_TEXT_PATTERN.test(message)) return message
  return `${message} (${label})`
}

export function extractHttpStatus(error: unknown): number | undefined {
  if (!isRecord(error)) return undefined
  const responseStatus = isRecord(error.response) ? error.response.status : undefined
  if (typeof responseStatus === 'number' && Number.isFinite(responseStatus)) return responseStatus
  const directStatus = error.status
  return typeof directStatus === 'number' && Number.isFinite(directStatus) ? directStatus : undefined
}

export function toApiErrorInfo(error: unknown, fallbackMessage: string): ApiErrorInfo {
  if (typeof error === 'string') {
    const message = readNonEmptyString(error)
    return {
      message: message === undefined ? fallbackMessage : message,
      requestId: extractRequestIdFromError(error),
    }
  }

  const record = isRecord(error) ? error : undefined
  const response = isRecord(record?.response) ? record.response : undefined
  const status = extractHttpStatus(error)
  const backendMessage = extractBackendMessage(response?.data, response?.headers)
  const errorMessage = readNonEmptyString(record?.message)
  const code = readNonEmptyString(record?.code)?.toUpperCase()
  let message: string
  if (backendMessage !== undefined) message = backendMessage
  else if (errorMessage !== undefined) message = errorMessage
  else message = fallbackMessage

  if (response === undefined && (code === 'ECONNABORTED' || code === 'ETIMEDOUT')) {
    message = `${fallbackMessage}：请求超时，后端可能仍在处理。请稍后刷新列表确认结果，或缩小本次操作范围后重试`
  }

  const normalizedMessage = errorMessage?.toLowerCase()
  if (
    response === undefined &&
    (code === 'ERR_NETWORK' || normalizedMessage === 'network error' || normalizedMessage === 'failed to fetch')
  ) {
    message = `${fallbackMessage}：无法连接后端 API，请确认后端服务已启动，或检查 NEXT_PUBLIC_API_URL / 反向代理配置`
  }

  if (status === 429) {
    const rateLimit = extractRateLimitInfo(response?.data, response?.headers)
    const retryAfterSec = rateLimit?.retryAfterSec
    if (retryAfterSec !== undefined && retryAfterSec > 0) {
      const details: string[] = []
      if (rateLimit?.scope !== undefined) details.push(`scope=${rateLimit.scope}`)
      if (rateLimit?.limit !== undefined) details.push(`limit=${rateLimit.limit}`)
      message = `请求过于频繁，请在 ${retryAfterSec} 秒后重试`
      if (details.length > 0) message += `（${details.join('，')}）`
    }
  }

  return { message, requestId: extractRequestIdFromError(error), status }
}

export function formatApiError(error: unknown, fallbackMessage: string): string {
  const info = toApiErrorInfo(error, fallbackMessage)
  return withRequestId(info.message, info.requestId)
}

export async function formatApiBlobError(
  error: unknown,
  fallbackMessage: string,
  maxBodyBytes?: number,
): Promise<string> {
  if (!isRecord(error) || error.isAxiosError !== true || !isRecord(error.response)) {
    return formatApiError(error, fallbackMessage)
  }
  const response = error.response
  const body = response.data
  if (!(body instanceof Blob) || (maxBodyBytes !== undefined && body.size > maxBodyBytes)) {
    return formatApiError(error, fallbackMessage)
  }

  let data: unknown
  try {
    data = JSON.parse(await body.text())
  } catch {
    return formatApiError(error, fallbackMessage)
  }
  return formatApiError(
    {
      message: error.message,
      code: error.code,
      requestId: extractRequestIdFromError(error),
      response: { status: response.status, headers: response.headers, data },
    },
    fallbackMessage,
  )
}
