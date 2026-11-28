import type {
  ChatRequest,
  ChatResponse,
  CheckpointDetailResponse,
  CheckpointListResponse,
  Conversation,
  ConversationDetail,
  ConversationListResponse,
  ConversationSummaryResponse,
  ConversationSummaryUpdateResponse,
  Message,
  RagTraceListResponse,
} from '@/types/chat'
import { z } from 'zod'
import { PROTOCOL_VERSION, type RunAgentInput } from '@ag-ui/core'
import { RunAgentInputSchema } from '@ag-ui/core/schemas'

import { getAuthHeaders } from '@/lib/auth-headers'
import { authenticatedFetch } from '@/lib/authenticated-fetch'
import { buildFetchError } from '@/lib/fetch-errors'
import { extractHeaderRequestId } from '@/lib/api-errors'
import { API_LONG_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { withPreferredLanguageHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'
import { readSseDataStrings } from '@/lib/sse-reader'
import { citationListSchema } from '@/lib/citations'
import { parseApiResponse } from '@/lib/openapi-request'
import { matchesResourceId } from '@/lib/resource-id'
import { chatMessageMetadataSchema, ontologyActionProposalSchema } from '@/lib/chat-message-metadata'
import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { dateTimeSchema, recordSchema } from '@/lib/response-schema'

const chatResponseSchema: z.ZodType<ChatResponse> = z.looseObject({
  conversation_id: z.string(),
  assistant_message_id: z.string(),
  request_id: z.string(),
  content: z.string(),
  citations: citationListSchema,
  total_tokens: z.number().int(),
  total_chars: z.number().int(),
  usage: z
    .object({
      prompt_tokens: z.number().int().nonnegative(),
      completion_tokens: z.number().int().nonnegative(),
      total_tokens: z.number().int().nonnegative(),
      source: z.enum(['provider', 'mock', 'estimate']),
    })
    .nullish(),
  metrics: chatMessageMetadataSchema,
  structured: z.boolean(),
  retrieval_mode: z.string().nullable().optional(),
  vector_backend: z.string().nullable().optional(),
  confidence_score: z.number().nullable().optional(),
  followup_questions: z.array(z.string()).optional(),
  structured_data: z.unknown().optional(),
  ontology_action: ontologyActionProposalSchema.nullish(),
})

const chatMessageSchema: z.ZodType<Message> = z.looseObject({
  id: z.string(),
  role: z.enum(['user', 'assistant']),
  content: z.string(),
  citations: citationListSchema.optional(),
  steps: z.array(z.string()).optional(),
  message_metadata: chatMessageMetadataSchema.nullable().optional(),
  ontology_action: ontologyActionProposalSchema.nullish(),
  created_at: dateTimeSchema,
})

const conversationMessagesSchema: z.ZodType<ConversationDetail> = z
  .looseObject({
    conversation_id: z.string(),
    returned: z.number().int().nonnegative(),
    has_more: z.boolean(),
    messages: z.array(chatMessageSchema),
  })
  .refine((page) => page.returned === page.messages.length && (!page.has_more || page.messages.length > 0), {
    message: 'Invalid conversation message pagination',
  })

const conversationSchema: z.ZodType<Conversation> = z.looseObject({
  id: z.string(),
  title: z.string().nullable().optional(),
  last_message: z.string().nullable().optional(),
  last_message_at: dateTimeSchema.nullable().optional(),
  message_count: z.number().int().nonnegative(),
  created_at: dateTimeSchema,
  updated_at: dateTimeSchema,
})

const conversationListSchema: z.ZodType<ConversationListResponse> = z
  .looseObject({
    total: z.number().int().nonnegative(),
    returned: z.number().int().nonnegative(),
    has_more: z.boolean(),
    next_skip: z.number().int().nonnegative().nullable(),
    items: z.array(conversationSchema),
  })
  .refine(
    (page) =>
      page.returned === page.items.length &&
      page.has_more === (page.next_skip !== null) &&
      (!page.has_more || page.returned > 0),
    { message: 'Invalid conversation list pagination' },
  )

const conversationSummarySchema: z.ZodType<ConversationSummaryResponse> = z.looseObject({
  available: z.boolean(),
  summary: z.string().nullish(),
})
const conversationSummaryUpdateSchema: z.ZodType<ConversationSummaryUpdateResponse> = z.looseObject({
  summary: z.string(),
})

const checkpointItemSchema = z.looseObject({
  checkpoint_id: z.string().nullish(),
  checkpoint_ns: z.string().optional(),
  created_at: dateTimeSchema.nullish(),
  next: z.unknown().optional(),
  metadata: recordSchema.nullish(),
  values: recordSchema.nullish(),
})
const checkpointListSchema: z.ZodType<CheckpointListResponse> = z.looseObject({
  thread_id: z.string(),
  items: z.array(checkpointItemSchema),
})
const checkpointDetailSchema: z.ZodType<CheckpointDetailResponse> = checkpointItemSchema.extend({
  thread_id: z.string(),
})

const traceTextSchema = z.string().nullish()
const traceNumberSchema = z.number().nullish()
const traceIntegerSchema = z.number().int().nullish()
const traceCitationSchema = z.object({
  document_id: traceTextSchema,
  chunk_id: traceTextSchema,
  chunk_index: traceIntegerSchema,
  page_number: traceIntegerSchema,
  bbox: z.object({ x0: z.number(), y0: z.number(), x1: z.number(), y1: z.number() }).nullish(),
  bbox_page_number: traceIntegerSchema,
  start_char: traceIntegerSchema,
  end_char: traceIntegerSchema,
  retrieval_role: traceTextSchema,
  neighbor_of: traceTextSchema,
  doc_pipeline_key: traceTextSchema,
  pipeline_hash: traceTextSchema,
  relevance_score: traceNumberSchema,
  vector_score: traceNumberSchema,
  bm25_score: traceNumberSchema,
  lexical_score: traceNumberSchema,
  keyword_score: traceNumberSchema,
  rerank_score: traceNumberSchema,
  retrieval_score: traceNumberSchema,
  reranker_provider: traceTextSchema,
  rerank_elapsed_sec: traceNumberSchema,
  rerank_model_used: traceTextSchema,
  retrieval_mode: traceTextSchema,
  vector_backend: traceTextSchema,
  retrieval_elapsed_sec: traceNumberSchema,
  hit_type: traceTextSchema,
  has_image: z.boolean().optional(),
  kg_path: z.array(recordSchema).nullish(),
  kg_path_provenance: recordSchema.nullish(),
})
const traceSchema = z.looseObject({
  schema_version: z.number().int(),
  ts_ms: z.number().int(),
  request_id: traceTextSchema,
  conversation_id: traceTextSchema,
  retrieval: z.looseObject({
    mode: traceTextSchema,
    requested_mode: traceTextSchema,
    auto_routed: z.boolean().nullish(),
    retrieval_config_hash: traceTextSchema,
    top_k: traceIntegerSchema,
    query_parallelism: traceIntegerSchema,
    query_count: traceIntegerSchema,
    per_query: z
      .array(
        z.looseObject({
          kind: traceTextSchema,
          query_chars: traceIntegerSchema,
          elapsed_sec: traceNumberSchema,
          ok: z.boolean().nullish(),
          retriever_debug: recordSchema.nullish(),
        }),
      )
      .optional(),
    errors: z.array(z.string()).optional(),
    enable_reranker: z.boolean().nullish(),
    reranker_provider: traceTextSchema,
    reranker_top_n: traceIntegerSchema,
    elapsed_sec: traceNumberSchema,
  }),
  rerank: z.looseObject({
    enabled: z.boolean(),
    provider: traceTextSchema,
    top_n: traceIntegerSchema,
    elapsed_sec: traceNumberSchema,
    model_used: traceTextSchema,
  }),
  citations: z.array(traceCitationSchema),
  citations_count: z.number().int().nonnegative(),
  steps: z.array(
    z.looseObject({
      key: z.string(),
      label: z.string(),
      elapsed_sec: traceNumberSchema,
      meta: recordSchema.optional(),
    }),
  ),
})
const traceListSchema: z.ZodType<RagTraceListResponse> = z
  .looseObject({
    enabled: z.boolean(),
    path: z.string(),
    window_minutes: z.number().int(),
    truncated: z.boolean(),
    returned: z.number().int().nonnegative(),
    items: z.array(traceSchema),
  })
  .refine((page) => page.returned === page.items.length, { message: 'Invalid trace record count' })

type ChatStreamMetadata = {
  requestId: string
  conversationId: string
  runId: string
  assistantMessageId?: string
}

export const chatApi = {
  async createConversation(params?: { title?: string; document_ids?: string[] }): Promise<Conversation> {
    const response = await apiClient.post<unknown>('/chat/conversations', params)
    return parseApiResponse(response, conversationSchema, 'Conversation')
  },

  async updateConversation(conversationId: string, payload: { title?: string | null }): Promise<Conversation> {
    const response = await apiClient.patch<unknown>(`/chat/conversations/${conversationId}`, payload)
    return parseApiResponse(response, conversationSchema, 'Conversation')
  },

  async exportConversation(
    conversationId: string,
    params?: { fmt?: 'markdown' | 'json'; include_citations?: boolean },
    options: ApiRequestOptions = {},
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/chat/conversations/${conversationId}/export`, {
      params,
      responseType: 'blob',
      signal: options.signal,
    })
    return data
  },

  async listConversations(
    params?: { skip?: number; limit?: number; q?: string },
    options: ApiRequestOptions = {},
  ): Promise<ConversationListResponse> {
    const response = await apiClient.get<unknown>('/chat/conversations', { params, signal: options.signal })
    return parseApiResponse(response, conversationListSchema, 'ConversationList')
  },

  async getMessages(
    conversationId: string,
    params?: { limit?: number; before?: string },
    options: ApiRequestOptions = {},
  ): Promise<ConversationDetail> {
    const response = await apiClient.get<unknown>(
      `/chat/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        params,
        signal: options.signal,
      },
    )
    const schema = conversationMessagesSchema.refine(
      (page) => matchesResourceId(page.conversation_id, conversationId),
      {
        message: 'Conversation history does not match the requested conversation',
        path: ['conversation_id'],
      },
    )
    return parseApiResponse(response, schema, 'ConversationMessages')
  },

  async deleteConversation(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}`)
  },

  async getRagTraces(
    conversationId: string,
    params?: { limit?: number; window_minutes?: number; max_bytes?: number },
    options: ApiRequestOptions = {},
  ): Promise<RagTraceListResponse> {
    const response = await apiClient.get<unknown>(`/chat/conversations/${conversationId}/rag-traces`, {
      params,
      signal: options.signal,
    })
    return parseApiResponse(response, traceListSchema, 'ConversationRagTraces')
  },

  async streamChat(
    request: ChatRequest,
    onJson: (jsonStr: string) => void,
    options: {
      signal?: AbortSignal
      onOpen?: (metadata: ChatStreamMetadata) => void
      messages?: RunAgentInput['messages']
    } = {},
  ): Promise<ChatStreamMetadata> {
    const requestId = generateRequestId()
    const { message, history, conversation_id, stream: _stream, ...forwardedProps } = request
    if (history !== undefined && history.length > 0 && options.messages === undefined) {
      throw new TypeError('Chat history requires stable message IDs')
    }
    const input: RunAgentInput = RunAgentInputSchema.parse({
      threadId: conversation_id ?? globalThis.crypto.randomUUID(),
      runId: globalThis.crypto.randomUUID(),
      protocolVersion: PROTOCOL_VERSION,
      messages: options.messages ?? [{ id: globalThis.crypto.randomUUID(), role: 'user', content: message }],
      state: {},
      tools: [],
      context: [],
      forwardedProps,
    })

    const response = await authenticatedFetch(`${API_V1_BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: withPreferredLanguageHeader({
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      }),
      body: JSON.stringify(input),
      signal: options.signal,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Chat stream failed')
    }

    const backendRequestId = extractHeaderRequestId(response.headers)
    const conversationId = response.headers.get('X-Conversation-ID')
    const assistantMessageId = response.headers.get('X-Assistant-Message-ID')
    const metadata = {
      requestId: backendRequestId === undefined ? requestId : backendRequestId,
      conversationId: input.threadId,
      runId: input.runId,
      assistantMessageId: assistantMessageId === null ? undefined : assistantMessageId,
    }
    await readSseDataStrings(response, onJson, () => {
      if (conversationId !== null && conversationId !== input.threadId) {
        throw new TypeError('AG-UI response belongs to another conversation')
      }
      options.onOpen?.(metadata)
    })
    return metadata
  },

  async chat(request: ChatRequest, options: { signal?: AbortSignal } = {}): Promise<ChatResponse> {
    const response = await apiClient.post<unknown>('/chat', request, {
      signal: options.signal,
      timeout: API_LONG_TIMEOUT_MS,
    })
    return parseApiResponse(response, chatResponseSchema, 'ChatResponse')
  },

  async listCheckpoints(
    conversationId: string,
    params?: { limit?: number; before?: string; include_values?: boolean },
    options: ApiRequestOptions = {},
  ): Promise<CheckpointListResponse> {
    const response = await apiClient.get<unknown>(`/chat/conversations/${conversationId}/checkpoints`, {
      params,
      signal: options.signal,
    })
    return parseApiResponse(response, checkpointListSchema, 'ConversationCheckpoints')
  },

  async getCheckpoint(
    conversationId: string,
    checkpointId: string,
    params?: { include_values?: boolean },
    options: ApiRequestOptions = {},
  ): Promise<CheckpointDetailResponse> {
    const response = await apiClient.get<unknown>(`/chat/conversations/${conversationId}/checkpoints/${checkpointId}`, {
      params,
      signal: options.signal,
    })
    return parseApiResponse(response, checkpointDetailSchema, 'ConversationCheckpoint')
  },

  async deleteCheckpoints(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}/checkpoints`)
  },

  async getConversationSummary(
    conversationId: string,
    options?: ApiRequestOptions,
  ): Promise<ConversationSummaryResponse> {
    const response = await apiClient.get<unknown>(`/chat/conversations/${encodeURIComponent(conversationId)}/summary`, {
      signal: options?.signal,
    })
    return parseApiResponse(response, conversationSummarySchema, 'ConversationSummary')
  },

  async updateConversationSummary(conversationId: string): Promise<ConversationSummaryUpdateResponse> {
    const response = await apiClient.post<unknown>(`/chat/conversations/${conversationId}/summary/update`)
    return parseApiResponse(response, conversationSummaryUpdateSchema, 'ConversationSummaryUpdate')
  },

  async deleteConversationSummary(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}/summary`)
  },
}
