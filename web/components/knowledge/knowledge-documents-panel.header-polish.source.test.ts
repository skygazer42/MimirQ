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
    expect(panelSrc).toContain('rounded-[14px] border border-border/50 bg-[linear-gradient(180deg,hsl(var(--card)/0.90),hsl(var(--surface-2)/0.52))] px-2.5 py-2')
    expect(panelSrc).toContain('border-b border-border/50 bg-[linear-gradient(180deg,hsl(var(--card)/0.70),hsl(var(--surface-2)/0.34))] px-3 py-2.5')
    expect(panelSrc).toContain("compactEmptyInventory && 'p-2'")
    expect(panelSrc).toContain("compactEmptyInventory && 'overflow-visible'")
    expect(pageSrc).toContain('<Database className="mr-1.5 size-3 text-info" />')
    expect(pageSrc).toContain('<Eye className="mr-1.5 size-3 text-info" />')
  })
})
