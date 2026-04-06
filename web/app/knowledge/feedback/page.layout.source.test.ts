import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('feedback triage page layout', () => {
  it('uses a dense full-width board with inline list controls instead of a floating capsule toolbar', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).not.toContain('toolbar={')
    expect(src).not.toContain('rounded-full p-1.5 max-w-4xl mx-auto md:mx-0')
    expect(src).toContain("const hasActiveFilters = searchTerm.trim().length > 0 || filterType !== 'all' || ratingFilter !== 'all'")
    expect(src).toContain('overflow-hidden rounded-2xl border border-border/60 bg-card shadow-soft')
    expect(src).toContain('placeholder="搜索反馈 / 原因 / 标签 / 账号"')
    expect(src).toContain('{hasActiveFilters ? (')
    expect(src).toContain('const listSummary = useMemo(() => {')
    expect(src).toContain("{items.length ? '长反馈与答复摘要优先' : '当前暂无反馈'}")
    expect(src).toContain('用户反馈')
    expect(src).toContain('模型答复摘要')
    expect(src).toContain("title={filterType === 'all' ? '按类型筛选（当前：全部）'")
    expect(src).toContain("title={ratingFilter === 'all' ? '按星级筛选（当前：全部）'")
    expect(src).toContain("{filterType === 'all' ? '类型' : filterType === 'thumbs_up' ? '类型 · 点赞' : '类型 · 点踩'}")
    expect(src).toContain("{ratingFilter === 'all' ? '星级' : `星级 · ${ratingFilter} 星`}")
  })
})
