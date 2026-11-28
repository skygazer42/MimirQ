// @vitest-environment happy-dom

import React, { act, useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChatResponse, Message } from '@/types/chat'
import { AUTH_SCOPE_CHANGED_EVENT } from '@/lib/auth-storage'
import { renderHook, waitForAssertion } from '@/test/hook-harness'
import { createChatStreamFixture } from '@/test/chat-stream-fixture'

const api = vi.hoisted(() => ({ chat: vi.fn(), getMessages: vi.fn(), streamChat: vi.fn() }))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({ chatApi: api }))
vi.mock('@/lib/api/chat', () => ({ chatApi: api }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn(), reportClientWarning: vi.fn() }))

import { useChat } from './use-chat'
import { recoverStreamedAssistantMessage } from './use-chat-stream-recovery'

const cleanup: Array<() => void> = []

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function assistant(id = 'old-assistant', content = 'old response'): Message {
  return {
    id,
    role: 'assistant',
    content,
    created_at: '2026-11-04T00:00:00Z',
    message_metadata: { request_id: 'old-request' },
  }
}

function response(): ChatResponse {
  return {
    assistant_message_id: 'old-assistant',
    conversation_id: 'old-conversation',
    request_id: 'old-request',
    content: 'old fallback',
    citations: [],
    total_tokens: 2,
    total_chars: 12,
    metrics: {},
    structured: false,
  }
}

function mount(options: Parameters<typeof useChat>[0] = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  })
  const hook = renderHook(() => useChat(options), {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  })
  cleanup.push(() => client.clear(), hook.unmount)
  return hook
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) =>
    globalThis.setTimeout(() => callback(0), 0),
  )
  vi.stubGlobal('cancelAnimationFrame', (id: number) => globalThis.clearTimeout(id))
})

afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('useChat conversation ownership', () => {
  it('preserves spaces and newlines from streamed token chunks', async () => {
    api.streamChat.mockImplementation(async (_request, onJson, options) => {
      const run = createChatStreamFixture({ messageId: 'assistant-a' })
      run.start(onJson, options.onOpen)
      for (const content of ['Hello', ' ', 'world', '\n', '  indented']) {
        onJson(run.text(content))
      }
      run.finish(onJson)
    })
    const hook = mount()

    await act(async () => hook.result.current.sendMessage('question'))

    expect(hook.result.current.messages.at(-1)?.content).toBe('Hello world\n  indented')
  })

  it('commits a done event once and notifies its conversation once', async () => {
    const onConversationId = vi.fn()
    api.streamChat.mockImplementation(async (_request, onJson, options) => {
      const run = createChatStreamFixture({
        requestId: 'request-a',
        threadId: 'conversation-a',
        messageId: 'assistant-a',
      })
      run.start(onJson, options.onOpen)
      onJson(run.text('answer'))
      run.finish(onJson, { conversation_id: 'conversation-a' })
      run.finish(onJson, { conversation_id: 'conversation-a' })
    })
    const hook = mount({ onConversationId })

    await act(async () => hook.result.current.sendMessage('question'))

    expect(hook.result.current.messages.filter((message) => message.role === 'assistant')).toHaveLength(1)
    expect(onConversationId.mock.calls).toEqual([['conversation-a']])
  })

  it('sends stable history IDs and the actual new user message ID to the stream boundary', async () => {
    api.streamChat.mockImplementation(async (_request, onJson, options) => {
      const run = createChatStreamFixture({
        runId: `run-${api.streamChat.mock.calls.length}`,
        messageId: `assistant-${api.streamChat.mock.calls.length}`,
      })
      run.start(onJson, options.onOpen)
      onJson(run.text('answer'))
      run.finish(onJson)
    })
    const hook = mount()
    await act(async () => {
      hook.result.current.sendMessage('first question')
    })
    const previous = [...hook.result.current.messages]
    await act(async () => {
      hook.result.current.sendMessage('second question')
    })

    expect(api.streamChat.mock.calls[0][2].messages[0].id).toBe(previous[0].id)
    expect(api.streamChat.mock.calls[1][2].messages).toEqual([
      ...previous.map(({ id, role, content }) => ({ id, role, content })),
      { id: hook.result.current.messages[2].id, role: 'user', content: 'second question' },
    ])
  })

  it('discards late stream callbacks after clearing messages', async () => {
    const completion = deferred<void>()
    let emit!: (json: string) => void
    api.streamChat.mockImplementation(async (_request, onJson) => {
      emit = onJson
      return completion.promise
    })
    const hook = mount()
    let sending!: boolean
    act(() => {
      sending = hook.result.current.sendMessage('old question')
    })
    act(() => hook.result.current.clearMessages())

    await act(async () => {
      const run = createChatStreamFixture({ messageId: 'old-assistant' })
      emit(run.text('late answer'))
      run.finish(emit)
      completion.resolve()
      await sending
    })

    expect(hook.result.current.messages).toEqual([])
    expect(hook.result.current.currentResponse).toBe('')
    expect(hook.result.current.isLoading).toBe(false)
  })

  it('keeps loaded history when an old stream reports done after navigation', async () => {
    const completion = deferred<void>()
    let emit!: (json: string) => void
    const onConversationId = vi.fn()
    api.streamChat.mockImplementation(async (_request, onJson, options) => {
      emit = onJson
      options.onOpen(createChatStreamFixture({ requestId: 'old-request', threadId: 'old-conversation' }).opened)
      return completion.promise
    })
    const currentMessage = assistant('new-assistant', 'new history')
    api.getMessages.mockResolvedValue({ conversation_id: 'new-conversation', messages: [currentMessage] })
    const hook = mount({ onConversationId })
    let sending!: boolean
    act(() => {
      sending = hook.result.current.sendMessage('old question')
    })
    await act(async () => hook.result.current.loadConversation('new-conversation'))

    await act(async () => {
      const run = createChatStreamFixture({ threadId: 'old-conversation', messageId: 'old-assistant' })
      emit(run.text('late old answer'))
      run.finish(emit, { conversation_id: 'old-conversation' })
      completion.resolve()
      await sending
    })

    expect(hook.result.current.conversationId).toBe('new-conversation')
    expect(hook.result.current.messages).toEqual([currentMessage])
    expect(onConversationId.mock.calls.at(-1)).toEqual(['new-conversation'])
  })

  it('discards a recovery response after the conversation is reset', async () => {
    const history = deferred<{ conversation_id: string; messages: Message[] }>()
    api.streamChat.mockImplementation(async (_request, _onJson, options) => {
      options.onOpen(createChatStreamFixture({ requestId: 'old-request', threadId: 'old-conversation' }).opened)
      throw new Error('stream disconnected')
    })
    api.getMessages.mockReturnValue(history.promise)
    const hook = mount()
    let sending!: boolean
    act(() => {
      sending = hook.result.current.sendMessage('old question')
    })
    await waitForAssertion(() => expect(api.getMessages).toHaveBeenCalledOnce())
    act(() => hook.result.current.resetConversation())

    await act(async () => {
      history.resolve({ conversation_id: 'old-conversation', messages: [assistant()] })
      await sending
    })

    expect(hook.result.current.messages).toEqual([])
    expect(hook.result.current.conversationId).toBeUndefined()
    expect(api.chat).not.toHaveBeenCalled()
  })

  it('stops recovery reads when the user stops generation', async () => {
    const history = deferred<{ conversation_id: string; messages: Message[] }>()
    api.streamChat.mockImplementation(async (_request, onJson, options) => {
      const run = createChatStreamFixture({ requestId: 'old-request', threadId: 'old-conversation' })
      run.start(onJson, options.onOpen)
      onJson(run.text('partial draft'))
      throw new Error('stream disconnected')
    })
    api.getMessages.mockReturnValueOnce(history.promise).mockResolvedValue({
      conversation_id: 'old-conversation',
      messages: [],
    })
    const hook = mount()
    let sending!: boolean
    act(() => {
      sending = hook.result.current.sendMessage('question')
    })
    await waitForAssertion(() => expect(api.getMessages).toHaveBeenCalledOnce())
    act(() => hook.result.current.stopGeneration())

    await act(async () => {
      history.resolve({ conversation_id: 'old-conversation', messages: [] })
      await sending
    })

    expect(api.getMessages).toHaveBeenCalledOnce()
    expect(api.chat).not.toHaveBeenCalled()
    expect(hook.result.current.messages.at(-1)).toMatchObject({
      content: 'partial draft',
      message_metadata: { stopped: true },
    })
  })

  it('does not replay an unconfirmed request and clears it when the conversation is reset', async () => {
    api.streamChat.mockRejectedValue(new Error('stream unavailable'))
    const onUnconfirmedMessage = vi.fn()
    const hook = mount({ onUnconfirmedMessage })
    let sending!: boolean
    act(() => {
      sending = hook.result.current.sendMessage('old question')
    })
    await waitForAssertion(() => expect(onUnconfirmedMessage).toHaveBeenCalledWith('old question'))
    expect(api.chat).not.toHaveBeenCalled()
    act(() => hook.result.current.resetConversation())
    await sending

    expect(hook.result.current.messages).toEqual([])
    expect(hook.result.current.conversationId).toBeUndefined()
  })

  it('does not replay an accepted request that reports a stream error', async () => {
    const onError = vi.fn()
    api.streamChat.mockImplementation(async (_request, onJson, options) => {
      const run = createChatStreamFixture({ requestId: 'old-request', threadId: 'old-conversation' })
      run.start(onJson, options.onOpen)
      onJson(run.error('generation failed'))
    })
    api.chat.mockResolvedValue(response())
    const hook = mount({ onError })

    await act(async () => hook.result.current.sendMessage('question'))

    expect(api.chat).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith('generation failed (request_id=old-request)')
    expect(hook.result.current.messages.map((message) => message.role)).toEqual(['user'])
  })

  it('keeps the user draft when the stream request is unconfirmed', async () => {
    const onError = vi.fn()
    api.streamChat.mockRejectedValue(new Error('stream unavailable'))
    const hook = mount({ onError })

    await act(async () => hook.result.current.sendMessage('unsent answer context'))

    expect(hook.result.current.messages).toMatchObject([{ role: 'user', content: 'unsent answer context' }])
    expect(onError).toHaveBeenCalledWith('stream unavailable')
    expect(api.chat).not.toHaveBeenCalled()
    expect(hook.result.current.messages[0].message_metadata?.send_state).toBe('unconfirmed')
    expect(hook.result.current.isLoading).toBe(false)
  })

  it('does not start fallback when a stopped stream later fails with a network error', async () => {
    const completion = deferred<void>()
    api.streamChat.mockReturnValue(completion.promise)
    api.chat.mockResolvedValue(response())
    const hook = mount()
    let sending!: boolean
    act(() => {
      sending = hook.result.current.sendMessage('question')
    })
    act(() => hook.result.current.stopGeneration())

    await act(async () => {
      completion.reject(new Error('network disconnected'))
      await sending
    })

    expect(api.chat).not.toHaveBeenCalled()
    expect(hook.result.current.messages).toMatchObject([{ role: 'user', content: 'question' }])
  })

  it('keeps request scope fields without replaying an unconfirmed stream', async () => {
    const options = {
      datasetId: 'dataset-a',
      documentIds: ['document-a'],
      structuredOutput: true,
      structuredPreset: 'brief',
      enableSummaryMemory: true,
      enableLongTermMemory: true,
      ragConfig: { top_k: 8 },
    }
    api.streamChat.mockRejectedValue(new Error('stream unavailable'))
    const hook = mount(options)

    await act(async () => hook.result.current.sendMessage('question'))

    expect(api.chat).not.toHaveBeenCalled()
    expect(api.streamChat.mock.calls[0]?.[0]).toMatchObject({
      message: 'question',
      document_ids: ['document-a'],
      dataset_id: undefined,
      structured_output: true,
      structured_preset: 'brief',
      enable_summary_memory: true,
      enable_long_term_memory: true,
      rag_config: { top_k: 8 },
    })
    expect(hook.result.current.messages).toMatchObject([{ role: 'user', content: 'question' }])
  })

  it('clears history and retires callbacks when the auth scope changes', async () => {
    const completion = deferred<void>()
    let emit!: (json: string) => void
    let open!: (meta: { requestId: string; conversationId?: string }) => void
    const onConversationId = vi.fn()
    api.streamChat.mockImplementation(async (_request, onJson, options) => {
      emit = onJson
      open = options.onOpen
      return completion.promise
    })
    const hook = mount({ onConversationId })
    let sending!: boolean
    act(() => {
      sending = hook.result.current.sendMessage('private question')
    })
    act(() => window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT)))

    await act(async () => {
      const run = createChatStreamFixture({ requestId: 'old-request', threadId: 'old-conversation' })
      open(run.opened)
      emit(run.text('private response'))
      run.finish(emit)
      completion.resolve()
      await sending
    })

    expect(hook.result.current.messages).toEqual([])
    expect(hook.result.current.conversationId).toBeUndefined()
    expect(onConversationId).not.toHaveBeenCalled()
  })

  it('loads history for an initial conversation link', async () => {
    const stored = assistant('stored-message', 'stored response')
    api.getMessages.mockResolvedValue({ conversation_id: 'conversation-a', messages: [stored] })
    const hook = mount({ conversationId: 'conversation-a' })

    await waitForAssertion(() => expect(hook.result.current.messages).toEqual([stored]))

    expect(api.getMessages).toHaveBeenCalledTimes(1)
    expect(api.streamChat).not.toHaveBeenCalled()
  })

  it('does not restart a navigation effect when only the error handler identity changes', async () => {
    const client = new QueryClient()
    const history = deferred<{ conversation_id: string; messages: Message[] }>()
    const loadStarted = vi.fn()
    api.getMessages.mockReturnValue(history.promise)
    const hook = renderHook(
      () => {
        const chat = useChat({ onError: () => undefined })
        const { conversationId, loadConversation } = chat
        useEffect(() => {
          if (conversationId === 'conversation-a') return
          if (loadStarted.mock.calls.length >= 3) return
          loadStarted()
          void loadConversation('conversation-a')
        }, [conversationId, loadConversation])
        return chat
      },
      {
        wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
      },
    )
    cleanup.push(() => client.clear(), hook.unmount)

    hook.rerender()

    expect(loadStarted).toHaveBeenCalledOnce()
    await act(async () => {
      history.resolve({ conversation_id: 'conversation-a', messages: [assistant()] })
      await history.promise
    })
    await waitForAssertion(() => expect(hook.result.current.conversationId).toBe('conversation-a'))
  })

  it('ignores callback publication after unmount', async () => {
    const completion = deferred<void>()
    let emit!: (json: string) => void
    const onConversationId = vi.fn()
    const onError = vi.fn()
    api.streamChat.mockImplementation(async (_request, onJson) => {
      emit = onJson
      return completion.promise
    })
    const hook = mount({ onConversationId, onError })
    let sending!: boolean
    act(() => {
      sending = hook.result.current.sendMessage('question')
    })
    hook.unmount()
    cleanup.splice(cleanup.indexOf(hook.unmount), 1)

    await act(async () => {
      createChatStreamFixture({ threadId: 'old-conversation', messageId: 'old-assistant' }).finish(emit)
      completion.resolve()
      await sending
    })

    expect(onConversationId).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
    expect(api.chat).not.toHaveBeenCalled()
  })

  it('matches recovered assistant messages by request id within the existing attempt budget', async () => {
    const getMessages = vi
      .fn()
      .mockResolvedValueOnce({
        conversation_id: 'conversation-a',
        messages: [assistant('unrelated')],
      })
      .mockResolvedValueOnce({
        conversation_id: 'conversation-a',
        messages: [{ ...assistant('matching'), message_metadata: { request_id: 'request-a' } }],
      })
    const wait = vi.fn().mockResolvedValue(undefined)

    const result = await recoverStreamedAssistantMessage({
      conversationId: 'conversation-a',
      requestId: 'request-a',
      getMessages,
      attempts: 4,
      wait,
    })

    expect(result?.id).toBe('matching')
    expect(getMessages).toHaveBeenCalledTimes(2)
    expect(getMessages.mock.calls[0]).toEqual(['conversation-a', { limit: 40 }, { signal: undefined }])
    expect(wait).toHaveBeenCalledTimes(1)
  })

  it('stops recovery after its bounded attempts when no request id matches', async () => {
    const getMessages = vi.fn().mockResolvedValue({ conversation_id: 'conversation-a', messages: [assistant()] })
    const wait = vi.fn().mockResolvedValue(undefined)

    expect(
      await recoverStreamedAssistantMessage({
        conversationId: 'conversation-a',
        requestId: 'request-a',
        getMessages,
        wait,
      }),
    ).toBeNull()

    expect(getMessages).toHaveBeenCalledTimes(4)
    expect(wait).toHaveBeenCalledTimes(3)
  })
})
