import { describe, expect, it, vi } from 'vitest'

import type { Message } from '@/types'
import { recoverStreamedAssistantMessage } from './use-chat-stream-recovery'

function makeMessage(partial: Partial<Message>): Message {
  return {
    id: partial.id || 'message-1',
    role: partial.role || 'assistant',
    content: partial.content || '',
    citations: partial.citations,
    steps: partial.steps,
    message_metadata: partial.message_metadata,
    created_at: partial.created_at || new Date().toISOString(),
  }
}

describe('recoverStreamedAssistantMessage', () => {
  it('returns a persisted assistant turn matched by request_id', async () => {
    const assistantMessage = makeMessage({
      id: 'assistant-1',
      role: 'assistant',
      content: 'Recovered answer',
      message_metadata: { request_id: 'req-1' },
    })

    const getMessages = vi.fn().mockResolvedValue({
      conversation_id: 'conv-1',
      messages: [assistantMessage],
      returned: 1,
      has_more: false,
    })

    await expect(
      recoverStreamedAssistantMessage({
        conversationId: 'conv-1',
        requestId: 'req-1',
        getMessages,
      })
    ).resolves.toEqual(assistantMessage)
  })

  it('retries until the assistant turn is persisted', async () => {
    const getMessages = vi
      .fn()
      .mockResolvedValueOnce({
        conversation_id: 'conv-1',
        messages: [makeMessage({ id: 'user-1', role: 'user', content: 'hello' })],
        returned: 1,
        has_more: false,
      })
      .mockResolvedValueOnce({
        conversation_id: 'conv-1',
        messages: [
          makeMessage({ id: 'user-1', role: 'user', content: 'hello' }),
          makeMessage({
            id: 'assistant-1',
            role: 'assistant',
            content: 'Recovered answer',
            message_metadata: { request_id: 'req-2' },
          }),
        ],
        returned: 2,
        has_more: false,
      })
    const wait = vi.fn().mockResolvedValue(undefined)

    const recovered = await recoverStreamedAssistantMessage({
      conversationId: 'conv-1',
      requestId: 'req-2',
      getMessages,
      wait,
      attempts: 2,
      delayMs: 1,
    })

    expect(recovered?.id).toBe('assistant-1')
    expect(getMessages).toHaveBeenCalledTimes(2)
    expect(wait).toHaveBeenCalledTimes(1)
  })

  it('returns null when the persisted turn never appears', async () => {
    const getMessages = vi.fn().mockResolvedValue({
      conversation_id: 'conv-1',
      messages: [makeMessage({ id: 'assistant-1', message_metadata: { request_id: 'other' } })],
      returned: 1,
      has_more: false,
    })
    const wait = vi.fn().mockResolvedValue(undefined)

    await expect(
      recoverStreamedAssistantMessage({
        conversationId: 'conv-1',
        requestId: 'req-missing',
        getMessages,
        wait,
        attempts: 3,
        delayMs: 1,
      })
    ).resolves.toBeNull()

    expect(getMessages).toHaveBeenCalledTimes(3)
    expect(wait).toHaveBeenCalledTimes(2)
  })
})
