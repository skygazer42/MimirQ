import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel inventory toolbar composition', () => {
  it('fuses inventory controls with the document list surface and strengthens the title/checkbox treatment', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    expect(src).toContain('text-[20px] font-semibold leading-tight tracking-[-0.015em] text-foreground')
    expect(src).toContain('const inventoryToolbar = (')
    expect(src).toContain('checkboxCellClassName')
    expect(src).toContain('checkboxInputClassName')
    expect(src).toContain('border-b border-border/50 bg-[linear-gradient(180deg,hsl(var(--card)/0.70),hsl(var(--surface-2)/0.34))]')
    expect(src).toContain('grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center')
  })
})
