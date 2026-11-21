import { EventType, type Event } from '@ag-ui/core'
import { EventSchema } from '@ag-ui/core/schemas'

export function createChatStreamFixture({
  threadId = '00000000-0000-4000-8000-000000000001',
  runId = '00000000-0000-4000-8000-000000000002',
  requestId = 'request-test',
  messageId = '00000000-0000-4000-8000-000000000003',
} = {}) {
  const metadata = { threadId, runId, requestId, assistantMessageId: messageId }
  const opened = { conversationId: threadId, runId, requestId, assistantMessageId: messageId }

  function event(value: Event) {
    return JSON.stringify(EventSchema.parse({ ...value, metadata: { ...metadata, ...value.metadata } }))
  }

  return {
    opened,
    event,
    start(emit: (value: string) => void, onOpen?: (value: typeof opened) => void) {
      onOpen?.(opened)
      emit(event({ type: EventType.RUN_STARTED, threadId, runId }))
      emit(event({ type: EventType.TEXT_MESSAGE_START, messageId, role: 'assistant' }))
    },
    text(delta: string) {
      return event({ type: EventType.TEXT_MESSAGE_CONTENT, messageId, delta })
    },
    finish(emit: (value: string) => void, result: Record<string, unknown> = {}) {
      emit(event({ type: EventType.TEXT_MESSAGE_END, messageId }))
      emit(event({ type: EventType.RUN_FINISHED, threadId, runId, result }))
    },
    error(message: string) {
      return event({ type: EventType.RUN_ERROR, message })
    },
  }
}
