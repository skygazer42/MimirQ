import type { AxiosInstance, AxiosRequestConfig } from 'axios'
import type { ZodType } from 'zod'

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
  let output = ''
  let cursor = 0
  while (cursor < base.length) {
    const open = base.indexOf('{', cursor)
    if (open === -1) {
      output += base.slice(cursor)
      break
    }
    const close = base.indexOf('}', open + 1)
    if (close === -1) {
      output += base.slice(cursor)
      break
    }
    output += base.slice(cursor, open)
    const key = base.slice(open + 1, close).trim()
    const value = params?.[key]
    if (value === undefined || value === null || key === '') {
      throw new Error(`[openapi-request] missing path param: ${key || '(empty)'}`)
    }
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
      output += encodeURIComponent(String(value))
      cursor = close + 1
      continue
    }
    throw new Error(`[openapi-request] invalid path param: ${key}`)
  }
  return output
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
        } else if (typeof v === 'object') {
          fd.append(k, JSON.stringify(v))
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

    if (typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean' || typeof raw === 'bigint') {
      fd.append(k, String(raw))
      continue
    }

    throw new Error(`[openapi-request] unsupported form-data field: ${k}`)
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
  responseSchema?: ZodType<OpenApiOkResponse<P, M>>
  responseSchemaName?: string
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

function headerValueToString(value: unknown): string | undefined {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed || undefined
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const joined = value
      .filter((item): item is string | number | boolean => typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean')
      .map(String)
      .join(', ')
      .trim()
    return joined || undefined
  }
  return undefined
}

function extractResponseRequestId(headers: unknown): string | undefined {
  if (!headers) return undefined

  try {
    if (typeof (headers as { get?: unknown }).get === 'function') {
      const get = (headers as { get(name: string): unknown }).get
      return headerValueToString(get('x-request-id') ?? get('X-Request-ID'))
    }
  } catch {
    // Ignore header accessor failures and fall back to object access below.
  }

  const record = headers as Record<string, unknown>
  return headerValueToString(record['x-request-id'] ?? record['X-Request-ID'])
}

function withRequestId(message: string, requestId?: string): string {
  const rid = String(requestId || '').trim()
  if (!rid || /\brequest_id=/.test(message)) return message
  return `${message} (request_id=${rid})`
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

    const contentType: OpenApiContentType = (args as any).contentType || 'application/json'
    let data = (args as any).body

    if (contentType === 'multipart/form-data' && data && !isFormData(data)) {
      data = toFormData(data)
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

    if (!args.responseSchema) {
      return res.data
    }

    const parsed = args.responseSchema.safeParse(res.data)
    if (parsed.success) {
      return parsed.data
    }

    const requestId = extractResponseRequestId(res.headers)
    const schemaLabel = String(args.responseSchemaName || `${String(args.method).toUpperCase()} ${String(args.path)}`)
    const firstIssue = parsed.error.issues[0]?.message
    const message = withRequestId(
      firstIssue
        ? `[openapi-request] invalid ${schemaLabel} response: ${firstIssue}`
        : `[openapi-request] invalid ${schemaLabel} response`,
      requestId
    )
    const error = new Error(message)
    ;(error as Error & { requestId?: string; issues?: unknown[]; status?: number }).requestId = requestId
    ;(error as Error & { requestId?: string; issues?: unknown[]; status?: number }).issues = parsed.error.issues
    ;(error as Error & { requestId?: string; issues?: unknown[]; status?: number }).status = res.status
    throw error
  }
}
