import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset-folder-tree visual contract', () => {
  it('uses flat selection rows and foreground ruled dividers without inset glow', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'dataset-folder-tree.tsx'),
      'utf8'
    )

    expect(src).toContain("'w-full flex items-center gap-2 rounded-md border border-transparent px-2 py-1.5 text-sm transition-colors group/node'")
    expect(src).toMatch(/isSelected\s*\? 'border-foreground\/10 bg-primary\/\[0\.06\] text-primary'\s*: 'hover:bg-muted\/40'/)
    expect(src).toContain("'w-full flex items-center justify-between rounded-md border border-transparent px-2 py-1.5 text-sm transition-colors focus-ring'")
    expect(src).toMatch(/selectedPath\s*\? 'hover:bg-muted\/40'\s*: 'border-foreground\/10 bg-primary\/\[0\.06\] text-primary'/)
    expect(src).toContain('pointer-events-none absolute bottom-2 top-0 left-[15px] w-px bg-foreground/10')
    expect(src).not.toContain('shadow-[inset_0_0_12px_-6px_rgba(var(--primary),0.3)]')
    expect(src).not.toContain('transition-all duration-200')
  })
})
