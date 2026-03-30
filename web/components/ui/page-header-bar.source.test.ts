import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('PageHeaderBar source', () => {
  it('uses sidebar tokens for sticky chrome instead of flat background fills', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-header-bar.tsx'), 'utf8')

    expect(src).toContain('bg-sidebar/80')
    expect(src).toContain('border-sidebar-border/70')
    expect(src).toContain('backdrop-blur-xl')
  })
})
