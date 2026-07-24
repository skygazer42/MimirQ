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
import { z } from 'zod'
import type { OpenApiOkResponse, OpenApiRequestBody } from '@/types/openapi-helpers'

import { getAuthHeaders } from '@/lib/auth-headers'
import { authenticatedFetch } from '@/lib/authenticated-fetch'
import { buildFetchError } from '@/lib/fetch-errors'
import { API_LONG_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { withPreferredLanguageHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'
import { readSseDataStrings } from '@/lib/sse-reader'
import { apiClient, openapiRequest } from '@/lib/api/core'

type ChatRequestBody = OpenApiRequestBody<'/api/v1/chat', 'post'>
type ChatResponseBody = OpenApiOkResponse<'/api/v1/chat', 'post'>

const chatCitationSchema = z.looseObject({
    document_id: z.string(),
    document_name: z.string(),
    chunk_content: z.string(),
    relevance_score: z.number(),
  })

const chatResponseSchema = z.looseObject({
    conversation_id: z.string(),
    assistant_message_id: z.string(),
    request_id: z.string(),
    content: z.string(),
    citations: z.array(chatCitationSchema).default([]),
    total_tokens: z.number().int().default(0),
    total_chars: z.number().int().default(0),
    metrics: z.record(z.string(), z.unknown()).default({}),
    structured: z.boolean().default(false),
    retrieval_mode: z.string().nullable().optional(),
    vector_backend: z.string().nullable().optional(),
    confidence_score: z.number().nullable().optional(),
    followup_questions: z.array(z.string()).optional(),
    structured_data: z.unknown().optional(),
  })

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
  }): Promise<{ total: number; returned?: number; has_more?: boolean; next_skip?: number | null; items: Conversation[] }> {
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

    const response = await authenticatedFetch(`${API_V1_BASE_URL}/chat/stream`, {
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
    const data = await openapiRequest({
      path: '/api/v1/chat',
      method: 'post',
      body: request as unknown as ChatRequestBody,
      signal: options.signal,
      timeoutMs: API_LONG_TIMEOUT_MS,
      responseSchema: chatResponseSchema as unknown as z.ZodType<ChatResponseBody>,
      responseSchemaName: 'ChatResponse',
    })
    return data as ChatResponse
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
