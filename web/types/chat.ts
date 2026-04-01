/**
 * Chat, feedback, quota, auth, and audit types re-exported by `@/types`.
 */

import type { JsonObject, LooseString } from './common'
import type { Citation } from './processing'

// ==================== 对话相关类型 ====================

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  steps?: string[]
  message_metadata?: Record<string, unknown> | null
  created_at: string
}

export interface Conversation {
  id: string
  title?: string
  last_message?: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ConversationListResponse {
  total: number
  returned?: number
  has_more?: boolean
  items: Conversation[]
}

export interface ConversationDetail {
  conversation_id: string
  returned?: number
  has_more?: boolean
  messages: Message[]
}

// ==================== RAG Trace (Visualization) ====================

export interface RagTraceStep {
  key: string
  label: string
  elapsed_sec?: number | null
  meta?: Record<string, unknown>
}

export interface RagTraceCitation {
  document_id?: string | null
  chunk_id?: string | null
  chunk_index?: number | null
  page_number?: number | null
  start_char?: number | null
  end_char?: number | null

  retrieval_role?: string | null
  neighbor_of?: string | null

  doc_pipeline_key?: string | null
  pipeline_hash?: string | null

  relevance_score?: number | null
  vector_score?: number | null
  bm25_score?: number | null
  lexical_score?: number | null
  sparse_score?: number | null
  colbert_score?: number | null
  keyword_score?: number | null
  rerank_score?: number | null
  retrieval_score?: number | null

  reranker_provider?: string | null
  rerank_elapsed_sec?: number | null
  rerank_model_used?: string | null

  retrieval_mode?: string | null
  vector_backend?: string | null
  retrieval_elapsed_sec?: number | null
  hit_type?: string | null

  has_image?: boolean

  kg_path?: Array<{ entity_id: string; type?: string }> | null
  kg_path_provenance?: Record<string, unknown> | null
}

export interface RagTraceRetrievalQuery {
  kind?: string | null
  query_chars?: number | null
  elapsed_sec?: number | null
  ok?: boolean | null
  retriever_debug?: JsonObject | null
}

export interface RagTraceRetrieval {
  mode?: string | null
  requested_mode?: string | null
  auto_routed?: boolean | null

  retrieval_config_hash?: string | null

  top_k?: number | null
  query_parallelism?: number | null
  query_count?: number | null

  per_query?: RagTraceRetrievalQuery[]
  errors?: string[]

  enable_reranker?: boolean | null
  reranker_provider?: string | null
  reranker_top_n?: number | null

  elapsed_sec?: number | null
}

export interface RagTraceRerank {
  enabled: boolean
  provider?: string | null
  top_n?: number | null
  elapsed_sec?: number | null
  model_used?: string | null
}

export interface RagTrace {
  schema_version: number
  ts_ms: number
  request_id?: string | null
  conversation_id?: string | null
  retrieval: RagTraceRetrieval
  rerank: RagTraceRerank
  citations: RagTraceCitation[]
  citations_count: number
  steps: RagTraceStep[]
}

export interface RagTraceListResponse {
  enabled: boolean
  path: string
  window_minutes: number
  truncated: boolean
  returned: number
  items: RagTrace[]
}

export interface StreamEvent {
  type: 'citations' | 'token' | 'done' | 'error' | 'route' | 'rewrite' | 'graph' | 'event'
  data: unknown
  request_id?: string
}

export interface ChatHistoryMessage {
  role: LooseString<'user' | 'assistant'>
  content: string
}

export interface ChatRequest {
  conversation_id?: string
  message: string
  history?: ChatHistoryMessage[]
  document_ids?: string[]
  dataset_id?: string | null
  stream: boolean
  structured_output?: boolean
  structured_preset?: LooseString<'faq' | 'summary' | 'action_items' | 'custom'> | null
  enable_long_term_memory?: boolean
  enable_summary_memory?: boolean
  prompt_template_id?: string
  prompt_template_key?: string
  prompt_ab_experiment_key?: string
  rag_config?: {
    retrieval_profile?: string
    top_k?: number
    score_threshold?: number
    max_tokens?: number
    retrieval_mode?: LooseString<'auto' | 'hybrid' | 'vector' | 'keyword' | 'mmr'>
    alpha?: number
    enable_weight_rerank?: boolean
    vector_weight?: number
    keyword_weight?: number
    mmr_lambda?: number
    enable_reranker?: boolean
    reranker_provider?: string
    reranker_top_n?: number
    use_graph?: boolean
    metadata_filter?: JsonObject
  }
}

export interface ConversationSummaryResponse {
  available: boolean
  summary?: string | null
}

export interface ConversationSummaryUpdateResponse {
  summary: string
}

// ==================== Usage / Quotas ====================

export interface ChatTokenUsageRow {
  dataset_id?: string | null
  assistant_messages: number
  assistant_tokens: number
}

export interface ChatTokenUsageSummary {
  window_start: string
  window_end: string
  total_assistant_messages: number
  total_assistant_tokens: number
  by_dataset: ChatTokenUsageRow[]
}

export interface ChatCostUsageRow {
  dataset_id?: string | null
  assistant_messages: number
  llm_prompt_tokens: number
  llm_completion_tokens: number
  llm_total_tokens: number
  embedding_query_tokens: number
  embedding_query_chars: number
  retrieval_elapsed_sec_sum: number
  rerank_elapsed_sec_sum: number
}

export interface ChatCostUsageSummary {
  window_start: string
  window_end: string
  total_assistant_messages: number
  total_llm_prompt_tokens: number
  total_llm_completion_tokens: number
  total_llm_total_tokens: number
  total_embedding_query_tokens: number
  total_embedding_query_chars: number
  total_retrieval_elapsed_sec: number
  total_rerank_elapsed_sec: number
  by_dataset: ChatCostUsageRow[]
}

export interface ChatTokenQuotaStatus {
  enabled: boolean
  mode: string
  limit: number
  used: number
  remaining: number
  exceeded: boolean
  window_hours: number
  window_start: string
  window_end: string
}

export interface TenantDocumentQuotaStatus {
  enabled: boolean
  limit: number
  used: number
  remaining: number
  exceeded: boolean
}

export interface TenantStorageQuotaStatus {
  enabled: boolean
  limit_bytes: number
  used_bytes: number
  remaining_bytes: number
  exceeded: boolean
}

export interface TenantEmbeddingCharQuotaStatus {
  enabled: boolean
  mode: string
  limit_chars: number
  used_chars: number
  remaining_chars: number
  exceeded: boolean
  window_hours: number
  window_start: string
  window_end: string
}

export interface TenantQpsQuotaConfig {
  enabled: boolean
  mode: string
  rps: number
  burst: number
}

export interface TenantQuotaSummary {
  documents: TenantDocumentQuotaStatus
  storage: TenantStorageQuotaStatus
  embedding_chars: TenantEmbeddingCharQuotaStatus
  qps: TenantQpsQuotaConfig
}

// ==================== Audit Logs ====================

export interface AuditLogItem {
  id: string
  tenant_id: string
  actor_id?: string | null
  action: string
  resource_type?: string | null
  resource_id?: string | null
  request_id?: string | null
  ip?: string | null
  user_agent?: string | null
  details: JsonObject
  created_at: string
}

export interface AuditLogListResponse {
  total: number
  items: AuditLogItem[]
}

export interface ChatResponse {
  conversation_id: string
  assistant_message_id: string
  request_id: string
  content: string
  citations: Citation[]
  total_tokens: number
  total_chars: number
  retrieval_mode?: string | null
  vector_backend?: string | null
  confidence_score?: number | null
  followup_questions?: string[]
  metrics: JsonObject
  structured: boolean
  structured_data?: unknown
}

export interface CheckpointItem {
  checkpoint_id?: string | null
  checkpoint_ns?: string
  created_at?: string | null
  next?: unknown
  metadata?: JsonObject | null
  values?: JsonObject | null
}

export interface CheckpointListResponse {
  thread_id: string
  items: CheckpointItem[]
}

export interface CheckpointDetailResponse {
  thread_id: string
  checkpoint_id?: string | null
  checkpoint_ns?: string
  created_at?: string | null
  next?: unknown
  metadata?: JsonObject | null
  values?: JsonObject | null
}

// ==================== 反馈相关类型 ====================

export interface MessageFeedback {
  id: string
  tenant_id: string
  conversation_id: string
  message_id: string
  account_id: string
  rating: number
  reason?: string
  tags: string[]
  expected_answer?: string
  extra?: JsonObject
  created_at: string
  updated_at: string
}

export interface MessageFeedbackCreate {
  message_id: string
  rating: number
  reason?: string
  tags?: string[]
  expected_answer?: string
  extra?: JsonObject
}

export interface MessageFeedbackListResponse {
  total: number
  items: MessageFeedback[]
}

export interface MessageFeedbackEnriched extends MessageFeedback {
  conversation_title?: string
  message_content?: string
  message_created_at?: string
}

export interface MessageFeedbackEnrichedListResponse {
  total: number
  items: MessageFeedbackEnriched[]
}

// ==================== Auth ====================

export type UserProfile = import('./backend').UserProfile
export type AuthToken = import('./backend').AuthToken
export type AuthResponse = import('./backend').AuthResponse
export type RegisterRequest = import('./backend').RegisterRequest
export type LoginRequest = import('./backend').LoginRequest

// ==================== Health ====================

export type HealthResponse = import('./backend').HealthResponse
export type ReadyResponse = import('./backend').ReadyResponse
export type MetaResponse = import('./backend').MetaResponse
