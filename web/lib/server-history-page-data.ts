import 'server-only'

import { API_V1_BASE_URL } from '@/lib/env'
import { getServerAuthHeaders } from '@/lib/server-auth-headers'
import type { Conversation, Message } from '@/types'

const DEFAULT_VISIBLE_MESSAGES = 80

type ConversationListResponse = {
  items?: Conversation[]
  total?: number
  returned?: number
  has_more?: boolean
  next_skip?: number | null
}

type ConversationMessagesResponse = {
  messages?: Message[]
  has_more?: boolean
}

export type HistoryPageInitialData = {
  initialConversationId: string | null
  initialConversations: Conversation[]
  initialSelectedConversation: Conversation | null
  initialMessages: Message[]
  initialHasMoreMessages: boolean
  initialHasMoreConversations: boolean
  initialConversationNextSkip: number | null
  initialConversationTotal: number
  initialConversationsLoaded: boolean
}

async function getJson<T>(url: string, headers: Record<string, string>): Promise<T> {
  const response = await fetch(url, {
    method: 'GET',
    headers,
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`history_prefetch_failed_${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function getServerHistoryPageData(
  requestedConversationId?: string | null
): Promise<HistoryPageInitialData> {
  const initialConversationId = String(requestedConversationId || '').trim() || null

  try {
    const authHeaders = await getServerAuthHeaders()
    const list = await getJson<ConversationListResponse>(
      `${API_V1_BASE_URL}/chat/conversations?skip=0&limit=100`,
      authHeaders
    )
    const initialConversations = list.items || []
    const initialSelectedConversation =
      initialConversationId
        ? initialConversations.find((conversation) => conversation.id === initialConversationId) || null
        : null

    if (!initialSelectedConversation) {
      return {
        initialConversationId,
        initialConversations,
        initialSelectedConversation: null,
        initialMessages: [],
        initialHasMoreMessages: false,
        initialHasMoreConversations: Boolean(list.has_more),
        initialConversationNextSkip: typeof list.next_skip === 'number' ? list.next_skip : null,
        initialConversationTotal: Number(list.total ?? initialConversations.length),
        initialConversationsLoaded: true,
      }
    }

    const detail = await getJson<ConversationMessagesResponse>(
      `${API_V1_BASE_URL}/chat/conversations/${encodeURIComponent(initialSelectedConversation.id)}/messages?limit=${DEFAULT_VISIBLE_MESSAGES}`,
      authHeaders
    )

    return {
      initialConversationId,
      initialConversations,
      initialSelectedConversation,
      initialMessages: detail.messages || [],
      initialHasMoreMessages: Boolean(detail.has_more),
      initialHasMoreConversations: Boolean(list.has_more),
      initialConversationNextSkip: typeof list.next_skip === 'number' ? list.next_skip : null,
      initialConversationTotal: Number(list.total ?? initialConversations.length),
      initialConversationsLoaded: true,
    }
  } catch {
    return {
      initialConversationId,
      initialConversations: [],
      initialSelectedConversation: null,
      initialMessages: [],
      initialHasMoreMessages: false,
      initialHasMoreConversations: false,
      initialConversationNextSkip: null,
      initialConversationTotal: 0,
      initialConversationsLoaded: false,
    }
  }
}
