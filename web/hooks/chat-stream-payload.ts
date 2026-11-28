import type { ChatMessageMetadata, ChatRequest, Message } from '@/types/chat'
import type { Citation } from '@/types/processing'
import { chatMessageMetadataSchema, ontologyActionProposalSchema } from '@/lib/chat-message-metadata'
import { readNonEmptyString } from '@/lib/primitive-text'

export type ChatRagConfig = NonNullable<ChatRequest['rag_config']>

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

const MESSAGE_METADATA_FIELDS = [
  'request_id',
  'total_tokens',
  'total_chars',
  'citations_count',
  'model_used',
  'route',
  'retrieval_mode',
  'vector_backend',
  'confidence_score',
  'followup_questions',
  'structured',
  'structured_preset',
  'structured_parse_ok',
]

function buildMessageMetadata(
  data: Record<string, unknown>,
  metrics: Record<string, unknown> | undefined,
  requestId?: string,
): ChatMessageMetadata {
  const metadata: Record<string, unknown> = { ...metrics }
  for (const field of MESSAGE_METADATA_FIELDS) {
    const value = data[field]
    if (value !== undefined) metadata[field] = value
  }
  if (requestId !== undefined) metadata.request_id = requestId
  return chatMessageMetadataSchema.parse(metadata)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readFiniteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function formatGraphStep(data: Record<string, unknown>): string | undefined {
  const rawMessage = readNonEmptyString(data.message)
  if (rawMessage !== undefined) return rawMessage
  const event = readNonEmptyString(data.event)
  if (event === undefined) return undefined

  const citationsCount = readFiniteNumber(data.citations_count)
  const elapsedSec = readFiniteNumber(data.elapsed_sec)
  const answerChars = readFiniteNumber(data.answer_chars)
  switch (event) {
    case 'retrieve_start':
      return '开始检索相关资料…'
    case 'retrieve_done': {
      let message = '检索完成'
      if (citationsCount !== undefined) message += `：${citationsCount} 条引用`
      if (elapsedSec !== undefined) message += `（${elapsedSec.toFixed(2)}s）`
      return message
    }
    case 'generate_start':
      return '开始生成回答…'
    case 'generate_done': {
      let message = '生成完成'
      if (answerChars !== undefined) message += `：${answerChars} 字符`
      if (elapsedSec !== undefined) message += `（${elapsedSec.toFixed(2)}s）`
      return message
    }
    default:
      return `Graph: ${event}`
  }
}

function formatRouteStep(data: Record<string, unknown>): string | undefined {
  const modelUsed = readNonEmptyString(data.model_used)
  const route = readNonEmptyString(data.route)
  const reason = readNonEmptyString(data.reason)
  if (modelUsed === undefined && route === undefined && reason === undefined) return undefined

  let message = '模型路由'
  if (route !== undefined) {
    message += `：${route}`
    if (modelUsed !== undefined) message += `（${modelUsed}）`
  } else if (modelUsed !== undefined) {
    message = `模型：${modelUsed}`
  }
  if (reason !== undefined) message += ` - ${Array.from(reason).slice(0, 120).join('')}`
  return message
}

function formatRewriteStep(data: Record<string, unknown>): string | undefined {
  if (data.used !== true) return undefined
  const rewritten = readNonEmptyString(data.rewritten)
  if (rewritten === undefined) return undefined
  const elapsedSec = readFiniteNumber(data.elapsed_sec)
  const characters = Array.from(rewritten)
  const preview = characters.length > 120 ? `${characters.slice(0, 120).join('')}…` : rewritten
  return elapsedSec === undefined ? `查询改写：${preview}` : `查询改写：${preview}（${elapsedSec.toFixed(2)}s）`
}

function formatAssistantContent(
  content: string,
  structuredOutput: boolean | undefined,
  structuredData: unknown,
): string {
  if (structuredOutput !== true || structuredData === null || structuredData === undefined) {
    return content
  }

  const json = JSON.stringify(structuredData, null, 2)
  if (json === undefined) throw new TypeError('Structured chat content must be JSON serializable')
  return `\`\`\`json\n${json}\n\`\`\``
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
}: BuildChatRequestOptions): ChatRequest {
  return {
    conversation_id: conversationId,
    message,
    history,
    document_ids: documentIds,
    dataset_id: documentIds !== undefined && documentIds.length > 0 ? undefined : datasetId,
    prompt_template_id: promptTemplateId,
    structured_output: structuredOutput,
    structured_preset: structuredPreset,
    enable_long_term_memory: enableLongTermMemory,
    enable_summary_memory: enableSummaryMemory,
    rag_config: ragConfig === undefined ? undefined : { ...ragConfig },
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
  const metrics = doneData.metrics
  if (metrics !== undefined && !isRecord(metrics)) throw new TypeError('Chat metrics must be an object')

  return {
    id: assistantMessageId,
    role: 'assistant',
    content: formatAssistantContent(content, structuredOutput, doneData.structured_data),
    citations,
    steps,
    message_metadata: buildMessageMetadata(doneData, metrics, requestId),
    ...(doneData.ontology_action !== undefined && {
      ontology_action: ontologyActionProposalSchema.parse(doneData.ontology_action),
    }),
    created_at: new Date().toISOString(),
  }
}

export function getStreamEventMessage(type: string, data: unknown): string | undefined {
  if (!isRecord(data)) return undefined
  if (type === 'event') return readNonEmptyString(data.message)
  if (type === 'graph') return formatGraphStep(data)
  if (type === 'route') return formatRouteStep(data)
  if (type === 'rewrite') return formatRewriteStep(data)
  return undefined
}

export function getHistory(messages: readonly Message[]): Array<ChatHistoryEntry & { id: string }> {
  return messages
    .filter((message) => {
      const sendState = message.message_metadata?.send_state
      return sendState !== 'sending' && sendState !== 'unconfirmed'
    })
    .slice(-10)
    .map((message) => ({ id: message.id, role: message.role, content: message.content }))
}
