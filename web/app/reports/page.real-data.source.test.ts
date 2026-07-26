// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const reportApiMock = vi.hoisted(() => ({
  getDatasetReport: vi.fn(),
}))

vi.mock('@/lib/api/reports', () => ({ reportApi: reportApiMock }))
vi.mock('@/i18n/navigation', () => ({
  Link: 'a',
  usePathname: () => '/reports',
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('next-intl', () => ({
  useLocale: () => 'en',
  useTranslations: () => (key: string) => key,
}))

import { useDatasetReportQuery } from './page-client'

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

afterEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ''
})

describe('reports page real data wiring', () => {
  it('loads the selected dataset report from the live report API', async () => {
    const report = {
      data_provenance: { mocked: false, source: 'database' },
      retrieval_audit: { status: 'passed' },
    }
    reportApiMock.getDatasetReport.mockResolvedValue(report)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    function Probe() {
      const query = useDatasetReportQuery('dataset-1', {
        pipeline_hash: 'pipeline-1',
        connector_runs_limit: 20,
      })
      return React.createElement('output', null, JSON.stringify(query.data ?? null))
    }

    act(() => {
      root.render(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(Probe)
        )
      )
    })

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain('database'))
    })
    expect(reportApiMock.getDatasetReport).toHaveBeenCalledWith('dataset-1', {
      pipeline_hash: 'pipeline-1',
      connector_runs_limit: 20,
    })
    act(() => root.unmount())
    queryClient.clear()
  })
})
