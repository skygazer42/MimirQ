import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge documents toolbar', () => {
  it('keeps search/sort/view in the main surface and leaves scope filters to the left panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    // Main surface keeps search + sort + view toggle.
    expect(src).toContain('<SearchInput')
    expect(src).toContain('aria-label="排序"')
    expect(src).toContain('aria-label="网格视图"')
    expect(src).toContain('aria-label="列表视图"')

    // Scope filters should not live in the main documents toolbar anymore.
    expect(src).not.toContain('aria-label="筛选数据集"')
    expect(src).not.toContain('aria-label="按目录筛选"')
    expect(src).not.toContain('aria-label="筛选生命周期"')
    expect(src).not.toContain('aria-pressed={statusFilter === item.key}')
  })
})

