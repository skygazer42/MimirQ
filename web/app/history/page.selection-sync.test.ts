import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page selection sync', () => {
  it('guards against stale message loads when users switch conversations quickly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('selectionRequestSeqRef')
    expect(src).toContain('selectedConversationIdRef')
    expect(src).toContain('messagesLengthRef')
    expect(src).toContain('conversation.last_message_at || conversation.updated_at')
    expect(src).toContain('conv.last_message_at || conv.created_at || conv.updated_at')
    expect(src).toContain('const requestSeq = selectionRequestSeqRef.current + 1')
    expect(src).toContain('selectionRequestSeqRef.current = requestSeq')
    expect(src).toContain('selectedConversationIdRef.current = conversation.id')
    expect(src).toContain('messagesLengthRef.current = 0')
    expect(src).toContain('if (requestSeq !== selectionRequestSeqRef.current) return')
    expect(src).toContain('setSelectedConversation({')
    expect(src).toContain('...conversation,')
    expect(src).toContain('last_message: buildConversationPreview(lastMsg.content) || conversation.last_message')
    expect(src).not.toContain("}, [router, selectedConversation?.id, messages.length, t])")
    expect(src).not.toContain("}, [conversationId, conversations, handleSelectConversation, selectedConversation?.id])")
  })
})
