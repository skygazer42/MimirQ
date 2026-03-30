import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('WorkbenchPane primitives', () => {
  it('enforces internal scrolling and safe sizing', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'workbench-pane.tsx'), 'utf8')

    // Pane containers should not create window scrollbars.
    expect(src).toContain('min-h-0')
    expect(src).toContain('overflow-hidden')

    // Pane bodies should be independently scrollable.
    expect(src).toMatch(/overflow-y-auto/)
    expect(src).toMatch(/overscroll-contain/)

    // RouteScrollReset relies on this attribute.
    expect(src).toMatch(/data-page-scroll-container="true"/)
  })

  it('uses sidebar-tinted pane chrome for workbench headers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'workbench-pane.tsx'), 'utf8')

    expect(src).toContain('bg-sidebar/72')
    expect(src).toContain('border-sidebar-border/70')
    expect(src).toContain('backdrop-blur-xl')
  })
})
