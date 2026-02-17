import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel dataset scope selector', () => {
  it('renders a dataset <Select> control in the left scope panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain('aria-label="筛选数据集"')
    expect(src).toContain('全部数据集')
    expect(src).toContain('<Select')
  })
})

