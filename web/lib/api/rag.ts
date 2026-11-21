import type {
  EvidenceRetrieveRequest,
  EvidenceRetrieveResponse,
  OpenApiSchema,
  PromptPreviewRequest,
  PromptPreviewResponse,
  RetrievePreviewRequest,
  RetrievePreviewResponse,
} from '@/types/backend'
import type {
  RagvizSimilarityCalculateResponse,
  RagvizSimilarityCollectionsResponse,
  RagvizSimilarityRequest,
} from '@/types/evaluation'
import { z } from 'zod'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient, openapiRequest, type ApiRequestOptions } from '@/lib/api/core'

type DocumentStructureInput = OpenApiSchema<'DocumentStructureRequest'>
export type DocumentStructureRequest = Pick<DocumentStructureInput, 'dataset_id' | 'document_id'> &
  Partial<Pick<DocumentStructureInput, 'max_nodes'>>

export type DocumentStructureResponse = Record<string, unknown>

type TreeSearchPreviewInput = OpenApiSchema<'TreeSearchPreviewRequest'>
export type TreeSearchPreviewRequest = Pick<TreeSearchPreviewInput, 'query'> &
  Partial<Omit<TreeSearchPreviewInput, 'query' | 'rag_config'>> & {
    rag_config?: Partial<NonNullable<TreeSearchPreviewInput['rag_config']>>
  }

export type TreeSearchPreviewResponse = Required<OpenApiSchema<'TreeSearchPreviewResponse'>> & {
  schema: 'mimirq.tree_search_preview.v1'
}

export type RagConfigTemplate = OpenApiSchema<'RagConfigTemplateOut'>
type RagConfigTemplateCreateInput = OpenApiSchema<'RagConfigTemplateCreate'>
export type RagConfigTemplateCreate = Pick<RagConfigTemplateCreateInput, 'name'> &
  Partial<Omit<RagConfigTemplateCreateInput, 'name'>>
export type RagConfigTemplateUpdate = OpenApiSchema<'RagConfigTemplateUpdate'>
export type RagConfigTemplateNewVersion = Partial<OpenApiSchema<'RagConfigTemplateNewVersion'>>

const retrievePreviewResponseSchema = z.looseObject({
  query_for_retrieval: z.string(),
  citations: z.array(z.record(z.string(), z.unknown())),
  metrics: z.record(z.string(), z.unknown()).optional(),
}) satisfies z.ZodType<RetrievePreviewResponse>

const evidenceRetrieveResponseSchema = retrievePreviewResponseSchema.extend({
  schema: z.string(),
  metrics: z.record(z.string(), z.unknown()),
  has_evidence: z.boolean(),
  abstain_triggered: z.boolean(),
  abstain_reason: z.string().nullable().optional(),
  retrieval_trace: z.record(z.string(), z.unknown()).nullable().optional(),
  evidence_capsule: z.record(z.string(), z.unknown()).nullable().optional(),
  query_debug: z.record(z.string(), z.unknown()).nullable().optional(),
})

// ChatRAGConfig's server-side defaults also apply to explicitly empty/partial
// request configs. The generated schema marks several defaulted fields required.
export type EvidenceRetrieveInput = Omit<EvidenceRetrieveRequest, 'rag_config'> & {
  rag_config?: Partial<NonNullable<EvidenceRetrieveRequest['rag_config']>>
}

export const ragApi = {
  async retrievePreview(params: RetrievePreviewRequest, options?: ApiRequestOptions): Promise<RetrievePreviewResponse> {
    return openapiRequest({
      path: '/api/v1/rag/retrieve-preview',
      method: 'post',
      body: params,
      signal: options?.signal,
      responseSchema: retrievePreviewResponseSchema,
      responseSchemaName: 'RetrievePreviewResponse',
    })
  },

  async documentStructure(params: DocumentStructureRequest): Promise<DocumentStructureResponse> {
    const { data } = await apiClient.post('/rag/document-structure', params)
    return data
  },

  async treeSearchPreview(params: TreeSearchPreviewRequest): Promise<TreeSearchPreviewResponse> {
    const { data } = await apiClient.post('/rag/tree-search-preview', params)
    return data
  },

  async retrieveEvidence(
    params: EvidenceRetrieveInput,
    options?: ApiRequestOptions,
  ): Promise<EvidenceRetrieveResponse> {
    const data = await openapiRequest({
      path: '/api/v1/rag/retrieve',
      method: 'post',
      body: params as EvidenceRetrieveRequest,
      signal: options?.signal,
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
  }): Promise<OpenApiSchema<'RagConfigTemplateList'>> {
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
