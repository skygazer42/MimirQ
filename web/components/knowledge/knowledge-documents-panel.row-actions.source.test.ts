import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel row actions', () => {
  it('uses contextual chrome that still works for touch + keyboard', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    // Contextual chrome should only hide on fine-pointer/hover devices.
    expect(src).toContain('[@media(hover:hover)_and_(pointer:fine)]:opacity-0')
    expect(src).toContain('[@media(hover:hover)_and_(pointer:fine)]:group-hover:opacity-100')

    // Hover-only affordances are undiscoverable on keyboard navigation.
    expect(src).toContain('group-focus-within:opacity-100')

    // Secondary row detail should follow the same reveal behavior.
    expect(src).toContain('[@media(hover:hover)_and_(pointer:fine)]:group-focus-within:opacity-100')
  })
})
