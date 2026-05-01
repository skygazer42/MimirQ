import { apiClient } from '@/lib/api/core'

export type RtbfRequest = {
  subject_account_id: string
  dry_run?: boolean
  max_docs?: number
  max_retries?: number
}

export type RtbfCascadeResponse = Record<string, any>

export type RtbfStatusResponse = {
  ticket_id: string
  status: string
  note: string
}

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
