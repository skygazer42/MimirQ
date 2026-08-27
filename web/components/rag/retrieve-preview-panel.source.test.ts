import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieve-preview panel visual contract', () => {
  it('keeps retrieval workbench on a flat ruled surface without blur or decorative overlays', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'retrieve-preview-panel.tsx'),
      'utf8'
    )

    expect(src).toContain(
      "const RETRIEVAL_PANEL_SURFACE_CLASS =\n  'border-foreground/10 bg-background shadow-none backdrop-blur-none"
    )
    expect(src).toContain(
      "const RETRIEVAL_CONTROL_SURFACE_CLASS =\n  'border-foreground/10 bg-background shadow-none"
    )
    expect(src).toContain("className={cn(className, 'relative flex h-full min-h-0 flex-col overflow-hidden bg-background')}")
    expect(src).toContain("className={cn('rounded-xl border', RETRIEVAL_PANEL_SURFACE_CLASS)}")
    expect(src).toContain("className={cn('rounded-lg border', RETRIEVAL_CONTROL_SURFACE_CLASS)}")
    expect(src).not.toContain('bg-[#F8FBFF]/75')
    expect(src).not.toContain('bg-[radial-gradient(')
    expect(src).not.toContain('backdrop-blur-xl')
    expect(src).not.toContain('shadow-[0_14px_26px_-24px_hsl(var(--info)/0.18)]')
    expect(src).not.toContain('rounded-[22px]')
    expect(src).not.toContain('rounded-[24px]')
  })

  it('preserves retrieval behavior and semantic states while simplifying chip chrome', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'retrieve-preview-panel.tsx'),
      'utf8'
    )

    expect(src).toContain('data-semantic-retrieval-mark="true"')
    expect(src).toContain('handleSearch()')
    expect(src).toContain('Family Hit')
    expect(src).toContain('Matched Terms')
    expect(src).toContain('border-warning/20 px-2.5 py-1 text-[11px] font-medium')
    expect(src).toContain('border-foreground/10 bg-background/70')
    expect(src).not.toContain('shadow-[inset_0_1px_0_rgba(255,255,255,0.82)]')
    expect(src).not.toContain('shadow-[0_6px_14px_-8px_hsl(var(--info)/0.55)]')
  })
})
