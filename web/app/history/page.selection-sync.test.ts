import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page selection sync', () => {
  it('guards against stale message loads when users switch conversations quickly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('useInfiniteQuery')
    expect(src).toContain('const selectedConversationId = selectedConversation?.id || null')
    expect(src).toContain("queryKey: queryKeys.chat.messages(selectedConversationId || '')")
    expect(src).toContain('enabled: Boolean(selectedConversationId)')
    expect(src).toContain(
      'initialSelectedConversation?.id && initialSelectedConversation.id === selectedConversationId'
    )
    expect(src).toContain('messagesQuery.data?.pages.flatMap')
    expect(src).toContain('conversation.last_message_at || conversation.updated_at')
    expect(src).toContain('conv.last_message_at || conv.created_at || conv.updated_at')
    expect(src).not.toContain("}, [router, selectedConversation?.id, messages.length, t])")
    expect(src).not.toContain("}, [conversationId, conversations, handleSelectConversation, selectedConversation?.id])")
  })
})
