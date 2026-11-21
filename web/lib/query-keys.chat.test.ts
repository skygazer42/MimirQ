import { InfiniteQueryObserver, QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import type { ConversationDetail } from '@/types/chat'
import { queryKeys } from './query-keys'

function conversationDetail(messageId: string): ConversationDetail {
  return {
    conversation_id: 'conversation-a',
    messages: [{ id: messageId, role: 'assistant', content: messageId, created_at: '2026-11-12T00:00:00Z' }],
    returned: 1,
    has_more: false,
  }
}

function historyObserver(client: QueryClient, loadPage: () => Promise<ConversationDetail>) {
  return new InfiniteQueryObserver(client, {
    queryKey: queryKeys.chat.messagePages('conversation-a'),
    queryFn: loadPage,
    initialPageParam: undefined,
    getNextPageParam: () => undefined,
  })
}

describe('conversation message cache contracts', () => {
  it('loads history pages after a fresh conversation detail without consuming its incompatible shape', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    const detail = conversationDetail('complete-history')
    await client.fetchQuery({ queryKey: queryKeys.chat.messages('conversation-a'), queryFn: async () => detail })
    const page = conversationDetail('history-page')
    const loadPage = vi.fn().mockResolvedValue(page)

    const history = await historyObserver(client, loadPage).fetchNextPage()

    expect(history.data?.pages).toEqual([page])
    expect(loadPage).toHaveBeenCalledOnce()
    expect(client.getQueryData(queryKeys.chat.messages('conversation-a'))).toEqual(detail)
    client.clear()
  })

  it('reads conversation detail after fresh history pages without returning InfiniteData as messages', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    const page = conversationDetail('history-page')
    await historyObserver(client, async () => page).fetchNextPage()
    const detail = conversationDetail('complete-history')
    const loadDetail = vi.fn().mockResolvedValue(detail)

    const result = await client.fetchQuery({
      queryKey: queryKeys.chat.messages('conversation-a'),
      queryFn: loadDetail,
    })

    expect(result.messages).toEqual(detail.messages)
    expect(loadDetail).toHaveBeenCalledOnce()
    expect(client.getQueryData(queryKeys.chat.messagePages('conversation-a'))).toEqual({
      pages: [page],
      pageParams: [undefined],
    })
    client.clear()
  })

  it('keeps the evaluation message limit separate from unbounded detail and infinite history', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    const evaluation = conversationDetail('evaluation-window')
    await client.fetchQuery({
      queryKey: queryKeys.chat.messages('conversation-a', { limit: 200 }),
      queryFn: async () => evaluation,
    })
    const page = conversationDetail('history-page')
    const loadPage = vi.fn().mockResolvedValue(page)
    const history = await historyObserver(client, loadPage).fetchNextPage()
    const detail = conversationDetail('complete-history')
    const loadDetail = vi.fn().mockResolvedValue(detail)
    const result = await client.fetchQuery({
      queryKey: queryKeys.chat.messages('conversation-a'),
      queryFn: loadDetail,
    })

    expect(history.data?.pages).toEqual([page])
    expect(result.messages).toEqual(detail.messages)
    expect(loadPage).toHaveBeenCalledOnce()
    expect(loadDetail).toHaveBeenCalledOnce()
    expect(client.getQueryData(queryKeys.chat.messages('conversation-a', { limit: 200 }))).toEqual(evaluation)
    client.clear()
  })
})
