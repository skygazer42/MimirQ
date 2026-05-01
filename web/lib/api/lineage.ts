import { apiClient } from '@/lib/api/core'

export type LineageResponse = Record<string, any>

export const lineageApi = {
  async getChunkLineage(chunkId: string): Promise<LineageResponse> {
    const { data } = await apiClient.get(`/lineage/chunk/${chunkId}`)
    return data
  },

  async getAnswerLineage(requestId: string): Promise<LineageResponse> {
    const { data } = await apiClient.get(`/lineage/answer/${requestId}`)
    return data
  },
}
