import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('reports issue rows', () => {
  it('does not render zero-count finding definitions as actual errors', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('const activeFindingRows = findingRows.filter')
    expect(src).toContain('safeNumber(item.count) > 0')
    expect(src).toContain('...activeFindingRows.map((item) => ({')
    expect(src).toContain('风险命中记录')
    expect(src).toContain('仅显示命中项')
    expect(src).not.toContain('...findingRows.map((item) => ({')
    expect(src).not.toContain('最近错误解析')
  })
})
