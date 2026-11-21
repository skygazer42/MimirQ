import { z } from 'zod'

import { apiClient } from '@/lib/api/core'
import { integerSchema } from '@/lib/response-schema'
import { parseApiResponse } from '@/lib/openapi-request'
import type { OpenApiSchema } from '@/types/backend'

export type RtbfRequest = OpenApiSchema<'RTBFRequest'>

const rtbfCascadeSchema = z.looseObject({
  schema: z.literal('mimirq.rtbf_cascade.v1'),
  subject_account_id: z.string(),
  dry_run: z.boolean(),
  eligible: integerSchema.nonnegative(),
  deleted: integerSchema.nonnegative(),
  errors: integerSchema.nonnegative(),
  cache_invalidations: integerSchema.nonnegative(),
})

export type RtbfCascadeResponse = z.infer<typeof rtbfCascadeSchema>

export const rtbfApi = {
  async request(body: RtbfRequest): Promise<RtbfCascadeResponse> {
    const response = await apiClient.post<unknown>('/rtbf/request', body)
    const result = parseApiResponse(response, rtbfCascadeSchema, 'RtbfCascadeResponse')
    if (result.subject_account_id !== body.subject_account_id.trim() || result.dry_run !== body.dry_run) {
      throw new Error('无法确认本次清理结果，返回的目标账号或执行模式与请求不一致。')
    }
    return result
  },
}
