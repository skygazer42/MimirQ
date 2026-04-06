import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk preview sidebar density source', () => {
  it('keeps the settings rail compact and uses tinted helper copy blocks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar-client.tsx'), 'utf8')

    expect(src).toContain("'p-4'")
    expect(src).not.toContain("'p-6'")
    expect(src).toContain("w-[19rem] border-r border-border/60")
    expect(src).toContain('function SidebarChip(')
    expect(src).toContain('function SidebarNote(')
  })
})
