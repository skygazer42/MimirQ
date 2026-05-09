import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings groups page layout source', () => {
  it('keeps the design-reference structure for summary, search, empty state, and pagination', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('GroupSummaryStrip')
    expect(src).toContain('PAGE_SIZE_OPTIONS')
    expect(src).toContain('每页 {size} 条')
    expect(src).toContain('按名称 / 外部组 ID（external_id） / 组 ID 过滤')
    expect(src).toContain('暂无组')
    expect(src).toContain('共 {filtered.length} 条')
    expect(src).toContain('min-h-[560px]')
    expect(src).toContain('min-h-[390px]')
    expect(src).toContain('[&_h1]:!text-[27px]')
  })
})
