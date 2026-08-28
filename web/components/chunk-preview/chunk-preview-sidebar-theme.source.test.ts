import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const sidebar = fs.readFileSync(
  path.resolve(__dirname, 'components/workbench/sidebar-client.tsx'),
  'utf8'
)

describe('chunk preview sidebar theme', () => {
  it('uses Ocean surfaces instead of gray gradients and inset highlights', () => {
    expect(sidebar).toContain(
      "panel: 'border-foreground/10 bg-background/72 antialiased shadow-none'"
    )
    expect(sidebar).toContain(
      "panel: 'border-info/20 bg-info/[0.045] antialiased shadow-none'"
    )
    expect(sidebar).toContain(
      "'rounded-2xl border px-3 py-3 shadow-none'"
    )
    expect(sidebar).not.toContain(
      "panel: 'border-border/60 bg-[linear-gradient(180deg"
    )
    expect(sidebar).not.toContain(
      "panel: 'border-primary/15 bg-[linear-gradient(165deg"
    )
  })

  it('keeps a continuous tinted sidebar without decorative glow meshes', () => {
    expect(sidebar).toContain("'bg-info/[0.035] p-4'")
    expect(sidebar).toContain(
      "chip: 'border-foreground/10 bg-background/82 text-muted-foreground antialiased shadow-none'"
    )
    expect(sidebar).toContain(
      "note: 'border-info/10 bg-background/55 text-muted-foreground antialiased'"
    )
    expect(sidebar).not.toContain('absolute -right-8 -top-8 size-24')
  })
})
