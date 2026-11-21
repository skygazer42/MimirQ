import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunAgentInputSchema } from '@ag-ui/core/schemas'

import { chatApi } from './api/chat'
import { createChatStreamFixture } from '@/test/chat-stream-fixture'

const originalFetch = globalThis.fetch

describe('chatApi.streamChat', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('surfaces request and conversation ids as soon as the stream opens', async () => {
    const run = createChatStreamFixture({ requestId: 'req-stream-1' })
    const expectedEvents: string[] = []
    run.start((event) => expectedEvents.push(event))
    run.finish((event) => expectedEvents.push(event))

    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(expectedEvents.map((event) => `data: ${event}\n\n`).join(''), {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'X-Request-ID': 'req-stream-1',
          'X-Conversation-ID': run.opened.conversationId,
          'X-Assistant-Message-ID': run.opened.assistantMessageId,
        },
      }),
    ) as typeof fetch

    const onOpen = vi.fn()
    const events: string[] = []

    const result = await chatApi.streamChat(
      { message: 'hello', stream: true, conversation_id: run.opened.conversationId },
      (json) => events.push(json),
      { onOpen },
    )

    expect(onOpen).toHaveBeenCalledWith({
      requestId: 'req-stream-1',
      conversationId: run.opened.conversationId,
      runId: expect.any(String),
      assistantMessageId: run.opened.assistantMessageId,
    })
    expect(events).toEqual(expectedEvents)
    expect(result).toEqual({
      requestId: 'req-stream-1',
      conversationId: run.opened.conversationId,
      runId: expect.any(String),
      assistantMessageId: run.opened.assistantMessageId,
    })
  })

  it.each([
    { name: 'LF', lineEnding: '\n' },
    { name: 'CRLF', lineEnding: '\r\n' },
  ])('delivers $name events when UTF-8 bytes and line endings cross network chunks', async ({ lineEnding }) => {
    const run = createChatStreamFixture()
    const events: string[] = []
    run.start((event) => events.push(event))
    events.push(run.text('你好'))
    run.finish((event) => events.push(event))
    const bytes = new TextEncoder().encode(events.map((event) => `data: ${event}${lineEnding}${lineEnding}`).join(''))
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte))
        controller.close()
      },
    })
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })) as typeof fetch
    const received: string[] = []

    await chatApi.streamChat({ message: 'hello', stream: true }, (json) => received.push(json))

    expect(received).toEqual(events)
  })

  it('sends standard run input with fresh UUIDs and forwards only business configuration', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async () => new Response('', { headers: { 'Content-Type': 'text/event-stream' } }))
    globalThis.fetch = fetchMock
    const request = {
      message: 'current question',
      history: [{ role: 'assistant' as const, content: 'prior answer' }],
      stream: true,
      dataset_id: 'dataset-1',
      document_ids: ['document-1'],
      structured_output: true,
      rag_config: { top_k: 8 },
    }

    const messages = [
      { id: 'existing-message', role: 'assistant' as const, content: 'prior answer' },
      { id: 'current-message', role: 'user' as const, content: 'current question' },
    ]
    await chatApi.streamChat(request, () => {}, { messages })
    await chatApi.streamChat(request, () => {}, { messages })

    const inputs = fetchMock.mock.calls.map(([, options]) => RunAgentInputSchema.parse(JSON.parse(options.body)))
    expect(inputs[0]).toMatchObject({
      state: {},
      tools: [],
      context: [],
      messages: [
        { id: 'existing-message', role: 'assistant', content: 'prior answer' },
        { id: 'current-message', role: 'user', content: 'current question' },
      ],
      forwardedProps: {
        dataset_id: 'dataset-1',
        document_ids: ['document-1'],
        structured_output: true,
        rag_config: { top_k: 8 },
      },
    })
    expect(inputs[0].threadId).toMatch(/^[0-9a-f-]{36}$/)
    expect(inputs[0].runId).toMatch(/^[0-9a-f-]{36}$/)
    expect(inputs[0].runId).not.toBe(inputs[1].runId)
    expect(inputs[0].threadId).not.toBe(inputs[1].threadId)
    expect(inputs[0].messages.map((message) => message.id)).toEqual(inputs[1].messages.map((message) => message.id))
    expect(inputs[0].forwardedProps).not.toHaveProperty('message')
    expect(inputs[0].forwardedProps).not.toHaveProperty('history')
    expect(inputs[0].forwardedProps).not.toHaveProperty('conversation_id')
    expect(inputs[0].forwardedProps).not.toHaveProperty('stream')
  })

  it('rejects history without stable message IDs before making a request', async () => {
    const fetchMock = vi.fn()
    globalThis.fetch = fetchMock

    await expect(
      chatApi.streamChat({ message: 'question', history: [{ role: 'user', content: 'prior question' }] }, () => {}),
    ).rejects.toThrow('Chat history requires stable message IDs')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects another conversation response and releases its stream', async () => {
    const cancelled = vi.fn()
    const body = new ReadableStream<Uint8Array>({ cancel: cancelled })
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(body, {
        headers: { 'Content-Type': 'text/event-stream', 'X-Conversation-ID': 'another-conversation' },
      }),
    )
    const onOpen = vi.fn()

    await expect(chatApi.streamChat({ message: 'question' }, () => {}, { onOpen })).rejects.toThrow(
      'AG-UI response belongs to another conversation',
    )
    expect(onOpen).not.toHaveBeenCalled()
    expect(cancelled).toHaveBeenCalledOnce()
  })
})
