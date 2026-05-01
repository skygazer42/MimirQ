import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('EvaluationDataOpsPanel source', () => {
  it('surfaces regression import/export, synthetic hardcases and purge APIs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evaluation-data-ops-panel.tsx'), 'utf8')

    expect(src).toContain('evaluationApi.exportRegressionCases')
    expect(src).toContain('evaluationApi.importRegressionCases')
    expect(src).toContain('evaluationApi.generateSyntheticHardcases')
    expect(src).toContain('evaluationApi.purgeRegressionRuns')
  })
})
