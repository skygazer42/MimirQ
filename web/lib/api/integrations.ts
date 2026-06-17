import { apiClient } from './core'

export type ExternalConversationMessageInput = {
  role: 'user' | 'assistant'
  content: string
  source_message_id?: string | null
  source_run_id?: string | null
  citations?: Record<string, unknown>[]
  metadata?: Record<string, unknown>
  created_at?: string | null
  token_count?: number | null
}

export type ExternalConversationIngestRequest = {
  source: string
  source_conversation_id: string
  conversation_id?: string | null
  title?: string | null
  update_title?: boolean
  dataset_id?: string | null
  document_ids?: string[]
  source_user_id?: string | null
  source_run_id?: string | null
  messages: ExternalConversationMessageInput[]
  metadata?: Record<string, unknown>
}

export type ExternalConversationIngestResponse = {
  success: boolean
  conversation_id: string
  created_conversation: boolean
  source: string
  source_conversation_id: string
  inserted_messages: number
  skipped_messages: number
  message_ids: string[]
  skipped_source_message_ids: string[]
}

export const integrationApi = {
  async ingestConversationHistory(
    payload: ExternalConversationIngestRequest
  ): Promise<ExternalConversationIngestResponse> {
    const { data } = await apiClient.post('/integrations/conversations/ingest', payload)
    return data
  },
}
