import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RagasRegressionRunDiffResponse } from '@/types'
import { AblationSliceDiffPanel } from './ablation-slice-diff-panel'
import { AblationStatisticsPanel } from './ablation-statistics-panel'

const base: RagasRegressionRunDiffResponse = {
  base_run_id: 'base', target_run_id: 'target', generated_at: '2026-10-26T00:00:00Z',
  base_params: {}, target_params: {}, metric_diffs: [], slice_diffs: {}, significance: [], case_diffs: [], significance_summary: {},
}

describe('missing ablation metrics', () => {
  it('keeps a missing statistical delta distinct from a measured zero', () => {
    const missing = renderToStaticMarkup(<AblationStatisticsPanel diff={{ ...base, significance: [{ key: 'recall', compared: 0, significant: false, delta_mean: null }] }} />)
    const measured = renderToStaticMarkup(<AblationStatisticsPanel diff={{ ...base, significance: [{ key: 'recall', compared: 2, significant: false, delta_mean: 0 }] }} />)

    expect(missing).toContain('等待 metric diff')
    expect(missing).not.toContain('0.0000')
    expect(measured).toContain('0.0000')
    expect(measured).toContain('无明显变化')
  })

  it('skips an absent preferred metric and shows the next measured slice delta', () => {
    const html = renderToStaticMarkup(<AblationSliceDiffPanel diff={{ ...base, slice_diffs: {
      file_type: { truncated_before: false, truncated_after: false, buckets: [{ key: 'pdf', items_before: 1, items_after: 1, metrics: [
        { key: 'retrieval_recall', delta: null }, { key: 'retrieval_mrr', delta: 0.25 },
      ] }] },
    } }} />)

    expect(html).toContain('retrieval_mrr')
    expect(html).toContain('+0.2500')
    expect(html).not.toContain('+0.0000')
  })
})
