// @vitest-environment happy-dom

import React, { act, useRef, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Message } from '@/types'
import { API_LONG_TIMEOUT_MS, API_TIMEOUT_MS } from '@/lib/env'
import type { ApiRequestOptions } from '@/lib/api/core'
import { renderHook, waitForAssertion } from '@/test/hook-harness'
import { createChatStreamFixture } from '@/test/chat-stream-fixture'
import { EventType, type Event as AguiEvent, type ToolCallResultEvent } from '@ag-ui/core'
import { EventSchema } from '@ag-ui/core/schemas'

const chatApiMock = vi.hoisted(() => ({
  chat: vi.fn(),
  getMessages: vi.fn(),
  streamChat: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))

const recoveryMock = vi.hoisted(() => ({
  recoverStreamedAssistantMessage: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  chatApi: chatApiMock,
}))
vi.mock('@/lib/api/chat', () => ({ chatApi: chatApiMock }))

vi.mock('@/lib/client-logging', () => ({
  reportClientError: vi.fn(),
  reportClientWarning: vi.fn(),
}))

vi.mock('./use-chat-stream-recovery', () => recoveryMock)

import { useChatStream } from './use-chat-stream'

function createAbortError() {
  const error = new Error('aborted')
  error.name = 'AbortError'
  return error
}

function createAssistantMessage(id: string, requestId: string, content: string): Message {
  return {
    id,
    role: 'assistant',
    content,
    created_at: '2026-07-24T00:00:00Z',
    message_metadata: {
      request_id: requestId,
    },
  }
}

function createFallbackResponse() {
  return {
    assistant_message_id: 'assistant-fallback',
    request_id: 'req-fallback-chat',
    conversation_id: 'conv-fallback',
    content: 'fallback answer',
    citations: [],
    total_tokens: 0,
    total_chars: 15,
    metrics: {},
    structured: false,
  }
}

function renderChatStreamHook(onError = vi.fn(), structuredOutput = false) {
  return renderHook(() => {
    const [conversationId, setConversationId] = useState<string | undefined>()
    const [messages, setMessages] = useState<Message[]>([])
    const messagesRef = useRef(messages)
    messagesRef.current = messages

    const stream = useChatStream({
      conversationId,
      setConversationId,
      messagesRef,
      setMessages,
      onError,
      structuredOutput,
    })

    return {
      ...stream,
      conversationId,
      messages,
    }
  })
}

describe('useChatStream accepted-stream recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      return globalThis.setTimeout(() => callback(0), 0)
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
      globalThis.clearTimeout(id)
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
  })

  it('keeps an accepted stream alive past the short timeout before the first event', async () => {
    vi.useFakeTimers()
    const onError = vi.fn()
    let rejectStream: ((reason?: unknown) => void) | null = null

    chatApiMock.streamChat.mockImplementation(
      async (
        _request: unknown,
        _onJson: unknown,
        options?: { signal?: AbortSignal; onOpen?: (meta: { requestId: string; conversationId?: string }) => void },
      ) => {
        options?.onOpen?.(createChatStreamFixture({ requestId: 'req-accepted', threadId: 'conv-accepted' }).opened)
        return await new Promise<never>((_resolve, reject) => {
          rejectStream = reject
          options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
        })
      },
    )
    recoveryMock.recoverStreamedAssistantMessage.mockResolvedValue(
      createAssistantMessage('assistant-recovered', 'req-accepted', 'recovered answer'),
    )

    const hook = renderChatStreamHook(onError)

    act(() => {
      void hook.result.current.sendMessage('hello')
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(hook.result.current.isLoading).toBe(true)

    await act(async () => {
      vi.advanceTimersByTime(API_TIMEOUT_MS + 1)
      await Promise.resolve()
    })

    expect(recoveryMock.recoverStreamedAssistantMessage).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
    expect(hook.result.current.isLoading).toBe(true)

    await act(async () => {
      rejectStream?.(createAbortError())
      await Promise.resolve()
    })

    await waitForAssertion(() => {
      expect(recoveryMock.recoverStreamedAssistantMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          conversationId: 'conv-accepted',
          requestId: 'req-accepted',
        }),
      )
      expect(hook.result.current.messages.at(-1)).toMatchObject({
        id: 'assistant-recovered',
        content: 'recovered answer',
      })
      expect(hook.result.current.isLoading).toBe(false)
    })

    expect(chatApiMock.chat).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
    hook.unmount()
  })

  it('cancels the actual history recovery request when generation is stopped', async () => {
    const recovery = await vi.importActual<typeof import('./use-chat-stream-recovery')>('./use-chat-stream-recovery')
    recoveryMock.recoverStreamedAssistantMessage.mockImplementation(recovery.recoverStreamedAssistantMessage)
    chatApiMock.streamChat.mockImplementation(
      async (
        _request: unknown,
        _onJson: unknown,
        options: { onOpen: (meta: { requestId: string; conversationId: string }) => void },
      ) => {
        options.onOpen(
          createChatStreamFixture({ requestId: 'request-recovery', threadId: 'conversation-recovery' }).opened,
        )
        throw new Error('Stream disconnected')
      },
    )
    let signal: AbortSignal | undefined
    chatApiMock.getMessages.mockImplementation(
      (_conversationId: string, _params: unknown, options: ApiRequestOptions = {}) => {
        signal = options.signal
        return new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
        })
      },
    )
    const onError = vi.fn()
    const hook = renderChatStreamHook(onError)
    let sending!: boolean
    act(() => {
      sending = hook.result.current.sendMessage('hello')
    })
    await waitForAssertion(() => expect(signal?.aborted).toBe(false))

    await act(async () => {
      hook.result.current.stopGeneration()
      await sending
    })

    expect(signal?.aborted).toBe(true)
    expect(hook.result.current.isLoading).toBe(false)
    expect(onError).not.toHaveBeenCalled()
    hook.unmount()
  })

  it('times out an accepted stream that never emits an event', async () => {
    vi.useFakeTimers()
    const onError = vi.fn()

    chatApiMock.streamChat.mockImplementation(
      async (
        _request: unknown,
        _onJson: unknown,
        options?: { signal?: AbortSignal; onOpen?: (meta: { requestId: string; conversationId?: string }) => void },
      ) => {
        options?.onOpen?.(createChatStreamFixture({ requestId: 'req-silent', threadId: 'conv-silent' }).opened)
        return await new Promise<never>((_resolve, reject) => {
          options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
        })
      },
    )
    recoveryMock.recoverStreamedAssistantMessage.mockResolvedValue(null)

    const hook = renderChatStreamHook(onError)

    act(() => {
      void hook.result.current.sendMessage('hello')
    })

    await act(async () => {
      await Promise.resolve()
      vi.advanceTimersByTime(API_LONG_TIMEOUT_MS + 1)
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(onError).toHaveBeenCalledWith('Request timed out (request_id=req-silent)')
    expect(hook.result.current.isLoading).toBe(false)
    hook.unmount()
  })

  it('does not replay an accepted request when recovery finds nothing', async () => {
    const onError = vi.fn()
    let rejectStream: ((reason?: unknown) => void) | null = null

    chatApiMock.streamChat.mockImplementation(
      async (
        _request: unknown,
        _onJson: unknown,
        options?: { signal?: AbortSignal; onOpen?: (meta: { requestId: string; conversationId?: string }) => void },
      ) => {
        options?.onOpen?.(createChatStreamFixture({ requestId: 'req-stream', threadId: 'conv-stream' }).opened)
        return await new Promise<never>((_resolve, reject) => {
          rejectStream = reject
          options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
        })
      },
    )
    recoveryMock.recoverStreamedAssistantMessage.mockResolvedValue(null)

    const hook = renderChatStreamHook(onError)

    act(() => {
      void hook.result.current.sendMessage('hello')
    })

    await act(async () => {
      rejectStream?.(createAbortError())
      await Promise.resolve()
    })

    await waitForAssertion(() => {
      expect(recoveryMock.recoverStreamedAssistantMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          conversationId: 'conv-stream',
          requestId: 'req-stream',
        }),
      )
      expect(onError).toHaveBeenCalledWith(
        'Chat stream interrupted before completion and could not be recovered (request_id=req-stream)',
      )
    })

    expect(chatApiMock.chat).not.toHaveBeenCalled()
    hook.unmount()
  })

  it('ignores a second send before the loading state rerenders', async () => {
    chatApiMock.streamChat.mockImplementation(
      async (_request: unknown, _onJson: unknown, options?: { signal?: AbortSignal }) => {
        return await new Promise<never>((_resolve, reject) => {
          options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
        })
      },
    )

    const hook = renderChatStreamHook()

    act(() => {
      void hook.result.current.sendMessage('first')
      void hook.result.current.sendMessage('second')
    })

    expect(chatApiMock.streamChat).toHaveBeenCalledTimes(1)
    expect(hook.result.current.messages.filter((message) => message.role === 'user')).toHaveLength(1)

    act(() => {
      hook.result.current.stopGeneration()
    })
    await waitForAssertion(() => {
      expect(hook.result.current.isLoading).toBe(false)
    })
    hook.unmount()
  })

  it('preserves user-stop semantics for partial streamed content', async () => {
    const onError = vi.fn()

    chatApiMock.streamChat.mockImplementation(
      async (
        _request: unknown,
        onJson: (json: string) => void,
        options?: { signal?: AbortSignal; onOpen?: (meta: { requestId: string; conversationId?: string }) => void },
      ) => {
        const run = createChatStreamFixture({ requestId: 'req-stop', threadId: 'conv-stop' })
        const opened = { ...run.opened, assistantMessageId: undefined }
        options?.onOpen?.(opened)
        run.start(onJson)
        onJson(run.text('partial answer'))
        return await new Promise<never>((_resolve, reject) => {
          options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
        })
      },
    )

    const hook = renderChatStreamHook(onError)

    act(() => {
      void hook.result.current.sendMessage('hello')
    })

    await act(async () => {
      await Promise.resolve()
    })

    act(() => {
      hook.result.current.stopGeneration()
    })

    await waitForAssertion(() => {
      expect(hook.result.current.messages.at(-1)).toMatchObject({
        role: 'assistant',
        content: 'partial answer',
        message_metadata: { stopped: true },
      })
      expect(hook.result.current.isLoading).toBe(false)
    })

    expect(recoveryMock.recoverStreamedAssistantMessage).not.toHaveBeenCalled()
    expect(chatApiMock.chat).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
    hook.unmount()
  })

  it.each([true, false])('keeps tool execution and domain results visible when tool success is %s', async (success) => {
    const run = createChatStreamFixture()
    const pending = Promise.withResolvers<void>()
    let emit!: (json: string) => void
    chatApiMock.streamChat.mockImplementation(async (_request, onJson, options) => {
      emit = onJson
      run.start(onJson, options.onOpen)
      onJson(run.event({ type: EventType.CUSTOM, name: 'ragvia.event', value: { message: '检索中' } }))
      onJson(
        run.event({
          type: EventType.CUSTOM,
          name: 'ragvia.citations',
          value: [{ document_id: 'document-1', document_name: 'Doc', chunk_content: 'Evidence', relevance_score: 0.9 }],
        }),
      )
      onJson(
        run.event({
          type: EventType.TOOL_CALL_START,
          toolCallId: 'tool-1',
          toolCallName: 'knowledge_search',
          parentMessageId: run.opened.assistantMessageId,
        }),
      )
      onJson(run.event({ type: EventType.TOOL_CALL_ARGS, toolCallId: 'tool-1', delta: '{"query":' }))
      onJson(run.event({ type: EventType.TOOL_CALL_ARGS, toolCallId: 'tool-1', delta: '"policy"}' }))
      onJson(run.event({ type: EventType.TOOL_CALL_END, toolCallId: 'tool-1' }))
      return pending.promise
    })
    const onError = vi.fn()
    const hook = renderChatStreamHook(onError, true)
    act(() => {
      hook.result.current.sendMessage('question')
    })

    expect(hook.result.current.currentSteps).toEqual(['检索中', '工具调用：knowledge_search'])
    expect(hook.result.current.currentCitations[0].document_id).toBe('document-1')
    await act(async () => {
      emit(
        run.event({
          type: EventType.TOOL_CALL_RESULT,
          toolCallId: 'tool-1',
          messageId: 'tool-result-1',
          content: '{"status":"complete"}',
          metadata: { success, error: success ? null : 'tool unavailable' },
        }),
      )
      emit(run.text('raw response'))
      run.finish(emit, { structured_data: { summary: 'answer' }, total_tokens: 12, metrics: {} })
      pending.resolve()
      await pending.promise
    })

    expect(hook.result.current.messages.at(-1)).toMatchObject({
      id: run.opened.assistantMessageId,
      content: '```json\n{\n  "summary": "answer"\n}\n```',
      steps: [
        '检索中',
        '工具调用：knowledge_search',
        success ? '工具完成：knowledge_search' : '工具失败：knowledge_search：tool unavailable',
      ],
      citations: [{ document_id: 'document-1' }],
      message_metadata: { total_tokens: 12, request_id: run.opened.requestId },
    })
    expect(onError).not.toHaveBeenCalled()
    hook.unmount()
  })

  it.each([
    { name: 'missing', result: undefined },
    { name: 'string', result: 'completed' },
    { name: 'number', result: 42 },
    { name: 'array', result: ['completed'] },
  ])('accepts standard events without metadata and a $name run result', async ({ result }) => {
    const run = createChatStreamFixture()
    chatApiMock.streamChat.mockImplementation(async (_request, onJson, options) => {
      options.onOpen({ ...run.opened, assistantMessageId: undefined })
      const events: AguiEvent[] = [
        { type: EventType.RUN_STARTED, threadId: run.opened.conversationId, runId: run.opened.runId },
        { type: EventType.TEXT_MESSAGE_START, messageId: run.opened.assistantMessageId, role: 'assistant' },
        { type: EventType.TEXT_MESSAGE_CONTENT, messageId: run.opened.assistantMessageId, delta: 'standard answer' },
        { type: EventType.TEXT_MESSAGE_END, messageId: run.opened.assistantMessageId },
        { type: EventType.RUN_FINISHED, threadId: run.opened.conversationId, runId: run.opened.runId, result },
      ]
      for (const event of events) onJson(JSON.stringify(EventSchema.parse(event)))
    })
    const onError = vi.fn()
    const hook = renderChatStreamHook(onError)
    await act(async () => {
      hook.result.current.sendMessage('question')
    })

    const message = hook.result.current.messages.at(-1)
    expect(message).toMatchObject({ id: run.opened.assistantMessageId, role: 'assistant', content: 'standard answer' })
    expect(message?.message_metadata).not.toHaveProperty('total_tokens')
    expect(onError).not.toHaveBeenCalled()
    expect(recoveryMock.recoverStreamedAssistantMessage).not.toHaveBeenCalled()
    expect(hook.result.current.isLoading).toBe(false)
    hook.unmount()
  })

  it.each([
    { name: 'text', content: 'tool output' },
    { name: 'parts', content: [{ type: 'text', text: 'tool output' }] },
  ] satisfies Array<{ name: string; content: ToolCallResultEvent['content'] }>)(
    'shows a neutral tool result for standard $name content without success metadata',
    async ({ content }) => {
      const run = createChatStreamFixture()
      chatApiMock.streamChat.mockImplementation(async (_request, onJson, options) => {
        options.onOpen(run.opened)
        const events: AguiEvent[] = [
          { type: EventType.RUN_STARTED, threadId: run.opened.conversationId, runId: run.opened.runId },
          { type: EventType.TEXT_MESSAGE_START, messageId: run.opened.assistantMessageId, role: 'assistant' },
          { type: EventType.TOOL_CALL_START, toolCallId: 'tool-1', toolCallName: 'search' },
          { type: EventType.TOOL_CALL_ARGS, toolCallId: 'tool-1', delta: '{}' },
          { type: EventType.TOOL_CALL_END, toolCallId: 'tool-1' },
          { type: EventType.TOOL_CALL_RESULT, toolCallId: 'tool-1', messageId: 'tool-result-1', content },
          { type: EventType.TEXT_MESSAGE_CONTENT, messageId: run.opened.assistantMessageId, delta: 'answer' },
          { type: EventType.TEXT_MESSAGE_END, messageId: run.opened.assistantMessageId },
          { type: EventType.RUN_FINISHED, threadId: run.opened.conversationId, runId: run.opened.runId },
        ]
        for (const event of events) onJson(JSON.stringify(EventSchema.parse(event)))
      })
      const onError = vi.fn()
      const hook = renderChatStreamHook(onError)
      await act(async () => {
        hook.result.current.sendMessage('question')
      })

      expect(hook.result.current.messages.at(-1)).toMatchObject({
        content: 'answer',
        steps: ['工具调用：search', '工具结果：search'],
      })
      expect(onError).not.toHaveBeenCalled()
      hook.unmount()
    },
  )

  it('keeps a cancelled run as a stopped partial answer without requiring closed text or tool results', async () => {
    const run = createChatStreamFixture()
    let signal: AbortSignal | undefined
    chatApiMock.streamChat.mockImplementation(async (_request, onJson, options) => {
      signal = options.signal
      options.onOpen({ ...run.opened, assistantMessageId: undefined })
      const events: AguiEvent[] = [
        { type: EventType.RUN_STARTED, threadId: run.opened.conversationId, runId: run.opened.runId },
        { type: EventType.TEXT_MESSAGE_START, messageId: run.opened.assistantMessageId, role: 'assistant' },
        { type: EventType.TEXT_MESSAGE_CONTENT, messageId: run.opened.assistantMessageId, delta: 'partial answer' },
        { type: EventType.TOOL_CALL_START, toolCallId: 'tool-1', toolCallName: 'search' },
        { type: EventType.TOOL_CALL_ARGS, toolCallId: 'tool-1', delta: '{}' },
        { type: EventType.TOOL_CALL_END, toolCallId: 'tool-1' },
        {
          type: EventType.RUN_FINISHED,
          threadId: run.opened.conversationId,
          runId: run.opened.runId,
          outcome: { type: 'cancelled' },
        },
      ]
      for (const event of events) onJson(JSON.stringify(EventSchema.parse(event)))
    })
    const onError = vi.fn()
    const hook = renderChatStreamHook(onError)
    await act(async () => {
      hook.result.current.sendMessage('question')
    })

    expect(hook.result.current.messages.at(-1)).toMatchObject({
      id: `local-assistant:${run.opened.assistantMessageId}`,
      role: 'assistant',
      content: 'partial answer',
      steps: ['工具调用：search'],
      message_metadata: { stopped: true },
    })
    expect(signal?.aborted).toBe(true)
    expect(hook.result.current.isLoading).toBe(false)
    expect(onError).not.toHaveBeenCalled()
    expect(chatApiMock.chat).not.toHaveBeenCalled()
    expect(recoveryMock.recoverStreamedAssistantMessage).not.toHaveBeenCalled()
    hook.unmount()
  })

  it('accepts cancellation before a text message starts without inventing an assistant response', async () => {
    const run = createChatStreamFixture()
    chatApiMock.streamChat.mockImplementation(async (_request, onJson, options) => {
      options.onOpen({ ...run.opened, assistantMessageId: undefined })
      onJson(
        JSON.stringify(
          EventSchema.parse({
            type: EventType.RUN_STARTED,
            threadId: run.opened.conversationId,
            runId: run.opened.runId,
          }),
        ),
      )
      onJson(
        JSON.stringify(
          EventSchema.parse({
            type: EventType.RUN_FINISHED,
            threadId: run.opened.conversationId,
            runId: run.opened.runId,
            outcome: { type: 'cancelled' },
          }),
        ),
      )
    })
    const onError = vi.fn()
    const hook = renderChatStreamHook(onError)
    await act(async () => {
      hook.result.current.sendMessage('question')
    })

    expect(hook.result.current.messages.map((message) => message.role)).toEqual(['user'])
    expect(hook.result.current.isLoading).toBe(false)
    expect(onError).not.toHaveBeenCalled()
    expect(recoveryMock.recoverStreamedAssistantMessage).not.toHaveBeenCalled()
    hook.unmount()
  })

  it('reports an interrupt outcome without committing success or recovering history', async () => {
    const run = createChatStreamFixture()
    chatApiMock.streamChat.mockImplementation(async (_request, onJson, options) => {
      run.start(onJson, options.onOpen)
      onJson(run.text('pending approval'))
      onJson(
        run.event({
          type: EventType.RUN_FINISHED,
          threadId: run.opened.conversationId,
          runId: run.opened.runId,
          outcome: {
            type: 'interrupt',
            interrupts: [{ id: 'approval-1', reason: 'approval', message: 'Approve tool?' }],
          },
        }),
      )
    })
    const onError = vi.fn()
    const hook = renderChatStreamHook(onError)
    await act(async () => {
      hook.result.current.sendMessage('question')
    })

    expect(hook.result.current.messages.map((message) => message.role)).toEqual(['user'])
    expect(onError).toHaveBeenCalledWith(
      `当前运行需要用户输入，但聊天暂不支持继续被中断的运行 (request_id=${run.opened.requestId})`,
    )
    expect(hook.result.current.isLoading).toBe(false)
    expect(chatApiMock.chat).not.toHaveBeenCalled()
    expect(recoveryMock.recoverStreamedAssistantMessage).not.toHaveBeenCalled()
    hook.unmount()
  })

  it.each([
    'old-wire',
    'foreign-run',
    'foreign-message',
    'early-finish',
    'duplicate-tool',
    'invalid-tool-status',
    'foreign-finish',
    'invalid-null-result',
    'foreign-cancel',
  ] as const)('rejects %s without committing another response or replaying the request', async (kind) => {
    const run = createChatStreamFixture()
    chatApiMock.streamChat.mockImplementation(async (_request, onJson, options) => {
      run.start(onJson, options.onOpen)
      if (kind === 'old-wire') onJson(JSON.stringify({ type: 'token', data: { content: 'wrong response' } }))
      if (kind === 'foreign-run')
        onJson(
          run.event({
            type: EventType.TEXT_MESSAGE_CONTENT,
            messageId: run.opened.assistantMessageId,
            delta: 'wrong response',
            metadata: { runId: 'another-run' },
          }),
        )
      if (kind === 'foreign-message')
        onJson(
          run.event({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: 'another-message', delta: 'wrong response' }),
        )
      if (kind === 'early-finish')
        onJson(
          run.event({
            type: EventType.RUN_FINISHED,
            threadId: run.opened.conversationId,
            runId: run.opened.runId,
            result: {},
          }),
        )
      if (kind === 'duplicate-tool') {
        const start = run.event({ type: EventType.TOOL_CALL_START, toolCallId: 'tool-1', toolCallName: 'search' })
        onJson(start)
        onJson(start)
      }
      if (kind === 'invalid-tool-status') {
        onJson(run.event({ type: EventType.TOOL_CALL_START, toolCallId: 'tool-1', toolCallName: 'search' }))
        onJson(run.event({ type: EventType.TOOL_CALL_ARGS, toolCallId: 'tool-1', delta: '{}' }))
        onJson(run.event({ type: EventType.TOOL_CALL_END, toolCallId: 'tool-1' }))
        onJson(
          run.event({
            type: EventType.TOOL_CALL_RESULT,
            toolCallId: 'tool-1',
            messageId: 'result-1',
            content: 'output',
            metadata: { success: 'yes' },
          }),
        )
      }
      if (kind === 'foreign-finish') {
        onJson(run.event({ type: EventType.TEXT_MESSAGE_END, messageId: run.opened.assistantMessageId }))
        onJson(
          JSON.stringify(
            EventSchema.parse({
              type: EventType.RUN_FINISHED,
              threadId: run.opened.conversationId,
              runId: 'foreign-run',
            }),
          ),
        )
      }
      if (kind === 'invalid-null-result') {
        onJson(run.event({ type: EventType.TEXT_MESSAGE_END, messageId: run.opened.assistantMessageId }))
        onJson(
          JSON.stringify({
            type: EventType.RUN_FINISHED,
            threadId: run.opened.conversationId,
            runId: run.opened.runId,
            result: null,
          }),
        )
      }
      if (kind === 'foreign-cancel') {
        onJson(
          JSON.stringify(
            EventSchema.parse({
              type: EventType.RUN_FINISHED,
              threadId: run.opened.conversationId,
              runId: 'foreign-run',
              outcome: { type: 'cancelled' },
            }),
          ),
        )
      }
    })
    const onError = vi.fn()
    const hook = renderChatStreamHook(onError)
    await act(async () => {
      hook.result.current.sendMessage('question')
    })

    expect(onError).toHaveBeenCalledOnce()
    expect(hook.result.current.messages.map((message) => message.role)).toEqual(['user'])
    expect(hook.result.current.currentResponse).not.toContain('wrong response')
    expect(chatApiMock.chat).not.toHaveBeenCalled()
    expect(recoveryMock.recoverStreamedAssistantMessage).not.toHaveBeenCalled()
    hook.unmount()
  })
})
