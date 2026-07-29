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
    expect(src).toContain("t('evaluateConversation')")
    expect(src).toContain("t('ragTrace')")
    expect(src).toContain('<Link href="/evaluations">')
    expect(src).toContain('<Link href="/observability">')
    expect(src).toContain('function HistorySidebarEmptyState')
    expect(src).toContain('function HistoryMainEmptyState')
    expect(src).toContain('data-history-empty-archive="true"')
    expect(src).toContain('data-history-empty-inline="true"')
    expect(src).toContain('className="mx-2 mt-4 px-4 text-center"')
    expect(src).not.toContain('className="mx-2 mt-8 px-4 text-center"')
    expect(src).toContain('data-history-main-empty="true"')
    expect(src).toContain("t('historyEmptyKicker')")
    expect(src).toContain("t('historyEmptyDescription')")
    expect(src).toContain('border border-border/60 bg-background/96 px-8 py-12 text-center')
    expect(src).toContain('rounded-[26px] border border-border/70 bg-muted/55 text-foreground')
    expect(src).toContain('className="h-10 rounded-full bg-foreground px-5 text-[13px] font-semibold text-background hover:bg-foreground/92"')
    expect(src).not.toContain('gradient')
    expect(src).not.toContain('blur-3xl')
    expect(messages).toContain("startNewConversation: '发起新对话'")
    expect(messages).toContain("evaluateConversation: 'RAGAS 评测'")
    expect(messages).toContain("ragTrace: 'RAG Trace'")
    expect(messages).toContain("historyEmptyKicker: 'ARCHIVE READY'")
    expect(messages).toContain("historyEmptyDescription: '提问后，对话会按时间自动沉淀到这里，方便回看答案、证据和评测链路。'")
  })
})
