import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel lifecycle filter', () => {
  it('owns the lifecycle <Select> control', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain('aria-label="筛选生命周期"')
    expect(src).toContain('启用中')
    expect(src).toContain('已归档')
  })
})

