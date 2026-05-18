import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel scroll containment', () => {
  it('keeps the list body as a flex column so the table area can scroll instead of being clipped', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    expect(src).toContain(`<div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              {(() =>`)
    expect(src).toContain('<div className="min-h-0 flex-1 overflow-auto">')
  })
})
