import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel density tuning', () => {
  it('uses tighter embedded controls and denser table spacing for knowledge workbench layouts', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain("const controlsClassName = embedded ? 'border-b border-border/60 bg-background/65 px-4 py-3 backdrop-blur-sm' : 'mb-4'")
    expect(src).toContain('sticky top-0 z-10 bg-background/95 px-3 py-2 font-medium')
    expect(src).toContain('className="group/row"')
    expect(src).toContain('grid min-h-[64px] items-center gap-3 px-3 py-3')
  })
})
