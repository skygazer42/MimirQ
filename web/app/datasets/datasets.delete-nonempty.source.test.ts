import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Datasets non-empty delete flow', () => {
  it('requires explicit document purge before deleting a non-empty dataset', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/datasets-page.tsx'), 'utf8')

    expect(src).toContain('deleteIncludingDocuments')
    expect(src).toContain('datasetApi.purge(datasetId')
    expect(src).toContain('同时删除文档和索引')
    expect(src).toContain('数据集内仍有文档，请勾选')
    expect(src).toContain('await datasetApi.delete(datasetId)')
  })
})
