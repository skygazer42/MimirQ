import type {
  EvidenceRetrieveRequest,
  EvidenceRetrieveResponse,
  PromptPreviewRequest,
  PromptPreviewResponse,
  RetrievePreviewRequest,
  RetrievePreviewResponse,
} from '@/types'

import { apiClient } from '@/lib/api/core'

export interface ClipImageIndexRequest {
  dataset_id: string
  top_k?: number
  max_chunks?: number
  upsert?: boolean
}

export interface ClipImageIndexResponse {
  indexed: number
  skipped: number
  failed: number
  dim: number
  errors: string[]
}

export interface ClipImageSearchRequest {
  dataset_id: string
  query: string
  top_k?: number
  auto_index?: boolean
}

export interface ClipImageSearchResponse {
  citations: any[]
  metrics: Record<string, any>
}

export const ragApi = {
  async retrievePreview(params: RetrievePreviewRequest): Promise<RetrievePreviewResponse> {
    const { data } = await apiClient.post('/rag/retrieve-preview', params)
    return data
  },

  async indexClipImages(params: ClipImageIndexRequest): Promise<ClipImageIndexResponse> {
    const { data } = await apiClient.post('/rag/image-index', params)
    return data
  },

  async searchClipImages(params: ClipImageSearchRequest): Promise<ClipImageSearchResponse> {
    const { data } = await apiClient.post('/rag/image-search-preview', params)
    return data
  },

  async retrieveEvidence(params: EvidenceRetrieveRequest): Promise<EvidenceRetrieveResponse> {
    const { data } = await apiClient.post('/rag/retrieve', params)
    return data
  },

  async promptPreview(params: PromptPreviewRequest): Promise<PromptPreviewResponse> {
    const { data } = await apiClient.post('/rag/prompt-preview', params)
    return data
  },
}
