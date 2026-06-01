import { apiClient } from '@/lib/api/core'

export type LineageResponse = Record<string, unknown>

export const lineageApi = {
  async getChunkLineage(chunkId: string): Promise<LineageResponse> {
    const { data } = await apiClient.get(`/lineage/chunk/${chunkId}`)
    return data
  },

  async getAnswerLineage(requestId: string): Promise<LineageResponse> {
    const { data } = await apiClient.get(`/lineage/answer/${requestId}`)
    return data
  },

  async getAnswerLineageIfAvailable(requestId: string): Promise<LineageResponse | null> {
    const response = await apiClient.get(`/lineage/answer/${requestId}`, {
      validateStatus: (status) => (status >= 200 && status < 300) || status === 404,
    })
    if (response.status === 404) return null
    return response.data
  },
}
