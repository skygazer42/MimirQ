import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('/diagnostics backend-bound selectors', () => {
  it('uses backend dataset and document lists instead of manual id entry', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('datasetApi.list({ limit: 200 })')
    expect(src).toContain('documentApi.list({ skip: 0, limit: 200')
    expect(src).toContain('id="diagnostics-dataset"')
    expect(src).toContain('id="diagnostics-documents"')
    expect(src).not.toContain('probeDocumentIdsRaw')
    expect(src).not.toContain('placeholder="例如：9b2f..."')
    expect(src).not.toContain('placeholder="例如：a1fa..., 8c02..."')
  })

  it('makes diagnostic dimensions explicitly selectable', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('aria-pressed={selected}')
    expect(src).toContain('selectedDimensionSet.has(dimension.id)')
    expect(src).toContain('onToggle={() => toggleDimension(dimension.id)}')
  })

  it('prefers the polling ready snapshot for vector dependency status', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("{ label: '向量后端', status: dependencyStatus(readySnapshot?.vector || depsSnapshot?.milvus) }")
    expect(src).toContain("{ label: '向量库', status: dependencyStatus(readySnapshot?.vector || depsSnapshot?.milvus) }")
  })
})
