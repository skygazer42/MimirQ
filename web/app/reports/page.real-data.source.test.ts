// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DatasetReport } from '@/lib/report-schema'
import { waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({
  getDatasetReport: vi.fn<typeof import('@/lib/api/reports').reportApi.getDatasetReport>(),
  listDatasets: vi.fn<typeof import('@/lib/api/datasets').datasetApi.listAll>(),
  listCategories: vi.fn<typeof import('@/lib/api/datasets').datasetCategoryApi.listTree>(),
}))

vi.mock('@/lib/api/reports', () => ({ reportApi: { getDatasetReport: api.getDatasetReport } }))
vi.mock('@/lib/api/datasets', () => ({
  datasetApi: { listAll: api.listDatasets },
  datasetCategoryApi: { listTree: api.listCategories },
}))
vi.mock('@/lib/auth-storage', () => ({
  getAuthSessionKey: () => 'report-session',
  subscribeAuthSession: () => () => {},
}))
vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: { children: React.ReactNode }) => children,
}))
vi.mock('./use-report-exports', () => ({
  useReportExports: () => ({ exporting: null, exportReport: vi.fn() }),
}))
vi.mock('./components/reports-control-panel', () => ({
  ReportsControlPanel: (
    props: React.ComponentProps<typeof import('./components/reports-control-panel').ReportsControlPanel>,
  ) =>
    React.createElement(
      'button',
      {
        onClick: () => {
          props.onPipelineHashChange('pipeline-1')
          props.onConnectorRunsLimitChange(50)
        },
      },
      'Apply report scope',
    ),
}))
vi.mock('./components/reports-result-section', () => ({
  ReportsResultSection: (
    props: React.ComponentProps<typeof import('./components/reports-result-section').ReportsResultSection>,
  ) =>
    React.createElement(
      'output',
      { role: props.reportErrorMessage === undefined ? 'status' : 'alert' },
      props.reportErrorMessage ?? JSON.stringify(props.report),
    ),
}))

import ReportsCenterPage from './page-client'

const percentiles = { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 }
const report = {
  dataset_id: 'dataset-1',
  dataset_name: 'Report dataset',
  pipeline_hash: null,
  generated_at: '2026-11-17T10:00:00Z',
  data_provenance: { mocked: false, source: 'database', generated_by: 'report-service', sections: {} },
  profile: {
    dataset_id: 'dataset-1',
    generated_at: '2026-11-17T10:00:00Z',
    total_documents: 0,
    total_size_bytes: 0,
    by_status: {},
    by_file_type: {},
    by_directory: {},
    by_quality_bucket: {},
    file_size_histogram: [],
    length_percentiles: percentiles,
    length_histogram: [],
    chunk_count_percentiles: percentiles,
    chunk_count_histogram: [],
    avg_chunk_chars_percentiles: percentiles,
    avg_chunk_chars_histogram: [],
    chunk_length_percentiles: percentiles,
    chunk_length_histogram: [],
    chunk_token_percentiles: percentiles,
    chunk_token_histogram: [],
    avg_chunk_tokens_percentiles: percentiles,
    avg_chunk_tokens_histogram: [],
    chunk_coverage_percentiles: percentiles,
    chunk_coverage_histogram: [],
    chunk_overlap_waste_percentiles: percentiles,
    chunk_overlap_waste_histogram: [],
    page_number_histogram: [],
    parse_quality_histogram: [],
    language_mix: {},
    pdf_scan: { scanned: 0, not_scanned: 0, unknown: 0 },
    parsing_provenance: {
      docs_with_provenance: 0,
      by_resolved_backend: {},
      fallback_docs: 0,
      elapsed_ms_percentiles: percentiles,
    },
    pii_hits_total: {},
    secrets_hits_total: {},
    findings: [],
    recall_risk_hints: [],
    chunk_targets: [],
    latest_scan_run: null,
  },
  compliance: { pii_hits_total: {}, secrets_hits_total: {}, quarantined_documents: 0, failed_documents: 0 },
  pipeline_versions: [{ pipeline_hash: 'pipeline-1', documents: 0 }],
  pipeline_snapshots: {},
  connectors: [],
  dataset_metadata: {},
  folder_tree: null,
  governance_metrics: null,
  governance_audit: null,
  retrieval_audit: null,
} satisfies DatasetReport

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
let queryClient: QueryClient

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  api.listDatasets.mockResolvedValue([
    { id: 'dataset-1', tenant_id: 'tenant-1', name: 'Report dataset', permission: 'only_me' },
  ])
  api.listCategories.mockResolvedValue({ total: 0, items: [] })
  api.getDatasetReport.mockImplementation(async (_id, params) => ({
    ...report,
    pipeline_hash: params?.pipeline_hash ?? null,
  }))
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  queryClient.clear()
  container.remove()
})

describe('reports page real data wiring', () => {
  it('loads the selected dataset and applies the current report scope', async () => {
    act(() => {
      root.render(
        React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(ReportsCenterPage)),
      )
    })
    await waitForAssertion(() => expect(container.textContent).toContain('database'))
    expect(api.getDatasetReport).toHaveBeenCalledWith(
      'dataset-1',
      { connector_runs_limit: 20 },
      { signal: expect.any(AbortSignal) },
    )

    act(() => container.querySelector<HTMLButtonElement>('button')?.click())

    await waitForAssertion(() =>
      expect(api.getDatasetReport).toHaveBeenCalledWith(
        'dataset-1',
        { pipeline_hash: 'pipeline-1', connector_runs_limit: 50 },
        { signal: expect.any(AbortSignal) },
      ),
    )
    await waitForAssertion(() => expect(container.querySelector('output')?.textContent).toContain('pipeline-1'))
  })

  it('passes a failed report request to the page error state', async () => {
    api.getDatasetReport.mockRejectedValue(new Error('Report service unavailable'))
    act(() => {
      root.render(
        React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(ReportsCenterPage)),
      )
    })

    await waitForAssertion(() =>
      expect(container.querySelector('[role="alert"]')?.textContent).toBe('Report service unavailable'),
    )
    expect(container.textContent).not.toContain('database')
  })
})
