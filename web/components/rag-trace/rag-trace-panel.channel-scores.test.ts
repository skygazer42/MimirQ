import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('rag trace panel channel scores', () => {
  it('surfaces per-channel scores + rerank reasons for diagnostics', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')
    expect(src).toContain('vector_score')
    expect(src).toContain('bm25_score')
    expect(src).toContain('lexical_score')
    expect(src).toContain('sparse_score')
    expect(src).toContain('skip_reason')
  })
})

