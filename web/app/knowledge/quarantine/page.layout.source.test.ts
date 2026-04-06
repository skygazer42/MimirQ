import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('quarantine queue page layout', () => {
  it('uses a full-width review table with inline filters and a right-side review drawer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).not.toContain('toolbar={')
    expect(src).not.toContain("xl:grid-cols-[1.2fr_0.8fr]")
    expect(src).toContain("const [reviewState, setReviewState] = useState<'all' | 'pending' | 'reviewed'>('pending')")
    expect(src).toContain('placeholder="搜索文件名 / 文档 ID"')
    expect(src).toContain('left-auto right-0 top-0 h-dvh w-[min(520px,100vw)] max-w-[520px] translate-x-0 translate-y-0 rounded-none p-0 overflow-hidden')
    expect(src).not.toContain('选择一条隔离记录查看详情')
    expect(src).toContain("const listSummary = useMemo(() => {")
    expect(src).toContain("{documents.length ? '选中后在右侧处置' : '当前空队列'}")
    expect(src).not.toContain('点击任意记录，在右侧抽屉中完成放行、重试或删除。')
  })
})
