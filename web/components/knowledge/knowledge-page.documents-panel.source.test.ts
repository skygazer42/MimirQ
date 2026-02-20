import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage documents panel', () => {
  it('uses extracted KnowledgeDocumentsPanel module for documents tab', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('knowledge-documents-panel')
    expect(src).toContain('<KnowledgeDocumentsPanel')
  })
})

