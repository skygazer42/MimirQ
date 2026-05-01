import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history answer lineage integration', () => {
  it('exposes answer lineage from assistant messages with request_id metadata', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { AnswerLineageAction } from '@/components/history/answer-lineage-action'")
    expect(src).toContain('extractMessageRequestId')
    expect(src).toContain('<AnswerLineageAction requestId={requestId} />')
  })
})
