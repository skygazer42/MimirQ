// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RagasRegressionRunDiffResponse, RegressionRunMetricDiff, RegressionRunMetricSignificance } from '@/types'

const controlled = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/lib/api/core', () => ({ apiClient: { get: controlled.get } }))

import { evaluationApi } from '@/lib/api/evaluation'
import { queryKeys } from '@/lib/query-keys'
import { AblationSliceDiffPanel } from './ablation-slice-diff-panel'
import { AblationStatisticsPanel } from './ablation-statistics-panel'

const BASE_ID = '11111111-1111-4111-8111-111111111111'
const TARGET_ID = '22222222-2222-4222-8222-222222222222'
const diffParams = { base_run_id: BASE_ID, include_significance: true, include_per_case: true, max_case_diffs: 500 }

function fixture(overrides: Partial<RagasRegressionRunDiffResponse> = {}): RagasRegressionRunDiffResponse {
  return {
    base_run_id: BASE_ID,
    target_run_id: TARGET_ID,
    generated_at: '2026-11-05T12:00:00Z',
    base_params: {},
    target_params: {},
    metric_diffs: [],
    diff_score: null,
    slice_diffs: {},
    significance: [],
    case_diffs: [],
    significance_summary: {},
    ...overrides,
  }
}

function significance(key: string, compared: number, delta: number | null): RegressionRunMetricSignificance {
  return {
    key,
    compared,
    base_mean: null,
    target_mean: null,
    delta_mean: delta,
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
}

function DiffSurface() {
  const query = useQuery({
    queryKey: queryKeys.evaluations.regressionRunDiff(TARGET_ID, diffParams),
    enabled: false,
    queryFn: () => evaluationApi.diffRegressionRuns(TARGET_ID, diffParams),
  })
  return (
    <>
      <button type="button" onClick={() => void query.refetch()}>
        Generate diff
      </button>
      <div data-testid="statistics">
        <AblationStatisticsPanel diff={query.data ?? null} />
      </div>
      <div data-testid="slices">
        <AblationSliceDiffPanel diff={query.data ?? null} metricKey="retrieval_recall" />
      </div>
    </>
  )
}

describe('nullable ablation deltas from the real diff API through React DOM', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>
  let client: QueryClient

  beforeEach(() => {
    controlled.get.mockReset()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Unexpected HTTP in controlled test')))
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
    vi.unstubAllGlobals()
  })

  function statistics() {
    return container.querySelector('[data-testid="statistics"]') as HTMLDivElement
  }

  function slices() {
    return container.querySelector('[data-testid="slices"]') as HTMLDivElement
  }

  function primarySliceDelta() {
    const label = Array.from(slices().querySelectorAll('div')).find((element) => element.textContent === 'pdf')!
    return label.parentElement!.nextElementSibling!.textContent
  }

  async function load(payload: RagasRegressionRunDiffResponse) {
    controlled.get.mockResolvedValue({ data: payload })
    act(() =>
      root.render(
        <QueryClientProvider client={client}>
          <DiffSurface />
        </QueryClientProvider>,
      ),
    )
    act(() => (container.querySelector('button') as HTMLButtonElement).click())
    await act(async () => {
      await vi.waitFor(() =>
        expect(client.getQueryData(queryKeys.evaluations.regressionRunDiff(TARGET_ID, diffParams))).toEqual(payload),
      )
    })
    expect(controlled.get).toHaveBeenCalledExactlyOnceWith(`/evaluations/ragas/regression/runs/${TARGET_ID}/diff`, {
      params: diffParams,
      signal: undefined,
    })
  }

  it('shows an unavailable statistical delta as missing', async () => {
    await load(fixture({ significance: [significance('retrieval_recall', 0, null)] }))
    expect(statistics().textContent).toContain('未提供')
    expect(statistics().textContent).not.toContain('0.0000')
  })

  it('rejects a response that omits a required nullable delta', async () => {
    controlled.get.mockResolvedValue({
      data: { ...fixture(), metric_diffs: [{ key: 'retrieval_mrr', before: 0.8, after: null }] },
    })
    await expect(evaluationApi.diffRegressionRuns(TARGET_ID, diffParams)).rejects.toThrow('RegressionRunDiff')
  })

  it('keeps the selected slice metric missing while showing other measured deltas', async () => {
    await load(
      fixture({
        slice_diffs: {
          file_type: {
            truncated_before: false,
            truncated_after: false,
            buckets: [
              {
                key: 'pdf',
                items_before: 10,
                items_after: 12,
                metrics: [
                  { key: 'retrieval_recall', before: 0.8, after: null, delta: null },
                  { key: 'retrieval_mrr', before: 0.7, after: 0.5, delta: -0.2 },
                ],
              },
            ],
          },
        },
      }),
    )
    expect(primarySliceDelta()).toBe('-')
    expect(slices().textContent).toContain('-0.2000')
  })

  it('shows a dash when a slice has no comparable metric', async () => {
    await load(
      fixture({
        slice_diffs: {
          file_type: {
            truncated_before: false,
            truncated_after: false,
            buckets: [
              {
                key: 'pdf',
                items_before: 10,
                items_after: 12,
                metrics: [{ key: 'retrieval_recall', before: 0.8, after: null, delta: null }],
              },
            ],
          },
        },
      }),
    )
    expect(primarySliceDelta()).toBe('-')
  })

  it('preserves a measured zero delta in the statistical result', async () => {
    await load(fixture({ significance: [{ ...significance('retrieval_recall', 2, 0), p_value_bh: 0.8 }] }))
    expect(statistics().textContent).toContain('0.0000')
    expect(statistics().textContent).toContain('未达显著')
  })

  it('keeps a genuine zero as the preferred slice metric', async () => {
    const metrics: RegressionRunMetricDiff[] = [
      { key: 'retrieval_recall', before: 0.8, after: 0.8, delta: 0 },
      { key: 'retrieval_mrr', before: 0.7, after: 0.5, delta: -0.2 },
    ]
    await load(
      fixture({
        slice_diffs: {
          file_type: {
            truncated_before: false,
            truncated_after: false,
            buckets: [{ key: 'pdf', items_before: 10, items_after: 12, metrics }],
          },
        },
      }),
    )
    expect(primarySliceDelta()).toBe('+0.0000')
  })

  it('preserves positive and negative measured significance and their verdicts', async () => {
    await load(
      fixture({
        significance: [
          { ...significance('retrieval_recall', 10, 0.3), p_value_bh: 0.01, significant: true },
          { ...significance('retrieval_mrr', 10, -0.3), p_value_bh: 0.2 },
        ],
      }),
    )
    expect(statistics().textContent).toContain('0.3000')
    expect(statistics().textContent).toContain('-0.3000')
    const verdicts = Array.from(statistics().querySelectorAll('tbody tr'), (row) => row.lastElementChild?.textContent)
    expect(verdicts).toEqual(['显著', '未达显著'])
  })
})
