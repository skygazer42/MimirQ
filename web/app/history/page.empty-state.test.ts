import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('history page empty state', () => {
  it('offers a clear next action via the shared messages catalog', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')
    const messages = fs.readFileSync(path.resolve(__dirname, '../../i18n/messages/zh-CN.ts'), 'utf8')

    expect(src).toContain("t('startNewConversation')")
    expect(src).toContain("t('evaluateConversation')")
    expect(src).toContain("t('ragTrace')")
    expect(src).toContain('<Link href="/evaluations">')
    expect(src).toContain('<Link href="/observability">')
    expect(messages).toContain("startNewConversation: '发起新对话'")
    expect(messages).toContain("evaluateConversation: 'RAGAS 评测'")
    expect(messages).toContain("ragTrace: 'RAG Trace'")
  })
})
