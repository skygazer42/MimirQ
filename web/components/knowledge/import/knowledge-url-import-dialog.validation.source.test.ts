import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeUrlImportDialog inline validation', () => {
  it('shows field-level URL validation (not toast-only)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-url-import-dialog.tsx'), 'utf8')

    expect(src).toContain('urlError')
    expect(src).toContain('aria-invalid')
    expect(src).toContain('knowledge-url-import-url-error')
  })
})

