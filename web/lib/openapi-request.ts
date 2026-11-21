import type { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'
import type { ZodType } from 'zod'

import { extractHeaderRequestId, withRequestId } from '@/lib/api-errors'

import type {
  OpenApiHeaderParams,
  OpenApiMethodForPath,
  OpenApiOkResponse,
  OpenApiPath,
  OpenApiPathParams,
  OpenApiQueryParams,
  OpenApiRequestBody,
} from '@/types/openapi-helpers'

type JsonContentType = 'application/json'
type MultipartContentType = 'multipart/form-data'

function isRequestScalar(value: unknown): value is string | number | boolean | bigint {
  return (
    typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint'
  )
}

function stripApiV1Prefix(path: string): string {
  if (path === '/api/v1') return '/'
  if (path.startsWith('/api/v1/')) return path.slice('/api/v1'.length)
  return path
}

function renderPathTemplate(pathTemplate: string, params: unknown): string {
  const base = stripApiV1Prefix(pathTemplate)
  const pathParams = isRecord(params) ? params : undefined
  let output = ''
  let cursor = 0
  while (cursor < base.length) {
    const open = base.indexOf('{', cursor)
    if (open === -1) {
      output += base.slice(cursor)
      break
    }
    const close = base.indexOf('}', open + 1)
    if (close === -1) throw new Error(`[openapi-request] invalid path template: ${pathTemplate}`)
    output += base.slice(cursor, open)
    const key = base.slice(open + 1, close)
    if (key.length === 0) throw new Error(`[openapi-request] invalid path template: ${pathTemplate}`)
    const value = pathParams?.[key]
    if (value === undefined || value === null) {
      throw new Error(`[openapi-request] missing path param: ${key}`)
    }
    if (!isRequestScalar(value)) throw new Error(`[openapi-request] invalid path param: ${key}`)
    output += encodeURIComponent(String(value))
    cursor = close + 1
  }
  return output
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function appendFormValue(form: FormData, name: string, value: unknown): void {
  if (value === undefined || value === null) return
  if (value instanceof Blob) {
    form.append(name, value)
    return
  }
  if (typeof value === 'object') {
    const serialized = JSON.stringify(value)
    if (serialized === undefined) throw new TypeError(`[openapi-request] unsupported form-data field: ${name}`)
    form.append(name, serialized)
    return
  }
  if (isRequestScalar(value)) {
    form.append(name, String(value))
    return
  }
  throw new TypeError(`[openapi-request] unsupported form-data field: ${name}`)
}

function toFormData(body: Record<string, unknown>): FormData {
  const form = new FormData()
  for (const [name, value] of Object.entries(body)) {
    if (Array.isArray(value)) {
      for (const item of value) appendFormValue(form, name, item)
    } else {
      appendFormValue(form, name, value)
    }
  }
  return form
}

type OpenApiAxiosRequestArgs<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> = {
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
          // Object bodies are serialized into multipart fields.
          body: FormData | OpenApiRequestBody<P, M, MultipartContentType>
        })
)

export function parseApiResponse<T>(response: AxiosResponse<unknown>, schema: ZodType<T>, schemaLabel: string): T {
  const parsed = schema.safeParse(response.data)
  if (parsed.success) return parsed.data

  const requestId = extractHeaderRequestId(response.headers)
  const firstIssue = parsed.error.issues[0]?.message
  const message = withRequestId(
    firstIssue === undefined
      ? `[openapi-request] invalid ${schemaLabel} response`
      : `[openapi-request] invalid ${schemaLabel} response: ${firstIssue}`,
    requestId,
  )
  throw Object.assign(new Error(message), {
    requestId,
    issues: parsed.error.issues,
    status: response.status,
  })
}

export function createOpenApiAxiosClient(apiClient: AxiosInstance) {
  return async function openapiRequest<P extends OpenApiPath, M extends OpenApiMethodForPath<P>>(
    args: OpenApiAxiosRequestArgs<P, M>,
  ): Promise<OpenApiOkResponse<P, M>> {
    const url = renderPathTemplate(args.path, args.pathParams)
    let data: unknown = args.body
    if (args.contentType === 'multipart/form-data' && isRecord(data) && !(data instanceof FormData)) {
      data = toFormData(data)
    }

    const res = await apiClient.request<OpenApiOkResponse<P, M>>({
      url,
      method: args.method,
      params: args.query,
      data,
      headers: args.headers as AxiosRequestConfig['headers'],
      signal: args.signal,
      timeout: args.timeoutMs,
      ...args.axios,
    })

    if (args.responseSchema === undefined) {
      return res.data
    }

    const schemaLabel =
      args.responseSchemaName === undefined ? `${args.method.toUpperCase()} ${args.path}` : args.responseSchemaName
    return parseApiResponse(res, args.responseSchema, schemaLabel)
  }
}
