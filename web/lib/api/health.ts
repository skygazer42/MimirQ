import { isAxiosError } from 'axios'
import { z } from 'zod'

import { openapiRequest, type ApiRequestOptions } from '@/lib/api/core'
import { recordSchema } from '@/lib/response-schema'
import type { HealthDetailsResponse, HealthResponse, ReadyResponse } from '@/types/backend'

const healthResponseSchema = z.object({
  ok: z.boolean(),
  status: z.string(),
})

const healthDetailsSchema: z.ZodType<HealthDetailsResponse> = healthResponseSchema.extend({
  database: recordSchema,
  vector: recordSchema,
  milvus: recordSchema.nullish(),
  redis: recordSchema,
  minio: recordSchema,
  rag_runtime_warmup: recordSchema.nullish(),
  dify_external_knowledge: recordSchema.nullish(),
  time: z.string(),
  vector_backend: z.string(),
  use_langgraph_pipeline: z.boolean(),
  task_queue: recordSchema,
  uploads: recordSchema,
})

async function readReadiness<T extends ReadyResponse>(request: Promise<T>, schema: z.ZodType<T>): Promise<T> {
  try {
    return await request
  } catch (error: unknown) {
    if (!isAxiosError<unknown>(error) || error.response?.status !== 503) throw error
    const result = schema.safeParse(error.response.data)
    if (result.success && result.data.ok === false && result.data.status === 'unready') return result.data
    throw error
  }
}

export const healthApi = {
  async health(): Promise<HealthResponse> {
    return openapiRequest({
      path: '/api/v1/health',
      method: 'get',
      responseSchema: healthResponseSchema,
      responseSchemaName: 'HealthResponse',
    })
  },

  ready(options?: ApiRequestOptions): Promise<ReadyResponse> {
    return readReadiness(
      openapiRequest({
        path: '/api/v1/health/ready',
        method: 'get',
        signal: options?.signal,
        responseSchema: healthResponseSchema,
        responseSchemaName: 'ReadyResponse',
      }),
      healthResponseSchema,
    )
  },

  details(options?: ApiRequestOptions): Promise<HealthDetailsResponse> {
    return readReadiness(
      openapiRequest({ path: '/api/v1/health/details', method: 'get', signal: options?.signal }),
      healthDetailsSchema,
    )
  },
}
