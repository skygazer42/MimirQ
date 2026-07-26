// @vitest-environment happy-dom

import React, { act, useRef, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Message } from '@/types'
import { API_LONG_TIMEOUT_MS, API_TIMEOUT_MS } from '@/lib/env'
import { renderHook, waitForAssertion } from '@/test/hook-harness'

const chatApiMock = vi.hoisted(() => ({
  chat: vi.fn(),
  getMessages: vi.fn(),
  streamChat: vi.fn(),
}))

const recoveryMock = vi.hoisted(() => ({
  recoverStreamedAssistantMessage: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  chatApi: chatApiMock,
}))

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

function renderChatStreamHook(onError = vi.fn()) {
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

    chatApiMock.streamChat.mockImplementation(async (_request: unknown, _onJson: unknown, options?: { signal?: AbortSignal; onOpen?: (meta: { requestId: string; conversationId?: string }) => void }) => {
      options?.onOpen?.({ requestId: 'req-accepted', conversationId: 'conv-accepted' })
      return await new Promise<never>((_resolve, reject) => {
        rejectStream = reject
        options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
      })
    })
    recoveryMock.recoverStreamedAssistantMessage.mockResolvedValue(
      createAssistantMessage('assistant-recovered', 'req-accepted', 'recovered answer')
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
        })
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

  it('times out an accepted stream that never emits an event', async () => {
    vi.useFakeTimers()
    const onError = vi.fn()

    chatApiMock.streamChat.mockImplementation(async (_request: unknown, _onJson: unknown, options?: { signal?: AbortSignal; onOpen?: (meta: { requestId: string; conversationId?: string }) => void }) => {
      options?.onOpen?.({ requestId: 'req-silent', conversationId: 'conv-silent' })
      return await new Promise<never>((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
      })
    })
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

    expect(onError).toHaveBeenCalledWith('Request timed out')
    expect(hook.result.current.isLoading).toBe(false)
    hook.unmount()
  })

  it('does not replay an accepted request when recovery finds nothing', async () => {
    const onError = vi.fn()
    let rejectStream: ((reason?: unknown) => void) | null = null

    chatApiMock.streamChat.mockImplementation(async (_request: unknown, _onJson: unknown, options?: { signal?: AbortSignal; onOpen?: (meta: { requestId: string; conversationId?: string }) => void }) => {
      options?.onOpen?.({ requestId: 'req-stream', conversationId: 'conv-stream' })
      return await new Promise<never>((_resolve, reject) => {
        rejectStream = reject
        options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
      })
    })
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
        })
      )
      expect(onError).toHaveBeenCalledWith(
        'Chat stream interrupted before completion and could not be recovered'
      )
    })

    expect(chatApiMock.chat).not.toHaveBeenCalled()
    hook.unmount()
  })

  it('ignores a second send before the loading state rerenders', async () => {
    chatApiMock.streamChat.mockImplementation(async (_request: unknown, _onJson: unknown, options?: { signal?: AbortSignal }) => {
      return await new Promise<never>((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
      })
    })

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

    chatApiMock.streamChat.mockImplementation(async (_request: unknown, onJson: (json: string) => void, options?: { signal?: AbortSignal; onOpen?: (meta: { requestId: string; conversationId?: string }) => void }) => {
      options?.onOpen?.({ requestId: 'req-stop', conversationId: 'conv-stop' })
      onJson(JSON.stringify({ type: 'token', data: { content: 'partial answer' } }))
      return await new Promise<never>((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () => reject(createAbortError()), { once: true })
      })
    })

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
})
