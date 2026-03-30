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
})
