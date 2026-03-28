// @vitest-environment jsdom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderHook, waitForAssertion } from '@/test/hook-harness'

const chatApiMocks = vi.hoisted(() => ({
  chat: vi.fn(),
  getMessages: vi.fn(),
  streamChat: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  chatApi: chatApiMocks,
}))

import { useChat } from './use-chat'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  })

  return {
    queryClient,
    wrapper({ children }: { children: React.ReactNode }) {
      return React.createElement(QueryClientProvider, { client: queryClient }, children)
    },
  }
}

describe('useChat behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'log').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('falls back to non-streaming chat when streaming is unavailable', async () => {
    chatApiMocks.streamChat.mockRejectedValue(new Error('sse unavailable'))
    chatApiMocks.chat.mockResolvedValue({
      assistant_message_id: 'assistant-1',
      content: 'Fallback answer',
      conversation_id: 'conv-fallback',
      citations: [],
      metrics: {},
      request_id: 'req-fallback',
      structured: false,
    })

    const onConversationId = vi.fn()
    const { queryClient, wrapper } = createWrapper()
    const hook = renderHook(() => useChat({ onConversationId }), { wrapper })

    await act(async () => {
      await hook.result.current.sendMessage('Hello fallback')
    })

    await waitForAssertion(() => {
      expect(hook.result.current.isLoading).toBe(false)
      expect(hook.result.current.conversationId).toBe('conv-fallback')
      expect(hook.result.current.messages).toHaveLength(2)
      expect(hook.result.current.messages[1]).toMatchObject({
        id: 'assistant-1',
        role: 'assistant',
        content: 'Fallback answer',
      })
    })

    expect(chatApiMocks.streamChat).toHaveBeenCalledTimes(1)
    expect(chatApiMocks.chat).toHaveBeenCalledTimes(1)
    expect(onConversationId).toHaveBeenCalledWith('conv-fallback')

    hook.unmount()
    queryClient.clear()
  })

  it('surfaces fallback failures through onError without fabricating an assistant reply', async () => {
    chatApiMocks.streamChat.mockRejectedValue(new Error('sse unavailable'))
    chatApiMocks.chat.mockRejectedValue(new Error('Fallback unavailable'))

    const onError = vi.fn()
    const { queryClient, wrapper } = createWrapper()
    const hook = renderHook(() => useChat({ onError }), { wrapper })

    await act(async () => {
      try {
        await hook.result.current.sendMessage('Hello error')
      } catch {
        // mutateAsync rejections are already converted into hook state + onError.
      }
    })

    await waitForAssertion(() => {
      expect(hook.result.current.isLoading).toBe(false)
      expect(hook.result.current.messages).toHaveLength(1)
      expect(hook.result.current.messages[0]).toMatchObject({
        role: 'user',
        content: 'Hello error',
      })
      expect(onError).toHaveBeenCalledWith('Fallback unavailable')
    })

    expect(chatApiMocks.chat).toHaveBeenCalledTimes(1)

    hook.unmount()
    queryClient.clear()
  })
})
