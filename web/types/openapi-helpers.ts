/**
 * OpenAPI type helpers for extracting request/response types from `types/openapi.ts`.
 *
 * The goal is to make incremental migration ergonomic:
 * - Use the OpenAPI schema as the single source of truth
 * - Keep call sites readable (no deeply nested `paths['/...']['get']['responses'][200]...`)
 */
import type { paths } from './openapi'

export type OpenApiPath = keyof paths

type OpenApiHttpMethod = 'get' | 'post' | 'put' | 'patch' | 'delete'

type OperationAtPath<P extends OpenApiPath, M extends OpenApiHttpMethod> = paths[P] extends {
  [Method in M]?: infer Operation
}
  ? Operation
  : never

export type OpenApiMethodForPath<P extends OpenApiPath> = {
  [M in OpenApiHttpMethod]: OperationAtPath<P, M> extends never ? never : M
}[OpenApiHttpMethod]

type OperationParameters<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> =
  OperationAtPath<P, M> extends { parameters: infer Parameters } ? Parameters : never

export type OpenApiQueryParams<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> =
  OperationParameters<P, M> extends { query?: infer Query } ? Query : never

export type OpenApiPathParams<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> =
  OperationParameters<P, M> extends { path?: infer Path } ? Path : never

export type OpenApiHeaderParams<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> =
  OperationParameters<P, M> extends { header?: infer Headers } ? Headers : never

type RequestBodyContent<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> =
  OperationAtPath<P, M> extends { requestBody: { content: infer Content } } ? Content : never

export type OpenApiRequestBody<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
  ContentType extends string = 'application/json',
> =
  RequestBodyContent<P, M> extends Record<string, unknown>
    ? ContentType extends keyof RequestBodyContent<P, M>
      ? RequestBodyContent<P, M>[ContentType]
      : never
    : never

type OperationResponses<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> =
  OperationAtPath<P, M> extends { responses: infer Responses } ? Responses : never

type ResponseStatus<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> = keyof OperationResponses<P, M>

type ResponseContent<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
  Status extends ResponseStatus<P, M>,
> = OperationResponses<P, M>[Status] extends { content: infer Content } ? Content : never

type ResponseBody<
  P extends OpenApiPath,
  M extends OpenApiMethodForPath<P>,
  Status extends ResponseStatus<P, M>,
  ContentType extends string = 'application/json',
> =
  ResponseContent<P, M, Status> extends Record<string, unknown>
    ? ContentType extends keyof ResponseContent<P, M, Status>
      ? ResponseContent<P, M, Status>[ContentType]
      : never
    : never

type SuccessStatus<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> =
  OperationResponses<P, M> extends infer Responses
    ? Responses extends Record<number, unknown>
      ? 200 extends keyof Responses
        ? 200
        : 201 extends keyof Responses
          ? 201
          : 202 extends keyof Responses
            ? 202
            : 204 extends keyof Responses
              ? 204
              : Extract<keyof Responses, number>
      : never
    : never

type SuccessJsonResponse<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> =
  SuccessStatus<P, M> extends infer Status
    ? Status extends ResponseStatus<P, M>
      ? ResponseBody<P, M, Status, 'application/json'>
      : never
    : never

export type OpenApiOkResponse<P extends OpenApiPath, M extends OpenApiMethodForPath<P>> = [
  SuccessJsonResponse<P, M>,
] extends [never]
  ? void
  : SuccessJsonResponse<P, M>
