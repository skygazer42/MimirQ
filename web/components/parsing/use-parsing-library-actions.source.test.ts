import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('useParsingLibraryActions source', () => {
  it('keeps restored queue runs aligned with remote normalized elements', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'), 'utf8')

    expect(src).toContain('elements: remote?.elements || libEntry.elements || []')
  })

  it('uploads directly into the selected dataset when parsing is in dataset-bound mode', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'), 'utf8')

    expect(src).toContain('selectedDatasetId: string | null')
    expect(src).toContain('if (selectedDatasetId) {')
    expect(src).toContain('documentApi.upload(queuedFile.file, {')
    expect(src).toContain('dataset_id: selectedDatasetId')
    expect(src).toContain('persist_parsed_content: true')
    expect(src).toContain("source: 'knowledge_base'")
    expect(src).toContain('已上传到当前数据集')
  })
})
