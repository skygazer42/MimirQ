import type { AxiosInstance, AxiosRequestConfig } from 'axios'

import type {
  OpenApiHeaderParams,
  OpenApiMethodForPath,
  OpenApiOkResponse,
  OpenApiPath,
  OpenApiPathParams,
  OpenApiQueryParams,
  OpenApiRequestBody,
} from '@/types/openapi-helpers'

const HTTP_METHODS = new Set(['get', 'post', 'put', 'patch', 'delete'])

function stripApiV1Prefix(rawPath: string): string {
  const p = String(rawPath || '')
  if (p === '/api/v1') return '/'
  if (p.startsWith('/api/v1/')) return p.slice('/api/v1'.length)
  if (p.startsWith('/api/v1')) return p.slice('/api/v1'.length) || '/'
  return p || '/'
}

function renderPathTemplate(pathTemplate: string, params?: Record<string, unknown>): string {
  const base = stripApiV1Prefix(pathTemplate)
  return base.replace(/\{([^}]+)\}/g, (_m, keyRaw) => {
    const key = String(keyRaw || '').trim()
    const value = params?.[key]
    if (value === undefined || value === null || key === '') {
      throw new Error(`[openapi-request] missing path param: ${key || '(empty)'}`)
    }
    return encodeURIComponent(String(value))
  })
}

export type OpenApiAxiosRequestArgs<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = {
  path: P
  method: M
  query?: OpenApiQueryParams<P, M>
  pathParams?: OpenApiPathParams<P, M>
  headers?: OpenApiHeaderParams<P, M>
  body?: OpenApiRequestBody<P, M, 'application/json'>
  signal?: AbortSignal
  timeoutMs?: number
  axios?: Omit<AxiosRequestConfig, 'url' | 'method' | 'params' | 'data' | 'headers' | 'signal' | 'timeout'>
}

export function createOpenApiAxiosClient(apiClient: AxiosInstance) {
  return async function openapiRequest<
    P extends OpenApiPath,
    M extends OpenApiMethodForPath<P>,
  >(args: OpenApiAxiosRequestArgs<P, M>): Promise<OpenApiOkResponse<P, M>> {
    const method = String(args.method || '').toLowerCase()
    if (!HTTP_METHODS.has(method)) {
      throw new Error(`[openapi-request] unsupported method: ${String(args.method)}`)
    }

    const url = renderPathTemplate(String(args.path), args.pathParams as any)

    const res = await apiClient.request({
      url,
      method: method as any,
      params: args.query as any,
      data: args.body as any,
      headers: args.headers as any,
      signal: args.signal,
      timeout: args.timeoutMs,
      ...args.axios,
    })

    return res.data as any
  }
}

