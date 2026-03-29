/**
 * Knowledge graph and retrieval debugging types re-exported by `@/types`.
 */

import type { JsonObject } from './common'

// ==================== KG 相关类型 ====================

export interface KGExtractResponse {
  document_id: string
  chunk_count: number
  event_count: number
  message: string
}

export interface KGSearchRequest {
  query: string
  tenant_id?: string
  document_ids?: string[]
}

export interface KGSearchResponse {
  result: JsonObject
  query: string
}

export interface KGGraphNode {
  id: string
  label: string
  group?: number
  val?: number
  meta?: JsonObject
}

export interface KGGraphLink {
  source: string
  target: string
  label?: string
  weight?: number
  meta?: JsonObject
}

export interface KGGraphResponse {
  nodes: KGGraphNode[]
  links: KGGraphLink[]
  stats?: JsonObject
}

export interface KGEntityItem {
  id: string
  name: string
  type: string
  normalized_name: string
  description?: string | null
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export interface KGEventItem {
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

export interface KGEventEntityItem {
  entity: KGEntityItem
  weight?: number
  role?: string | null
}

export interface KGEventDetailResponse {
  event: KGEventItem
  entities: KGEventEntityItem[]
}

export interface KGEntityNeighbor {
  entity_id: string
  name: string
  type: string
  count: number
}

export interface KGEntityDetailResponse {
  entity: KGEntityItem
  events: KGEventItem[]
  neighbors: KGEntityNeighbor[]
  stats?: JsonObject
}

export interface KGEntityTypeCount {
  type: string
  count: number
}

export interface KGStatsResponse {
  events: number
  entities: number
  links: number
  entity_types: KGEntityTypeCount[]
  updated_at?: string | null
}

export interface KGDeleteResponse {
  document_id: string
  events_deleted: number
  entities_pruned: number
}

export interface KGEntityMergeRequest {
  source_entity_id: string
  target_entity_id: string
}

export interface KGEntityMergePreviewResponse {
  source_entity_id: string
  target_entity_id: string
  stats?: JsonObject
}

export interface KGEntityMergeResponse {
  action_id: string
  source_entity_id: string
  target_entity_id: string
  stats?: JsonObject
}

export interface KGEntityResolutionUndoResponse {
  action_id: string
  status: string
  stats?: JsonObject
}

export interface KGEntitySplitRequest {
  entity_id: string
  new_entity_name: string
  event_ids: string[]
}

export interface KGEntitySplitResponse {
  action_id: string
  original_entity_id: string
  new_entity_id: string
  stats?: JsonObject
}

export interface KGEntityAliasCreateRequest {
  alias: string
}

export interface KGEntityAliasItem {
  id: string
  canonical_entity_id: string
  alias: string
  normalized_alias: string
  created_by?: string | null
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export interface KGEntityAliasesResponse {
  entity_id: string
  resolved_entity_id: string
  aliases: KGEntityAliasItem[]
}

export interface KGEntityAliasSuggestionItem {
  entity_id: string
  name: string
  type: string
  similarity: number
  reason?: string
}

export interface KGEntityAliasSuggestionsResponse {
  entity_id: string
  suggestions: KGEntityAliasSuggestionItem[]
  mode?: string
  stats?: JsonObject
}

export interface KGPredicateOntologyItem {
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

export interface KGPredicateOntologyCreateRequest {
  predicate: string
  display_name?: string | null
  description?: string | null
  is_enabled?: boolean
}

export interface KGPredicateOntologyUpdateRequest {
  display_name?: string | null
  description?: string | null
  is_enabled?: boolean | null
}

export interface KGPredicateOntologyListResponse {
  predicates: KGPredicateOntologyItem[]
}

// ==================== RAG 调试相关类型 ====================

export type RetrievePreviewRequest = import('./backend').RetrievePreviewRequest
export type RetrievePreviewResponse = import('./backend').RetrievePreviewResponse
export type EvidenceRetrieveRequest = import('./backend').EvidenceRetrieveRequest
export type EvidenceRetrieveResponse = import('./backend').EvidenceRetrieveResponse
export type PromptPreviewRequest = import('./backend').PromptPreviewRequest
export type PromptPreviewResponse = import('./backend').PromptPreviewResponse
