import type { HealthResponse, ReadyResponse } from '@/types'
import { z } from 'zod'

import { openapiRequest } from '@/lib/api/core'

const healthResponseSchema: z.ZodType<HealthResponse> = z.object({
  ok: z.boolean(),
  time: z.string(),
  vector_backend: z.string().nullable().optional(),
  use_langgraph_pipeline: z.boolean().nullable().optional(),
})

export const healthApi = {
  async health(): Promise<HealthResponse> {
    return openapiRequest({
      path: '/api/v1/health',
      method: 'get',
      responseSchema: healthResponseSchema,
      responseSchemaName: 'HealthResponse',
    })
  },

  async ready(): Promise<ReadyResponse> {
    return openapiRequest({ path: '/api/v1/health/ready', method: 'get' })
  },
}
