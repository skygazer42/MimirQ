import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('rag trace panel retrieval_config_hash', () => {
  it('surfaces retrieval_config_hash for cross-run comparisons', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')
    expect(src).toContain('retrieval_config_hash')
  })
})

