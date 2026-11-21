/**
 * Chat, feedback, quota, auth, and audit types re-exported by `@/types`.
 */

import type { JsonObject } from './common'
import type { OpenApiSchema } from './backend'
import type { Citation } from './processing'

// ==================== 对话相关类型 ====================

export type ClaimEvidenceReference = {
  document_id: string | null
  chunk_id: string | null
  start_char: number | null
  end_char: number | null
  quote: string
  score: number
}

export type ClaimEvidenceItem = {
  claim: string
  evidence: ClaimEvidenceReference[]
}

export type ChatMessageMetadata = Record<string, unknown> & {
  request_id?: string | null
  confidence_score?: number | null
  claim_evidence?: ClaimEvidenceItem[] | null
  sentence_citations?: ClaimEvidenceItem[] | null
  retrieved_docs?: unknown[] | null
  docs_returned?: number | null
  followup_questions?: string[] | null
  dataset_id?: string | null
  send_state?: 'sending' | 'accepted' | 'unconfirmed'
}

export type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  steps?: string[]
  message_metadata?: ChatMessageMetadata | null
  created_at: string
}

export type Conversation = {
  id: string
  title?: string | null
  last_message?: string | null
  last_message_at?: string | null
  message_count: number
  created_at: string
  updated_at: string
}

export type ConversationListResponse = {
  total: number
  returned: number
  has_more: boolean
  next_skip: number | null
  items: Conversation[]
}

export type ConversationDetail = {
  conversation_id: string
  returned: number
  has_more: boolean
  messages: Message[]
}

// ==================== RAG Trace (Visualization) ====================

export type RagTraceStep = {
  key: string
  label: string
  elapsed_sec?: number | null
  meta?: Record<string, unknown>
}

export type RagTraceCitation = {
  document_id?: string | null
  chunk_id?: string | null
  chunk_index?: number | null
  page_number?: number | null
  bbox?: { x0: number; y0: number; x1: number; y1: number } | null
  bbox_page_number?: number | null
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

  kg_path?: Array<Record<string, unknown>> | null
  kg_path_provenance?: Record<string, unknown> | null
}

export type RagTraceRetrievalQuery = {
  kind?: string | null
  query_chars?: number | null
  elapsed_sec?: number | null
  ok?: boolean | null
  retriever_debug?: Record<string, unknown> | null
}

export type RagTraceRetrieval = {
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

export type RagTraceRerank = {
  enabled: boolean
  provider?: string | null
  top_n?: number | null
  elapsed_sec?: number | null
  model_used?: string | null
}

export type RagTrace = {
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

export type RagTraceListResponse = {
  enabled: boolean
  path: string
  window_minutes: number
  truncated: boolean
  returned: number
  items: RagTrace[]
}

export type StreamEvent = import('@ag-ui/core').Event

export type ChatHistoryMessage = OpenApiSchema<'HistoryMessage'>

type GeneratedChatRequest = OpenApiSchema<'ChatRequest'>

// The request schema requires only message; omitted options inherit server defaults.
export type ChatRequest = Pick<GeneratedChatRequest, 'message'> &
  Partial<Omit<GeneratedChatRequest, 'message' | 'rag_config'>> & {
    rag_config?: Partial<OpenApiSchema<'ChatRAGConfig'>>
  }

export type ConversationSummaryResponse = {
  available: boolean
  summary?: string | null
}

export type ConversationSummaryUpdateResponse = {
  summary: string
}

export type ChatResponse = {
  conversation_id: string
  assistant_message_id: string
  request_id: string
  content: string
  citations: Citation[]
  total_tokens: number
  total_chars: number
  usage?: OpenApiSchema<'TokenUsage'> | null
  retrieval_mode?: string | null
  vector_backend?: string | null
  confidence_score?: number | null
  followup_questions?: string[]
  metrics: JsonObject
  structured: boolean
  structured_data?: unknown
}

export type CheckpointItem = {
  checkpoint_id?: string | null
  checkpoint_ns?: string
  created_at?: string | null
  next?: unknown
  metadata?: Record<string, unknown> | null
  values?: Record<string, unknown> | null
}

export type CheckpointListResponse = {
  thread_id: string
  items: CheckpointItem[]
}

export type CheckpointDetailResponse = {
  thread_id: string
  checkpoint_id?: string | null
  checkpoint_ns?: string
  created_at?: string | null
  next?: unknown
  metadata?: Record<string, unknown> | null
  values?: Record<string, unknown> | null
}

export type {
  FeedbackCategory,
  FeedbackCategorySource,
  FeedbackLoopCandidatesResponse,
  MessageFeedback,
  MessageFeedbackCreate,
  MessageFeedbackEnriched,
  MessageFeedbackEnrichedListResponse,
} from './feedback'

// ==================== Auth ====================

export type UserProfile = import('./backend').UserProfile
export type AuthToken = import('./backend').AuthToken
export type AuthResponse = import('./backend').AuthResponse
export type RegisterRequest = import('./backend').RegisterRequest
export type LoginRequest = import('./backend').LoginRequest

// ==================== Health ====================

export type HealthResponse = import('./backend').HealthResponse
export type ReadyResponse = import('./backend').ReadyResponse
export type HealthDetailsResponse = import('./backend').HealthDetailsResponse
export type MetaResponse = import('./backend').MetaResponse
export type MetaDetailsResponse = import('./backend').MetaDetailsResponse
