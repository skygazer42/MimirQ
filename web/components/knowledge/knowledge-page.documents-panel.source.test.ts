import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage documents panel', () => {
  it('uses extracted KnowledgeDocumentsPanel module for documents tab', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('knowledge-documents-panel')
    expect(src).toContain('<KnowledgeDocumentsPanel')
  })

  it('keeps document inventory scoped to the selected dataset even while cached list data is transitioning', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('const scopedDocuments = useMemo(() => {')
    expect(src).toContain("if (!selectedDatasetId) return documents")
    expect(src).toContain("String(doc.dataset_id || '') === selectedDatasetId")
    expect(src).toContain('const next = scopedDocuments.filter((doc) => {')
    expect(src).toContain('const totalDocs = scopedDocuments.length')
    expect(src).toContain('documents={scopedDocuments}')
  })

  it('does not stretch the empty document inventory to full workbench height', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('const documentsEmptySurface =')
    expect(src.split("documentsEmptySurface ? 'flex-none overflow-visible pb-2' : undefined")).toHaveLength(3)
    expect(src).toContain("documentsEmptySurface ? 'flex-none' : 'flex-1'")
  })
})
