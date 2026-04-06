import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel embedded density', () => {
  it('flattens embedded sections into a denser rail instead of nested cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain("const sectionClassName = embedded ? 'space-y-3 border-b border-border/50 pb-4 last:border-b-0 last:pb-0' : 'space-y-2'")
    expect(src).toContain("cn('space-y-4', embedded && 'p-3.5 lg:p-4')")
  })
})
