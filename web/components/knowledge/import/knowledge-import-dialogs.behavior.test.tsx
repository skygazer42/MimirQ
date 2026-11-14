// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConnectorRunOut } from '@/types'
import { setAccessToken, setAuthSession } from '@/lib/auth-storage'

const api = vi.hoisted(() => ({ createRun: vi.fn(), listRuns: vi.fn() }))
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('@/lib/api', () => ({ connectorApi: api }))
vi.mock('@/lib/api/connectors', () => ({ connectorApi: api }))
vi.mock('sonner', () => ({ toast: notices }))
vi.mock('@/contexts/parser-backend-context', () => ({
  useParserBackendPreference: () => ({ parserBackend: 'auto', setParserBackend: vi.fn() }),
}))
vi.mock('@/contexts/chunk-strategy-context', () => ({
  useChunkStrategyPreference: () => ({ chunkStrategy: 'langchain_recursive', setChunkStrategy: vi.fn() }),
}))
vi.mock('@/contexts/pipeline-options-context', () => ({ usePipelineOptions: () => ({ enabled: false, options: {} }) }))
vi.mock('@/components/pipeline-options-panel', () => ({ PipelineOptionsPanel: () => null }))
vi.mock('@/components/business/parser-dropdown', () => ({ ParserDropdown: () => null }))
vi.mock('@/components/business/chunk-strategy-dropdown', () => ({ ChunkStrategyDropdown: () => null }))
vi.mock('@/components/groups/group-chips-input', () => ({ GroupChipsInput: () => null }))
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}))
vi.mock('@/components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string
    onValueChange: (value: string) => void
    children: React.ReactNode
  }) => (
    <select value={value} onChange={(event) => onValueChange(event.target.value)}>
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}))
vi.mock('@/components/ui/checkbox', () => ({
  Checkbox: ({ checked, onCheckedChange }: { checked: boolean; onCheckedChange: (value: boolean) => void }) => (
    <input type="checkbox" checked={checked} onChange={(event) => onCheckedChange(event.target.checked)} />
  ),
}))

import { KnowledgeUrlImportDialog } from './knowledge-url-import-dialog'
import { KnowledgeUrlBatchDialog } from './knowledge-url-batch-dialog'
import { KnowledgeWebCrawlDialog } from './knowledge-web-crawl-dialog'
import { KnowledgeJiraProjectDialog } from './knowledge-jira-project-dialog'
import { useConnectorRuns } from '@/hooks/use-connector-runs'

const cases = [
  {
    name: 'single URL',
    Component: KnowledgeUrlImportDialog,
    selector: 'input[placeholder^="https://example.com/doc.pdf"]',
    value: 'https://example.org/A.pdf',
    next: 'https://example.org/B.pdf',
    label: '开始导入',
  },
  {
    name: 'URL batch',
    Component: KnowledgeUrlBatchDialog,
    selector: 'textarea[placeholder^="https://example.com/doc1.pdf"]',
    value: 'https://example.org/A.pdf',
    next: 'https://example.org/B.pdf',
    label: '开始导入',
  },
  {
    name: 'web crawl',
    Component: KnowledgeWebCrawlDialog,
    selector: 'textarea',
    value: 'https://example.org/A',
    next: 'https://example.org/B',
    label: 'Start',
  },
  {
    name: 'Jira project',
    Component: KnowledgeJiraProjectDialog,
    selector: 'input[placeholder="PLAT"]',
    value: 'OLD',
    next: 'NEW',
    label: 'Start Jira Sync',
  },
] as const
const run: ConnectorRunOut = {
  id: 'accepted-run',
  tenant_id: 'tenant-1',
  dataset_id: 'ds-1',
  connector_id: 'url_batch',
  status: 'pending',
  created_at: '2026-11-05T00:00:00Z',
}
const session = {
  token: { access_token: 'token-a', token_type: 'bearer', expires_in: 3600 },
  user: { id: 'user-a', email: 'a@example.org', username: 'A', is_active: true, created_at: '2026-11-05T00:00:00Z' },
}
function deferred() {
  let resolve!: (value: ConnectorRunOut) => void
  let reject!: (error: Error) => void
  const promise = new Promise<ConnectorRunOut>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
const cleanups: Array<() => void> = []
function setup(testCase: (typeof cases)[number]) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const props = {
    datasets: [],
    datasetsLoading: false,
    selectedDatasetId: 'ds-1',
    datasetDefaultValue: '__default__',
    onOpenChange: vi.fn(),
    uploadDocumentFromUrl: vi.fn(),
    onAfterImport: vi.fn(),
    loadDocuments: vi.fn(),
    loadConnectorRuns: vi.fn(),
    onRunCreated: vi.fn(),
  }
  const submit = testCase.name === 'single URL' ? props.uploadDocumentFromUrl : api.createRun
  const Component: React.ComponentType<typeof props & { open: boolean }> = testCase.Component
  submit.mockResolvedValue(run)
  async function visit(open = true) {
    await act(async () => root.render(<Component {...props} open={open} />))
  }
  function input() {
    const field = host.querySelector(testCase.selector)
    if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement))
      throw new Error('draft field missing')
    return field
  }
  async function fill(value: string) {
    const field = input()
    const prototype = field instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype
    await act(async () => {
      Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(field, value)
      field.dispatchEvent(new Event('input', { bubbles: true }))
      field.dispatchEvent(new Event('change', { bubbles: true }))
    })
  }
  function button() {
    const buttons = Array.from(host.querySelectorAll('button'))
    const value = buttons.find((item) => item.textContent?.trim() === testCase.label)
    if (!value) throw new Error('submit missing')
    return value
  }
  cleanups.push(() => {
    act(() => root.unmount())
    host.remove()
  })
  return { host, props, submit, visit, input, fill, button }
}
beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  window.localStorage.clear()
  window.sessionStorage.clear()
  setAuthSession(session)
})
afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup())
  vi.resetAllMocks()
})

describe.each(cases)('$name import ownership', (testCase) => {
  it('submits once for two synchronous clicks', async () => {
    const view = setup(testCase)
    const pending = deferred()
    view.submit.mockReturnValue(pending.promise)
    await view.visit()
    await view.fill(testCase.value)
    await act(async () => {
      view.button().click()
      view.button().click()
    })
    expect(view.submit).toHaveBeenCalledTimes(1)
    await act(async () => pending.resolve(run))
  })
  it('retains a reopened draft while refreshing an accepted same-session write', async () => {
    const view = setup(testCase)
    const pending = deferred()
    view.submit.mockReturnValueOnce(pending.promise)
    await view.visit()
    await view.fill(testCase.value)
    await act(async () => view.button().click())
    await view.visit(false)
    await view.visit()
    await view.fill(testCase.next)
    await act(async () => pending.resolve(run))
    expect(view.props.onOpenChange).not.toHaveBeenCalled()
    expect(view.input().value).toBe(testCase.next)
    expect(notices.success).not.toHaveBeenCalled()
    expect(view.button().disabled).toBe(false)
    if (testCase.name === 'single URL') expect(view.props.onAfterImport).toHaveBeenCalledTimes(1)
    else {
      expect(view.props.loadDocuments).toHaveBeenCalledTimes(1)
      expect(view.props.loadConnectorRuns).toHaveBeenCalledWith({ datasetId: 'ds-1' }, { selectScope: false })
    }
  })
  it('retires a replaced login but releases its own pending state', async () => {
    const view = setup(testCase)
    const pending = deferred()
    view.submit.mockReturnValueOnce(pending.promise)
    await view.visit()
    await view.fill(testCase.value)
    await act(async () => view.button().click())
    setAuthSession(session)
    await act(async () => pending.resolve(run))
    expect(view.props.onOpenChange).not.toHaveBeenCalled()
    expect(view.input().value).toBe(testCase.value)
    expect(notices.success).not.toHaveBeenCalled()
    expect(view.props.onAfterImport).not.toHaveBeenCalled()
    expect(view.props.loadDocuments).not.toHaveBeenCalled()
    expect(view.props.loadConnectorRuns).not.toHaveBeenCalled()
    expect(view.button().disabled).toBe(false)
  })
  it('preserves current success across an ordinary token refresh and retains drafts on error', async () => {
    const view = setup(testCase)
    const pending = deferred()
    view.submit.mockReturnValueOnce(pending.promise)
    await view.visit()
    await view.fill(testCase.value)
    await act(async () => view.button().click())
    setAccessToken({ access_token: 'refreshed-token', token_type: 'bearer', expires_in: 3600 })
    await act(async () => pending.resolve(run))
    expect(view.props.onOpenChange).toHaveBeenCalledWith(false)
    expect(notices.success).toHaveBeenCalledTimes(1)
    await view.visit(false)
    await view.visit()
    await view.fill(testCase.next)
    view.submit.mockRejectedValueOnce(new Error('current import failed'))
    await act(async () => view.button().click())
    expect(view.input().value).toBe(testCase.next)
    expect(notices.error).toHaveBeenCalledWith('current import failed')
    expect(view.button().disabled).toBe(false)
  })
})

describe.each(cases.filter((testCase) => testCase.name !== 'single URL'))(
  '$name connector refresh integration',
  (testCase) => {
    it('refreshes accepted A runs while the actual hook keeps selected B visible', async () => {
      const pending = deferred()
      api.createRun.mockReturnValueOnce(pending.promise)
      const runA = { ...run, id: 'run-A' }
      const runB = { ...run, id: 'run-B', dataset_id: 'ds-2', status: 'completed' as const }
      const accepted = { ...run, id: 'accepted-A' }
      let serverA = [runA]
      api.listRuns.mockImplementation(async ({ dataset_id }: { dataset_id: string }) => ({
        total: 1,
        items: dataset_id === 'ds-1' ? serverA : [runB],
      }))
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 10_000 } } })
      const host = document.createElement('div')
      document.body.append(host)
      const root = createRoot(host)
      const loadDocuments = vi.fn()
      const onOpenChange = vi.fn()
      const Component: React.ComponentType<React.ComponentProps<typeof KnowledgeUrlBatchDialog>> = testCase.Component
      function Host({ selectedDatasetId, open }: { selectedDatasetId: string; open: boolean }) {
        const model = useConnectorRuns({ selectedDatasetId })
        return (
          <>
            <div data-visible-runs="true">{model.connectorRuns.map((item) => item.id).join(',')}</div>
            <button onClick={() => model.loadConnectorRuns()}>load selected runs</button>
            <Component
              open={open}
              selectedDatasetId={selectedDatasetId}
              onOpenChange={onOpenChange}
              datasets={[]}
              datasetsLoading={false}
              datasetDefaultValue="__default__"
              loadDocuments={loadDocuments}
              loadConnectorRuns={model.loadConnectorRuns}
            />
          </>
        )
      }
      async function visit(selectedDatasetId: string, open: boolean) {
        await act(async () =>
          root.render(
            <QueryClientProvider client={client}>
              <Host selectedDatasetId={selectedDatasetId} open={open} />
            </QueryClientProvider>,
          ),
        )
      }
      const button = (text: string) => {
        const value = Array.from(host.querySelectorAll('button')).find((item) => item.textContent?.trim() === text)
        if (!value) throw new Error(`button missing: ${text}`)
        return value
      }
      try {
        await visit('ds-1', true)
        await act(async () => {
          button('load selected runs').click()
          await vi.waitFor(() => expect(host.querySelector('[data-visible-runs]')?.textContent).toBe('run-A'))
        })
        const input = host.querySelector<HTMLInputElement | HTMLTextAreaElement>(testCase.selector)!
        const prototype = input instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype
        await act(async () => {
          Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, testCase.value)
          input.dispatchEvent(new Event('input', { bubbles: true }))
          input.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await act(async () => button(testCase.label).click())
        await visit('ds-1', false)
        await visit('ds-2', true)
        await act(async () => {
          button('load selected runs').click()
          await vi.waitFor(() => expect(host.querySelector('[data-visible-runs]')?.textContent).toBe('run-B'))
        })
        const keyA = ['connectors', 'runs', { datasetId: 'ds-1', limit: 20 }]
        client.setQueryData(keyA, [runA], { updatedAt: Date.now() - 10_001 })
        serverA = [accepted]
        await act(async () => {
          pending.resolve(accepted)
          await vi.waitFor(() => expect(client.getQueryData(keyA)).toEqual([accepted]))
        })
        expect(host.querySelector('[data-visible-runs]')?.textContent).toBe('run-B')
        expect(loadDocuments).toHaveBeenCalledTimes(1)
        expect(onOpenChange).not.toHaveBeenCalled()
      } finally {
        act(() => root.unmount())
        client.clear()
        host.remove()
      }
    })
  },
)
