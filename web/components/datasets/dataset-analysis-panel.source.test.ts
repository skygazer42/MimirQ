import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset analysis business panel', () => {
  it('connects dataset analysis endpoints outside diagnostics', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'dataset-analysis-panel.tsx'), 'utf8')

    expect(src).toContain('datasetApi.getAnalysisDashboard')
    expect(src).toContain('datasetApi.getAnalysisSummary')
    expect(src).toContain('datasetApi.getAnalysisExamples')
    expect(src).toContain('datasetApi.getAnalysisRuleSuggestions')
    expect(src).toContain('datasetApi.writebackAnalysisGlossary')
    expect(src).toContain('datasetApi.exportAnalysisJson')
    expect(src).toContain('datasetApi.exportAnalysisJsonl')
    expect(src).toContain('datasetApi.exportAnalysisHtmlReport')
    expect(src).toContain('datasetApi.createAnalysisPngExportTask')
    expect(src).toContain('datasetApi.getAnalysisPngExportTask')
    expect(src).toContain('datasetApi.getAnalysisPngExportResult')
  })
})
