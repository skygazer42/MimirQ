import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeInspector', () => {
  it('uses Panel and token borders (no ad-hoc chrome)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-inspector.tsx'), 'utf8')
    expect(src).toContain('Panel')
    expect(src).toContain('border-border/60')
  })
})

