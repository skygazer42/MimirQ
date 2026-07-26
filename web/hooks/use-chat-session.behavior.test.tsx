// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderHook } from '@/test/hook-harness'

const chatApiMock = vi.hoisted(() => ({
  getMessages: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  chatApi: chatApiMock,
}))

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
    chatApiMock.getMessages.mockImplementation((id: string) =>
      id === 'first' ? first.promise : second.promise
    )

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const harness = renderHook(
      () => useChatSession({}),
      {
        wrapper: ({ children }) => (
          <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        ),
      }
    )

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
})
