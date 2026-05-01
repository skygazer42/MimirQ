import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeDocumentsPanel floating command bar', () => {
  it('renders the batch action bar as a strongly detached floating capsule with heavy blur and physical shadow', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    expect(src).toContain('backdrop-blur-2xl')
    expect(src).toContain('shadow-[0_30px_90px_-32px_rgba(15,23,42,0.88)')
    expect(src).toContain('absolute inset-0 bg-background/90')
    expect(src).toContain('absolute -left-8 top-1/2 size-28 -translate-y-1/2 rounded-full bg-primary/10 blur-3xl')
  })
})
