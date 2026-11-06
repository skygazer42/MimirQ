// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { readMessageCatalogSource } from '@/lib/source-test-utils'

describe('history page empty state', () => {
  it('offers a clear next action via the shared messages catalog', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')
    const messages = readMessageCatalogSource(path.resolve(__dirname, '../..'))

    expect(src).toContain("t('startNewConversation')")
    expect(src).toContain("t('startFirstConversation')")
    expect(src).toContain("t('startFirstConversationDescription')")
    expect(src).not.toContain('<Link href="/evaluations">')
    expect(src).not.toContain('<Link href="/observability">')
    expect(src).not.toContain("['答案留存', '保存对话结论']")
    expect(src).toContain('function HistorySidebarEmptyState')
    expect(src).toContain('function HistoryMainEmptyState')
    expect(src).toContain('data-history-empty-archive="true"')
    expect(src).toContain('data-history-empty-inline="true"')
    expect(src).toContain('data-history-main-empty="true"')
    expect(src).not.toContain("t('historyEmptyKicker')")
    expect(src).toContain("t('historyEmptyDescription')")
    expect(src.match(/<ConversationHistory /g)).toHaveLength(2)
    expect(src).not.toContain('mimirq-history-archive.png')
    expect(src).not.toContain('gradient')
    expect(src).not.toContain('blur-3xl')
    expect(messages).toContain("startNewConversation: '新建对话'")
    expect(messages).toContain("startFirstConversation: '暂无问答记录'")
    expect(messages).not.toContain('ARCHIVE READY')
    expect(messages).toContain("historyEmptyDescription: '新建对话后，记录会保存在这里。'")
  })
})
