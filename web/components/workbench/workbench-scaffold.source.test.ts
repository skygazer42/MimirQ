import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('WorkbenchScaffold', () => {
  it('uses safe sizing and avoids window scrolling primitives', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'workbench-scaffold.tsx'), 'utf8')

    // Workbench pages must fit inside AppFrame's locked window scroll.
    expect(src).toContain('min-h-0')
    expect(src).toContain('overflow-hidden')

    // baseline-ui: never use h-screen.
    expect(src).not.toMatch(/\bh-screen\b/)
  })

  it('supports a custom header slot for workbenches that need page-specific title composition', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'workbench-scaffold.tsx'), 'utf8')

    expect(src).toContain('header?: React.ReactNode')
    expect(src).toContain('{header ? (')
    expect(src).toContain("<div className={cn('p-0', headerClassName)}>{header}</div>")
  })

  it('allows pages to opt the main pane out of full-height stretching', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'workbench-scaffold.tsx'), 'utf8')

    expect(src).toContain('mainPaneClassName?: string')
    expect(src).toContain("className={cn('flex-1', mainPaneClassName)}")
  })
})
