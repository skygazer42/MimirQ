// @vitest-environment jsdom

import React, { act, useState } from 'react'
import { QueryClient } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const chatApiMock = vi.hoisted(() => ({
  deleteConversation: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ chatApi: chatApiMock }))
vi.mock('@/i18n/navigation', () => ({
  Link: 'a',
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('next-intl', () => ({
  useLocale: () => 'en',
  useTranslations: () => (key: string) => key,
}))

import { ConversationItem, deleteConversationFromHistory } from './page-client'
import { queryKeys } from '@/lib/query-keys'

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  chatApiMock.deleteConversation.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ''
})

describe('history page delete action', () => {
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
