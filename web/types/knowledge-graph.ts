/**
 * Knowledge graph and retrieval debugging types re-exported by `@/types`.
 */

import type { JsonObject } from './common'

// ==================== KG 相关类型 ====================

export type KGExtractResponse = {
  document_id: string
  chunk_count: number
  event_count: number
  message: string
}

export type KGSearchRequest = {
  query: string
  tenant_id?: string
  document_ids?: string[]
}

export type KGSearchResponse = {
  result: JsonObject
  query: string
}

export type KGGraphNode = {
  id: string
  label: string
  group?: number
  val?: number
  meta?: JsonObject
}

export type KGGraphLink = {
  source: string
  target: string
  label?: string
  weight?: number
  meta?: JsonObject
}

export type KGGraphResponse = {
  nodes: KGGraphNode[]
  links: KGGraphLink[]
  stats?: JsonObject
}

export type KGEntityItem = {
  id: string
  name: string
  type: string
  normalized_name: string
  description?: string | null
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export type KGEventItem = {
  id: string
  title: string
  summary: string
  content: string
  document_id?: string | null
  chunk_id?: string | null
  references?: JsonObject
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export type KGEventEntityItem = {
  entity: KGEntityItem
  weight?: number
  role?: string | null
}

export type KGEventDetailResponse = {
  event: KGEventItem
  entities: KGEventEntityItem[]
}

export type KGEntityNeighbor = {
  entity_id: string
  name: string
  type: string
  count: number
}

export type KGEntityDetailResponse = {
  entity: KGEntityItem
  events: KGEventItem[]
  neighbors: KGEntityNeighbor[]
  stats?: JsonObject
}

export type KGEntityTypeCount = {
  type: string
  count: number
}

export type KGStatsResponse = {
  events: number
  entities: number
  links: number
  entity_types: KGEntityTypeCount[]
  updated_at?: string | null
}

export type KGDeleteResponse = {
  document_id: string
  events_deleted: number
  entities_pruned: number
}

export type KGManualEntityInput = {
  key?: string | null
  name: string
  type: string
  description?: string | null
  aliases?: string[]
  extra_data?: JsonObject
}

export type KGManualEntityRef =
  | string
  | {
      key?: string | null
      name?: string | null
      type?: string | null
    }

export type KGManualRelationInput = {
  subject: KGManualEntityRef
  predicate: string
  object: KGManualEntityRef
  confidence?: number
  evidence?: string | null
  source?: string | null
  qualifiers?: JsonObject
  references?: JsonObject
  extra_data?: JsonObject
}

export type KGManualImportRequest = {
  name?: string
  import_id?: string | null
  dataset_id?: string | null
  dataset_name?: string | null
  pipeline_hash?: string | null
  replace_existing?: boolean
  upsert_entities?: boolean
  allow_label_truncation?: boolean
  index_vectors?: boolean
  entities: KGManualEntityInput[]
  relations?: KGManualRelationInput[]
}

export type KGManualImportStats = {
  entities: number
  relations: number
  events: number
  chunks: number
  aliases: number
  warnings: number
}

export type KGManualImportIssue = {
  level: string
  message: string
  row?: number | null
  field?: string | null
}

export type KGManualImportPreviewResponse = {
  import_id: string
  pipeline_hash: string
  name: string
  valid: boolean
  stats: KGManualImportStats
  issues: KGManualImportIssue[]
}

export type KGManualImportResponse = KGManualImportPreviewResponse & {
  dataset_id?: string | null
  document_id?: string | null
  inserted?: JsonObject
  vector_index?: JsonObject
  message: string
}

export type KGManualImportListItem = {
  import_id: string
  name: string
  pipeline_hash: string
  dataset_id?: string | null
  document_id: string
  stats?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export type KGManualImportListResponse = {
  items: KGManualImportListItem[]
}

export type KGManualImportDeleteResponse = {
  import_id: string
  document_id: string
  events_deleted: number
  relations_deleted: number
  chunks_deleted: number
  entities_pruned: number
  message: string
}

export type KGEntityMergeRequest = {
  source_entity_id: string
  target_entity_id: string
}

export type KGEntityMergePreviewResponse = {
  source_entity_id: string
  target_entity_id: string
  stats?: JsonObject
}

export type KGEntityMergeResponse = {
  action_id: string
  source_entity_id: string
  target_entity_id: string
  stats?: JsonObject
}

export type KGEntityResolutionUndoResponse = {
  action_id: string
  status: string
  stats?: JsonObject
}

export type KGEntitySplitRequest = {
  entity_id: string
  new_entity_name: string
  event_ids: string[]
}

export type KGEntitySplitResponse = {
  action_id: string
  original_entity_id: string
  new_entity_id: string
  stats?: JsonObject
}

export type KGEntityAliasCreateRequest = {
  alias: string
}

export type KGEntityAliasItem = {
  id: string
  canonical_entity_id: string
  alias: string
  normalized_alias: string
  created_by?: string | null
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export type KGEntityAliasesResponse = {
  entity_id: string
  resolved_entity_id: string
  aliases: KGEntityAliasItem[]
}

export type KGEntityAliasSuggestionItem = {
  entity_id: string
  name: string
  type: string
  similarity: number
  reason?: string
}

export type KGEntityAliasSuggestionsResponse = {
  entity_id: string
  suggestions: KGEntityAliasSuggestionItem[]
  mode?: string
  stats?: JsonObject
}

export type KGPredicateOntologyItem = {
  id: string
  tenant_id: string
  predicate: string
  display_name?: string | null
  description?: string | null
  is_enabled: boolean
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export type KGPredicateOntologyCreateRequest = {
  predicate: string
  display_name?: string | null
  description?: string | null
  is_enabled?: boolean
}

export type KGPredicateOntologyUpdateRequest = {
  display_name?: string | null
  description?: string | null
  is_enabled?: boolean | null
}

export type KGPredicateOntologyListResponse = {
  predicates: KGPredicateOntologyItem[]
}

// ==================== RAG 调试相关类型 ====================

export type RetrievePreviewRequest = import('./backend').RetrievePreviewRequest
export type RetrievePreviewResponse = import('./backend').RetrievePreviewResponse
export type EvidenceRetrieveRequest = import('./backend').EvidenceRetrieveRequest
export type EvidenceRetrieveResponse = import('./backend').EvidenceRetrieveResponse
export type PromptPreviewRequest = import('./backend').PromptPreviewRequest
export type PromptPreviewResponse = import('./backend').PromptPreviewResponse
