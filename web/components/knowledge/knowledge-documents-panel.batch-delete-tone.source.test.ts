import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel batch delete tone', () => {
  it('uses a light danger treatment for the toolbar entry while keeping the final confirmation destructive', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('bg-destructive/5 text-destructive hover:bg-destructive/15')
    expect(src).toContain("onClick={() => setBatchDeleteOpen(true)}")
    expect(src).toContain('variant="destructive" onClick={() => detachPromise(confirmBatchDelete())}')
  })
})
