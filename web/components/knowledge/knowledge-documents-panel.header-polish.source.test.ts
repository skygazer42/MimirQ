import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge documents inventory header polish', () => {
  it('uses a richer workbench header and tool strip instead of plain controls', () => {
    const panelSrc = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-page.tsx'),
      'utf8'
    )

    expect(panelSrc).toContain('const inventoryStatCardClassName =')
    expect(panelSrc).toContain('radial-gradient(circle_at_14%_0%')
    expect(panelSrc).toContain('bg-[linear-gradient(90deg,transparent,hsl(var(--primary)/0.42),transparent)]')
    expect(panelSrc).toContain('border border-border/60 bg-card/56')
    expect(panelSrc).toContain('rounded-[14px] border border-border/60 bg-muted/30 px-3 py-2.5')
    expect(panelSrc).toContain("compactEmptyInventory && 'flex-none'")
    expect(panelSrc).toContain('min-h-[272px]')
    expect(pageSrc).toContain('inline-flex max-w-full flex-wrap items-center gap-2 rounded-[12px]')
    expect(pageSrc).toContain('<Database className="mr-1.5 size-3 text-info" />')
    expect(pageSrc).toContain('<Eye className="mr-1.5 size-3 text-info" />')
  })
})
