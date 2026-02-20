import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel list table header', () => {
  it('uses a sticky header so the console table stays scannable while scrolling', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    // We apply sticky positioning to table header cells (safer than relying on <thead> sticky).
    expect(src).toContain('sticky top-0')
    expect(src).toContain('z-10')
    expect(src).toContain('bg-card')
  })
})

