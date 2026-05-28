import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge settings panel colors', () => {
  it('adds strategic color accents to embedding and retrieval strategy cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('border border-border/60 bg-card/82')
    expect(src).toContain('border-border/60 bg-background/74')
    expect(src).toContain('[&::-webkit-slider-thumb]:border-primary/45')
    expect(src).toContain('[&::-webkit-slider-thumb]:bg-card')
    expect(src).toContain('bg-primary/10 px-2.5 py-0.5 rounded-lg border border-primary/20')
    expect(src).toContain('bg-info/[0.04]')
    expect(src).toContain('border border-border/60 bg-card/80')
    expect(src).toContain('border border-border/60 bg-card/82')
    expect(src).toContain('bg-primary/10')
    expect(src).toContain('hover:bg-amber-100/75 hover:text-amber-900')
    expect(src).toContain('hover:bg-card/82 hover:text-primary')
    expect(src).toContain('disabled:bg-muted/40 disabled:text-muted-foreground/60')
    expect(src).toContain('border-primary/45 bg-[linear-gradient(180deg,hsl(var(--primary)/0.12),hsl(var(--card)/0.84))]')
    expect(src).toContain('hover:border-primary/30 hover:bg-background/82')
    expect(src).toContain("selected ? 'text-primary' : 'text-foreground'")
    expect(src).toContain('bg-primary shadow-[0_0_12px_hsl(var(--primary)/0.35)]')
  })
})
