import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('navbar section collapse source', () => {
  it('defines default-open navigation sections so lower-priority groups can collapse', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain('DEFAULT_OPEN_SECTIONS')
    expect(src).toContain("title: '核心'")
    expect(src).toContain("title: '知识库管理'")
    expect(src).toContain('setOpenSections')
  })
})
