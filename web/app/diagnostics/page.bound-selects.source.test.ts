import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('/diagnostics backend-bound selectors', () => {
  it('uses backend dataset and document lists instead of manual id entry', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'page-client.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'datasetApi.list({ limit: 200 })')
    expectSourceToContain(src, 'documentApi.list({ skip: 0, limit: 200')
    expectSourceToContain(src, 'id="diagnostics-dataset"')
    expectSourceToContain(src, 'id="diagnostics-documents"')
    expectSourceNotToContain(src, 'probeDocumentIdsRaw')
    expectSourceNotToContain(src, 'placeholder="例如：9b2f..."')
    expectSourceNotToContain(src, 'placeholder="例如：a1fa..., 8c02..."')
  })

  it('makes diagnostic dimensions explicitly selectable', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'page-client.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'aria-pressed={selected}')
    expectSourceToContain(src, 'selectedDimensionSet.has(dimension.id)')
    expectSourceToContain(src, 'onToggle={() => toggleDimension(dimension.id)}')
  })

  it('prefers the polling ready snapshot for vector dependency status', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'page-client.tsx'),
      'utf8'
    )

    expectSourceToContain(
      src,
      "{ label: '向量后端', status: dependencyStatus(readySnapshot?.vector || depsSnapshot?.milvus) }"
    )
    expectSourceToContain(
      src,
      "{ label: '向量库', status: dependencyStatus(readySnapshot?.vector || depsSnapshot?.milvus) }"
    )
  })
})
