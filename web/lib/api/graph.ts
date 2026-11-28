import type {
  KGDeleteResponse,
  KGEntityAliasCreateRequest,
  KGEntityAliasItem,
  KGEntityAliasSuggestionsResponse,
  KGEntityAliasesResponse,
  KGEntityDetailResponse,
  KGEntityMergePreviewResponse,
  KGEntityMergeRequest,
  KGEntityMergeResponse,
  KGEntityResolutionUndoResponse,
  KGEntitySplitRequest,
  KGEntitySplitResponse,
  KGEventDetailResponse,
  KGExtractResponse,
  KGGraphNode,
  KGGraphResponse,
  KGManualImportDeleteResponse,
  KGManualImportListResponse,
  KGManualImportPreviewResponse,
  KGManualImportResponse,
  KGPredicateOntologyCreateRequest,
  KGPredicateOntologyItem,
  KGPredicateOntologyListResponse,
  KGPredicateOntologyUpdateRequest,
  KGSearchRequest,
  KGSearchResponse,
  KGStatsResponse,
} from '@/types/knowledge-graph'
import type { OpenApiSchema } from '@/types/backend'
import type { OpenApiQueryParams } from '@/types/openapi-helpers'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'

type NetworkEdgeInput = OpenApiSchema<'EdgeIn'>
export type KGNetworkEdge = Pick<NetworkEdgeInput, 'source' | 'target'> & Partial<Pick<NetworkEdgeInput, 'weight'>>

export type KGNetworkRequest = Partial<Omit<OpenApiSchema<'GraphRequest'>, 'edges'>> & {
  edges: KGNetworkEdge[]
}

export type KGNetworkResponse = Record<string, unknown>
type KGSnapshotExportResponse = Record<string, unknown>
type KGSnapshotDiffResponse = Record<string, unknown>
type KGSnapshotCompareResponse = Record<string, unknown>
type KGGraphQuery = NonNullable<OpenApiQueryParams<'/api/v1/kg/graph', 'get'>>

export const kgApi = {
  async extract(
    documentId: string,
    params?: {
      async?: boolean
      pipeline_hash?: string
      replace_existing?: boolean
      prune_orphan_entities?: boolean
      prompt_template_id?: string
      prompt_template_key?: string
      prompt_ab_experiment_key?: string
    },
  ): Promise<KGExtractResponse & { queued: boolean }> {
    const { data, status } = await apiClient.post<KGExtractResponse>(
      `/kg/documents/${encodeURIComponent(documentId)}/extract`,
      null,
      { params, headers: { Prefer: 'respond-async' } },
    )
    return { ...data, queued: status === 202 }
  },

  async deleteDocumentKG(documentId: string, params?: { prune_orphan_entities?: boolean }): Promise<KGDeleteResponse> {
    const { data } = await apiClient.delete(`/kg/documents/${encodeURIComponent(documentId)}`, { params })
    return data
  },

  async previewManualImport(
    body: Record<string, unknown>,
    options?: ApiRequestOptions,
  ): Promise<KGManualImportPreviewResponse> {
    const { data } = await apiClient.post('/kg/imports/preview', body, { signal: options?.signal })
    return data
  },

  async importManualGraph(body: Record<string, unknown>): Promise<KGManualImportResponse> {
    const { data } = await apiClient.post('/kg/imports', body)
    return data
  },

  async listManualImports(params?: { limit?: number }): Promise<KGManualImportListResponse> {
    const { data } = await apiClient.get('/kg/imports', { params })
    return data
  },

  async deleteManualImport(
    importId: string,
    params?: { prune_entities?: boolean },
  ): Promise<KGManualImportDeleteResponse> {
    const { data } = await apiClient.delete(`/kg/imports/${encodeURIComponent(importId)}`, { params })
    return data
  },

  async search(params: KGSearchRequest): Promise<KGSearchResponse> {
    const { data } = await apiClient.post('/kg/search', params)
    return data
  },

  async getStats(params?: {
    document_ids?: string[]
    dataset_id?: string
    pipeline_hash?: string
  }): Promise<KGStatsResponse> {
    const { data } = await apiClient.get('/kg/stats', { params })
    return data
  },

  async getGraph(params?: KGGraphQuery, options?: ApiRequestOptions): Promise<KGGraphResponse> {
    const { data } = await apiClient.get<KGGraphResponse>('/kg/graph', { params, signal: options?.signal })
    return data
  },

  async expandGraph(params: KGGraphQuery & { node_id: string }, options?: ApiRequestOptions): Promise<KGGraphResponse> {
    const { data } = await apiClient.get<KGGraphResponse>('/kg/graph/expand', { params, signal: options?.signal })
    return data
  },

  async exportGraphML(params?: KGGraphQuery, options?: ApiRequestOptions): Promise<string> {
    const { data, headers } = await apiClient.get<string>('/kg/graph/export', {
      params,
      responseType: 'text',
      signal: options?.signal,
    })
    const contentType = headers['content-type']
    if (
      typeof contentType !== 'string' ||
      contentType.split(';', 1)[0].trim().toLowerCase() !== 'application/graphml+xml'
    ) {
      throw new Error('GraphML 响应格式不正确')
    }
    return data
  },

  async getKHopNeighbors(body: KGNetworkRequest, options?: ApiRequestOptions): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/k_hop_neighbors', body, { signal: options?.signal })
    return data
  },

  async getShortestPath(body: KGNetworkRequest, options?: ApiRequestOptions): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/shortest_path', body, { signal: options?.signal })
    return data
  },

  async getPathsBetween(body: KGNetworkRequest, options?: ApiRequestOptions): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/paths_between', body, { signal: options?.signal })
    return data
  },

  async getCentrality(body: KGNetworkRequest, options?: ApiRequestOptions): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/centrality', body, { signal: options?.signal })
    return data
  },

  async getCommunityOf(body: KGNetworkRequest, options?: ApiRequestOptions): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/community_of', body, { signal: options?.signal })
    return data
  },

  async getConnectedComponent(body: KGNetworkRequest, options?: ApiRequestOptions): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/connected_component', body, { signal: options?.signal })
    return data
  },

  async exportSnapshot(
    params: { pipeline_hash: string; document_ids?: string[]; dataset_id?: string; include_details?: boolean },
    options?: ApiRequestOptions,
  ): Promise<KGSnapshotExportResponse> {
    const { data } = await apiClient.get('/kg/snapshots/export', { params, signal: options?.signal })
    return data
  },

  async diffSnapshots(
    body: { snapshot_a: Record<string, unknown>; snapshot_b: Record<string, unknown> },
    options?: ApiRequestOptions,
  ): Promise<KGSnapshotDiffResponse> {
    const { data } = await apiClient.post('/kg/snapshots/diff', body, { signal: options?.signal })
    return data
  },

  async compareSnapshots(
    params: { pipeline_hash_a: string; pipeline_hash_b: string; document_ids?: string[]; dataset_id?: string },
    options?: ApiRequestOptions,
  ): Promise<KGSnapshotCompareResponse> {
    const { data } = await apiClient.get('/kg/snapshots/compare', { params, signal: options?.signal })
    return data
  },

  async getEvent(
    eventId: string,
    params?: { document_ids?: string[]; dataset_id?: string; pipeline_hash?: string },
    options?: ApiRequestOptions,
  ): Promise<KGEventDetailResponse> {
    const { data } = await apiClient.get(`/kg/events/${encodeURIComponent(eventId)}`, {
      params,
      signal: options?.signal,
    })
    return data
  },

  async getEntity(
    entityId: string,
    params?: {
      document_ids?: string[]
      dataset_id?: string
      pipeline_hash?: string
      max_events?: number
      max_neighbors?: number
    },
    options?: ApiRequestOptions,
  ): Promise<KGEntityDetailResponse> {
    const { data } = await apiClient.get(`/kg/entities/${encodeURIComponent(entityId)}`, {
      params,
      signal: options?.signal,
    })
    return data
  },

  async listEntityAliases(entityId: string, options: ApiRequestOptions = {}): Promise<KGEntityAliasesResponse> {
    const { data } = await apiClient.get<KGEntityAliasesResponse>(
      `/kg/entities/${encodeURIComponent(entityId)}/aliases`,
      {
        signal: options.signal,
      },
    )
    return data
  },

  async createEntityAlias(entityId: string, body: KGEntityAliasCreateRequest): Promise<KGEntityAliasItem> {
    const { data } = await apiClient.post(`/kg/entities/${encodeURIComponent(entityId)}/aliases`, body)
    return data
  },

  async deleteEntityAlias(entityId: string, aliasId: string): Promise<KGEntityAliasesResponse> {
    const { data } = await apiClient.delete(
      `/kg/entities/${encodeURIComponent(entityId)}/aliases/${encodeURIComponent(aliasId)}`,
    )
    return data
  },

  async suggestEntityAliases(
    entityId: string,
    params?: { mode?: string; k?: number; min_similarity?: number },
    options: ApiRequestOptions = {},
  ): Promise<KGEntityAliasSuggestionsResponse> {
    const { data } = await apiClient.get<KGEntityAliasSuggestionsResponse>(
      `/kg/entities/${encodeURIComponent(entityId)}/alias_suggestions`,
      {
        params,
        signal: options.signal,
      },
    )
    return data
  },

  async listPredicateOntology(options?: ApiRequestOptions): Promise<KGPredicateOntologyListResponse> {
    const { data } = await apiClient.get('/kg/ontology/predicates', { signal: options?.signal })
    return data
  },

  async upsertPredicateOntology(body: KGPredicateOntologyCreateRequest): Promise<KGPredicateOntologyItem> {
    const { data } = await apiClient.post('/kg/ontology/predicates', body)
    return data
  },

  async updatePredicateOntology(
    predicateId: string,
    body: KGPredicateOntologyUpdateRequest,
  ): Promise<KGPredicateOntologyItem> {
    const { data } = await apiClient.patch(`/kg/ontology/predicates/${encodeURIComponent(predicateId)}`, body)
    return data
  },

  async deletePredicateOntology(predicateId: string): Promise<KGPredicateOntologyListResponse> {
    const { data } = await apiClient.delete(`/kg/ontology/predicates/${encodeURIComponent(predicateId)}`)
    return data
  },

  async previewMergeEntities(
    body: KGEntityMergeRequest,
    options: ApiRequestOptions = {},
  ): Promise<KGEntityMergePreviewResponse> {
    const { data } = await apiClient.post<KGEntityMergePreviewResponse>('/kg/entities/merge/preview', body, {
      signal: options.signal,
    })
    return data
  },

  async mergeEntities(body: KGEntityMergeRequest): Promise<KGEntityMergeResponse> {
    const { data } = await apiClient.post('/kg/entities/merge', body)
    return data
  },

  async splitEntity(body: KGEntitySplitRequest): Promise<KGEntitySplitResponse> {
    const { data } = await apiClient.post('/kg/entities/split', body)
    return data
  },

  async undoResolutionAction(actionId: string): Promise<KGEntityResolutionUndoResponse> {
    const { data } = await apiClient.post(`/kg/entities/resolution/actions/${encodeURIComponent(actionId)}/undo`)
    return data
  },

  async searchGraphNodes(
    params: { q: string; kind?: string; limit?: number; document_ids?: string[]; pipeline_hash?: string },
    options?: ApiRequestOptions,
  ): Promise<KGGraphNode[]> {
    const { data } = await apiClient.get<KGGraphNode[]>('/kg/graph/search', { params, signal: options?.signal })
    return data
  },
}
