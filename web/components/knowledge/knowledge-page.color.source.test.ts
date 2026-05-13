import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage color accents', () => {
  it('adds strategic color to the workbench chrome without changing the layout contract', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('rgba(37,99,235,0.08)')
    expect(src).toContain('data-knowledge-page-root="true"')
    expect(src).toContain('KNOWLEDGE_GRID_OVERLAY_CLASS')
    expect(src).toContain('bg-white/[0.86]')
    expect(src).toContain('shadow-[0_8px_24px_rgba(15,23,42,0.04)]')
    expect(src).toContain('border-success/15 bg-success/[0.08]')
  })
})
