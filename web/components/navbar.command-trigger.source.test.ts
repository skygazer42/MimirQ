import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('navbar command trigger source', () => {
  it('surfaces a visible command-menu affordance inside the navigation', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain('打开命令搜索')
    expect(src).toContain('⌘K')
    expect(src).toContain('setCommandMenuOpen')
  })
})
