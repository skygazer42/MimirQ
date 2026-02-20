import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage query state', () => {
  it('uses shared parse/serialize helpers instead of inline URL logic', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('use-knowledge-query-state')
    expect(src).toContain('parseKnowledgeQueryState')
    expect(src).toContain('serializeKnowledgeQueryState')
  })
})

