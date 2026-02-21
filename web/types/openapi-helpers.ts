/**
 * OpenAPI type helpers for extracting request/response types from `types/openapi.ts`.
 *
 * The goal is to make incremental migration ergonomic:
 * - Use the OpenAPI schema as the single source of truth
 * - Keep call sites readable (no deeply nested `paths['/...']['get']['responses'][200]...`)
 */
import type { components, paths } from './openapi'

export type OpenApiPaths = paths
export type OpenApiComponents = components
export type OpenApiSchemas = components['schemas']

export type OpenApiPath = keyof OpenApiPaths

export type OpenApiHttpMethod = 'get' | 'post' | 'put' | 'patch' | 'delete'

type _OpAtPath<
  P extends OpenApiPath,
  M extends OpenApiHttpMethod,
> = OpenApiPaths[P] extends { [K in M]?: infer Op } ? Op : never

export type OpenApiMethodForPath<P extends OpenApiPath> = {
  [M in OpenApiHttpMethod]: _OpAtPath<P, M> extends never ? never : M
}[OpenApiHttpMethod]

export type OpenApiOperation<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = _OpAtPath<P, M>

type _Params<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = OpenApiOperation<P, M> extends { parameters: infer Params } ? Params : never

export type OpenApiQueryParams<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = _Params<P, M> extends { query?: infer Q } ? Q : never

export type OpenApiPathParams<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = _Params<P, M> extends { path?: infer PP } ? PP : never

export type OpenApiHeaderParams<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = _Params<P, M> extends { header?: infer H } ? H : never

type _RequestBodyContent<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = OpenApiOperation<P, M> extends { requestBody: { content: infer C } } ? C : never

export type OpenApiRequestBody<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
  ContentType extends string = 'application/json',
> = _RequestBodyContent<P, M> extends Record<string, any>
  ? ContentType extends keyof _RequestBodyContent<P, M>
    ? _RequestBodyContent<P, M>[ContentType]
    : never
  : never

type _Responses<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = OpenApiOperation<P, M> extends { responses: infer R } ? R : never

export type OpenApiResponseStatus<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = keyof _Responses<P, M>

export type OpenApiResponseContent<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
  Status extends OpenApiResponseStatus<P, M>,
> = _Responses<P, M>[Status] extends { content: infer C } ? C : never

export type OpenApiResponseBody<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
  Status extends OpenApiResponseStatus<P, M>,
  ContentType extends string = 'application/json',
> = OpenApiResponseContent<P, M, Status> extends Record<string, any>
  ? ContentType extends keyof OpenApiResponseContent<P, M, Status>
    ? OpenApiResponseContent<P, M, Status>[ContentType]
    : never
  : never

type _OkStatus<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = _Responses<P, M> extends infer R
  ? R extends Record<number, any>
    ? 200 extends keyof R
      ? 200
      : 201 extends keyof R
        ? 201
        : 202 extends keyof R
          ? 202
          : 204 extends keyof R
            ? 204
            : Extract<keyof R, number>
    : never
  : never

export type OpenApiOkStatus<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = _OkStatus<P, M>

export type OpenApiOkJsonResponse<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = OpenApiOkStatus<P, M> extends infer S
  ? S extends OpenApiResponseStatus<P, M>
    ? OpenApiResponseBody<P, M, S, 'application/json'>
    : never
  : never

export type OpenApiOkResponse<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
> = [OpenApiOkJsonResponse<P, M>] extends [never] ? void : OpenApiOkJsonResponse<P, M>
