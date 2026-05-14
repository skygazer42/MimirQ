import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge settings panel colors', () => {
  it('adds strategic color accents to embedding and retrieval strategy cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('border-sky-100/80 bg-white/90')
    expect(src).toContain('bg-sky-100/75')
    expect(src).toContain('[&::-webkit-slider-thumb]:border-sky-300')
    expect(src).toContain('[&::-webkit-slider-thumb]:bg-white')
    expect(src).toContain('bg-primary/10 px-2.5 py-0.5 rounded-lg border border-primary/20')
    expect(src).toContain('bg-[#F6FAFF]/70')
    expect(src).toContain('border-sky-100/75 bg-white/88')
    expect(src).toContain('border-sky-100/80 bg-white/86')
    expect(src).toContain('bg-primary/10')
    expect(src).toContain('hover:bg-amber-100/75 hover:text-amber-900')
    expect(src).toContain('hover:bg-sky-100/75 hover:text-sky-900')
    expect(src).toContain('disabled:bg-white/70 disabled:text-muted-foreground/60')
    expect(src).toContain('border-sky-300/90 bg-[linear-gradient(180deg,rgba(239,246,255,0.98),rgba(219,234,254,0.64))]')
    expect(src).toContain('hover:border-sky-200/90 hover:bg-sky-50/72')
    expect(src).toContain('selected ? \'text-sky-800\' : \'text-foreground\'')
    expect(src).toContain('bg-sky-500 shadow-[0_0_12px_rgba(14,165,233,0.45)]')
  })
})
