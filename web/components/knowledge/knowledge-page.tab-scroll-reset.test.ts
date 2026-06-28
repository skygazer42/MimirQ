import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage tab switch scroll reset', () => {
  it('targets the main pane scroll element (no global selector)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('scrollTarget?.scrollTo')
    expect(src).not.toContain('document.querySelector')
    expect(src).not.toContain('[data-page-scroll-container="true"]')
  })
})
