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
    expect(src).toContain('data-history-main-empty="true"')
    expect(src).toContain("t('historyEmptyKicker')")
    expect(src).toContain("t('historyEmptyDescription')")
    expect(src).toContain('bg-[linear-gradient(135deg,rgba(14,165,233,0.08),transparent_42%),radial-gradient(circle_at_50%_105%,rgba(59,130,246,0.10),transparent_45%)]')
    expect(src).not.toContain('border border-sky-200/70 bg-[radial-gradient(circle_at_50%_0%,rgba(14,165,233,0.16),transparent_55%)]')
    expect(src).not.toContain('shadow-[0_18px_48px_rgba(37,99,235,0.10)]')
    expect(src).not.toContain('rounded-[27px] bg-background/88 px-5 py-6 text-center ring-1 ring-white/70')
    expect(src).not.toContain('<MessageSquare className="mx-auto mb-3 h-8 w-8 opacity-20"/>')
    expect(messages).toContain("startNewConversation: '发起新对话'")
    expect(messages).toContain("evaluateConversation: 'RAGAS 评测'")
    expect(messages).toContain("ragTrace: 'RAG Trace'")
    expect(messages).toContain("historyEmptyKicker: 'ARCHIVE READY'")
    expect(messages).toContain("historyEmptyDescription: '提问后，对话会按时间自动沉淀到这里，方便回看答案、证据和评测链路。'")
  })
})
