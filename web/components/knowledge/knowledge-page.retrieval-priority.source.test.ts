import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage retrieval workbench hierarchy', () => {
  it('makes retrieval testing the main canvas, keeps a retrieval-specific scope, and moves audit into the right rail', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')
    const retrievalSection = src.split("{activeTab === 'retrieval' && (")[1] ?? ''

    expect(retrievalSection).toContain('mode="retrieval"')
    expect(retrievalSection).toContain('<RetrievePreviewPanel selectedDatasetId={selectedDatasetId} className="h-full border-0 bg-transparent p-0 shadow-none" />')
    expect(retrievalSection).toContain('<KnowledgeRetrievalPanel selectedDatasetId={selectedDatasetId} compact />')
    expect(retrievalSection).not.toContain('<KnowledgeInspector embedded selectedDocs={selectedDocs}>')
  })
})
