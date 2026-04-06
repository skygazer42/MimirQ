import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge feedback page source', () => {
  it('renders the refined feedback page description with inline tags', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('汇总点赞、点踩与低分原因，快速定位需要回归验证的反馈。')
    expect(src).toContain('实时分析')
    expect(src).toContain('长文本优先')
    expect(src).toContain('回归线索')
  })
})
