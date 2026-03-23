import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KG diagnostics quality report wiring', () => {
  it('wires the aggregate KG quality report controls and API client method', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'kg-diagnostics-page.tsx'), 'utf8')
    const apiSrc = fs.readFileSync(path.resolve(__dirname, '../../lib/api-client.ts'), 'utf8')

    expect(pageSrc).toContain('KG Extraction Quality（aggregate）')
    expect(pageSrc).toContain('loadQualityReport')
    expect(pageSrc).toContain('evaluationApi.getKgQualityReport')
    expect(pageSrc).toContain('qualityPipelineHash')
    expect(apiSrc).toContain('getKgQualityReport')
    expect(apiSrc).toContain("'/evaluations/kg/quality/report'")
  })
})
