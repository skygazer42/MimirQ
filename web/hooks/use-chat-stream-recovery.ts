import type { Message } from '@/types'

type GetMessagesResult = {
  conversation_id: string
  messages: Message[]
  returned?: number
  has_more?: boolean
}

type RecoverStreamedAssistantMessageOptions = Readonly<{
  conversationId: string
  requestId: string
  getMessages: (conversationId: string, params?: { limit?: number }) => Promise<GetMessagesResult>
  attempts?: number
  delayMs?: number
  limit?: number
  wait?: (delayMs: number) => Promise<void>
}>

function sleep(delayMs: number) {
  return new Promise<void>((resolve) => {
    globalThis.setTimeout(resolve, delayMs)
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
  attempts = 4,
  delayMs = 500,
  limit = 40,
  wait = sleep,
}: RecoverStreamedAssistantMessageOptions): Promise<Message | null> {
  const trimmedConversationId = String(conversationId || '').trim()
  const trimmedRequestId = String(requestId || '').trim()

  if (!trimmedConversationId || !trimmedRequestId) return null

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const response = await getMessages(trimmedConversationId, { limit })
    const recovered = (response.messages || []).find((message) => {
      return message.role === 'assistant' && getMessageRequestId(message) === trimmedRequestId
    })

    if (recovered) return recovered

    if (attempt < attempts - 1) {
      await wait(delayMs)
    }
  }

  return null
}
