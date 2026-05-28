import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion view switch theme source', () => {
  it('uses theme tokens instead of hardcoded slate and white colors', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'view-switch.tsx'), 'utf8')

    expect(src).toContain('border-border/60')
    expect(src).toContain('bg-card/72')
    expect(src).toContain('bg-primary')
    expect(src).toContain('text-primary-foreground')
    expect(src).toContain('hover:bg-background/82')
    expect(src).toContain('hsl(var(--primary)/0.18)')
    expect(src).not.toContain('border-slate-200')
    expect(src).not.toContain('bg-slate-50')
    expect(src).not.toContain('bg-slate-950')
    expect(src).not.toContain('text-white')
    expect(src).not.toContain('text-slate-600')
    expect(src).not.toContain('hover:bg-white')
  })
})
