// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const chatApiMock = vi.hoisted(() => ({
  deleteConversation: vi.fn(),
  getMessages: vi.fn(),
  listConversations: vi.fn(),
}))

const navigationMock = vi.hoisted(() => ({ search: '', push: vi.fn(), replace: vi.fn() }))

vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', { 'data-app-frame': 'true' }, children),
}))
vi.mock('@/lib/api', () => ({ chatApi: chatApiMock }))
vi.mock('@/i18n/navigation', () => ({
  Link: ({ prefetch: _prefetch, ...props }: React.ComponentProps<'a'> & { prefetch?: boolean }) =>
    React.createElement('a', props),
  usePathname: () => '/history',
  useRouter: () => navigationMock,
}))
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(navigationMock.search),
}))
vi.mock('next-intl', () => ({
  useLocale: () => 'en',
  useTranslations: () => (key: string) => key,
}))

import HistoryPageClient from './page-client'
import { queryKeys } from '@/lib/query-keys'

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  navigationMock.search = ''
  chatApiMock.deleteConversation.mockResolvedValue(undefined)
  chatApiMock.getMessages.mockImplementation(async (conversationId: string) => ({
    conversation_id: conversationId,
    messages: [],
    returned: 0,
    has_more: false,
  }))
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
        React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(HistoryPageClient)),
      )
    })

    await act(async () => {
      await vi.waitFor(() =>
        expect(chatApiMock.listConversations).toHaveBeenCalledWith(
          {
            skip: 0,
            limit: 100,
          },
          { signal: expect.any(AbortSignal) },
        ),
      )
      await vi.waitFor(() => expect(container.querySelector('[data-history-empty-archive="true"]')).not.toBeNull())
      await vi.waitFor(() => expect(container.querySelector('[data-history-main-empty="true"]')).not.toBeNull())
    })

    expect(container.querySelector('[data-history-main-empty="true"] a[href="/"]')?.textContent).toContain(
      'startNewConversation',
    )
    expect(container.querySelector('[data-history-main-empty="true"] a[href="/evaluations"]')).toBeNull()
    expect(container.querySelector('[data-history-main-empty="true"] a[href="/observability"]')).toBeNull()

    act(() => root.unmount())
  })

  it('returns to the active conversation when it is selected again from the mobile list', async () => {
    const conversation = {
      id: 'conversation-mobile',
      title: 'Mobile conversation',
      message_count: 0,
      created_at: '2026-10-20T08:00:00Z',
      updated_at: '2026-10-20T08:00:00Z',
    }
    navigationMock.search = `id=${conversation.id}`
    chatApiMock.listConversations.mockResolvedValue({
      items: [conversation],
      total: 1,
      returned: 1,
      has_more: false,
      next_skip: null,
    })
    const matchMedia = vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      media: query,
      matches: query === '(max-width: 767px)',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    try {
      act(() =>
        root.render(
          React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(HistoryPageClient)),
        ),
      )
      await act(async () => {
        await vi.waitFor(() => expect(container.textContent).toContain(conversation.title))
      })
      const sidebar = container.querySelector('[data-history-sidebar="true"]')
      expect(sidebar?.classList.contains('hidden')).toBe(true)
      const expandButton = container.querySelector<HTMLButtonElement>('[aria-label="expandHistory"]')
      expect(expandButton).not.toBeNull()
      act(() => expandButton?.click())
      expect(sidebar?.classList.contains('hidden')).toBe(false)
      const activeRow = Array.from(container.querySelectorAll('button')).find((button) =>
        button.textContent?.includes(conversation.title),
      )
      expect(activeRow).not.toBeUndefined()
      act(() => activeRow?.click())
      expect(sidebar?.classList.contains('hidden')).toBe(true)
    } finally {
      act(() => root.unmount())
      matchMedia.mockRestore()
    }
  })

  it('searches the complete server-side history and renders zero-match semantics', async () => {
    const selectedConversation = {
      id: 'conversation-current',
      title: 'Current selection',
      message_count: 1,
      last_message: 'current message',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    navigationMock.search = `id=${selectedConversation.id}`
    const olderMatch = {
      id: 'conversation-101',
      title: 'Older matching conversation',
      message_count: 1,
      last_message: 'needle in an older page',
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
    }
    chatApiMock.listConversations.mockImplementation(async (params?: { q?: string }) => {
      if (params?.q === 'needle') {
        return {
          items: [olderMatch],
          total: 1,
          returned: 1,
          has_more: false,
          next_skip: null,
        }
      }
      if (params?.q === 'missing') {
        return {
          items: [],
          total: 0,
          returned: 0,
          has_more: false,
          next_skip: null,
        }
      }
      return {
        items: [selectedConversation],
        total: 101,
        returned: 1,
        has_more: true,
        next_skip: 100,
      }
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(
        React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(HistoryPageClient)),
      )
    })
    await act(async () => {
      await vi.waitFor(() => expect(chatApiMock.listConversations).toHaveBeenCalled())
    })

    const input = container.querySelector<HTMLInputElement>('input[placeholder="searchPlaceholder"]')
    expect(input).not.toBeNull()
    expect(input?.maxLength).toBe(500)
    const recentButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (button) => button.textContent === 'recentConversations',
    )
    expect(recentButton).not.toBeUndefined()
    act(() => recentButton?.click())
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    act(() => {
      valueSetter?.call(input, 'needle')
      input?.dispatchEvent(new Event('input', { bubbles: true }))
    })

    await act(async () => {
      await vi.waitFor(() =>
        expect(chatApiMock.listConversations).toHaveBeenCalledWith(
          {
            skip: 0,
            limit: 100,
            q: 'needle',
          },
          { signal: expect.any(AbortSignal) },
        ),
      )
      await vi.waitFor(() => expect(container.textContent).toContain(olderMatch.title))
    })

    act(() => {
      valueSetter?.call(input, 'missing')
      input?.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => {
      await vi.waitFor(() =>
        expect(chatApiMock.listConversations).toHaveBeenCalledWith(
          {
            skip: 0,
            limit: 100,
            q: 'missing',
          },
          { signal: expect.any(AbortSignal) },
        ),
      )
      await vi.waitFor(() => expect(container.textContent).toContain('noMatchedConversation'))
    })
    expect(container.textContent).not.toContain('加载更早记录')
    expect(container.textContent).toContain(selectedConversation.title)

    act(() => root.unmount())
  })

  it('loads messages directly for a deep-linked conversation outside the first conversation page', async () => {
    navigationMock.search = 'id=conversation-150'
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
        React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(HistoryPageClient)),
      )
    })

    await act(async () => {
      await vi.waitFor(() =>
        expect(chatApiMock.getMessages).toHaveBeenCalledWith(
          'conversation-150',
          { limit: 80, before: undefined },
          { signal: expect.any(AbortSignal) },
        ),
      )
      await vi.waitFor(() => expect(container.textContent).toContain('legacy answer'))
    })

    expect(container.querySelector('[data-history-main-empty="true"]')).toBeNull()
    act(() => root.unmount())
  })

  it('does not expose actions for a rejected deep-linked conversation', async () => {
    navigationMock.search = 'id=missing-conversation'
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
        React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(HistoryPageClient)),
      )
    })

    await act(async () => {
      await vi.waitFor(() => expect(container.querySelector('[role="alert"]')).not.toBeNull())
    })

    expect(container.querySelector('[aria-label="继续当前对话"]')).toBeNull()
    expect(container.querySelector('[aria-label="更多对话操作"]')).toBeNull()
    expect(container.querySelector('[aria-label="进行对话分析评测"]')).toBeNull()
    expect(container.querySelector('[aria-label="查看数据追踪"]')).toBeNull()
    act(() => root.unmount())
  })

  it('confirms deletion, refreshes the visible list and invalidates other conversation caches', async () => {
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
    const searchCacheKey = queryKeys.chat.conversationPages({ limit: 100, q: 'delete' })
    const commandCacheKey = queryKeys.chat.conversations({ limit: 6, q: 'delete' })
    queryClient.setQueryData(cacheKey, {
      pages: [{ items: [conversation], returned: 1, total: 2, has_more: true, next_skip: 1 }],
      pageParams: [0],
    })
    queryClient.setQueryData(searchCacheKey, {
      pages: [{ items: [conversation], returned: 1, total: 2, has_more: true, next_skip: 1 }],
      pageParams: [0],
    })
    queryClient.setQueryData(commandCacheKey, [conversation])
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    let deleted = false
    chatApiMock.listConversations.mockImplementation(async () => ({
      items: deleted ? [] : [conversation],
      total: deleted ? 0 : 1,
      returned: deleted ? 0 : 1,
      has_more: false,
      next_skip: null,
    }))
    chatApiMock.deleteConversation.mockImplementation(async () => {
      deleted = true
    })
    act(() =>
      root.render(
        React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(HistoryPageClient)),
      ),
    )
    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain(conversation.title))
    })
    const deleteButton = container.querySelector<HTMLButtonElement>('[aria-label="deleteConversation"]')
    expect(deleteButton).not.toBeNull()
    act(() => deleteButton?.click())
    const confirmButton = container.querySelector<HTMLButtonElement>('[aria-label="confirmDeleteConversation"]')
    expect(confirmButton).not.toBeNull()
    act(() => confirmButton?.click())

    await vi.waitFor(() => expect(chatApiMock.deleteConversation).toHaveBeenCalledWith('conversation-1'))
    await vi.waitFor(() => {
      const cached = queryClient.getQueryData<{ pages: Array<{ items: unknown[] }> }>(cacheKey)
      expect(cached?.pages[0].items).toEqual([])
      expect(queryClient.getQueryState(searchCacheKey)?.isInvalidated).toBe(true)
      expect(queryClient.getQueryState(commandCacheKey)?.isInvalidated).toBe(true)
    })
    expect(container.textContent).not.toContain(conversation.title)
    act(() => root.unmount())
  })
})
