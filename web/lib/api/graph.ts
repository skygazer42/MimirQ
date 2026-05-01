import type {
  KGDeleteResponse,
  KGEntityAliasCreateRequest,
  KGEntityAliasItem,
  KGEntityAliasesResponse,
  KGEntityAliasSuggestionsResponse,
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
  KGPredicateOntologyCreateRequest,
  KGPredicateOntologyItem,
  KGPredicateOntologyListResponse,
  KGPredicateOntologyUpdateRequest,
  KGSearchRequest,
  KGSearchResponse,
  KGStatsResponse,
} from '@/types'

import { apiClient } from '@/lib/api/core'

export type KGNetworkEdge = {
  source: string
  target: string
  weight?: number
}

export type KGNetworkRequest = {
  edges: KGNetworkEdge[]
  start_id?: string
  target_id?: string
  max_hops?: number
  top_k?: number
  algorithm?: 'degree' | 'pagerank'
  node_id?: string
}

export type KGNetworkResponse = Record<string, any>

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
    }
  ): Promise<KGExtractResponse> {
    const { data } = await apiClient.post(`/kg/documents/${documentId}/extract`, null, { params })
    return data
  },

  async deleteDocumentKG(
    documentId: string,
    params?: { prune_orphan_entities?: boolean }
  ): Promise<KGDeleteResponse> {
    const { data } = await apiClient.delete(`/kg/documents/${documentId}`, { params })
    return data
  },

  async search(params: KGSearchRequest): Promise<KGSearchResponse> {
    const { data } = await apiClient.post('/kg/search', params)
    return data
  },

  async getStats(params?: { document_ids?: string[]; pipeline_hash?: string }): Promise<KGStatsResponse> {
    const { data } = await apiClient.get('/kg/stats', { params })
    return data
  },

  async getGraph(params?: {
    document_ids?: string[]
    pipeline_hash?: string
    max_events?: number
    max_entities?: number
    max_links?: number
    include_entity_links?: boolean
    include_relation_links?: boolean
    min_shared_events?: number
    max_entity_links?: number
  }): Promise<KGGraphResponse> {
    const { data } = await apiClient.get('/kg/graph', { params })
    return data
  },

  async expandGraph(params: {
    node_id: string
    document_ids?: string[]
    pipeline_hash?: string
    max_events?: number
    max_entities?: number
    max_links?: number
    include_entity_links?: boolean
    include_relation_links?: boolean
    min_shared_events?: number
    max_entity_links?: number
  }): Promise<KGGraphResponse> {
    const { data } = await apiClient.get('/kg/graph/expand', { params })
    return data
  },

  async exportGraphML(params?: {
    document_ids?: string[]
    pipeline_hash?: string
    max_events?: number
    max_entities?: number
    max_links?: number
    include_entity_links?: boolean
    include_relation_links?: boolean
    min_shared_events?: number
    max_entity_links?: number
  }): Promise<string> {
    const { data } = await apiClient.get('/kg/graph/export', {
      params,
      responseType: 'text',
    })
    return data as unknown as string
  },

  async getKHopNeighbors(body: KGNetworkRequest): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/k_hop_neighbors', body)
    return data
  },

  async getShortestPath(body: KGNetworkRequest): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/shortest_path', body)
    return data
  },

  async getPathsBetween(body: KGNetworkRequest): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/paths_between', body)
    return data
  },

  async getCentrality(body: KGNetworkRequest): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/centrality', body)
    return data
  },

  async getCommunityOf(body: KGNetworkRequest): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/community_of', body)
    return data
  },

  async getConnectedComponent(body: KGNetworkRequest): Promise<KGNetworkResponse> {
    const { data } = await apiClient.post('/kg/network/connected_component', body)
    return data
  },

  async exportSnapshot(params: { pipeline_hash: string; document_ids?: string[]; include_details?: boolean }): Promise<any> {
    const { data } = await apiClient.get('/kg/snapshots/export', { params })
    return data
  },

  async diffSnapshots(body: { snapshot_a: Record<string, any>; snapshot_b: Record<string, any> }): Promise<any> {
    const { data } = await apiClient.post('/kg/snapshots/diff', body)
    return data
  },

  async compareSnapshots(params: {
    pipeline_hash_a: string
    pipeline_hash_b: string
    document_ids?: string[]
  }): Promise<any> {
    const { data } = await apiClient.get('/kg/snapshots/compare', { params })
    return data
  },

  async getEvent(
    eventId: string,
    params?: { document_ids?: string[]; pipeline_hash?: string }
  ): Promise<KGEventDetailResponse> {
    const { data } = await apiClient.get(`/kg/events/${eventId}`, { params })
    return data
  },

  async getEntity(
    entityId: string,
    params?: { document_ids?: string[]; pipeline_hash?: string; max_events?: number; max_neighbors?: number }
  ): Promise<KGEntityDetailResponse> {
    const { data } = await apiClient.get(`/kg/entities/${entityId}`, { params })
    return data
  },

  async listEntityAliases(entityId: string): Promise<KGEntityAliasesResponse> {
    const { data } = await apiClient.get(`/kg/entities/${entityId}/aliases`)
    return data
  },

  async createEntityAlias(entityId: string, body: KGEntityAliasCreateRequest): Promise<KGEntityAliasItem> {
    const { data } = await apiClient.post(`/kg/entities/${entityId}/aliases`, body)
    return data
  },

  async deleteEntityAlias(entityId: string, aliasId: string): Promise<KGEntityAliasesResponse> {
    const { data } = await apiClient.delete(`/kg/entities/${entityId}/aliases/${aliasId}`)
    return data
  },

  async suggestEntityAliases(
    entityId: string,
    params?: { mode?: string; k?: number; min_similarity?: number }
  ): Promise<KGEntityAliasSuggestionsResponse> {
    const { data } = await apiClient.get(`/kg/entities/${entityId}/alias_suggestions`, { params })
    return data
  },

  async listPredicateOntology(): Promise<KGPredicateOntologyListResponse> {
    const { data } = await apiClient.get('/kg/ontology/predicates')
    return data
  },

  async upsertPredicateOntology(body: KGPredicateOntologyCreateRequest): Promise<KGPredicateOntologyItem> {
    const { data } = await apiClient.post('/kg/ontology/predicates', body)
    return data
  },

  async updatePredicateOntology(
    predicateId: string,
    body: KGPredicateOntologyUpdateRequest
  ): Promise<KGPredicateOntologyItem> {
    const { data } = await apiClient.patch(`/kg/ontology/predicates/${predicateId}`, body)
    return data
  },

  async deletePredicateOntology(predicateId: string): Promise<KGPredicateOntologyListResponse> {
    const { data } = await apiClient.delete(`/kg/ontology/predicates/${predicateId}`)
    return data
  },

  async previewMergeEntities(body: KGEntityMergeRequest): Promise<KGEntityMergePreviewResponse> {
    const { data } = await apiClient.post('/kg/entities/merge/preview', body)
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
    const { data } = await apiClient.post(`/kg/entities/resolution/actions/${actionId}/undo`)
    return data
  },

  async searchGraphNodes(params: {
    q: string
    kind?: string
    limit?: number
    document_ids?: string[]
    pipeline_hash?: string
  }): Promise<KGGraphNode[]> {
    const { data } = await apiClient.get('/kg/graph/search', { params })
    return data
  },
}
