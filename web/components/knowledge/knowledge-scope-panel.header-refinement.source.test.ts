import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel header refinement', () => {
  it('uses a micro navigation header with a filter icon and a gradient divider instead of the older heavy title stack', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toMatch(/import\s*\{[^}]*ChevronDown[^}]*Filter[^}]*\}\s*from\s*'lucide-react'/)
    expect(src).toContain("text-[11px] font-semibold uppercase tracking-[0.22em]")
    expect(src).toContain("text-[11px] font-medium tracking-[0.08em]")
    expect(src).toContain('bg-gradient-to-r from-primary/35 via-border/60 to-transparent')
    expect(src).toContain("t('header.subtitle')")
    expect(src).toContain("t('header.title')")
  })
})
