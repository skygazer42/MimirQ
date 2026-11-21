import type { Message } from '@/types/chat'
import type { chatApi } from '@/lib/api/chat'
import { matchesResourceId } from '@/lib/resource-id'

type RecoverStreamedAssistantMessageOptions = Readonly<{
  conversationId?: string
  requestId?: string
  getMessages: typeof chatApi.getMessages
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
  if (conversationId === undefined || requestId === undefined) return null
  const trimmedConversationId = conversationId.trim()
  const trimmedRequestId = requestId.trim()

  if (trimmedConversationId.length === 0 || trimmedRequestId.length === 0) return null

  try {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      if (signal?.aborted) return null
      const response = await getMessages(trimmedConversationId, { limit }, { signal })
      if (signal?.aborted) return null
      if (!matchesResourceId(response.conversation_id, trimmedConversationId)) {
        throw new Error('Chat recovery history belongs to another conversation')
      }

      const recovered = response.messages.find(
        (message) => message.role === 'assistant' && message.message_metadata?.request_id?.trim() === trimmedRequestId,
      )
      if (recovered !== undefined) return recovered

      if (attempt < attempts - 1) await wait(delayMs, signal)
    }
  } catch (error) {
    if (signal?.aborted) return null
    throw error
  }

  return null
}
