import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage color accents', () => {
  it('uses theme tokens for the workbench chrome without changing the layout contract', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('hsl(var(--primary)/0.10)')
    expect(src).toContain('data-knowledge-page-root="true"')
    expect(src).toContain('KNOWLEDGE_GRID_OVERLAY_CLASS')
    expect(src).toContain('bg-card/80')
    expect(src).toContain('bg-background/35')
    expect(src).toContain('shadow-[0_8px_22px_hsl(var(--primary)/0.06)]')
    expect(src).toContain('border-success/15 bg-success/[0.08]')
    expect(src).not.toContain('#fbfdff')
    expect(src).not.toContain('#f2f7ff')
    expect(src).not.toContain('rgba(37,99,235')
    expect(src).not.toContain('bg-[#F5FAFF]/70')
  })
})
