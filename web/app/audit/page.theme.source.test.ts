import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('audit page theme source', () => {
  it('uses theme tokens for the audit console and log table', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('AUDIT_PANEL_CLASS')
    expect(src).toContain('AUDIT_SURFACE_CLASS')
    expect(src).toContain('AUDIT_TABLE_HEAD_CLASS')
    expect(src).toContain('FIELD_LABEL =')
    expect(src).toContain('text-muted-foreground')
    expect(src).toContain('bodyClassName="bg-transparent"')
    expect(src).toContain('accent-[hsl(var(--primary))]')

    expect(src).not.toContain('bg-slate-50/50')
    expect(src).not.toContain('text-blue-400/80')
    expect(src).not.toMatch(/\b(?:bg|text|border|divide|hover:bg|hover:text|hover:border|accent)-(?:slate|blue|purple)-/)
  })
})
