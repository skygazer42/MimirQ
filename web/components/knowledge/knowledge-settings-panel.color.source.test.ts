import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge settings panel colors', () => {
  it('adds strategic color accents to embedding and retrieval strategy cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('border-primary/20 bg-primary/[0.05]')
    expect(src).toContain('border-indigo/20 bg-indigo/[0.05]')
    expect(src).toContain('bg-primary/10 px-2.5 py-0.5 rounded-lg border border-primary/20')
    expect(src).toContain('border-border/40 bg-background/70')
    expect(src).toContain('bg-primary/10')
  })
})
