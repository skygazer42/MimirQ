import type {
  EvidenceRetrieveRequest,
  EvidenceRetrieveResponse,
  PromptPreviewRequest,
  PromptPreviewResponse,
  RagvizSimilarityCalculateResponse,
  RagvizSimilarityCollectionsResponse,
  RagvizSimilarityRequest,
  RetrievePreviewRequest,
  RetrievePreviewResponse,
} from '@/types'
import { z } from 'zod'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient, openapiRequest } from '@/lib/api/core'

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

export interface DocumentStructureRequest {
  dataset_id: string
  document_id: string
  max_nodes?: number
}

export type DocumentStructureResponse = Record<string, unknown>

export interface TreeSearchPreviewRequest {
  query: string
  dataset_id?: string | null
  document_ids?: string[]
  rag_config?: Record<string, unknown>
  max_structure_docs?: number
  max_nodes_per_doc?: number
}

export interface TreeSearchPreviewResponse {
  schema: 'mimirq.tree_search_preview.v1'
  query: string
  query_for_retrieval: string
  citations: Array<Record<string, unknown>>
  document_structures: Array<Record<string, unknown>>
  selected_sections: Array<Record<string, unknown>>
  metrics: Record<string, unknown>
}

export interface RagConfigTemplate {
  id: string
  tenant_id: string
  template_key?: string | null
  name: string
  description?: string | null
  config_patch: Record<string, any>
  is_active: boolean
  usage_count: number
  version: number
  parent_id?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight: number
  created_at: string
  updated_at: string
}

export interface RagConfigTemplateCreate {
  template_key?: string
  name: string
  description?: string
  config_patch?: Record<string, any>
  is_active?: boolean
  parent_id?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight?: number
}

export interface RagConfigTemplateUpdate {
  template_key?: string | null
  name?: string
  description?: string | null
  config_patch?: Record<string, any>
  is_active?: boolean
  version?: number
  parent_id?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight?: number
}

export interface RagConfigTemplateNewVersion {
  name?: string
  description?: string | null
  config_patch?: Record<string, any>
  is_active?: boolean
  deactivate_previous?: boolean
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight?: number
}

const evidenceRetrieveResponseSchema = z
  .object({
    query_for_retrieval: z.string(),
    citations: z.array(z.record(z.string(), z.unknown())),
    schema: z.string().default('mimirq.evidence.v1'),
    metrics: z.record(z.string(), z.unknown()).optional(),
    has_evidence: z.boolean().default(false),
    abstain_triggered: z.boolean().default(false),
    abstain_reason: z.string().nullable().optional(),
    retrieval_trace: z.record(z.string(), z.unknown()).nullable().optional(),
    evidence_capsule: z.record(z.string(), z.unknown()).nullable().optional(),
    query_debug: z.record(z.string(), z.unknown()).nullable().optional(),
  })
  .passthrough()

export const ragApi = {
  async retrievePreview(params: RetrievePreviewRequest): Promise<RetrievePreviewResponse> {
    const { data } = await apiClient.post('/rag/retrieve-preview', params)
    return data
  },

  async documentStructure(params: DocumentStructureRequest): Promise<DocumentStructureResponse> {
    const { data } = await apiClient.post('/rag/document-structure', params)
    return data
  },

  async treeSearchPreview(params: TreeSearchPreviewRequest): Promise<TreeSearchPreviewResponse> {
    const { data } = await apiClient.post('/rag/tree-search-preview', params)
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
    const data = await openapiRequest({
      path: '/api/v1/rag/retrieve',
      method: 'post',
      body: params,
      responseSchema: evidenceRetrieveResponseSchema,
      responseSchemaName: 'EvidenceRetrieveResponse',
    })
    return data
  },

  async promptPreview(params: PromptPreviewRequest): Promise<PromptPreviewResponse> {
    const { data } = await apiClient.post('/rag/prompt-preview', params)
    return data
  },
}

export const retrievalApi = {
  async listProfiles(): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get('/retrieval/profiles')
    return data
  },

  async explain(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post('/retrieval/explain', body, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  async configHash(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post('/retrieval/config-hash', body)
    return data
  },
}

export const ragConfigTemplateApi = {
  async create(params: RagConfigTemplateCreate): Promise<RagConfigTemplate> {
    const { data } = await apiClient.post('/rag-config-templates', params)
    return data
  },

  async list(params?: {
    skip?: number
    limit?: number
    template_key?: string
    ab_experiment_key?: string
    is_active?: boolean
  }): Promise<{ total: number; items: RagConfigTemplate[] }> {
    const { data } = await apiClient.get('/rag-config-templates', { params })
    return data
  },

  async get(templateId: string): Promise<RagConfigTemplate> {
    const { data } = await apiClient.get(`/rag-config-templates/${templateId}`)
    return data
  },

  async update(templateId: string, params: RagConfigTemplateUpdate): Promise<RagConfigTemplate> {
    const { data } = await apiClient.patch(`/rag-config-templates/${templateId}`, params)
    return data
  },

  async createVersion(templateId: string, params: RagConfigTemplateNewVersion): Promise<RagConfigTemplate> {
    const { data } = await apiClient.post(`/rag-config-templates/${templateId}/versions`, params)
    return data
  },
}

export const ragvizApi = {
  async listSimilarityCollections(): Promise<RagvizSimilarityCollectionsResponse> {
    const { data } = await apiClient.get('/ragviz/similarity/collections')
    return data
  },

  async calculateSimilarityMatrix(params: RagvizSimilarityRequest): Promise<RagvizSimilarityCalculateResponse> {
    const { data } = await apiClient.post('/ragviz/similarity/calculate', params)
    return data
  },
}
