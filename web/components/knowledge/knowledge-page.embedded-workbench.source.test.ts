import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage embedded documents workbench', () => {
  it('renders the documents tab as a unified surface with embedded scope and inspector sections', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('surface="embedded"')
    expect(src).toContain('<KnowledgeDocumentsPanel')
    expect(src).toContain('<KnowledgeInspector embedded')
    expect(src).toContain('rounded-[28px]')
  })
})
