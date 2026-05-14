import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage color accents', () => {
  it('adds strategic color to the workbench chrome without changing the layout contract', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('rgba(37,99,235,0.10)')
    expect(src).toContain('data-knowledge-page-root="true"')
    expect(src).toContain('KNOWLEDGE_GRID_OVERLAY_CLASS')
    expect(src).toContain('bg-white/[0.92]')
    expect(src).toContain('bg-[#F5FAFF]/70')
    expect(src).toContain('shadow-[0_8px_22px_rgba(37,99,235,0.035)]')
    expect(src).toContain('border-success/15 bg-success/[0.08]')
  })
})
