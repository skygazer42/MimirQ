import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel batch delete confirmation', () => {
  it('uses AlertDialog for destructive batch delete (baseline-ui)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('<AlertDialog open={batchDeleteOpen}')
    expect(src).toContain('确认删除')
    expect(src).not.toContain('<Dialog open={batchDeleteOpen}')
  })
})

