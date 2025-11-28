/**
 * 类型定义
 */

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
}

export interface DocumentStatus {
  id: string
  status: string
  processing_progress: number
  current_stage?: string
  error_message?: string
}

export interface Citation {
  document_id: string
  document_name: string
  chunk_content: string
  page_number?: number
  relevance_score: number
}

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
