import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage color accents', () => {
  it('adds strategic color to the workbench chrome without changing the layout contract', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('border-info/20 bg-info/[0.08] text-info')
    expect(src).toContain('border-success/15 bg-success/[0.08]')
  })
})
