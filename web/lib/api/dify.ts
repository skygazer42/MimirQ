import { apiClient } from './core'

export interface DifyRetrievalSetting {
  top_k?: number
  score_threshold?: number
}

export interface DifyExternalKnowledgeRequest {
  knowledge_id: string
  query: string
  retrieval_setting?: DifyRetrievalSetting
  metadata_condition?: Record<string, unknown> | null
}

export interface DifyExternalKnowledgeRecord {
  content: string
  score: number
  title: string
  metadata: Record<string, unknown>
}

export interface DifyExternalKnowledgeResponse {
  records: DifyExternalKnowledgeRecord[]
}

export const difyExternalKnowledgeApi = {
  async retrieve(
    payload: DifyExternalKnowledgeRequest
  ): Promise<DifyExternalKnowledgeResponse> {
    const { data } = await apiClient.post('/integrations/dify/retrieval', payload)
    return data
  },
}
