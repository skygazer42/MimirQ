import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('ragApi PageIndex-style structure endpoints', () => {
  it('exposes real document structure and tree search preview endpoints', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api/rag.ts'), 'utf8')

    expect(src).toContain('DocumentStructureRequest')
    expect(src).toContain('TreeSearchPreviewRequest')
    expect(src).toContain("apiClient.post('/rag/document-structure'")
    expect(src).toContain("apiClient.post('/rag/tree-search-preview'")
    expect(src).toContain('documentStructure(')
    expect(src).toContain('treeSearchPreview(')
  })
})
