import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RagasRegressionRunDiffResponse } from '@/types'
import { AblationComparisonSummary } from './ablation-comparison-summary'

const diff: RagasRegressionRunDiffResponse = {
  base_run_id: 'baseline-run',
  target_run_id: 'candidate-run',
  generated_at: '2026-11-23T00:00:00Z',
  base_params: {},
  target_params: {},
  metric_diffs: [],
  diff_score: {
    version: '1',
    used_metric_keys: ['retrieval_mrr'],
    weights: { retrieval_mrr: 1 },
    base_score: 0.6,
    target_score: 0.75,
    delta: 0.15,
    base_metrics: { retrieval_mrr: 0.6 },
    target_metrics: { retrieval_mrr: 0.75 },
  },
  slice_diffs: {},
  significance: [],
  case_diffs: [],
  significance_summary: {},
}

describe('ablation comparison conclusion', () => {
  it('shows baseline, candidate and a signed improvement at the same precision', () => {
    const html = renderToStaticMarkup(<AblationComparisonSummary diff={diff} />)
    expect(html).toContain('基线得分')
    expect(html).toContain('候选得分')
    expect(html).toContain('0.6000')
    expect(html).toContain('0.7500')
    expect(html).toContain('+0.1500')
    expect(html).toContain('text-success')
  })

  it.each([
    { delta: -0.15, text: '-0.1500', tone: 'text-destructive' },
    { delta: 0, text: '0.0000', tone: null },
    { delta: null, text: '—', tone: null },
  ])('distinguishes a $delta delta from improvement', ({ delta, text, tone }) => {
    const html = renderToStaticMarkup(
      <AblationComparisonSummary diff={{ ...diff, diff_score: { ...diff.diff_score!, delta } }} />,
    )
    expect(html).toContain(`>${text}</dd>`)
    expect(html).not.toContain('text-success')
    if (tone) expect(html).toContain(tone)
    else expect(html).not.toContain('text-destructive')
  })

  it('does not turn unavailable scores into measured zeros', () => {
    const html = renderToStaticMarkup(<AblationComparisonSummary diff={{ ...diff, diff_score: null }} />)
    expect(html.match(/>—<\/dd>/g)).toHaveLength(3)
    expect(html).not.toContain('0.0000')
  })
})
