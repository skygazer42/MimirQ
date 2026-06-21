import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel scroll containment', () => {
  it('exposes one real document-list scroll container for grid and table virtualization', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    expect(src).toContain(
      'onScrollContainerChange?: (node: HTMLDivElement | null) => void'
    )
    expect(src).toContain('ref={onScrollContainerChange}')
    expect(src).toContain(
      'data-knowledge-documents-scroll-container="true"'
    )
    expect(src).toContain(
      'min-h-0 flex-1 overflow-y-auto overscroll-contain custom-scrollbar [scrollbar-gutter:stable]'
    )
    expect(src).not.toContain('<div className="min-h-0 flex-1 overflow-auto">')
  })
})
