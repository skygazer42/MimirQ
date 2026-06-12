import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('useParsingLibraryActions source', () => {
  it('keeps restored queue runs aligned with remote normalized elements', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'), 'utf8')

    expect(src).toContain('elements: remote?.elements || libEntry.elements || []')
    expect(src).toContain('function readPersistedElements(')
    expect(src).toContain('restoredElements = readPersistedElements(persistedMeta.elements)')
    expect(src).toContain('elements: restoredElements')
    expect(src).toContain('forceRefresh?: boolean')
    expect(src).toContain('const forceRefresh = Boolean(options.forceRefresh)')
    expect(src).toContain('if (forceRefresh || needsRemoteContent)')
    expect(src).toContain('forceRefresh: true')
  })

  it('keeps parsing uploads isolated from knowledge-base ingestion', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'), 'utf8')

    expect(src).toContain('parsingApi.upload(queuedFile.file, {')
    expect(src).toContain('parser_backend: queuedFile.parserBackend')
    expect(src).toContain('dataset_id: selectedDatasetId')
    expect(src).not.toContain('documentApi.upload(queuedFile.file')
    expect(src).not.toContain('DATASET_SCOPED_UPLOAD_PIPELINE')
    expect(src).not.toContain('已上传到当前数据集')
  })

  it('preserves dataset scope when restoring a library document into the parsing queue', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'), 'utf8')

    expect(src).toContain('datasetId: libEntry.datasetId')
    expect(src).toContain('datasetName: libEntry.datasetName')
    expect(src).toContain('sourcePath: libEntry.sourcePath || libEntry.datasetName || undefined')
  })
})
