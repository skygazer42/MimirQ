import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeRetrievalPanel module', () => {
  it('exports KnowledgeRetrievalPanel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-retrieval-panel.tsx'), 'utf8')

    expect(src).toContain('export function KnowledgeRetrievalPanel')
  })
})

