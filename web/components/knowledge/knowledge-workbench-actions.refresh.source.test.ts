import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeWorkbenchActions refresh wiring', () => {
  it('refreshes documents after URL import success', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-workbench-actions.tsx'), 'utf8')

    expect(src).toContain('onAfterImport={loadDocuments}')
  })
})

