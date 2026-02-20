import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel row actions', () => {
  it('does not rely on hover-only affordances (touch + keyboard)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    // Hover-only actions are undiscoverable on touch devices.
    // This guard ensures actions can be revealed via keyboard focus within the row.
    expect(src).toContain('md:group-focus-within:opacity-100')
  })
})

