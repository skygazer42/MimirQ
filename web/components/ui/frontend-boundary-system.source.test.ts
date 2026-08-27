import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readWorkspaceFile(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '../..', relativePath), 'utf8')
}

describe('frontend boundary system', () => {
  it('keeps the global app backdrop uniform instead of layering decorative orbs', () => {
    const background = readWorkspaceFile('components/ui/app-background.tsx')

    expect(background).toContain('app-background__base')
    expect(background).not.toContain('app-background__orb-primary')
    expect(background).not.toContain('app-background__orb-secondary')
    expect(background).not.toContain('blur-3xl')
  })

  it('uses a ruled shared page header without translucent blur or shadow', () => {
    const headerBar = readWorkspaceFile('components/ui/page-header-bar.tsx')
    const header = readWorkspaceFile('components/ui/page-header.tsx')

    expect(headerBar).toContain('border-b border-foreground/15 bg-background')
    expect(headerBar).not.toContain('backdrop-blur')
    expect(headerBar).not.toContain('shadow-subtle')
    expect(header).toContain('border border-foreground/10 bg-background/70')
    expect(header).not.toContain('backdrop-blur-xl')
  })

  it('keeps knowledge workbenches on the same flat boundary baseline', () => {
    const src = readWorkspaceFile('components/ui/knowledge-ops-hero.tsx')

    expect(src).toContain('bg-background')
    expect(src).toContain('border-b border-foreground/15')
    expect(src).toContain('border border-foreground/10 bg-background/70')
    expect(src).not.toContain('radial-gradient')
  })

  it('makes default cards flat while keeping glass an explicit opt-in', () => {
    const card = readWorkspaceFile('components/ui/card.tsx')
    const panel = readWorkspaceFile('components/ui/panel.tsx')

    expect(card).toContain(
      'rounded-lg border border-foreground/10 bg-background text-card-foreground'
    )
    expect(card).not.toContain('shadow-soft')
    expect(card).not.toContain('hover:bg-card/90')
    expect(panel).toContain(
      'default: "rounded-lg border border-foreground/10 bg-background shadow-none"'
    )
    expect(panel).toContain('glass: "rounded-xl border border-border/40 bg-card/50 shadow-soft backdrop-blur-xl"')
  })
})
