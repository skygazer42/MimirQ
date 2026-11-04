// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderHook } from '@/test/hook-harness'
import { AUTH_SCOPE_CHANGED_EVENT } from '@/lib/auth-storage'

const chatApiMock = vi.hoisted(() => ({
  getMessages: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))

vi.mock('@/lib/api', () => ({
  chatApi: chatApiMock,
}))
vi.mock('@/lib/api/chat', () => ({ chatApi: chatApiMock }))

import { useChatSession } from './use-chat-session'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

function message(id: string) {
  return {
    id,
    role: 'user' as const,
    content: id,
    created_at: '2026-07-20T00:00:00Z',
  }
}

afterEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ''
})

describe('useChatSession request ordering', () => {
  it('keeps the newest conversation when an older request finishes last', async () => {
    const first = deferred<{ conversation_id: string; messages: ReturnType<typeof message>[] }>()
    const second = deferred<{ conversation_id: string; messages: ReturnType<typeof message>[] }>()
    chatApiMock.getMessages.mockImplementation((id: string) => (id === 'first' ? first.promise : second.promise))

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const harness = renderHook(() => useChatSession({}), {
      wrapper: ({ children }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
    })

    let firstLoad!: Promise<void>
    let secondLoad!: Promise<void>
    act(() => {
      firstLoad = harness.result.current.loadConversation('first')
      secondLoad = harness.result.current.loadConversation('second')
    })

    await act(async () => {
      second.resolve({ conversation_id: 'second', messages: [message('second-message')] })
      await secondLoad
    })
    expect(harness.result.current.conversationId).toBe('second')

    await act(async () => {
      first.resolve({ conversation_id: 'first', messages: [message('first-message')] })
      await firstLoad
    })

    expect(harness.result.current.conversationId).toBe('second')
    expect(harness.result.current.messages).toEqual([message('second-message')])
    harness.unmount()
  })

  it.each(['clear', 'reset', 'auth'] as const)('retires a history response after %s', async (transition) => {
    const response = deferred<{ conversation_id: string; messages: ReturnType<typeof message>[] }>()
    chatApiMock.getMessages.mockReturnValue(response.promise)
    const onConversationId = vi.fn()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
    const harness = renderHook(() => useChatSession({ onConversationId }), {
      wrapper: ({ children }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
    })
    let completion!: Promise<void>
    act(() => {
      completion = harness.result.current.loadConversation('old')
    })
    act(() => {
      if (transition === 'clear') harness.result.current.clearMessages()
      else if (transition === 'reset') harness.result.current.resetConversationState()
      else window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT))
    })

    await act(async () => {
      response.resolve({ conversation_id: 'old', messages: [message('old-message')] })
      await completion
    })

    expect(harness.result.current.messages).toEqual([])
    expect(harness.result.current.isLoading).toBe(false)
    expect(onConversationId).not.toHaveBeenCalled()
    harness.unmount()
    queryClient.clear()
  })

  it('keeps the messages ref consistent when clearing before another send', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
    const harness = renderHook(() => useChatSession({}), {
      wrapper: ({ children }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
    })
    act(() => harness.result.current.setMessages([message('old-message')]))

    act(() => {
      harness.result.current.clearMessages()
      expect(harness.result.current.messagesRef.current).toEqual([])
    })

    harness.unmount()
    queryClient.clear()
  })
})
