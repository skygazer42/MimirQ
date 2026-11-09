// @vitest-environment happy-dom

import React, { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { queryKeys } from '@/lib/query-keys'
import type { DatasetPrecheckScanRunOut, DatasetPrecheckSummary, DatasetTableAsset } from '@/types/datasets'

const api = vi.hoisted(() => ({
  get: vi.fn(),
  listTables: vi.fn(),
  getTable: vi.fn(),
  queryTable: vi.fn(),
  askTable: vi.fn(),
  lotusSemFilter: vi.fn(),
  listPrecheckScanRuns: vi.fn(),
  getPrecheckSummary: vi.fn(),
  getProfileSummary: vi.fn(),
  listProfileScanRuns: vi.fn(),
  getProfileScanRun: vi.fn(),
}))

vi.mock('next/navigation', () => ({ useParams: () => ({ id: 'dataset-a' }) }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api', () => ({ datasetApi: api, documentApi: {}, sseApi: {} }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn(), reportClientWarning: vi.fn() }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('@/components/app-frame', () => ({ AppFrame: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/components/ui/page-scaffold', () => ({
  PageScaffold: ({ top, toolbar, children }: { top: ReactNode; toolbar: ReactNode; children: ReactNode }) => (
    <main>
      {top}
      {toolbar}
      {children}
    </main>
  ),
}))
vi.mock('@/components/ui/safe-responsive-chart', () => ({ SafeResponsiveChart: () => null }))
vi.mock('@/components/document-detail-dialog', () => ({ DocumentDetailDialog: () => null }))

import DatasetTablesPage from './tables/page'
import DatasetPrecheckPage from './precheck/page-client'
import DatasetProfilePage from './profile/page-client'

const disposers: Array<() => void> = []

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function table(id: string, sheetIndex: number): DatasetTableAsset {
  return {
    table_id: id,
    document_id: `doc-${id}`,
    sheet_name: id,
    sheet_index: sheetIndex,
    row_count: 1,
    col_count: 1,
    truncated: false,
    columns: [{ name: `${id}-column` }],
    sample_rows: [{ value: id }],
  }
}

function run(id: string): DatasetPrecheckScanRunOut {
  return {
    id,
    dataset_id: 'dataset-a',
    tenant_id: 'tenant-a',
    kind: 'precheck',
    status: 'completed',
    progress: 100,
    config: {},
    summary: {},
    artifacts: {},
  }
}

function summary(id: string, findingLabel: string): DatasetPrecheckSummary {
  return {
    dataset_id: 'dataset-a',
    scan_run_id: id,
    generated_at: '2026-11-05T00:00:00Z',
    total_files: 1,
    total_size_bytes: 10,
    by_file_type: {},
    file_size_histogram: [],
    length_percentiles: { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 },
    length_histogram: [],
    pdf_scan: { scanned: 0, not_scanned: 0, unknown: 0 },
    pii_hits_total: {},
    secrets_hits_total: {},
    findings: [{ key: id, label: findingLabel, severity: 'warning', count: 1 }],
  }
}

function mount(element: ReactNode, seed?: (client: QueryClient) => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } },
  })
  client.setQueryData(queryKeys.datasets.detail('dataset-a'), { id: 'dataset-a', name: 'Dataset A' })
  seed?.(client)
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root: Root = createRoot(container)
  act(() => root.render(<QueryClientProvider client={client}>{element}</QueryClientProvider>))
  let mounted = true
  const unmount = () => {
    if (!mounted) return
    act(() => root.unmount())
    mounted = false
  }
  disposers.push(() => {
    unmount()
    client.clear()
    container.remove()
  })
  return { container, unmount }
}

function button(text: string, container: ParentNode = document): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll('button')).find((node) => node.textContent?.trim() === text)
  expect(found, `button ${text}`).toBeTruthy()
  return found!
}

function tableButton(name: string): HTMLButtonElement {
  const found = Array.from(document.querySelectorAll('button')).find((node) =>
    Array.from(node.querySelectorAll('div')).some((child) => child.textContent?.trim() === name),
  )
  expect(found, `table ${name}`).toBeTruthy()
  return found!
}

async function click(node: HTMLElement) {
  await act(async () => node.click())
}

async function setInput(node: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(node, value)
    node.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function chooseRun(id: string) {
  const trigger = document.getElementById('precheck-run-history')!
  await act(async () => trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })))
  const option = Array.from(document.querySelectorAll<HTMLElement>('[role="option"]')).find((node) =>
    node.textContent?.includes(id),
  )
  expect(option, `run ${id}`).toBeTruthy()
  await act(async () => option!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
})

afterEach(() => {
  for (const dispose of disposers.splice(0).reverse()) dispose()
  vi.useRealTimers()
})

describe('dataset workspace request ownership', () => {
  const first = table('table-a', 1)
  const second = table('table-b', 2)

  function mountTables() {
    return mount(<DatasetTablesPage />, (client) =>
      client.setQueryData(queryKeys.datasets.tables('dataset-a', { skip: 0, limit: 200 }), {
        items: [first, second],
        total: 2,
      }),
    )
  }

  it('keeps the latest table and SQL target when a previous detail finishes last', async () => {
    const earlier = deferred<DatasetTableAsset>()
    api.getTable.mockImplementation((_dataset: string, id: string) =>
      id === first.table_id ? earlier.promise : Promise.resolve(second),
    )
    const view = mountTables()
    await click(tableButton(first.sheet_name!))
    await click(tableButton(second.sheet_name!))
    await act(async () => earlier.resolve(first))

    expect(view.container.querySelector('textarea')?.value).toBe('SELECT * FROM "sheet_2" LIMIT 20')
    expect(view.container.textContent).toContain('table-b-column')
    expect(view.container.textContent).not.toContain('table-a-column')
  })

  it('publishes the current table detail and query result', async () => {
    api.getTable.mockResolvedValue(second)
    api.queryTable.mockResolvedValue({ columns: ['value'], rows: [['CURRENT_RESULT']], truncated: false })
    const view = mountTables()
    await click(tableButton(second.sheet_name!))
    await click(button('执行'))

    expect(api.queryTable).toHaveBeenCalledWith('dataset-a', 'table-b', { sql: 'SELECT * FROM "sheet_2" LIMIT 20' })
    expect(view.container.textContent).toContain('CURRENT_RESULT')
  })

  it.each(['queryTable', 'askTable', 'lotusSemFilter'] as const)(
    'keeps a previous %s result out of the newly selected table',
    async (operation) => {
      const earlier = deferred<unknown>()
      api[operation].mockReturnValue(earlier.promise)
      api.getTable.mockResolvedValue(second)
      const view = mountTables()
      if (operation === 'queryTable') {
        await click(button('执行'))
      } else if (operation === 'askTable') {
        await setInput(view.container.querySelector('input[placeholder*="按地区"]')!, 'question for A')
        await click(button('询问'))
      } else {
        await setInput(view.container.querySelector('input[placeholder*="客户名称"]')!, 'filter for A')
        await click(button('运行'))
      }
      expect(api[operation]).toHaveBeenCalledOnce()
      await click(tableButton(second.sheet_name!))
      await act(async () => {
        earlier.resolve(
          operation === 'askTable'
            ? { answer: 'ONLY_TABLE_A_RESULT' }
            : { sql: 'select', columns: ['value'], rows: [['ONLY_TABLE_A_RESULT']], truncated: false },
        )
      })

      expect(view.container.textContent).not.toContain('ONLY_TABLE_A_RESULT')
      expect(view.container.textContent).toContain('table-b-column')
    },
  )

  it.each(['success', 'failure'] as const)('keeps the selected precheck summary after an old %s', async (outcome) => {
    const earlier = deferred<DatasetPrecheckSummary>()
    api.getPrecheckSummary.mockImplementation((_dataset: string, id: string) =>
      id === 'run-a' ? earlier.promise : Promise.resolve(summary('run-b', 'FINDING_FOR_B')),
    )
    const view = mount(<DatasetPrecheckPage />, (client) =>
      client.setQueryData(queryKeys.datasets.precheckRuns('dataset-a', { skip: 0, limit: 20 }), {
        items: [run('run-a'), run('run-b')],
        total: 2,
      }),
    )
    await act(async () => {})
    expect(api.getPrecheckSummary).toHaveBeenCalledWith('dataset-a', 'run-a')
    await chooseRun('run-b')
    expect(api.getPrecheckSummary).toHaveBeenCalledWith('dataset-a', 'run-b')
    expect(view.container.textContent).toContain('FINDING_FOR_B')
    await act(async () => {
      if (outcome === 'success') earlier.resolve(summary('run-a', 'OLD_FINDING_FOR_A'))
      else earlier.reject(new Error('old summary unavailable'))
    })

    expect(view.container.textContent).toContain('FINDING_FOR_B')
    expect(view.container.textContent).not.toContain('OLD_FINDING_FOR_A')
  })

  it('publishes the current completed precheck summary', async () => {
    api.getPrecheckSummary.mockResolvedValue(summary('run-a', 'CURRENT_FINDING'))
    const view = mount(<DatasetPrecheckPage />, (client) =>
      client.setQueryData(queryKeys.datasets.precheckRuns('dataset-a', { skip: 0, limit: 20 }), {
        items: [run('run-a')],
        total: 1,
      }),
    )
    await act(async () => {})

    expect(view.container.textContent).toContain('CURRENT_FINDING')
  })

  it('continues the active profile polling request', async () => {
    vi.useFakeTimers()
    const inFlight = deferred<unknown>()
    api.getProfileScanRun.mockReturnValueOnce(inFlight.promise).mockReturnValue(new Promise(() => {}))
    const view = mount(<DatasetProfilePage />, (client) => {
      client.setQueryData(queryKeys.datasets.profileSummary('dataset-a'), {
        total_documents: 0,
        pdf_scan: { scanned: 0, not_scanned: 0, unknown: 0 },
        latest_scan_run: { id: 'profile-a', status: 'running', progress: 10 },
      })
      client.setQueryData(queryKeys.datasets.profileScanRuns('dataset-a', { skip: 0, limit: 20 }), {
        items: [],
        total: 0,
      })
    })
    await act(async () => vi.advanceTimersByTimeAsync(500))
    await act(async () => inFlight.resolve({ id: 'profile-a', status: 'running', progress: 30 }))
    expect(view.container.textContent).toContain('30%')
    await act(async () => vi.advanceTimersByTimeAsync(2000))

    expect(api.getProfileScanRun).toHaveBeenCalledTimes(2)
  })

  it('does not restart profile polling after its page is unmounted', async () => {
    vi.useFakeTimers()
    const inFlight = deferred<unknown>()
    api.getProfileScanRun.mockReturnValue(inFlight.promise)
    const view = mount(<DatasetProfilePage />, (client) => {
      client.setQueryData(queryKeys.datasets.profileSummary('dataset-a'), {
        total_documents: 0,
        pdf_scan: { scanned: 0, not_scanned: 0, unknown: 0 },
        latest_scan_run: { id: 'profile-a', status: 'running', progress: 10 },
      })
      client.setQueryData(queryKeys.datasets.profileScanRuns('dataset-a', { skip: 0, limit: 20 }), {
        items: [],
        total: 0,
      })
    })
    await act(async () => vi.advanceTimersByTimeAsync(500))
    expect(api.getProfileScanRun).toHaveBeenCalledOnce()
    view.unmount()
    await act(async () => inFlight.resolve({ id: 'profile-a', status: 'running', progress: 30 }))
    await act(async () => vi.advanceTimersByTimeAsync(2000))

    expect(api.getProfileScanRun).toHaveBeenCalledOnce()
  })

  it('independent review: returning to A keeps its new query busy and excludes the previous visit result', async () => {
    const earlier = deferred<unknown>()
    const current = deferred<unknown>()
    api.getTable.mockImplementation((_dataset: string, id: string) => Promise.resolve(id === first.table_id ? first : second))
    api.queryTable.mockReturnValueOnce(earlier.promise).mockReturnValueOnce(current.promise)
    const view = mountTables()
    await click(button('执行'))
    await click(tableButton(second.sheet_name!))
    await click(tableButton(first.sheet_name!))
    await click(button('执行'))
    expect(api.queryTable).toHaveBeenCalledTimes(2)
    expect(button('执行').disabled).toBe(true)
    await act(async () => earlier.resolve({ columns: ['value'], rows: [['PREVIOUS_A_VISIT']], truncated: false }))
    expect(button('执行').disabled).toBe(true)
    expect(view.container.textContent).not.toContain('PREVIOUS_A_VISIT')
    await act(async () => current.resolve({ columns: ['value'], rows: [['CURRENT_A_VISIT']], truncated: false }))
    expect(view.container.textContent).toContain('CURRENT_A_VISIT')
    expect(button('执行').disabled).toBe(false)
  })

  it('independent review: a previous table failure does not publish an error into the current table', async () => {
    const earlier = deferred<unknown>()
    api.getTable.mockResolvedValue(second)
    api.queryTable.mockReturnValue(earlier.promise)
    const view = mountTables()
    await click(button('执行'))
    await click(tableButton(second.sheet_name!))
    await act(async () => earlier.reject(new Error('previous table unavailable')))
    const notifications = await import('sonner')
    expect(notifications.toast.error).not.toHaveBeenCalled()
    expect(view.container.textContent).toContain('table-b-column')
    expect(button('执行').disabled).toBe(false)
  })

  it('independent review: StrictMode still publishes the current table and query', async () => {
    api.getTable.mockResolvedValue(second)
    api.queryTable.mockResolvedValue({ columns: ['value'], rows: [['STRICT_CURRENT_RESULT']], truncated: false })
    const view = mount(<React.StrictMode><DatasetTablesPage /></React.StrictMode>, (client) =>
      client.setQueryData(queryKeys.datasets.tables('dataset-a', { skip: 0, limit: 200 }), { items: [first, second], total: 2 }),
    )
    await click(tableButton(second.sheet_name!))
    await click(button('执行'))
    expect(api.queryTable).toHaveBeenCalledWith('dataset-a', 'table-b', { sql: 'SELECT * FROM "sheet_2" LIMIT 20' })
    expect(view.container.textContent).toContain('STRICT_CURRENT_RESULT')
  })

})
