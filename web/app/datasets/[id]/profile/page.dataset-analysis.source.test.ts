import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset profile analysis integration', () => {
  it('keeps dataset analysis tools out of the dataset profile page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).not.toContain("import { DatasetAnalysisPanel } from '@/components/datasets/dataset-analysis-panel'")
    expect(src).not.toContain('<DatasetAnalysisPanel')
    expect(src).not.toContain("id=\"prof-analysis\"")
    expect(src).not.toContain("label: '分析闭环'")
  })
})
