import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('answer lineage action', () => {
  it('loads backend lineage details only after an evidence-backed action is opened', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'answer-lineage-action.tsx'), 'utf8')

    expect(src).toContain('lineageApi.getAnswerLineageIfAvailable')
    expect(src).toContain('enabled: open && Boolean(requestId)')
    expect(src).toContain('lineageQuery.data === null')
    expect(src).toContain('disabled={lineageQuery.isFetching}')
    expect(src).toContain("'加载血缘'")
    expect(src).toContain('requestId')
  })
})
