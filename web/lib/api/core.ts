import axios, { AxiosHeaders } from 'axios'
import type { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

import {
  extractBackendMessage,
  extractHeaderRequestId,
  extractRateLimitInfo,
  extractRequestIdFromError,
  HTML_API_ERROR_MESSAGE,
  isHtmlApiResponse,
  type RateLimitInfo,
} from '@/lib/api-errors'
import { getAuthHeaders } from '@/lib/auth-headers'
import { clearAuthSession, getAccessToken, getAuthSessionKey, setAccessToken } from '@/lib/auth-storage'
import { API_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { tryRefreshOidcAccessToken } from '@/lib/oidc-session'
import { createOpenApiAxiosClient } from '@/lib/openapi-request'
import { applyPreferredLanguageAxiosHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'

type RetriableRequestConfig = InternalAxiosRequestConfig<unknown> & {
  __mimirqOidcRetried?: boolean
  __mimirqAuthSessionKey?: string
  __mimirqUsesSessionToken?: boolean
}

type ApiClientError = AxiosError<unknown, unknown> & {
  requestId?: string
  config?: RetriableRequestConfig
}

function ensureRequestId(headers: AxiosHeaders): void {
  if (extractHeaderRequestId(headers) !== undefined) return
  headers.set('X-Request-ID', generateRequestId(), true)
}

export type ApiRequestOptions = {
  signal?: AbortSignal
}

export const apiClient = axios.create({
  baseURL: API_V1_BASE_URL,
  timeout: API_TIMEOUT_MS,
})

function shouldAvoidDevOverlayForHandledApiError(): boolean {
  return globalThis.window !== undefined && process.env.NODE_ENV !== 'production'
}

function logRequestScopedError(message: string, requestId?: string, detail?: string) {
  const parts = [message]
  if (detail !== undefined) parts.push(detail)
  if (requestId !== undefined) parts.push(`(request_id=${requestId})`)
  const log = shouldAvoidDevOverlayForHandledApiError() ? console.warn : console.error
  log(...parts)
}

function formatRateLimitLogMessage(rateLimit: RateLimitInfo | undefined): {
  message: string
  extra?: string
} {
  const details: string[] = []
  if (rateLimit?.scope !== undefined) details.push(`scope=${rateLimit.scope}`)
  if (rateLimit?.limit !== undefined) details.push(`limit=${rateLimit.limit}`)
  const seconds = rateLimit?.retryAfterSec
  let message = '[API] 请求过于频繁，请稍后重试'
  if (seconds !== undefined && seconds > 0) {
    message = `[API] 请求过于频繁，请在 ${seconds} 秒后重试`
    details.push(`retry_after=${seconds}s`)
  }
  return {
    message,
    extra: details.length === 0 ? undefined : `(${details.join(', ')})`,
  }
}

async function handleUnauthorizedApiError(error: ApiClientError, requestId?: string) {
  logRequestScopedError('[API] 未授权，请检查登录状态', requestId)
  const config = error.config
  if (config === undefined) return
  if (config.signal?.aborted) throw new axios.CanceledError('canceled')

  const requestOwnsSession = () => config.__mimirqAuthSessionKey === getAuthSessionKey()
  if (!requestOwnsSession() || config.__mimirqUsesSessionToken !== true) return

  const token = getAccessToken()
  if (token === null) return
  const sentAuthorization = config.headers.get('Authorization')

  if (globalThis.window !== undefined && !config.__mimirqOidcRetried) {
    config.__mimirqOidcRetried = true
    const refreshed =
      sentAuthorization === `Bearer ${token}`
        ? await tryRefreshOidcAccessToken().finally(() => {
            if (config.signal?.aborted) throw new axios.CanceledError('canceled')
          })
        : null
    if (!requestOwnsSession()) return

    const activeToken = getAccessToken()
    if (activeToken === null) return
    const tokenRotated = sentAuthorization !== `Bearer ${activeToken}`
    if (!tokenRotated && refreshed !== null) setAccessToken(refreshed)
    const retryToken = tokenRotated ? activeToken : refreshed?.access_token
    if (retryToken !== undefined) {
      config.headers.set('Authorization', `Bearer ${retryToken}`)
      return apiClient.request(config)
    }
  }

  if (sentAuthorization !== `Bearer ${token}`) return
  clearAuthSession()
  if (globalThis.window !== undefined && !globalThis.window.location.pathname.startsWith('/auth')) {
    globalThis.window.location.href = '/auth'
  }
}

function handleResponseStatusError(
  status: number,
  detail: string,
  requestId: string | undefined,
  data: unknown,
  error: ApiClientError,
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
    const rateLimit = extractRateLimitInfo(data, error.response?.headers)
    const { message, extra } = formatRateLimitLogMessage(rateLimit)
    logRequestScopedError(message, requestId, extra)
    return
  }
  if (status === 500) {
    logRequestScopedError('[API] 服务器错误:', requestId, detail)
    return
  }
  logRequestScopedError('[API] 请求失败:', requestId, detail)
}

async function handleApiClientError(error: unknown) {
  if (axios.isCancel(error) || !axios.isAxiosError<unknown, unknown>(error)) throw error
  const apiError: ApiClientError = error
  const requestId = extractRequestIdFromError(apiError)
  apiError.requestId = requestId

  if (apiError.response !== undefined) {
    const { status, data, headers } = apiError.response
    const backendMessage = extractBackendMessage(data, headers)
    const detail = backendMessage === undefined ? apiError.message : backendMessage
    if (status === 401) {
      const retried = await handleUnauthorizedApiError(apiError, requestId)
      if (retried !== undefined) return retried
      throw apiError
    }
    handleResponseStatusError(status, detail, requestId, data, apiError)
    throw apiError
  }

  if (apiError.request !== undefined) {
    logRequestScopedError('[API] 网络连接中断或后端不可达，请检查后端服务 / API 地址', requestId)
  }
  throw apiError
}

function prepareApiRequest(config: InternalAxiosRequestConfig<unknown>): InternalAxiosRequestConfig<unknown> {
  const headers = config.headers
  const sessionHeaders = getAuthHeaders()
  const requestConfig: RetriableRequestConfig = config
  if (requestConfig.__mimirqAuthSessionKey === undefined) {
    requestConfig.__mimirqAuthSessionKey = getAuthSessionKey()
    requestConfig.__mimirqUsesSessionToken = !headers.has('Authorization') && sessionHeaders.Authorization !== undefined
  }
  for (const [key, value] of Object.entries(sessionHeaders)) {
    if (!headers.has(key)) headers.set(key, value)
  }
  applyPreferredLanguageAxiosHeader(headers)
  ensureRequestId(headers)
  return config
}

function rejectUnexpectedHtmlResponse(response: AxiosResponse<unknown>): AxiosResponse<unknown> | Promise<never> {
  const responseType = response.config.responseType
  if (responseType !== undefined && responseType !== 'json') return response
  if (!isHtmlApiResponse(response.data, response.headers)) return response

  return Promise.reject(
    Object.assign(new Error(HTML_API_ERROR_MESSAGE), {
      code: 'ERR_BAD_RESPONSE',
      response: { ...response, data: undefined },
      config: response.config,
      request: response.request,
    }),
  )
}

apiClient.interceptors.request.use(prepareApiRequest)
apiClient.interceptors.response.use(rejectUnexpectedHtmlResponse, handleApiClientError)

export const openapiRequest = createOpenApiAxiosClient(apiClient)
