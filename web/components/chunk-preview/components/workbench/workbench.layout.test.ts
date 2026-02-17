import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview workbench layout', () => {
  it('uses safe sizing + workbench primitives (min-h-0, overflow-hidden, panes, pipeline rail)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')

    expect(src).toContain('min-h-0')
    expect(src).toContain('overflow-hidden')
    expect(src).toContain('WorkbenchPane')
    expect(src).toContain('PipelineRail')

    // baseline-ui: avoid window-sized primitives.
    expect(src).not.toMatch(/\bh-screen\b/)
  })
})

