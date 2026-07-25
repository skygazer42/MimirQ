// @vitest-environment jsdom

import React, { act, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const chatApiMock = vi.hoisted(() => ({
  deleteConversation: vi.fn(),
  getMessages: vi.fn(),
  listConversations: vi.fn(),
}))

vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', { 'data-app-frame': 'true' }, children),
}))
vi.mock('@/lib/api', () => ({ chatApi: chatApiMock }))
vi.mock('@/i18n/navigation', () => ({
  Link: ({ prefetch: _prefetch, ...props }: React.ComponentProps<'a'> & { prefetch?: boolean }) =>
    React.createElement('a', props),
  usePathname: () => '/history',
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('next-intl', () => ({
  useLocale: () => 'en',
  useTranslations: () => (key: string) => key,
}))

import HistoryPageClient, { ConversationItem, deleteConversationFromHistory } from './page-client'
import { queryKeys } from '@/lib/query-keys'

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  chatApiMock.deleteConversation.mockResolvedValue(undefined)
  chatApiMock.getMessages.mockResolvedValue({
    conversation_id: 'conversation-default',
    messages: [],
    returned: 0,
    has_more: false,
  })
  chatApiMock.listConversations.mockResolvedValue({
    items: [],
    total: 0,
    returned: 0,
    has_more: false,
    next_skip: null,
  })
  globalThis.window.matchMedia =
    globalThis.window.matchMedia ||
    ((query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as MediaQueryList)
  globalThis.window.requestAnimationFrame =
    globalThis.window.requestAnimationFrame ||
    ((cb: FrameRequestCallback) => setTimeout(() => cb(0), 0) as unknown as number)
  globalThis.IntersectionObserver =
    globalThis.IntersectionObserver ||
    class IntersectionObserver {
      disconnect() {}
      observe() {}
      unobserve() {}
    }
})

afterEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ''
})

describe('history page delete action', () => {
  it('loads conversations at runtime when the server shell no longer prefetched them', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(HistoryPageClient, { initialConversationId: null })
        )
      )
    })

    await act(async () => {
      await vi.waitFor(() =>
        expect(chatApiMock.listConversations).toHaveBeenCalledWith({
          skip: 0,
          limit: 100,
        })
      )
      await vi.waitFor(() =>
        expect(container.querySelector('[data-history-empty-archive="true"]')).not.toBeNull()
      )
    })

    act(() => root.unmount())
  })

  it('loads messages directly for a deep-linked conversation outside the first conversation page', async () => {
    chatApiMock.listConversations.mockResolvedValue({
      items: Array.from({ length: 100 }, (_, index) => ({
        id: `conversation-${index + 1}`,
        title: `Conversation ${index + 1}`,
        message_count: 1,
        last_message: `message ${index + 1}`,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      })),
      total: 150,
      returned: 100,
      has_more: true,
      next_skip: 100,
    })
    chatApiMock.getMessages.mockResolvedValue({
      conversation_id: 'conversation-150',
      messages: [
        {
          id: 'message-1',
          role: 'assistant',
          content: 'legacy answer',
          created_at: '2026-01-02T00:00:00Z',
        },
      ],
      returned: 1,
      has_more: false,
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(HistoryPageClient, { initialConversationId: 'conversation-150' })
        )
      )
    })

    await act(async () => {
      await vi.waitFor(() =>
        expect(chatApiMock.getMessages).toHaveBeenCalledWith('conversation-150', {
          limit: 80,
          before: undefined,
        })
      )
      await vi.waitFor(() => expect(container.textContent).toContain('legacy answer'))
    })

    expect(container.querySelector('[data-history-main-empty="true"]')).toBeNull()
    act(() => root.unmount())
  })

  it('does not expose actions for a rejected deep-linked conversation', async () => {
    chatApiMock.getMessages.mockRejectedValueOnce(new Error('conversation not found'))
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(HistoryPageClient, { initialConversationId: 'missing-conversation' })
        )
      )
    })

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.querySelector('[data-history-main-empty="true"]')).not.toBeNull()
      )
    })

    expect(container.querySelector('[aria-label="继续当前对话"]')).toBeNull()
    expect(container.querySelector('[aria-label="进行对话分析评测"]')).toBeNull()
    expect(container.querySelector('[aria-label="查看数据追踪"]')).toBeNull()
    act(() => root.unmount())
  })

  it('confirms deletion, calls the API, and removes the cached conversation', async () => {
    const queryClient = new QueryClient()
    const conversation = {
      id: 'conversation-1',
      title: 'Delete me',
      message_count: 1,
      last_message: 'hello',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    const cacheKey = queryKeys.chat.conversationPages({ limit: 100 })
    queryClient.setQueryData(cacheKey, {
      pages: [{ items: [conversation], returned: 1, total: 1 }],
      pageParams: [0],
    })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    function Harness() {
      const [confirming, setConfirming] = useState(false)
      return React.createElement(ConversationItem, {
        conversation: conversation as never,
        isSelected: false,
        onSelect: () => undefined,
        onDelete: () => setConfirming(true),
        showDeleteConfirm: confirming,
        onConfirmDelete: () => {
          void deleteConversationFromHistory(conversation.id, queryClient)
        },
        onCancelDelete: () => setConfirming(false),
      })
    }

    act(() => root.render(React.createElement(Harness)))
    const deleteButton = container.querySelector<HTMLButtonElement>(
      '[aria-label="deleteConversation"]'
    )
    expect(deleteButton).not.toBeNull()
    act(() => deleteButton?.click())
    const confirmButton = container.querySelector<HTMLButtonElement>(
      '[aria-label="confirmDeleteConversation"]'
    )
    expect(confirmButton).not.toBeNull()
    act(() => confirmButton?.click())

    await vi.waitFor(() => expect(chatApiMock.deleteConversation).toHaveBeenCalledWith('conversation-1'))
    await vi.waitFor(() => {
      const cached = queryClient.getQueryData<{ pages: Array<{ items: unknown[] }> }>(cacheKey)
      expect(cached?.pages[0].items).toEqual([])
    })
    act(() => root.unmount())
  })
})
