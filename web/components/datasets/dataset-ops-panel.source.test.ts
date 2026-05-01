import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('DatasetOpsPanel source', () => {
  it('surfaces dataset clone/export/precheck/table and category maintenance APIs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'dataset-ops-panel.tsx'), 'utf8')

    for (const api of [
      'datasetApi.clone',
      'datasetApi.exportDocumentsNdjson',
      'datasetApi.exportBundleZip',
      'datasetApi.listPrecheckFiles',
      'datasetApi.previewTable',
      'datasetCategoryApi.update',
      'datasetCategoryApi.move',
    ]) {
      expect(src).toContain(api)
    }
  })
})
