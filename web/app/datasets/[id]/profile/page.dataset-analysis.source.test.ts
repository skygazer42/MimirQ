import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset profile analysis integration', () => {
  it('mounts the dataset analysis panel on the dataset profile page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { DatasetAnalysisPanel } from '@/components/datasets/dataset-analysis-panel'")
    expect(src).toContain('<DatasetAnalysisPanel')
    expect(src).toContain('datasetId={datasetId}')
  })
})
