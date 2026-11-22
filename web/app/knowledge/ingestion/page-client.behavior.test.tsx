// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const routeState = vi.hoisted(() => ({
  pathname: '/knowledge/ingestion',
  search: 'datasetId=ds-1',
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}))

const datasetsState = vi.hoisted(() => ({
  datasets: [{ id: 'ds-1', name: 'Dataset One' }],
  isLoading: false,
  isFetching: false,
  error: null,
  refreshDatasets: vi.fn(),
}))

const documentApiMock = vi.hoisted(() => ({
  list: vi.fn(),
}))

const datasetApiMock = vi.hoisted(() => ({
  listPrecheckScanRuns: vi.fn(),
  getPrecheckSummary: vi.fn(),
  getPrecheckSamples: vi.fn(),
  getPrecheckNearDups: vi.fn(),
}))

const observabilityApiMock = vi.hoisted(() => ({
  getIngestionDashboardSummary: vi.fn(),
  getTaskQueueSnapshot: vi.fn(),
}))

vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))

vi.mock('next/navigation', () => ({
  useSearchParams: () => {
    const search = routeState.search
    return React.useMemo(() => new URLSearchParams(search), [search])
  },
}))

vi.mock('@/i18n/navigation', () => ({
  usePathname: () => routeState.pathname,
  useRouter: () => routerMock,
}))

vi.mock('@/hooks/use-datasets', () => ({
  useDatasets: () => datasetsState,
}))

vi.mock('@/lib/api', () => ({
  documentApi: documentApiMock,
  datasetApi: datasetApiMock,
  observabilityApi: observabilityApiMock,
}))
vi.mock('@/lib/api/documents', () => ({ documentApi: documentApiMock }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: datasetApiMock }))
vi.mock('@/lib/api/observability', () => ({ observabilityApi: observabilityApiMock }))

vi.mock('@/lib/event-bus', () => ({
  globalEventBus: {
    on: vi.fn(() => vi.fn()),
  },
}))

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('framer-motion', async () => {
  const React = await import('react')
  return {
    AnimatePresence: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
    motion: new Proxy(
      {},
      {
        get:
          (_target, tag: string) =>
          ({
            children,
            drag: _drag,
            dragConstraints: _dragConstraints,
            dragElastic: _dragElastic,
            onDragEnd: _onDragEnd,
            ...props
          }: React.HTMLAttributes<HTMLElement> & {
            drag?: unknown
            dragConstraints?: unknown
            dragElastic?: unknown
            onDragEnd?: unknown
          }) =>
            React.createElement(tag, props, children),
      },
    ),
    useReducedMotion: () => false,
  }
})

vi.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement('button', props, children),
}))

vi.mock('@/components/ui/select', async () => {
  const React = await import('react')
  const Context = React.createContext<((value: string) => void) | undefined>(undefined)
  return {
    Select: ({ children, onValueChange }: { children: React.ReactNode; onValueChange: (value: string) => void }) => (
      <Context.Provider value={onValueChange}>
        <div>{children}</div>
      </Context.Provider>
    ),
    SelectContent: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
    SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => {
      const change = React.useContext(Context)
      return (
        <button data-value={value} onClick={() => change?.(value)}>
          {children}
        </button>
      )
    },
    SelectTrigger: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) =>
      React.createElement('div', props, children),
    SelectValue: () => null,
  }
})

vi.mock('@/components/ui/sheet', () => ({
  Sheet: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
  SheetContent: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  SheetDescription: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  SheetHeader: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  SheetTitle: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
}))

vi.mock('@/components/ui/echart', () => ({
  EChart: () => React.createElement('div', { 'data-echart': 'true' }),
}))

vi.mock('@/components/ui/page-title-icon', () => ({
  PageTitleIcon: () => React.createElement('div', { 'data-page-title-icon': 'true' }),
}))

vi.mock('@/components/ingestion/ingestion-detail-dialog', () => ({
  IngestionDetailDialog: () => null,
}))

import KnowledgeIngestionPageClient from './page-client'

const EMPTY_SUMMARY = {
  window_hours: 12,
  bucket_minutes: 20,
  window_start: '2026-08-16T00:00:00Z',
  window_end: '2026-08-16T12:00:00Z',
  dataset_id: 'ds-1',
  created_count: 0,
  by_status: {},
  by_stage_processing: {},
  avg_completed_latency_sec: null,
  top_error_reasons: {},
  timeseries: {
    ts_ms: [],
    completed: [],
    failed: [],
    quarantined: [],
    cancelled: [],
  },
}

function createExecutionDocument(id: number) {
  return {
    id: `doc-${id}`,
    filename: `Run ${id}.pdf`,
    file_type: 'pdf',
    file_size: 1024 * id,
    status: 'processing',
    current_stage: 'chunking',
    created_at: new Date(Date.UTC(2026, 7, 16, 0, id)).toISOString(),
    updated_at: new Date(Date.UTC(2026, 7, 16, 1, id)).toISOString(),
    total_characters: 1000 * id,
    metadata: {},
  }
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  function Wrapper({ children }: Readonly<{ children: React.ReactNode }>) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children)
  }

  return Wrapper
}

function renderPage() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const Wrapper = createWrapper()

  act(() => {
    root.render(React.createElement(Wrapper, null, React.createElement(KnowledgeIngestionPageClient)))
  })

  return { container, root }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  routeState.pathname = '/knowledge/ingestion'
  routeState.search = 'datasetId=ds-1'
  routerMock.push.mockReset()
  routerMock.replace.mockReset()

  documentApiMock.list.mockResolvedValue({
    items: [createExecutionDocument(1)],
  })
  datasetApiMock.listPrecheckScanRuns.mockResolvedValue({
    items: [{ id: 'run-1', status: 'completed' }],
  })
  datasetApiMock.getPrecheckSummary.mockResolvedValue({
    dataset_id: 'ds-1',
    scan_run_id: 'run-1',
    generated_at: '2026-08-16T08:00:00Z',
    total_files: 1,
    total_size_bytes: 1024,
    by_file_type: { pdf: 1 },
    file_size_histogram: [],
    length_percentiles: { p25: 50, p50: 200, p75: 320, p90: 480, p99: 640 },
    length_histogram: [],
    pdf_scan: { scanned: 1, not_scanned: 0, unknown: 0 },
    pii_hits_total: {},
    secrets_hits_total: {},
    findings: [],
    embedding_advisories: [],
  })
  datasetApiMock.getPrecheckSamples.mockResolvedValue({
    requested: 0,
    strata_count: 0,
    representative: [],
    needs_review: {},
    top_large_files: [],
    top_long_text: [],
  })
  datasetApiMock.getPrecheckNearDups.mockResolvedValue({
    threshold: 3,
    max_pairs: 0,
    pairs_returned: 0,
    clusters_returned: 0,
    clusters: [],
    pairs: [],
  })

  observabilityApiMock.getIngestionDashboardSummary.mockResolvedValue(EMPTY_SUMMARY)
  observabilityApiMock.getTaskQueueSnapshot.mockResolvedValue(null)

  globalThis.window.matchMedia =
    globalThis.window.matchMedia ||
    ((query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as MediaQueryList)
  globalThis.ResizeObserver =
    globalThis.ResizeObserver ||
    class ResizeObserver {
      disconnect() {}
      observe() {}
      unobserve() {}
    }
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

describe('knowledge ingestion page behavior', () => {
  it('shows a primary document query failure', async () => {
    routeState.search = 'datasetId=ds-1&mode=execution-monitor'
    documentApiMock.list.mockRejectedValueOnce(new Error('documents unavailable'))
    const { container, root } = renderPage()
    try {
      await act(async () => {
        await vi.waitFor(() =>
          expect(container.querySelector('[role="alert"]')?.textContent ?? '').toContain('documents unavailable'),
        )
      })
    } finally {
      act(() => root.unmount())
    }
  })
  it('renders execution monitor queue degradation and paginates runtime rows', async () => {
    routeState.search = 'datasetId=ds-1&mode=execution-monitor'
    documentApiMock.list.mockResolvedValueOnce({
      items: Array.from({ length: 21 }, (_, index) => createExecutionDocument(index + 1)),
    })
    observabilityApiMock.getTaskQueueSnapshot.mockResolvedValueOnce({
      enabled: true,
      broker_up: false,
      error: 'queue offline',
    })

    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain('执行监控'))
      await vi.waitFor(() => expect(container.querySelector('[role="alert"]')?.textContent).toContain('queue offline'))
      await vi.waitFor(() => expect(container.textContent).toContain('Run 21.pdf'))
    })

    expect(container.textContent).toContain('queue offline')
    expect(container.textContent).toContain('1 / 2')

    const taskTables = container.querySelectorAll('table')
    const taskTable = taskTables.item(taskTables.length - 1)
    expect(taskTable?.textContent).toContain('Run 21.pdf')
    expect(taskTable?.textContent).not.toContain('Run 1.pdf')

    const nextButton = container.querySelector<HTMLButtonElement>('[aria-label="下一页任务"]')
    expect(nextButton).not.toBeUndefined()

    await act(async () => {
      nextButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await Promise.resolve()
    })

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain('2 / 2'))
      await vi.waitFor(() => expect(taskTables.item(taskTables.length - 1)?.textContent).toContain('Run 1.pdf'))
    })

    act(() => root.unmount())
  })
})
