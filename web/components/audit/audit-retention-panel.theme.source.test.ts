import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('AuditRetentionPanel theme source', () => {
  it('uses theme tokens instead of fixed audit-operation colors', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'audit-retention-panel.tsx'),
      'utf8'
    )

    expect(src).toContain('AUDIT_RETENTION_PANEL_CLASS')
    expect(src).toContain('AUDIT_RETENTION_HEADER_CLASS')
    expect(src).toContain('AUDIT_RETENTION_PILL_CLASS')
    expect(src).toContain('bg-primary')
    expect(src).toContain('text-primary')
    expect(src).toContain('border-border/60')

    expect(src).not.toContain('bg-white/90')
    expect(src).not.toContain('from-white via-blue-50/35 to-white')
    expect(src).not.toContain("checked ? 'bg-blue-500' : 'bg-slate-200'")
    expect(src).not.toMatch(/\b(?:bg|text|border|divide|hover:bg|hover:text|hover:border|disabled:bg|disabled:text)-(?:slate|blue)-/)
  })
})
