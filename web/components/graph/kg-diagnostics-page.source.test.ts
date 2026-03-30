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
})
