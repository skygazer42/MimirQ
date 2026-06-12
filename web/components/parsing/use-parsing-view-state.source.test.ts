import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing view state source', () => {
  it('uses React Query for parsing library sync and active content hydration', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('const datasetsQuery = useQuery(')
    expect(src).toContain('const librarySyncQuery = useQuery(')
    expect(src).toContain("queryKey: ['parsing', 'library-documents', datasetNameSignature, selectedDatasetId || 'all']")
    expect(src).toContain('const activeLibraryContentQuery = useQuery(')
    expect(src).toContain("queryKey: ['parsing', 'library-content', activeLibraryFileId, activeLibraryFile?.source]")
    expect(src).toContain('enabled: activeLibraryNeedsRemoteContent')
    expect(src).toContain('activeLibraryFileId &&')
    expect(src).toContain('enabled: isLibraryLoaded')
  })

  it('keeps parsing library sync requests within the backend listDocuments limit', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain('parsingApi.listDocuments(syncListParams)')
    expect(src).toContain('documentApi.list(syncListParams)')
    expect(src).toContain(': { skip: 0, limit: 200 }')
    expect(src).toContain('datasetApi.list({ skip: 0, limit: 200 })')
    expect(src).not.toContain('parsingApi.listDocuments({ skip: 0, limit: 500 })')
  })

  it('scopes parsing library sync to the selected dataset so active previews are not dropped by global pagination', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain('const syncListParams = selectedDatasetId')
    expect(src).toContain('? { skip: 0, limit: 200, dataset_id: selectedDatasetId }')
    expect(src).toContain('parsingApi.listDocuments(syncListParams)')
    expect(src).toContain('documentApi.list(syncListParams)')
  })

  it('bridges knowledge-base documents into the parsing library without reusing parsing content endpoints', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain("source: 'knowledge_base'")
    expect(src).toContain("file.source === 'parsing_workspace'")
    expect(src).toContain('file.datasetId === selectedDatasetId')
    expect(src).toContain('target_dataset_id')
    expect(src).toContain('documentApi.getParsedContent(id, { max_chars: 2_000_000 })')
    expect(src).toContain("file.source === 'knowledge_base') return false")
  })

  it('polls selected knowledge-base parsing content until background MinerU results are available', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain('const activeLibraryNeedsRemoteContent = Boolean(')
    expect(src).toContain("activeLibraryFile.status === 'pending' || activeLibraryFile.status === 'parsing'")
    expect(src).toContain('refetchInterval: activeLibraryContentPollInterval,')
  })

  it('hydrates normalized parsing elements from remote content responses', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain('elements: remote?.elements || []')
    expect(src).toContain('function readPersistedElements(')
    expect(src).toContain('const serverElements = readPersistedElements(meta?.elements)')
    expect(src).toContain('elements: serverElements.length > 0 ? serverElements : existing?.elements || []')
    expect(src).toContain('const elements = readPersistedElements(persistedMeta.elements)')
    expect(src).toContain('elements,')
  })
})
