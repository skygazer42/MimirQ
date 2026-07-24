import type { OpenApiSchema } from '@/types/backend'

import { apiClient } from './core'

export type DifyRetrievalSetting = OpenApiSchema<'DifyRetrievalSetting'>
export type DifyExternalKnowledgeRequest = OpenApiSchema<'DifyExternalKnowledgeRequest'>
export type DifyExternalKnowledgeRecord = OpenApiSchema<'DifyExternalKnowledgeRecord'>
export type DifyExternalKnowledgeResponse = OpenApiSchema<'DifyExternalKnowledgeResponse'>

export const difyExternalKnowledgeApi = {
  async retrieve(
    payload: DifyExternalKnowledgeRequest
  ): Promise<DifyExternalKnowledgeResponse> {
    const { data } = await apiClient.post('/integrations/dify/retrieval', payload)
    return data
  },
}
