import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage embedded documents workbench', () => {
  it('renders the shared workbench surface with embedded scope and specialized document or retrieval panels', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('surface="embedded"')
    expect(src).toContain('<KnowledgeDocumentsPanel')
    expect(src).toContain('<RetrievePreviewPanel selectedDatasetId={selectedDatasetId} className="h-full border-0 bg-transparent p-0 shadow-none" />')
    expect(src).toContain('<KnowledgeRetrievalPanel selectedDatasetId={selectedDatasetId} compact />')
    expect(src).toContain('rounded-2xl')
  })
})
