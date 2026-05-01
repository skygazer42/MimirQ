import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function expectKeys(src: string, keys: string[]) {
  for (const key of keys) {
    expect(src).toContain(`t('${key}')`)
  }
}

describe('KG diagnostics quality report wiring', () => {
  it('wires the aggregate KG quality report controls and API client method', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')
    const apiClientSrc = fs.readFileSync(path.resolve(__dirname, '../../lib/api-client.ts'), 'utf8')
    const evaluationApiSrc = fs.readFileSync(path.resolve(__dirname, '../../lib/api/evaluation.ts'), 'utf8')

    expect(pageSrc).toContain("useTranslations('KGDiagnosticsPage')")
    expectKeys(pageSrc, ['qualityReport.title', 'qualityReport.hint'])
    expect(pageSrc).toContain('loadQualityReport')
    expect(pageSrc).toContain('evaluationApi.getKgQualityReport')
    expect(pageSrc).toContain('qualityPipelineHash')
    expect(apiClientSrc).toContain("export { evaluationApi } from '@/lib/api/evaluation'")
    expect(evaluationApiSrc).toContain('getKgQualityReport')
    expect(evaluationApiSrc).toContain("'/evaluations/kg/quality/report'")
  })

  it('moves KG diagnostics page scaffold actions and toast copy into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expectKeys(pageSrc, [
      'page.title',
      'page.description',
      'page.actions.refreshRuns',
      'page.actions.run',
      'page.actions.exportRun',
      'toasts.datasetRequired',
      'toasts.runsLoadFailed',
      'toasts.qualityReportLoaded',
      'toasts.qualityReportLoadFailed',
      'toasts.diagnosticsRan',
      'toasts.diagnosticsRunFailed',
      'toasts.runExported',
    ])
    expect(pageSrc).toContain("t('toasts.runLoadFailed'")
  })

  it('moves KG diagnostics run config labels and placeholders into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expectKeys(pageSrc, [
      'runConfig.title',
      'runConfig.datasetId',
      'runConfig.datasetPlaceholder',
      'runConfig.hardcaseMode',
      'runConfig.hardcaseModePlaceholder',
      'runConfig.maxCases',
      'runConfig.k',
      'runConfig.hardcasesPerFailedCase',
      'runConfig.maxFailedCasesForHardcase',
      'runConfig.llmTemperature',
      'runConfig.extractSkills',
      'runConfig.extractRelations',
      'runConfig.extractModePlaceholder',
      'runConfig.autoExtractKg',
      'runConfig.persistRun',
    ])
  })

  it('moves KG diagnostics summary and quality report controls into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expectKeys(pageSrc, [
      'summary.title',
      'summary.baselineHitRate',
      'summary.baselineMrr',
      'summary.baselineRecall',
      'summary.baselineNdcg',
      'summary.baselineMap',
      'summary.hardcasesGenerated',
      'summary.empty',
      'summary.runHint',
      'qualityReport.pull',
      'qualityReport.documentLimit',
      'qualityReport.pipelineHash',
      'qualityReport.pipelineHashPlaceholder',
    ])
  })

  it('moves KG diagnostics runs and compare copy into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expectKeys(pageSrc, [
      'runs.title',
      'runs.refresh',
      'runs.hint',
      'runs.runA',
      'runs.runAPlaceholder',
      'runs.loadA',
      'runs.runB',
      'runs.runBPlaceholder',
      'runs.loadB',
      'compare.title',
      'compare.export',
      'compare.exported',
      'compare.hitFlips',
      'compare.summaryKeys',
      'compare.empty',
      'compare.diffJson',
      'compare.diffHint',
      'compare.changedCases',
      'compare.noQuestion',
    ])
  })
})
