import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history answer lineage integration', () => {
  it('exposes answer lineage only when assistant messages include backend evidence metadata', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { AnswerLineageAction } from '@/components/history/answer-lineage-action'")
    expect(src).toContain('extractMessageRequestId')
    expect(src).toContain('hasAnswerLineageEvidence(message)')
    expect(src).toContain('const showAnswerLineage = Boolean(requestId && hasAnswerLineageEvidence(message))')
    expect(src).toContain('showAnswerLineage ? <AnswerLineageAction requestId={requestId} /> : null')
    expect(src).toContain('metadata.retrieved_docs')
    expect(src).toContain('metadata.docs_returned')
  })
})
