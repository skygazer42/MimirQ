import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('answer lineage action', () => {
  it('drives the action from backend lineage availability before opening details', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'answer-lineage-action.tsx'), 'utf8')

    expect(src).toContain('lineageApi.getAnswerLineageIfAvailable')
    expect(src).toContain("enabled: Boolean(requestId)")
    expect(src).toContain('lineageQuery.data === null')
    expect(src).toContain('disabled={isUnavailable || lineageQuery.isLoading}')
    expect(src).toContain("'检查血缘'")
    expect(src).toContain('requestId')
  })
})
