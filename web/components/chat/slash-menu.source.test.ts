import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('slash menu source', () => {
  it('supports richer search semantics and empty states', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'slash-menu.tsx'), 'utf8')

    expect(src).toContain('CommandEmpty')
    expect(src).toContain('搜索命令或用途...')
    expect(src).toContain('keywords')
    expect(src).toContain('快捷指令')
  })
})
