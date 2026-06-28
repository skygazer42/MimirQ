import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel density tuning', () => {
  it('uses tighter embedded controls and denser table spacing for knowledge workbench layouts', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain("compactEmptyInventory && 'p-2'")
    expect(src).toContain("compactEmptyInventory && 'overflow-visible'")
    expect(src).toContain('sticky top-0 z-10 bg-card/92 px-3 py-2 font-medium dark:bg-background/90')
    expect(src).toContain('group relative flex h-full flex-col rounded-2xl overflow-hidden transition-all duration-300 motion-reduce:transition-none border-border/50 bg-card/40 backdrop-blur-sm')
    expect(src).toContain('border-b border-border/50 bg-[linear-gradient(180deg,hsl(var(--card)/0.70),hsl(var(--surface-2)/0.34))] px-3 py-2.5')
  })
})
