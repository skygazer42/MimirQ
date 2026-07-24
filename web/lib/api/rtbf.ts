import type { OpenApiSchema } from '@/types/backend'

import { apiClient } from '@/lib/api/core'

export type RtbfRequest = OpenApiSchema<'RTBFRequest'>

export type RtbfCascadeResponse = Record<string, unknown>

export type RtbfStatusResponse = OpenApiSchema<'RTBFStatusResponse'>

export const rtbfApi = {
  async request(body: RtbfRequest): Promise<RtbfCascadeResponse> {
    const { data } = await apiClient.post('/rtbf/request', body)
    return data
  },

  async getStatus(ticketId: string): Promise<RtbfStatusResponse> {
    const { data } = await apiClient.get(`/rtbf/status/${ticketId}`)
    return data
  },
}
