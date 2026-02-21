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

type JsonContentType = 'application/json'
type MultipartContentType = 'multipart/form-data'
export type OpenApiContentType = JsonContentType | MultipartContentType

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

function isFormData(value: unknown): value is FormData {
  return typeof FormData !== 'undefined' && value instanceof FormData
}

function toFormData(body: Record<string, unknown>): FormData {
  if (typeof FormData === 'undefined') {
    throw new Error('[openapi-request] FormData is not available in this environment')
  }

  const fd = new FormData()
  const hasBlob = typeof Blob !== 'undefined'

  for (const [k, raw] of Object.entries(body)) {
    if (raw === undefined || raw === null) continue

    if (Array.isArray(raw)) {
      for (const v of raw) {
        if (v === undefined || v === null) continue
        if (hasBlob && v instanceof Blob) {
          fd.append(k, v)
        } else {
          fd.append(k, String(v))
        }
      }
      continue
    }

    if (hasBlob && raw instanceof Blob) {
      fd.append(k, raw)
      continue
    }

    if (typeof raw === 'object') {
      fd.append(k, JSON.stringify(raw))
      continue
    }

    fd.append(k, String(raw))
  }

  return fd
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
  signal?: AbortSignal
  timeoutMs?: number
  axios?: Omit<AxiosRequestConfig, 'url' | 'method' | 'params' | 'data' | 'headers' | 'signal' | 'timeout'>
} & (
  | {
      contentType?: JsonContentType
      body?: OpenApiRequestBody<P, M, JsonContentType>
    }
  | ([OpenApiRequestBody<P, M, MultipartContentType>] extends [never]
      ? never
      : {
          contentType: MultipartContentType
          // Allow passing pre-built FormData for cases that need custom filenames or repeated keys.
          // Typed multipart bodies (object shape) are also accepted and will be converted best-effort.
          body: FormData | OpenApiRequestBody<P, M, MultipartContentType>
        })
)

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

    const contentType: OpenApiContentType = (args as any).contentType || 'application/json'
    let data = (args as any).body

    if (contentType === 'multipart/form-data' && data && !isFormData(data)) {
      data = toFormData(data as any)
    }

    const res = await apiClient.request({
      url,
      method: method as any,
      params: args.query as any,
      data,
      headers: args.headers as any,
      signal: args.signal,
      timeout: args.timeoutMs,
      ...args.axios,
    })

    return res.data as any
  }
}
