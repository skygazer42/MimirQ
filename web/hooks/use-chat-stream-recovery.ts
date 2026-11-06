import type { ConversationDetail, Message } from '@/types/chat'

type RecoverStreamedAssistantMessageOptions = Readonly<{
  conversationId: string
  requestId: string
  getMessages: (conversationId: string, params?: { limit?: number }) => Promise<ConversationDetail>
  signal?: AbortSignal
  attempts?: number
  delayMs?: number
  limit?: number
  wait?: (delayMs: number, signal?: AbortSignal) => Promise<void>
}>

function sleep(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise<void>((resolve) => {
    const finish = () => {
      globalThis.clearTimeout(timer)
      signal?.removeEventListener('abort', finish)
      resolve()
    }
    const timer = globalThis.setTimeout(finish, delayMs)
    if (signal?.aborted) finish()
    else signal?.addEventListener('abort', finish, { once: true })
  })
}

function getMessageRequestId(message: Message): string {
  const value = message.message_metadata?.request_id
  return typeof value === 'string' ? value.trim() : ''
}

export async function recoverStreamedAssistantMessage({
  conversationId,
  requestId,
  getMessages,
  signal,
  attempts = 4,
  delayMs = 500,
  limit = 40,
  wait = sleep,
}: RecoverStreamedAssistantMessageOptions): Promise<Message | null> {
  const trimmedConversationId = String(conversationId || '').trim()
  const trimmedRequestId = String(requestId || '').trim()

  if (!trimmedConversationId || !trimmedRequestId) return null

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (signal?.aborted) return null
    const response = await getMessages(trimmedConversationId, { limit })
    if (signal?.aborted) return null
    const recovered = (response.messages || []).find((message) => {
      return message.role === 'assistant' && getMessageRequestId(message) === trimmedRequestId
    })

    if (recovered) return recovered

    if (attempt < attempts - 1) {
      await wait(delayMs, signal)
    }
  }

  return null
}
