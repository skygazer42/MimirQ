import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage main scroll container binding', () => {
  it('uses a document-list scroll container for virtualized rows with the main pane as fallback', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('useKnowledgeScrollContainer')
    expect(src).toContain('data-knowledge-main-scroll-sentinel="true"')
    expect(src).not.toContain('pageScrollEl')
    expect(src).toContain('const [documentsScrollEl, setDocumentsScrollEl] =')
    expect(src).toContain('getScrollElement: () => documentsScrollEl ?? mainPaneScrollEl')
    expect(src).toContain('onScrollContainerChange={setDocumentsScrollEl}')
  })
})
