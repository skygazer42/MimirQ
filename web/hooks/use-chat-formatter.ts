'use client'

import type { ChatRequest, ChatResponse, Citation, JsonObject, Message } from '@/types'

export type ChatRagConfig = Partial<Omit<NonNullable<ChatRequest['rag_config']>, 'metadata_filter'>> & {
  metadata_filter?: JsonObject | null
}

export type UseChatOptions = {
  conversationId?: string
  documentIds?: string[]
  datasetId?: string
  promptTemplateId?: string
  ragConfig?: ChatRagConfig
  structuredOutput?: boolean
  structuredPreset?: string
  enableLongTermMemory?: boolean
  enableSummaryMemory?: boolean
  onConversationId?: (conversationId: string) => void
  onError?: (error: string) => void
}

type ChatHistoryEntry = NonNullable<ChatRequest['history']>[number]

type BuildChatRequestOptions = {
  conversationId?: string
  message: string
  history: ChatHistoryEntry[]
  documentIds?: string[]
  datasetId?: string
  promptTemplateId?: string
  structuredOutput?: boolean
  structuredPreset?: string
  enableLongTermMemory?: boolean
  enableSummaryMemory?: boolean
  ragConfig?: ChatRagConfig
  useGraph: boolean
}

type DoneAssistantMessageOptions = {
  assistantMessageId: string
  content: string
  citations: Citation[]
  steps: string[]
  doneData: Record<string, unknown>
  structuredOutput?: boolean
  requestId?: string
}

type FallbackAssistantMessageOptions = {
  response: ChatResponse
  structuredOutput?: boolean
  structuredPreset?: string
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asTrimmedString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

export function formatGraphStep(data: unknown): string | null {
  const payload = asRecord(data)
  if (!payload) return null

  const rawMessage = asTrimmedString(payload.message)
  if (rawMessage) return rawMessage

  const event = asTrimmedString(payload.event)
  if (!event) return null

  const citationsCount = asFiniteNumber(payload.citations_count)
  const elapsedSec = asFiniteNumber(payload.elapsed_sec)
  const answerChars = asFiniteNumber(payload.answer_chars)

  switch (event) {
    case 'retrieve_start':
      return '开始检索相关资料…'
    case 'retrieve_done': {
      let message = '检索完成'
      if (citationsCount != null) message += `：${citationsCount} 条引用`
      if (elapsedSec != null) message += `（${elapsedSec.toFixed(2)}s）`
      return message
    }
    case 'generate_start':
      return '开始生成回答…'
    case 'generate_done': {
      let message = '生成完成'
      if (answerChars != null) message += `：${answerChars} 字符`
      if (elapsedSec != null) message += `（${elapsedSec.toFixed(2)}s）`
      return message
    }
    default:
      return `Graph: ${event}`
  }
}

export function formatRouteStep(data: unknown): string | null {
  const payload = asRecord(data)
  if (!payload) return null

  const modelUsed = asTrimmedString(payload.model_used)
  const route = asTrimmedString(payload.route)
  const reason = asTrimmedString(payload.reason)

  let message = '模型路由'
  if (route) message += `：${route}`
  if (modelUsed) message += `（${modelUsed}）`
  if (!route && modelUsed) message = `模型：${modelUsed}`
  if (reason) message += ` - ${reason.slice(0, 120)}`
  return message
}

export function formatRewriteStep(data: unknown): string | null {
  const payload = asRecord(data)
  if (!payload || !payload.used) return null

  const rewritten = asTrimmedString(payload.rewritten)
  const elapsedSec = asFiniteNumber(payload.elapsed_sec)
  if (!rewritten) return null

  const preview = rewritten.length > 120 ? `${rewritten.slice(0, 120)}…` : rewritten
  return elapsedSec == null ? `查询改写：${preview}` : `查询改写：${preview}（${elapsedSec.toFixed(2)}s）`
}

export function formatAssistantContent(
  content: string,
  structuredOutput: boolean | undefined,
  structuredData: unknown
): string {
  if (!structuredOutput || structuredData == null) {
    return content
  }

  try {
    return `\`\`\`json\n${JSON.stringify(structuredData, null, 2)}\n\`\`\``
  } catch {
    return content
  }
}

export function buildChatRequest({
  conversationId,
  message,
  history,
  documentIds,
  datasetId,
  promptTemplateId,
  structuredOutput,
  structuredPreset,
  enableLongTermMemory,
  enableSummaryMemory,
  ragConfig,
  useGraph,
}: BuildChatRequestOptions): ChatRequest {
  const normalizedRagConfig = ragConfig
    ? Object.fromEntries(
        Object.entries({
          ...ragConfig,
          metadata_filter: ragConfig.metadata_filter ?? undefined,
        }).filter(([, value]) => value !== undefined)
      )
    : undefined

  return {
    conversation_id: conversationId,
    message,
    history,
    document_ids: documentIds,
    dataset_id: documentIds?.length ? undefined : datasetId || undefined,
    prompt_template_id: promptTemplateId,
    stream: !useGraph,
    structured_output: Boolean(structuredOutput),
    structured_preset: structuredPreset || undefined,
    enable_long_term_memory: Boolean(enableLongTermMemory),
    enable_summary_memory: Boolean(enableSummaryMemory),
    rag_config:
      normalizedRagConfig && Object.keys(normalizedRagConfig).length > 0
        ? normalizedRagConfig
        : undefined,
  }
}

export function buildDoneAssistantMessage({
  assistantMessageId,
  content,
  citations,
  steps,
  doneData,
  structuredOutput,
  requestId,
}: DoneAssistantMessageOptions): Message {
  const metrics = asRecord(doneData.metrics) ?? {}

  return {
    id: assistantMessageId,
    role: 'assistant',
    content: formatAssistantContent(content, structuredOutput, doneData.structured_data),
    citations,
    steps,
    message_metadata: {
      ...metrics,
      request_id: requestId || doneData.request_id,
      total_tokens: doneData.total_tokens,
      total_chars: doneData.total_chars,
      citations_count: doneData.citations_count,
      model_used: doneData.model_used,
      route: doneData.route,
      retrieval_mode: doneData.retrieval_mode,
      vector_backend: doneData.vector_backend,
      structured: doneData.structured,
      structured_preset: doneData.structured_preset,
      structured_parse_ok: metrics.structured_parse_ok,
    },
    created_at: new Date().toISOString(),
  }
}

export function buildFallbackAssistantMessage({
  response,
  structuredOutput,
  structuredPreset,
}: FallbackAssistantMessageOptions): Message {
  return {
    id: String(response.assistant_message_id || Date.now().toString()),
    role: 'assistant',
    content: formatAssistantContent(response.content || '', structuredOutput, response.structured_data),
    citations: response.citations || [],
    steps: [],
    message_metadata: {
      ...(response.metrics || {}),
      request_id: response.request_id,
      total_tokens: response.total_tokens,
      total_chars: response.total_chars,
      citations_count: (response.citations || []).length,
      retrieval_mode: response.retrieval_mode,
      vector_backend: response.vector_backend,
      structured: response.structured,
      structured_preset: structuredPreset || undefined,
      structured_parse_ok: (response.metrics || {}).structured_parse_ok,
    },
    created_at: new Date().toISOString(),
  }
}

export function getStreamEventMessage(type: string, data: unknown): string | null {
  if (type === 'event') {
    return asTrimmedString(asRecord(data)?.message)
  }
  if (type === 'graph') return formatGraphStep(data)
  if (type === 'route') return formatRouteStep(data)
  if (type === 'rewrite') return formatRewriteStep(data)
  return null
}

export function getTokenContent(data: unknown): string {
  return asTrimmedString(asRecord(data)?.content)
}

export function getConversationId(value: unknown): string {
  return asTrimmedString(value)
}

export function getAssistantMessageId(value: unknown): string {
  return asTrimmedString(value) || Date.now().toString()
}

export function getCitations(value: unknown): Citation[] {
  return Array.isArray(value) ? (value as Citation[]) : []
}

export function getHistory(messages: Message[]): ChatHistoryEntry[] {
  return messages.slice(-10).map((message) => ({
    role: message.role,
    content: message.content,
  }))
}

export function getStepList(value: unknown): string[] {
  return asStringArray(value)
}
