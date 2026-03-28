// @vitest-environment jsdom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { queryKeys } from '@/lib/query-keys'
import { renderHook, waitForAssertion } from '@/test/hook-harness'
import type { ConversationDetail, Message } from '@/types'

const chatApiMocks = vi.hoisted(() => ({
  getMessages: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  chatApi: chatApiMocks,
}))

import { useChatSession } from './use-chat-session'

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

function makeMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: 'msg-1',
    role: 'assistant',
    content: 'Hello from history',
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

describe('useChatSession behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads conversation through query cache while preserving local state updates', async () => {
    const conversationId = 'conv-123'
    const response: ConversationDetail = {
      conversation_id: conversationId,
      messages: [makeMessage()],
    }
    chatApiMocks.getMessages.mockResolvedValue(response)

    const onConversationId = vi.fn()
    const { queryClient, wrapper } = createWrapper()
    const hook = renderHook(() => useChatSession({ onConversationId }), { wrapper })

    await act(async () => {
      await hook.result.current.loadConversation(conversationId)
    })

    await waitForAssertion(() => {
      expect(hook.result.current.isLoading).toBe(false)
      expect(hook.result.current.conversationId).toBe(conversationId)
      expect(hook.result.current.messages).toEqual(response.messages)
      expect(hook.result.current.messagesRef.current).toEqual(response.messages)
      expect(onConversationId).toHaveBeenCalledWith(conversationId)
    })

    expect(queryClient.getQueryData(queryKeys.chat.messages(conversationId))).toEqual(response)
    expect(chatApiMocks.getMessages).toHaveBeenCalledWith(conversationId)

    hook.unmount()
    queryClient.clear()
  })

  it('surfaces backend failures with request id context', async () => {
    chatApiMocks.getMessages.mockRejectedValue({
      response: {
        data: {
          message: 'Could not load',
          request_id: 'req-77',
        },
      },
    })

    const onError = vi.fn()
    const { queryClient, wrapper } = createWrapper()
    const hook = renderHook(() => useChatSession({ onError }), { wrapper })

    await act(async () => {
      await hook.result.current.loadConversation('conv-fail')
    })

    await waitForAssertion(() => {
      expect(hook.result.current.isLoading).toBe(false)
      expect(hook.result.current.messages).toEqual([])
      expect(onError).toHaveBeenCalledWith('Could not load (request_id=req-77)')
    })

    hook.unmount()
    queryClient.clear()
  })
})
