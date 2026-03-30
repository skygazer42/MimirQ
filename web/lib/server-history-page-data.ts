import 'server-only'

import { API_V1_BASE_URL } from '@/lib/env'
import { getServerAuthHeaders } from '@/lib/server-auth-headers'
import type { Conversation, Message } from '@/types'

const DEFAULT_VISIBLE_MESSAGES = 80

type ConversationListResponse = {
  items?: Conversation[]
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
      `${API_V1_BASE_URL}/chat/conversations?limit=100`,
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
      initialConversationsLoaded: true,
    }
  } catch {
    return {
      initialConversationId,
      initialConversations: [],
      initialSelectedConversation: null,
      initialMessages: [],
      initialHasMoreMessages: false,
      initialConversationsLoaded: false,
    }
  }
}
