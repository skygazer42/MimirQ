import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RagasRegressionRunDiffResponse, RegressionRunMetricSignificance } from '@/types'
import { AblationSliceDiffPanel } from './ablation-slice-diff-panel'
import { AblationStatisticsPanel } from './ablation-statistics-panel'

const base: RagasRegressionRunDiffResponse = {
  base_run_id: 'base',
  target_run_id: 'target',
  generated_at: '2026-10-26T00:00:00Z',
  base_params: {},
  target_params: {},
  metric_diffs: [],
  diff_score: null,
  slice_diffs: {},
  significance: [],
  case_diffs: [],
  significance_summary: {},
}

const missingRecall: RegressionRunMetricSignificance = {
  key: 'recall',
  compared: 0,
  base_mean: null,
  target_mean: null,
  delta_mean: null,
  bootstrap_ci_low: null,
  bootstrap_ci_high: null,
  p_value: null,
  p_value_method: null,
  p_value_bh: null,
  wilcoxon_p_value: null,
  mcnemar_p_value: null,
  cohen_d: null,
  significant: false,
}

describe('missing ablation metrics', () => {
  it('keeps a missing statistical delta distinct from a measured zero', () => {
    const missing = renderToStaticMarkup(<AblationStatisticsPanel diff={{ ...base, significance: [missingRecall] }} />)
    const measured = renderToStaticMarkup(
      <AblationStatisticsPanel
        diff={{ ...base, significance: [{ ...missingRecall, compared: 2, delta_mean: 0, p_value_bh: 0.8 }] }}
      />,
    )

    expect(missing).toContain('未提供')
    expect(missing).not.toContain('0.0000')
    expect(measured).toContain('0.0000')
    expect(measured).toContain('未达显著')
  })

  it('shows the selected slice metric alongside the unavailable metric', () => {
    const html = renderToStaticMarkup(
      <AblationSliceDiffPanel
        metricKey="retrieval_mrr"
        diff={{
          ...base,
          slice_diffs: {
            file_type: {
              truncated_before: false,
              truncated_after: false,
              buckets: [
                {
                  key: 'pdf',
                  items_before: 1,
                  items_after: 1,
                  metrics: [
                    { key: 'retrieval_recall', delta: null },
                    { key: 'retrieval_mrr', delta: 0.25 },
                  ],
                },
              ],
            },
          },
        }}
      />,
    )

    expect(html).toContain('retrieval_mrr')
    expect(html).toContain('+0.2500')
    expect(html).not.toContain('+0.0000')
  })
})
