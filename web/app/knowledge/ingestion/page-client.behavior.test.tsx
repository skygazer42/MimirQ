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

const triggerFilePickerMock = vi.hoisted(() => vi.fn())

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(routeState.search),
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
    AnimatePresence: ({
      children,
    }: {
      children: React.ReactNode
    }) => React.createElement(React.Fragment, null, children),
    motion: new Proxy(
      {},
      {
        get: (_target, tag: string) =>
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
          }) => React.createElement(tag, props, children),
      }
    ),
    useReducedMotion: () => false,
  }
})

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement('button', props, children),
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SelectContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SelectItem: ({
    children,
    value,
  }: {
    children: React.ReactNode
    value: string
  }) => React.createElement('div', { 'data-value': value }, children),
  SelectTrigger: ({
    children,
    ...props
  }: React.HTMLAttributes<HTMLDivElement>) =>
    React.createElement('div', props, children),
  SelectValue: () => null,
}))

vi.mock('@/components/ui/sheet', () => ({
  Sheet: ({
    children,
  }: {
    children: React.ReactNode
  }) => React.createElement(React.Fragment, null, children),
  SheetContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SheetDescription: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SheetHeader: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SheetTitle: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
}))

vi.mock('@/components/ui/echart', () => ({
  EChart: () => React.createElement('div', { 'data-echart': 'true' }),
}))

vi.mock('@/components/ui/page-title-icon', () => ({
  PageTitleIcon: () =>
    React.createElement('div', { 'data-page-title-icon': 'true' }),
}))

vi.mock('@/components/ingestion/drop-zone', async () => {
  const React = await import('react')
  return {
    DropZone: React.forwardRef(function DropZone(
      _props: Record<string, unknown>,
      ref: React.ForwardedRef<{ triggerFilePicker: (args?: unknown) => void }>
    ) {
      React.useImperativeHandle(ref, () => ({
        triggerFilePicker: triggerFilePickerMock,
      }))
      return React.createElement('div', { 'data-drop-zone': 'true' })
    }),
  }
})

vi.mock('@/components/ingestion/empty-state', () => ({
  EmptyState: ({ mode }: { mode: string }) =>
    React.createElement('div', { 'data-empty-state': mode }, mode),
}))

vi.mock('@/components/ingestion/ingestion-detail-dialog', () => ({
  IngestionDetailDialog: () => null,
}))

vi.mock('./components/loading-wireframe', () => ({
  LoadingWireframe: () =>
    React.createElement('div', { 'data-loading-wireframe': 'true' }),
}))

vi.mock('./components/sales-panel-header', () => ({
  SalesPanelHeader: ({
    title,
    actionLabel,
    onAction,
  }: {
    title: string
    actionLabel?: string
    onAction?: () => void
  }) =>
    React.createElement(
      'div',
      null,
      React.createElement('span', null, title),
      actionLabel
        ? React.createElement(
            'button',
            { onClick: onAction, type: 'button' },
            actionLabel
          )
        : null
    ),
}))

vi.mock('./view-switch', () => ({
  IngestionViewSwitch: () =>
    React.createElement('div', { 'data-view-switch': 'true' }),
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
    created_at: `2026-08-16T00:0${id}:00Z`,
    updated_at: `2026-08-16T00:1${id}:00Z`,
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

  return function Wrapper({
    children,
  }: Readonly<{ children: React.ReactNode }>) {
    return React.createElement(
      QueryClientProvider,
      { client: queryClient },
      children
    )
  }
}

function renderPage() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const Wrapper = createWrapper()

  act(() => {
    root.render(
      React.createElement(
        Wrapper,
        null,
        React.createElement(KnowledgeIngestionPageClient)
      )
    )
  })

  return { container, root }
}

beforeEach(() => {
  ;(
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true
  routeState.pathname = '/knowledge/ingestion'
  routeState.search = 'datasetId=ds-1'
  routerMock.push.mockReset()
  routerMock.replace.mockReset()
  triggerFilePickerMock.mockReset()

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

  observabilityApiMock.getIngestionDashboardSummary.mockResolvedValue(
    EMPTY_SUMMARY
  )
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
  it('renders precheck embedding advisories as warnings without implying an automatic model switch', async () => {
    datasetApiMock.getPrecheckSummary.mockResolvedValueOnce({
      dataset_id: 'ds-1',
      scan_run_id: 'run-1',
      generated_at: '2026-08-16T08:00:00Z',
      total_files: 12,
      total_size_bytes: 2048,
      by_file_type: { pdf: 12 },
      file_size_histogram: [],
      length_percentiles: { p25: 50, p50: 200, p75: 320, p90: 480, p99: 640 },
      length_histogram: [],
      pdf_scan: { scanned: 2, not_scanned: 10, unknown: 0 },
      pii_hits_total: {},
      secrets_hits_total: {},
      findings: [],
      embedding_advisories: [
        {
          code: 'zh_or_mixed_corpus_uses_generic_embedding',
          effective_embedding: 'text-embedding-3-small',
          recommended_action: '建议评估中文或多语言 embedding',
          recommended_model_ids: ['text-embedding-v4', 'bge-large-zh'],
        },
      ],
    })

    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('预检发现 embedding 建议')
      )
    })

    expect(container.textContent).toContain(
      '这只是 warning，不表示系统已经自动切换模型。'
    )
    expect(container.textContent).toContain(
      'code=zh_or_mixed_corpus_uses_generic_embedding'
    )
    expect(container.textContent).toContain(
      'current=text-embedding-3-small'
    )
    expect(container.textContent).toContain('recommended=text-embedding-v4')
    expect(container.textContent).toContain('recommended=bge-large-zh')

    act(() => root.unmount())
  })

  it('opens the sales-audit evidence drawer from a high-risk file row', async () => {
    datasetApiMock.getPrecheckSummary.mockResolvedValueOnce({
      dataset_id: 'ds-1',
      scan_run_id: 'run-1',
      generated_at: '2026-08-16T08:00:00Z',
      total_files: 3,
      total_size_bytes: 4096,
      by_file_type: { pdf: 3 },
      file_size_histogram: [],
      length_percentiles: { p25: 50, p50: 200, p75: 320, p90: 480, p99: 640 },
      length_histogram: [],
      pdf_scan: { scanned: 1, not_scanned: 2, unknown: 0 },
      pii_hits_total: { email: 1 },
      secrets_hits_total: {},
      findings: [
        {
          key: 'pii',
          label: 'PII',
          severity: 'warning',
          count: 1,
          description: 'contains personal data',
        },
      ],
      embedding_advisories: [],
    })
    datasetApiMock.getPrecheckSamples.mockResolvedValueOnce({
      requested: 1,
      strata_count: 1,
      representative: [],
      needs_review: {
        pii: [
          {
            name: 'contract-risk.pdf',
            file_type: 'pdf',
            file_size: 4096,
            text_characters: 1200,
            estimated_text: false,
            pdf_scanned: true,
            pdf_pages: {
              page_count: 4,
              scanned_pages: 2,
              text_pages: 2,
              low_density_pages: 0,
              unknown_pages: 0,
              scan_ratio: 0.5,
              low_density_ratio: 0,
            },
            pii_hits: { email: 1 },
            secrets_hits: {},
            pii_samples: [
              {
                kind: 'email',
                masked: 'a***@example.com',
                context: 'Contact: a***@example.com',
              },
            ],
            findings: ['pii'],
          },
        ],
      },
      top_large_files: [],
      top_long_text: [],
    })

    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('高风险文件（示例）')
      )
      await vi.waitFor(() =>
        expect(
          Array.from(container.querySelectorAll<HTMLButtonElement>('button')).some(
            (button) => button.textContent === '查看'
          )
        ).toBe(true)
      )
    })

    const viewButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button')
    ).find((button) => button.textContent === '查看')
    expect(viewButton).not.toBeUndefined()

    await act(async () => {
      viewButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('敏感信息待审核列表')
      )
      await vi.waitFor(() =>
        expect(container.textContent).toContain('为何复杂')
      )
      await vi.waitFor(() =>
        expect(container.textContent).toContain('a***@example.com')
      )
    })

    act(() => root.unmount())
  })

  it('keeps upload actions wired to the drop zone precheck and formal ingest modes', async () => {
    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('入库预检工作台')
      )
    })

    const buttons = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button')
    )
    const sampleButton = buttons.find((button) =>
      button.textContent?.includes('上传预检文件')
    )
    const formalButton = buttons.find((button) =>
      button.textContent?.includes('正式入库')
    )

    expect(sampleButton).not.toBeUndefined()
    expect(formalButton).not.toBeUndefined()

    await act(async () => {
      sampleButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      formalButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(triggerFilePickerMock).toHaveBeenNthCalledWith(1, {
      precheckOnly: true,
    })
    expect(triggerFilePickerMock).toHaveBeenNthCalledWith(2, {
      precheckOnly: false,
    })

    act(() => root.unmount())
  })

  it('keeps the demo exit control removing the demo query flag', async () => {
    routeState.pathname = '/demo/knowledge/ingestion'
    routeState.search = 'datasetId=ds-1&demo=1'

    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('退出演示')
      )
    })

    const exitButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button')
    ).find((button) => button.textContent?.includes('退出演示'))
    expect(exitButton).not.toBeUndefined()

    await act(async () => {
      exitButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(routerMock.replace).toHaveBeenCalledWith(
      '/demo/knowledge/ingestion?datasetId=ds-1'
    )

    act(() => root.unmount())
  })

  it('keeps audit queue checkbox selection toggled by click', async () => {
    documentApiMock.list.mockResolvedValueOnce({
      items: [createExecutionDocument(1)],
    })
    datasetApiMock.getPrecheckSummary.mockResolvedValueOnce({
      dataset_id: 'ds-1',
      scan_run_id: 'run-1',
      generated_at: '2026-08-16T08:00:00Z',
      total_files: 1,
      total_size_bytes: 4096,
      by_file_type: { pdf: 1 },
      file_size_histogram: [],
      length_percentiles: { p25: 50, p50: 200, p75: 320, p90: 480, p99: 640 },
      length_histogram: [],
      pdf_scan: { scanned: 1, not_scanned: 0, unknown: 0 },
      pii_hits_total: { email: 1 },
      secrets_hits_total: {},
      findings: [
        {
          key: 'pii',
          label: 'PII',
          severity: 'warning',
          count: 1,
          description: 'contains personal data',
        },
      ],
      embedding_advisories: [],
    })
    datasetApiMock.getPrecheckSamples.mockResolvedValueOnce({
      requested: 1,
      strata_count: 1,
      representative: [],
      needs_review: {
        pii: [
          {
            name: 'selection-target.pdf',
            file_type: 'pdf',
            file_size: 4096,
            text_characters: 1200,
            estimated_text: false,
            pdf_scanned: true,
            pdf_pages: {
              page_count: 4,
              scanned_pages: 2,
              text_pages: 2,
              low_density_pages: 0,
              unknown_pages: 0,
              scan_ratio: 0.5,
              low_density_ratio: 0,
            },
            pii_hits: { email: 1 },
            secrets_hits: {},
            pii_samples: [],
            findings: ['pii'],
          },
        ],
      },
      top_large_files: [],
      top_long_text: [],
    })

    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('Run 1.pdf')
      )
    })

    const checkbox = container.querySelector<HTMLInputElement>(
      'input[aria-label="选择 Run 1.pdf"]'
    )
    expect(checkbox).not.toBeNull()
    expect(checkbox?.checked).toBe(false)

    await act(async () => {
      checkbox?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(checkbox?.checked).toBe(true)

    await act(async () => {
      checkbox?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(checkbox?.checked).toBe(false)

    act(() => root.unmount())
  })

  it('opens the demo audit snapshot sheet for demo documents', async () => {
    routeState.pathname = '/demo/knowledge/ingestion'
    routeState.search = 'demo=1&mode=execution-monitor'
    documentApiMock.list.mockResolvedValueOnce({
      items: [],
    })

    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('supplier-contract.pdf')
      )
    })

    const snapshotButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button')
    ).find((button) => button.textContent === '快照')
    expect(snapshotButton).not.toBeUndefined()

    await act(async () => {
      snapshotButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('入库快照')
      )
      await vi.waitFor(() =>
        expect(container.textContent).toContain('建议动作')
      )
      await vi.waitFor(() =>
        expect(container.textContent).toContain('supplier-contract.pdf')
      )
    })

    act(() => root.unmount())
  })

  it('renders execution monitor queue degradation and paginates runtime rows', async () => {
    routeState.search = 'datasetId=ds-1&mode=execution-monitor'
    documentApiMock.list.mockResolvedValueOnce({
      items: Array.from({ length: 6 }, (_, index) =>
        createExecutionDocument(index + 1)
      ),
    })
    observabilityApiMock.getTaskQueueSnapshot.mockResolvedValueOnce({
      enabled: true,
      broker_up: false,
      error: 'queue offline',
    })

    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain('执行监控'))
      await vi.waitFor(() => expect(container.textContent).toContain('Broker 异常'))
      await vi.waitFor(() => expect(container.textContent).toContain('Run 1.pdf'))
    })

    expect(container.textContent).toContain('Broker 异常')
    expect(container.textContent).toContain('queue offline')
    expect(container.textContent).toContain('第 1 / 2 页')

    const taskTables = container.querySelectorAll('table')
    const taskTable = taskTables.item(taskTables.length - 1)
    expect(taskTable?.textContent).toContain('Run 6.pdf')
    expect(taskTable?.textContent).not.toContain('Run 1.pdf')

    const nextButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button')
    ).find((button) => button.textContent?.includes('下一页'))
    expect(nextButton).not.toBeUndefined()

    await act(async () => {
      nextButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await Promise.resolve()
    })

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain('第 2 / 2 页'))
      await vi.waitFor(() =>
        expect(taskTables.item(taskTables.length - 1)?.textContent).toContain(
          'Run 1.pdf'
        )
      )
    })

    act(() => root.unmount())
  })
})
