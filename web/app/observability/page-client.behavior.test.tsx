// @vitest-environment happy-dom

import React, { type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { RagMetricsSummaryResponse } from '@/types/observability'

const query = vi.hoisted(() => ({ summary: undefined as Partial<RagMetricsSummaryResponse> | undefined }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: ({ queryKey }: { queryKey: string[] }) => ({
    data: queryKey[1] === 'summary' ? query.summary : undefined,
    error: null,
    isPending: false,
    isFetching: false,
  }),
}))
vi.mock('@/components/app-frame', () => ({ AppFrame: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/components/observability/observability-ops-panel', () => ({ ObservabilityOpsPanel: () => null }))

import ObservabilityPage from './page-client'

function rerankMetric(count: number, elapsed: number | null | undefined) {
  query.summary = {
    enabled: true,
    path: 'test-metrics.jsonl',
    window_minutes: 60,
    truncated: false,
    record_count: 0,
    rag_trace_count: 0,
    reranker_api_count: count,
    retrieval_avg_elapsed_sec: null,
    retrieval_p95_elapsed_sec: null,
    rerank_avg_elapsed_sec: elapsed,
    citations_avg_count: null,
    retriever_overfetch_count: 0,
    retriever_overfetch_avg_ratio: null,
    retriever_filtered_acl_total: 0,
    retrieval_candidate_cache_hit_count: 0,
    retrieval_candidate_cache_store_ok_count: 0,
    retrieval_candidate_cache_backend_counts: {},
    retrieval_candidate_cache_skip_reason_counts: {},
    retrieval_rerank_skip_reason_counts: {},
    retrieval_mode_counts: {},
    hit_type_counts: {},
    error_counts: {},
    timeseries: { ts_ms: [], rag_trace: [], reranker_api: [], retrieval_avg_elapsed_sec: [] },
  }
  const container = document.createElement('div')
  container.innerHTML = renderToStaticMarkup(<ObservabilityPage />)
  const label = Array.from(container.querySelectorAll('dt')).find((node) => node.textContent === '重排平均耗时')!
  return label.nextElementSibling!
}

describe('rerank latency reporting', () => {
  it.each([null, undefined])('explains missing elapsed time with recorded calls (%s)', (elapsed) => {
    const metric = rerankMetric(12, elapsed)
    expect(metric.firstChild?.textContent).toBe('—')
    expect(metric.querySelector('small')?.textContent).toBe('12 次调用 · 暂未上报耗时')
  })

  it('distinguishes a window with no calls', () => {
    expect(rerankMetric(0, null).textContent).toBe('—暂无调用')
  })

  it.each([0, 0.125])('keeps a reported duration, including zero (%s)', (elapsed) => {
    const metric = rerankMetric(12, elapsed)
    expect(metric.firstChild?.textContent).toBe(`${elapsed.toFixed(3)}s`)
    expect(metric.querySelector('small')?.textContent).toBe('12 次调用')
  })
})

describe('disabled metrics disclosure', () => {
  it('shows a single setup state without empty metrics when disabled with no records', () => {
    rerankMetric(0, null)
    query.summary!.enabled = false
    const container = document.createElement('div')
    container.innerHTML = renderToStaticMarkup(<ObservabilityPage />)
    expect(container.querySelectorAll('h2')).toHaveLength(1)
    expect(container.querySelector('h2')?.textContent).toBe('指标记录未开启')
    expect(container.querySelector('a[href="/settings"]')?.textContent).toBe('前往设置')
    expect(container.querySelectorAll('dt')).toHaveLength(0)
    expect(container.textContent).not.toContain('当前时间范围暂无观测记录')
  })

  it('keeps historical metrics visible with a compact disabled notice', () => {
    rerankMetric(12, 0.125)
    query.summary!.enabled = false
    query.summary!.record_count = 12
    const container = document.createElement('div')
    container.innerHTML = renderToStaticMarkup(<ObservabilityPage />)
    expect(container.querySelector('[role="status"]')?.textContent).toContain('历史记录')
    expect(container.querySelectorAll('dt').length).toBeGreaterThanOrEqual(4)
    expect(container.textContent).toContain('0.125s')
    expect(container.textContent).not.toContain('当前时间范围暂无观测记录')
  })

  it('keeps the overview and one empty state when recording is enabled', () => {
    rerankMetric(0, null)
    const container = document.createElement('div')
    container.innerHTML = renderToStaticMarkup(<ObservabilityPage />)
    expect(container.querySelectorAll('dt')).toHaveLength(4)
    expect([...container.querySelectorAll('h2')].map((heading) => heading.textContent)).toEqual([
      '当前时间范围暂无观测记录',
    ])
    expect(container.textContent).not.toContain('指标记录未开启')
  })
})
