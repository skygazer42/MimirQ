import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing view state source', () => {
  it('uses React Query for parsing library sync and active content hydration', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('const datasetsQuery = useQuery(')
    expect(src).toContain('const librarySyncQuery = useQuery(')
    expect(src).toContain("queryKey: ['parsing', 'library-documents', datasetNameSignature]")
    expect(src).toContain('const activeLibraryContentQuery = useQuery(')
    expect(src).toContain("queryKey: ['parsing', 'library-content', activeLibraryFileId, activeLibraryFile?.source]")
    expect(src).toContain('enabled: Boolean(')
    expect(src).toContain('activeLibraryFileId &&')
    expect(src).toContain('enabled: isLibraryLoaded')
  })

  it('keeps parsing library sync requests within the backend listDocuments limit', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain('parsingApi.listDocuments({ skip: 0, limit: 200 })')
    expect(src).toContain('documentApi.list({ skip: 0, limit: 200 })')
    expect(src).toContain('datasetApi.list({ skip: 0, limit: 200 })')
    expect(src).not.toContain('parsingApi.listDocuments({ skip: 0, limit: 500 })')
  })

  it('bridges knowledge-base documents into the parsing library without reusing parsing content endpoints', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain("source: 'knowledge_base'")
    expect(src).toContain("file.source === 'knowledge_base' && file.datasetId === selectedDatasetId")
    expect(src).toContain('documentApi.getParsedContent(id, { max_chars: 2_000_000 })')
    expect(src).toContain("file.source === 'knowledge_base') return false")
  })

  it('hydrates normalized parsing elements from remote content responses', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain('elements: remote?.elements || []')
  })
})
