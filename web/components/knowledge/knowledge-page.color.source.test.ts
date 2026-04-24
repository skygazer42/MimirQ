import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage color accents', () => {
  it('adds strategic color to the workbench chrome without changing the layout contract', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('bg-[radial-gradient(circle_at_top_left')
    expect(src).toContain('bg-[linear-gradient(90deg,rgba(14,165,233,0.08),rgba(255,255,255,0.55),rgba(16,185,129,0.08))]')
    expect(src).toContain('border-sky-500/20 bg-sky-500/8')
    expect(src).toContain('border-emerald-500/20 bg-emerald-500/8')
    expect(src).toContain('text-primary shadow-[0_0_12px_-5px_rgba(var(--primary),0.4)]')
  })
})
