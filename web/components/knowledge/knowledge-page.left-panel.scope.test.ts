import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage left panel scope', () => {
  it('mounts KnowledgeScopePanel in WorkbenchScaffold.leftPanel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('leftPanel={')
    expect(src).toContain('<KnowledgeScopePanel')
  })
})
