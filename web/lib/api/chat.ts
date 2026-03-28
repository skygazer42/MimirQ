import type {
  ChatRequest,
  ChatResponse,
  CheckpointDetailResponse,
  CheckpointListResponse,
  Conversation,
  ConversationSummaryResponse,
  ConversationSummaryUpdateResponse,
  Message,
  RagTraceListResponse,
} from '@/types'

import { getAuthHeaders } from '@/lib/auth-headers'
import { buildFetchError } from '@/lib/fetch-errors'
import { API_LONG_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { withPreferredLanguageHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'
import { readSseDataStrings } from '@/lib/sse-reader'
import { apiClient } from '@/lib/api/core'

export const chatApi = {
  async createConversation(params?: {
    title?: string
    document_ids?: string[]
  }): Promise<Conversation> {
    const { data } = await apiClient.post('/chat/conversations', params)
    return data
  },

  async updateConversation(conversationId: string, payload: { title?: string | null }): Promise<Conversation> {
    const { data } = await apiClient.patch(`/chat/conversations/${conversationId}`, payload)
    return data
  },

  async exportConversation(conversationId: string, params?: { fmt?: 'markdown' | 'json'; include_citations?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/export`, { params, responseType: 'blob' })
    return data as Blob
  },

  async listConversations(params?: {
    skip?: number
    limit?: number
  }): Promise<{ total: number; returned?: number; has_more?: boolean; items: Conversation[] }> {
    const { data } = await apiClient.get('/chat/conversations', { params })
    return data
  },

  async getMessages(
    conversationId: string,
    params?: { limit?: number; before?: string }
  ): Promise<{ conversation_id: string; messages: Message[]; returned?: number; has_more?: boolean }> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/messages`, { params })
    return data
  },

  async deleteConversation(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}`)
  },

  async getRagTraces(
    conversationId: string,
    params?: { limit?: number; window_minutes?: number; max_bytes?: number }
  ): Promise<RagTraceListResponse> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/rag-traces`, { params })
    return data
  },

  async streamChat(
    request: ChatRequest,
    onJson: (jsonStr: string) => void,
    options: {
      signal?: AbortSignal
      onError?: (error: unknown) => void
      onOpen?: (meta: { requestId: string; conversationId?: string }) => void
    } = {}
  ): Promise<{ requestId: string; conversationId?: string }> {
    const requestId = generateRequestId()

    const response = await fetch(`${API_V1_BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: withPreferredLanguageHeader({
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      }),
      body: JSON.stringify(request),
      signal: options.signal,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Chat stream failed')
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const backendRequestId = response.headers.get('X-Request-ID') || requestId
    const conversationId = response.headers.get('X-Conversation-ID') || undefined
    options.onOpen?.({ requestId: backendRequestId, conversationId })
    await readSseDataStrings(reader, onJson, options.onError)
    return { requestId: backendRequestId, conversationId }
  },

  async chat(request: ChatRequest, options: { signal?: AbortSignal } = {}): Promise<ChatResponse> {
    const { data } = await apiClient.post('/chat', request, { timeout: API_LONG_TIMEOUT_MS, signal: options.signal })
    return data
  },

  async listCheckpoints(
    conversationId: string,
    params?: { limit?: number; before?: string; include_values?: boolean }
  ): Promise<CheckpointListResponse> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/checkpoints`, { params })
    return data
  },

  async getCheckpoint(
    conversationId: string,
    checkpointId: string,
    params?: { include_values?: boolean }
  ): Promise<CheckpointDetailResponse> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/checkpoints/${checkpointId}`, { params })
    return data
  },

  async deleteCheckpoints(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}/checkpoints`)
  },

  async getConversationSummary(conversationId: string): Promise<ConversationSummaryResponse> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/summary`)
    return data
  },

  async updateConversationSummary(conversationId: string): Promise<ConversationSummaryUpdateResponse> {
    const { data } = await apiClient.post(`/chat/conversations/${conversationId}/summary/update`)
    return data
  },

  async deleteConversationSummary(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}/summary`)
  },
}
