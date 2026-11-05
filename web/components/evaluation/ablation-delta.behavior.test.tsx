// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RagasRegressionRunDiffResponse, RegressionRunMetricDiff } from '@/types'

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
    slice_diffs: {},
    significance: [],
    case_diffs: [],
    significance_summary: {},
    ...overrides,
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
        <AblationSliceDiffPanel diff={query.data ?? null} />
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
    })
  }

  it('shows an unavailable metric delta as waiting instead of a measured zero', async () => {
    await load(fixture({ metric_diffs: [{ key: 'retrieval_recall', before: 0.8, after: null, delta: null }] }))
    expect(statistics().textContent).toContain('等待 metric diff')
    expect(statistics().textContent).not.toContain('0.0000')
  })

  it('keeps an omitted optional delta unavailable through the significance fallback', async () => {
    await load(fixture({ metric_diffs: [{ key: 'retrieval_mrr', before: 0.8, after: null }] }))
    expect(statistics().textContent).toContain('等待 metric diff')
    expect(statistics().textContent).not.toContain('0.0000')
  })

  it('uses the next measured slice metric when the preferred metric is unavailable', async () => {
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
    expect(primarySliceDelta()).toBe('-0.2000')
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

  it('preserves a measured zero delta in the statistics fallback', async () => {
    await load(fixture({ metric_diffs: [{ key: 'retrieval_recall', before: 0.8, after: 0.8, delta: 0 }] }))
    expect(statistics().textContent).toContain('0.0000')
    expect(statistics().textContent).toContain('无明显变化')
    expect(statistics().textContent).not.toContain('等待 metric diff')
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
          { key: 'retrieval_recall', compared: 10, delta_mean: 0.3, significant: false },
          { key: 'retrieval_mrr', compared: 10, delta_mean: -0.3, significant: false },
        ],
      }),
    )
    expect(statistics().textContent).toContain('0.3000')
    expect(statistics().textContent).toContain('-0.3000')
    expect(statistics().textContent).toContain('显著候选')
    expect(statistics().textContent).toContain('退化风险')
  })
})
