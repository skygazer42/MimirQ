import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage main scroll container binding', () => {
  it('uses a sentinel + useKnowledgeScrollContainer (not pageScrollEl state)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('useKnowledgeScrollContainer')
    expect(src).toContain('data-knowledge-main-scroll-sentinel="true"')
    expect(src).not.toContain('pageScrollEl')
    expect(src).toContain('getScrollElement: () => mainPaneScrollEl')
  })
})

