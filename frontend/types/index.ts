/**
 * 类型定义
 */

// ==================== 通用类型 ====================

export type PermissionEnum = 'only_me' | 'all_team_members' | 'partial_members'

// ==================== 文档相关类型 ====================

export interface Document {
  id: string
  filename: string
  file_type: string
  file_size: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  processing_progress: number
  chunk_count: number
  total_characters: number
  created_at: string
  updated_at: string
  current_stage?: string
  error_message?: string
  metadata?: Record<string, any>
  chunks?: DocumentChunk[]
  dataset_id?: string
}

export interface DocumentStatus {
  id: string
  status: string
  processing_progress: number
  current_stage?: string
  error_message?: string
}

export interface DocumentChunk {
  id: string
  content: string
  page_number?: number
  start_char?: number
  end_char?: number
  chunk_index: number
  metadata?: Record<string, any>
}

export interface DocumentPipelineOptions {
  governance_enabled?: boolean
  governance_remove_toc_lines?: boolean
  governance_remove_noise_lines?: boolean
  governance_unwrap_lines?: boolean
  governance_remove_common_lines?: boolean
  governance_unwrap_max_line_length?: number
  governance_noise_min_chars?: number
  governance_noise_ratio_threshold?: number
  governance_common_lines_min_docs?: number
  governance_common_lines_min_ratio?: number
  chunk_size?: number
  chunk_overlap?: number
  chunk_vector_enabled?: boolean
  bm25_index_enabled?: boolean
  sag_enabled?: boolean
  event_vector_enabled?: boolean
  entity_vector_enabled?: boolean
}

export interface Citation {
  document_id: string
  document_name: string
  chunk_content: string
  page_number?: number
  relevance_score: number
  has_image?: boolean
  img_id?: string
  img_url?: string
}

export interface ParsedSegment {
  index: number
  content: string
  page_number?: number
  metadata?: Record<string, any>
}

export interface DocumentPreview {
  filename: string
  file_type: string
  file_size: number
  segments: ParsedSegment[]
  parser_backend: string
}

export interface ManualChunk {
  content: string
  page_number?: number
  start_char?: number
  end_char?: number
  metadata?: Record<string, any>
}

// ==================== 切块预览相关类型 ====================

export interface ChunkPreviewParams {
  chunk_size: number
  chunk_overlap: number
}

export interface ChunkPreviewItem {
  index: number
  content: string
  length: number
  start_index: number
  end_index: number
  page_number?: number
  metadata?: Record<string, any>
}

export interface ChunkPreviewResponse {
  filename: string
  file_type: string
  file_size: number
  total_chunks: number
  total_characters: number
  params: ChunkPreviewParams
  chunks: ChunkPreviewItem[]
  original_text?: string
  parser_backend: string
  chunk_strategy: string
}

// ==================== 数据集相关类型 ====================

export interface Dataset {
  id: string
  tenant_id: string
  name: string
  description?: string
  permission: PermissionEnum
  owner_id?: string
  partial_member_list?: string[]
}

export interface DatasetCreate {
  name: string
  description?: string
  permission?: PermissionEnum
  partial_member_list?: string[]
}

export interface DatasetUpdate {
  name?: string
  description?: string
  permission?: PermissionEnum
  partial_member_list?: string[]
}

export interface DatasetListResponse {
  total: number
  items: Dataset[]
}

// ==================== 对话相关类型 ====================

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
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
  items: Conversation[]
}

export interface ConversationDetail {
  conversation_id: string
  messages: Message[]
}

export interface StreamEvent {
  type: 'citations' | 'token' | 'done' | 'error'
  data: any
}

export interface ChatRequest {
  conversation_id?: string
  message: string
  document_ids?: string[]
  stream: boolean
  rag_config?: {
    top_k?: number
    score_threshold?: number
    max_tokens?: number
  }
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
  extra?: Record<string, any>
  created_at: string
  updated_at: string
}

export interface MessageFeedbackCreate {
  message_id: string
  rating: number
  reason?: string
  tags?: string[]
  expected_answer?: string
  extra?: Record<string, any>
}

export interface MessageFeedbackListResponse {
  total: number
  items: MessageFeedback[]
}

// ==================== SAG 相关类型 ====================

export interface SAGExtractResponse {
  document_id: string
  chunk_count: number
  event_count: number
  message: string
}

export interface SAGSearchRequest {
  query: string
  tenant_id?: string
  document_ids?: string[]
}

export interface SAGSearchResponse {
  result: Record<string, any>
  query: string
}

// ==================== 批量上传相关类型 ====================

export interface BatchFileInfo {
  name: string
  data_id: string
}

export interface BatchUploadRequest {
  files: BatchFileInfo[]
}

export interface BatchUploadResponse {
  batch_id: string
  file_urls: string[]
  files: BatchFileInfo[]
  message: string
}

export interface BatchTaskStatus {
  batch_id: string
  status: string
  total_files: number
  completed_files: number
  failed_files: number
  progress: number
  result_url?: string
  error?: string
}
