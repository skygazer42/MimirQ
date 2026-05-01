import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('EvaluationDataOpsPanel KG diagnostics operations', () => {
  it('surfaces KG diagnostics APIs outside diagnostics pages', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evaluation-data-ops-panel.tsx'), 'utf8')

    for (const api of [
      'evaluationApi.runKgSearchDiagnostics',
      'evaluationApi.listKgSearchDiagnosticsRuns',
      'evaluationApi.getKgSearchDiagnosticsRun',
      'evaluationApi.getKgQualityReport',
    ]) {
      expect(src).toContain(api)
    }
  })
})
