import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('quarantine queue page layout', () => {
  it('uses a compact dashboard header, inline queue filters, and a right-side review drawer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).not.toContain('toolbar={')
    expect(src).not.toContain("xl:grid-cols-[1.2fr_0.8fr]")
    expect(src).toContain('showHeader={false}')
    expect(src).toContain("const [selectedDataset, setSelectedDataset] = useState('all')")
    expect(src).toContain("const [reviewState, setReviewState] = useState<'all' | 'pending' | 'reviewed'>('all')")
    expect(src).toContain('grid gap-2.5 md:grid-cols-2 xl:grid-cols-4')
    expect(src).toContain('placeholder="搜索文件名 / ID / 规则 / 原因"')
    expect(src).toContain('规则集中率')
    expect(src).toContain('较昨日')
    expect(src).toContain('max-w-[1520px]')
    expect(src).toContain('min-h-[104px]')
    expect(src).toContain('bg-[radial-gradient(circle_at_top,rgba(37,99,235,0.10),transparent_34rem)')
    expect(src).toContain('规则命中分布 TOP5')
    expect(src).toContain('快捷操作')
    expect(src).toContain('left-auto right-0 top-0 h-dvh w-[min(520px,100vw)] max-w-[520px] translate-x-0 translate-y-0 rounded-none p-0 overflow-hidden')
    expect(src).toContain("const listSummary = useMemo(() => {")
    expect(src).toContain('当前筛选条件下暂无隔离记录')
    expect(src).toContain('当前没有待审隔离样本')
  })
})
