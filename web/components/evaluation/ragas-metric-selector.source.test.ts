import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('ragas metric selector productized metric catalog', () => {
  it('surfaces necessary regression-only deterministic metrics without exposing heavy research scope', () => {
    const src = read('ragas-metric-selector.tsx')
    const regressionSrc = read('regression-tab.tsx')
    const pageSrc = fs.readFileSync(path.resolve(__dirname, '..', '..', 'app/evaluations/page.tsx'), 'utf8')

    expect(src).toContain("scope?: 'conversation' | 'regression'")
    expect(src).toContain('atomic_faithfulness')
    expect(src).toContain('hallucination_rate')
    expect(src).toContain('citation_accuracy')
    expect(src).toContain('citation_coverage')
    expect(src).toContain('quote_verifiability')
    expect(src).toContain('程序化')
    expect(src).toContain('回归专用')
    expect(src).not.toContain('ELO Arena')
    expect(src).not.toContain('BEIR')
    expect(src).not.toContain('MTEB')

    expect(regressionSrc).toContain('scope="regression"')
    expect(pageSrc).toContain('scope="conversation"')
  })
})
