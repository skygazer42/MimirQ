// Source contract check only; interactive behavior is covered by browser verification.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chat composer tools source', () => {
  it('keeps dataset and retrieval controls behind one collapsible entry point', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')
    const messages = fs.readFileSync(
      path.resolve(__dirname, '../i18n/messages/zh-CN/chat.ts'),
      'utf8'
    )

    expect(src).toContain('const [showConversationTools, setShowConversationTools]')
    expect(src).toContain('id="chat-conversation-tools"')
    expect(src).toContain('aria-controls="chat-conversation-tools"')
    expect(src).toContain('aria-expanded={showConversationTools}')
    expect(src).toContain("t('collapseConversationTools')")
    expect(src).not.toContain('RAG 检索')
    expect(messages).toContain("scopeAndRetrieval: '范围与检索'")
    expect(messages).toContain("collapseConversationTools: '收起范围与检索'")
  })
})
