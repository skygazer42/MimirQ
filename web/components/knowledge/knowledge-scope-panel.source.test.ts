import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel', () => {
  it('exports KnowledgeScopePanel and uses WorkbenchPane (no h-screen)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain('export function KnowledgeScopePanel')
    expect(src).toContain('WorkbenchPane')
    expect(src).not.toContain('h-screen')
  })
})

