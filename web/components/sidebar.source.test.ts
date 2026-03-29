import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('sidebar chrome contract', () => {
  it('keeps a surface-first, low-noise shell and card treatment', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar.tsx'), 'utf8')

    expect(src).toContain('border-r border-sidebar-border/40')
    expect(src).toContain('shadow-sm relative z-20')
    expect(src).toContain('border-b border-border/40')
    expect(src).toContain('bg-background/35 border border-border/45')
    expect(src).toContain('bg-primary/8 border-primary/35 shadow-xs')
    expect(src).toContain('bg-background/25 hover:bg-background/45 border-border/45 hover:border-primary/15')
  })
})
