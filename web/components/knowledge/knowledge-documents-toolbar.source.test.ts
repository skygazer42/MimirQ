import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge documents toolbar', () => {
  it('keeps search/sort/view in the main surface and leaves scope filters to the left panel', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')
    const panelSrc = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    // Main surface keeps search + sort + view toggle.
    expect(panelSrc).toContain('<SearchInput')
    expect(panelSrc).toContain('aria-label="排序"')
    expect(pageSrc).toContain('aria-label="网格视图"')
    expect(pageSrc).toContain('aria-label="列表视图"')

    // Scope filters should not live in the main documents toolbar anymore.
    expect(panelSrc).not.toContain('aria-label="筛选数据集"')
    expect(panelSrc).not.toContain('aria-label="按目录筛选"')
    expect(panelSrc).not.toContain('aria-label="筛选生命周期"')
    expect(panelSrc).not.toContain('aria-pressed={statusFilter === item.key}')
  })
})
