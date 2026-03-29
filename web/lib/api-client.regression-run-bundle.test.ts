import fs from 'node:fs'

import { describe, expect, it } from 'vitest'

describe('evaluationApi regression run artifacts', () => {
  it('exposes exportRegressionRunBundle (/export-bundle)', () => {
    const url = new URL('./api/evaluation.ts', import.meta.url)
    const src = fs.readFileSync(url, 'utf8')

    expect(src).toContain('exportRegressionRunBundle')
    expect(src).toContain('/evaluations/ragas/regression/runs/')
    expect(src).toContain('/export-bundle')
  })

  it('exposes purgeRegressionRuns (/runs/purge)', () => {
    const url = new URL('./api/evaluation.ts', import.meta.url)
    const src = fs.readFileSync(url, 'utf8')

    expect(src).toContain('purgeRegressionRuns')
    expect(src).toContain("/evaluations/ragas/regression/runs/purge")
  })
})
