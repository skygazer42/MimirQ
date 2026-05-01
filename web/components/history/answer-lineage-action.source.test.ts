import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('answer lineage action', () => {
  it('connects the answer lineage endpoint from history', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'answer-lineage-action.tsx'), 'utf8')

    expect(src).toContain('lineageApi.getAnswerLineage')
    expect(src).toContain('requestId')
  })
})
