import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel retrieval mode', () => {
  it('supports tab-specific modes so only documents show status, folder, and lifecycle filters', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain("mode?: 'documents' | 'retrieval' | 'settings'")
    expect(src).toContain("const showDocumentFilters = mode === 'documents'")
  })
})
