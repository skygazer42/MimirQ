import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage embedded scope panel', () => {
  it('renders KnowledgeScopePanel inside the shared workbench surface', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('surface="embedded"')
    expect(src).toContain('<KnowledgeScopePanel')
  })
})
