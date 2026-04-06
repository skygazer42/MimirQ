import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieve preview panel workbench layout', () => {
  it('uses a sticky multiline composer with a ranked hit list and desktop detail rail instead of the old wide results table', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('<textarea')
    expect(src).toContain("e.key === 'Enter' && !e.shiftKey")
    expect(src).toContain('sticky top-0 z-20')
    expect(src).toContain('aria-label="检索结果排名列表"')
    expect(src).toContain("const activeResult = activeHit ?? searchResults[0] ?? null")
    expect(src).toContain('2xl:grid-cols-[minmax(0,1fr)_21rem]')
    expect(src).not.toContain('aria-label="检索结果候选列表"')
  })

  it('renders a denser no-results diagnostic state with query summary and suggestion chips', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('Top-K 排序为空')
    expect(src).toContain('建议动作')
    expect(src).toContain('排查方向')
    expect(src).toContain('noResultActionTips.map((label) => (')
    expect(src).toContain('searchQueryForRetrieval || searchQuery.trim()')
    expect(src).not.toContain('border-dashed border-border/60 bg-background/40 p-8 text-left')
  })
})
