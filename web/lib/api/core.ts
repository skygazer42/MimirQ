import axios, { AxiosHeaders } from 'axios'
import type { AxiosRequestConfig, AxiosResponse } from 'axios'

import { extractBackendMessage, extractBackendRequestId, extractRateLimitDetail } from '@/lib/api-errors'
import { getAuthHeaders } from '@/lib/auth-headers'
import { clearAuthSession, getAccessToken, setAccessToken } from '@/lib/auth-storage'
import { API_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { tryRefreshOidcAccessToken } from '@/lib/oidc-session'
import { createOpenApiAxiosClient } from '@/lib/openapi-request'
import { applyPreferredLanguageAxiosHeader } from '@/lib/preferred-language'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { generateRequestId } from '@/lib/request-id'

type PrimitiveHeaderValue = string | number | boolean

function headerValueToString(value: unknown): string | undefined {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const joined = value
      .filter(
        (item): item is PrimitiveHeaderValue =>
          typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean'
      )
      .map(String)
      .join(', ')
      .trim()
    return joined || undefined
  }
  return undefined
}

function getOrCreateRequestId(headers: AxiosHeaders): string {
  const existing = headerValueToString(headers.get('X-Request-ID'))
  if (existing) return existing

  const requestId = generateRequestId()
  headers.set('X-Request-ID', requestId)
  return requestId
}

export type ApiRequestOptions = {
  signal?: AbortSignal
}

type RateLimitLogMessageInput = {
  retryAfterSec?: number
  scope?: string
  limit?: number
}
type RetriableRequestConfig = AxiosRequestConfig & {
  __mimirqOidcRetried?: boolean
}
type ApiClientError = Error & {
  code?: string
  config?: RetriableRequestConfig
  request?: unknown
  requestId?: string
  response?: {
    status: number
    data: unknown
    headers?: Record<string, unknown>
  }
}
type HtmlResponseError = Error & {
  code?: string
  response?: AxiosResponse
  config?: AxiosResponse['config']
  request?: AxiosResponse['request']
}

function asApiClientError(error: unknown): ApiClientError {
  return error instanceof Error
    ? error
    : Object.assign(new Error(toTrimmedPrimitiveString(error, 'API request failed')), {
        cause: error,
      }) as ApiClientError
}

export const apiClient = axios.create({
  baseURL: API_V1_BASE_URL,
  timeout: API_TIMEOUT_MS,
})

function shouldAvoidDevOverlayForHandledApiError(): boolean {
  // Next dev overlay treats browser console.error as a page error. These API
  // failures are already thrown to page-level handlers, so keep dev UX usable.
  return globalThis.window !== undefined && process.env.NODE_ENV !== 'production'
}

function logRequestScopedError(message: string, requestId?: string, detail?: string) {
  const parts = [message]
  if (detail) parts.push(detail)
  if (requestId) parts.push(`(request_id=${requestId})`)
  const log = shouldAvoidDevOverlayForHandledApiError() ? console.warn : console.error
  log(...parts)
}

function toFiniteNumber(value: unknown): number | undefined {
  if (value === null || value === undefined || value === '') return undefined
  const number = Number(value)
  return Number.isFinite(number) ? number : undefined
}

export function coerceRetryAfterSeconds(retryAfterBody: unknown, retryAfterHeader: unknown): number | undefined {
  return toFiniteNumber(retryAfterBody) ?? toFiniteNumber(retryAfterHeader)
}

export function formatRateLimitLogMessage({
  retryAfterSec,
  scope,
  limit,
}: Readonly<RateLimitLogMessageInput>): { message: string; extra: string } {
  const bits: string[] = []
  if (scope) bits.push(`scope=${scope}`)
  if (typeof limit === 'number' && Number.isFinite(limit) && limit > 0) bits.push(`limit=${String(limit)}`)
  if (typeof retryAfterSec === 'number' && Number.isFinite(retryAfterSec) && retryAfterSec > 0) {
    bits.push(`retry_after=${String(retryAfterSec)}s`)
  }

  return {
    message:
      typeof retryAfterSec === 'number' && Number.isFinite(retryAfterSec) && retryAfterSec > 0
        ? `[API] 请求过于频繁，请在 ${String(Math.round(retryAfterSec))} 秒后重试`
        : '[API] 请求过于频繁，请稍后重试',
    extra: bits.length ? `(${bits.join(', ')})` : '',
  }
}

function isRequestCancellationError(error: unknown): boolean {
  const candidate = error as { code?: unknown; name?: unknown; message?: unknown } | null
  if (!candidate || typeof candidate !== 'object') return false

  if (candidate.code === 'ERR_CANCELED') return true
  if (candidate.name === 'AbortError' || candidate.name === 'CanceledError') return true

  const message = typeof candidate.message === 'string' ? candidate.message.trim().toLowerCase() : ''
  return message === 'canceled'
}

async function handleUnauthorizedApiError(error: ApiClientError, requestId?: string) {
  logRequestScopedError('[API] 未授权，请检查登录状态', requestId)

  const token = getAccessToken()
  const canAttemptRefresh =
    !!token && globalThis.window !== undefined && !!error.config && !error.config.__mimirqOidcRetried
  if (canAttemptRefresh && error.config) {
    error.config.__mimirqOidcRetried = true

    const refreshed = await tryRefreshOidcAccessToken()
    if (refreshed) {
      setAccessToken(refreshed)
      return apiClient.request(error.config)
    }
  }

  if (!token) return undefined

  clearAuthSession()
  if (globalThis.window === undefined) return undefined

  const path = String(globalThis.window.location?.pathname || '')
  if (!path.startsWith('/auth')) {
    globalThis.window.location.href = '/auth'
  }

  return undefined
}

function handleResponseStatusError(
  status: number,
  detail: string,
  requestId: string | undefined,
  data: unknown,
  error: ApiClientError
) {
  if (status === 403) {
    logRequestScopedError('[API] 无权限访问', requestId)
    return
  }
  if (status === 404) {
    logRequestScopedError('[API] 资源不存在', requestId)
    return
  }
  if (status === 422) {
    logRequestScopedError('[API] 请求参数错误:', requestId, detail)
    return
  }
  if (status === 429) {
    const retryAfterHeader = error.response?.headers?.['retry-after']
    const rateLimit = extractRateLimitDetail(data)
    const retryAfterSec = coerceRetryAfterSeconds(rateLimit?.retryAfterSec, retryAfterHeader)
    const { message, extra } = formatRateLimitLogMessage({
      retryAfterSec,
      scope: rateLimit?.scope,
      limit: rateLimit?.limit,
    })
    logRequestScopedError(message, requestId, extra)
    return
  }
  if (status === 500) {
    logRequestScopedError('[API] 服务器错误:', requestId, detail)
    return
  }
  logRequestScopedError('[API] 请求失败:', requestId, detail || error.message)
}

async function handleApiClientError(error: unknown) {
  if (isRequestCancellationError(error)) {
    throw error
  }

  const apiError = asApiClientError(error)

  if (apiError.response) {
    const status = apiError.response.status
    const data = apiError.response.data
    const detail = extractBackendMessage(data) || apiError.message
    const headerRequestId = headerValueToString(apiError.response.headers?.['x-request-id'])
    const requestId = extractBackendRequestId(data) || headerRequestId
    apiError.requestId = requestId

    if (status === 401) {
      const retried = await handleUnauthorizedApiError(apiError, requestId)
      if (retried) return retried
      throw apiError
    }

    handleResponseStatusError(status, detail, requestId, data, apiError)
    throw apiError
  }

  if (apiError.request) {
    const headers = AxiosHeaders.from(
      (apiError.config?.headers ?? {}) as Record<string, string | number | boolean>
    )
    const requestId = headerValueToString(headers.get('X-Request-ID'))
    apiError.requestId = requestId
    logRequestScopedError('[API] 网络连接中断或后端不可达，请检查后端服务 / API 地址', requestId)
  }

  throw apiError
}

apiClient.interceptors.request.use((config) => {
  const headers = AxiosHeaders.from(config.headers)
  const authHeaders = getAuthHeaders()
  for (const [key, value] of Object.entries(authHeaders)) {
    if (!headers.has(key)) {
      headers.set(key, value)
    }
  }
  applyPreferredLanguageAxiosHeader(headers)
  getOrCreateRequestId(headers)
  config.headers = headers
  return config
})

apiClient.interceptors.response.use(
  (response) => {
    const responseType = response.config?.responseType
    const expectsJson = !responseType || responseType === 'json'
    if (expectsJson) {
      const contentType = String(response.headers?.['content-type'] || '').toLowerCase()
      if (typeof response.data === 'string') {
        const trimmed = response.data.trimStart().slice(0, 200).toLowerCase()
        const looksHtml = trimmed.startsWith('<!doctype html') || trimmed.startsWith('<html')
        if (looksHtml || contentType.includes('text/html')) {
          const err: HtmlResponseError = new Error(
            'Backend returned HTML (可能 API 地址配错了；请检查 NEXT_PUBLIC_API_URL / 反向代理配置)'
          )
          err.code = 'ERR_BAD_RESPONSE'
          err.response = response
          err.config = response.config
          err.request = response.request
          return Promise.reject(err)
        }
      }
    }

    return response
  },
  handleApiClientError
)

export const openapiRequest = createOpenApiAxiosClient(apiClient)

export default apiClient
