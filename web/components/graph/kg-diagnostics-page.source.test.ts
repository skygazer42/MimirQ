import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KG diagnostics quality report wiring', () => {
  it('wires the aggregate KG quality report controls and API client method', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')
    const apiClientSrc = fs.readFileSync(path.resolve(__dirname, '../../lib/api-client.ts'), 'utf8')
    const evaluationApiSrc = fs.readFileSync(path.resolve(__dirname, '../../lib/api/evaluation.ts'), 'utf8')

    expect(pageSrc).toContain("useTranslations('KGDiagnosticsPage')")
    expect(pageSrc).toContain('t("qualityReport.title")')
    expect(pageSrc).toContain('t("qualityReport.hint")')
    expect(pageSrc).toContain('loadQualityReport')
    expect(pageSrc).toContain('evaluationApi.getKgQualityReport')
    expect(pageSrc).toContain('qualityPipelineHash')
    expect(apiClientSrc).toContain("export { evaluationApi } from '@/lib/api/evaluation'")
    expect(evaluationApiSrc).toContain('getKgQualityReport')
    expect(evaluationApiSrc).toContain("'/evaluations/kg/quality/report'")
  })

  it('moves KG diagnostics page scaffold actions and toast copy into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('t("page.title")')
    expect(pageSrc).toContain('t("page.description")')
    expect(pageSrc).toContain('t("page.actions.refreshRuns")')
    expect(pageSrc).toContain('t("page.actions.run")')
    expect(pageSrc).toContain('t("page.actions.exportRun")')
    expect(pageSrc).toContain('t("toasts.datasetRequired")')
    expect(pageSrc).toContain('t("toasts.runsLoadFailed")')
    expect(pageSrc).toContain('t("toasts.runLoadFailed"')
    expect(pageSrc).toContain('t("toasts.qualityReportLoaded")')
    expect(pageSrc).toContain('t("toasts.qualityReportLoadFailed")')
    expect(pageSrc).toContain('t("toasts.diagnosticsRan")')
    expect(pageSrc).toContain('t("toasts.diagnosticsRunFailed")')
    expect(pageSrc).toContain('t("toasts.runExported")')
  })

  it('moves KG diagnostics run config labels and placeholders into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('t("runConfig.title")')
    expect(pageSrc).toContain('t("runConfig.datasetId")')
    expect(pageSrc).toContain('t("runConfig.datasetPlaceholder")')
    expect(pageSrc).toContain('t("runConfig.hardcaseMode")')
    expect(pageSrc).toContain('t("runConfig.hardcaseModePlaceholder")')
    expect(pageSrc).toContain('t("runConfig.maxCases")')
    expect(pageSrc).toContain('t("runConfig.k")')
    expect(pageSrc).toContain('t("runConfig.hardcasesPerFailedCase")')
    expect(pageSrc).toContain('t("runConfig.maxFailedCasesForHardcase")')
    expect(pageSrc).toContain('t("runConfig.llmTemperature")')
    expect(pageSrc).toContain('t("runConfig.extractSkills")')
    expect(pageSrc).toContain('t("runConfig.extractRelations")')
    expect(pageSrc).toContain('t("runConfig.extractModePlaceholder")')
    expect(pageSrc).toContain('t("runConfig.autoExtractKg")')
    expect(pageSrc).toContain('t("runConfig.persistRun")')
  })

  it('moves KG diagnostics summary and quality report controls into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('t("summary.title")')
    expect(pageSrc).toContain('t("summary.baselineHitRate")')
    expect(pageSrc).toContain('t("summary.baselineMrr")')
    expect(pageSrc).toContain('t("summary.baselineRecall")')
    expect(pageSrc).toContain('t("summary.hardcasesGenerated")')
    expect(pageSrc).toContain('t("summary.empty")')
    expect(pageSrc).toContain('t("summary.runHint")')
    expect(pageSrc).toContain('t("qualityReport.pull")')
    expect(pageSrc).toContain('t("qualityReport.documentLimit")')
    expect(pageSrc).toContain('t("qualityReport.pipelineHash")')
    expect(pageSrc).toContain('t("qualityReport.pipelineHashPlaceholder")')
  })

  it('moves KG diagnostics runs and compare copy into next-intl lookups', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')

    expect(pageSrc).toContain('t("runs.title")')
    expect(pageSrc).toContain('t("runs.refresh")')
    expect(pageSrc).toContain('t("runs.hint")')
    expect(pageSrc).toContain('t("runs.runA")')
    expect(pageSrc).toContain('t("runs.runAPlaceholder")')
    expect(pageSrc).toContain('t("runs.loadA")')
    expect(pageSrc).toContain('t("runs.runB")')
    expect(pageSrc).toContain('t("runs.runBPlaceholder")')
    expect(pageSrc).toContain('t("runs.loadB")')
    expect(pageSrc).toContain('t("compare.title")')
    expect(pageSrc).toContain('t("compare.export")')
    expect(pageSrc).toContain('t("compare.exported")')
    expect(pageSrc).toContain('t("compare.hitFlips")')
    expect(pageSrc).toContain('t("compare.summaryKeys")')
    expect(pageSrc).toContain('t("compare.empty")')
    expect(pageSrc).toContain('t("compare.diffJson")')
    expect(pageSrc).toContain('t("compare.diffHint")')
    expect(pageSrc).toContain('t("compare.changedCases")')
    expect(pageSrc).toContain('t("compare.noQuestion")')
  })
})
