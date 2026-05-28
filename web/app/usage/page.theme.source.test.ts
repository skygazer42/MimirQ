import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('usage page theme source', () => {
  it('uses theme tokens instead of fixed light-blue surfaces', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('USAGE_PANEL_CLASS')
    expect(src).toContain('USAGE_SURFACE_CLASS')
    expect(src).toContain('USAGE_TABLE_HEAD_CLASS')
    expect(src).toContain('bodyClassName="bg-transparent relative"')
    expect(src).toContain('bg-primary')
    expect(src).toContain('border-border/60')
    expect(src).toContain('text-muted-foreground')

    expect(src).not.toContain('bg-[#F8FAFC]')
    expect(src).not.toContain('border border-slate-200/80 bg-white/85')
    expect(src).not.toContain('border-blue-100 bg-blue-50 text-blue-600')
    expect(src).not.toContain('border-slate-200/70 bg-white/75 text-slate-700')
    expect(src).not.toContain('rgba(59,130,246')
    expect(src).not.toMatch(/\b(?:bg|text|border|divide|hover:bg|hover:text|hover:border)-(?:slate|blue|indigo)-/)
  })
})
