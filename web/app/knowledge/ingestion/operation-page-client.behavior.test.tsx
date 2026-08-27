// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const routeState = vi.hoisted(() => ({
  search: 'datasetId=ds-1',
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}))

const settingsState = vi.hoisted(() => ({
  urlIngestEnabled: false,
}))

const clientStorageState = vi.hoisted(() => ({
  raw: '',
}))

const toastMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
}))

const datasetApiMock = vi.hoisted(() => ({
  listAll: vi.fn(),
  getIngestionStats: vi.fn(),
}))

const documentApiMock = vi.hoisted(() => ({
  list: vi.fn(),
  folders: vi.fn(),
  uploadBatch: vi.fn(),
  createFromChunks: vi.fn(),
}))

const connectorApiMock = vi.hoisted(() => ({
  createRun: vi.fn(),
}))

const settingsApiMock = vi.hoisted(() => ({
  get: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => routerMock,
  useSearchParams: () => new URLSearchParams(routeState.search),
}))

vi.mock('sonner', () => ({
  toast: toastMock,
}))

vi.mock('@/lib/client-storage', () => ({
  readClientStorage: vi.fn(() => clientStorageState.raw),
}))

vi.mock('@/lib/api-errors', () => ({
  formatApiError: (_error: unknown, fallback: string) => fallback,
}))

vi.mock('@/lib/utils', () => ({
  cn: (...values: Array<string | false | null | undefined>) =>
    values.filter(Boolean).join(' '),
  detachPromise: (promise: Promise<unknown>) => {
    promise.catch(() => undefined)
  },
  formatFileSize: (size: number) => `${size} B`,
}))

vi.mock('@/lib/api', () => ({
  datasetApi: datasetApiMock,
  documentApi: documentApiMock,
  connectorApi: connectorApiMock,
  settingsApi: settingsApiMock,
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement('button', { type: 'button', ...props }, children),
}))

vi.mock('@/components/ui/input', () => ({
  Input: React.forwardRef(function Input(
    props: React.InputHTMLAttributes<HTMLInputElement>,
    ref: React.ForwardedRef<HTMLInputElement>
  ) {
    return React.createElement('input', { ref, ...props })
  }),
}))

vi.mock('@/components/ui/textarea', () => ({
  Textarea: ({
    ...props
  }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) =>
    React.createElement('textarea', props),
}))

vi.mock('@/components/ui/page-title-icon', () => ({
  PageTitleIcon: () =>
    React.createElement('div', { 'data-page-title-icon': 'true' }),
}))

vi.mock('@/components/ui/select', async () => {
  const React = await import('react')

  const SelectContext = React.createContext<{
    value?: string
    onValueChange?: (value: string) => void
  } | null>(null)

  function Select({
    children,
    value,
    onValueChange,
  }: {
    children: React.ReactNode
    value?: string
    onValueChange?: (value: string) => void
  }) {
    return React.createElement(
      SelectContext.Provider,
      { value: { value, onValueChange } },
      children
    )
  }

  function SelectTrigger({
    children,
    ...props
  }: React.HTMLAttributes<HTMLDivElement>) {
    return React.createElement('div', props, children)
  }

  function SelectContent({
    children,
    ...props
  }: React.HTMLAttributes<HTMLDivElement>) {
    return React.createElement('div', props, children)
  }

  function SelectItem({
    children,
    value,
    textValue: _textValue,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    value: string
    textValue?: string
  }) {
    const context = React.useContext(SelectContext)
    return React.createElement(
      'button',
      {
        ...props,
        type: 'button',
        'data-select-item': value,
        'data-selected': context?.value === value ? 'true' : 'false',
        onClick: () => context?.onValueChange?.(value),
      },
      children
    )
  }

  return {
    Select,
    SelectTrigger,
    SelectContent,
    SelectItem,
  }
})

vi.mock('@/components/ui/tabs', async () => {
  const React = await import('react')

  const TabsContext = React.createContext<{
    value?: string
    onValueChange?: (value: string) => void
  } | null>(null)

  function Tabs({
    children,
    value,
    onValueChange,
  }: {
    children: React.ReactNode
    value?: string
    onValueChange?: (value: string) => void
  }) {
    return React.createElement(
      TabsContext.Provider,
      { value: { value, onValueChange } },
      children
    )
  }

  function TabsContent({
    children,
    value,
  }: {
    children: React.ReactNode
    value: string
  }) {
    const context = React.useContext(TabsContext)
    if (context?.value !== value) return null
    return React.createElement('div', { 'data-tabs-content': value }, children)
  }

  return {
    Tabs,
    TabsContent,
  }
})

vi.mock('./view-switch', () => ({
  IngestionViewSwitch: () =>
    React.createElement('div', { 'data-view-switch': 'true' }),
}))

import KnowledgeIngestionOperationPage from './operation-page-client'

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
        React.createElement(KnowledgeIngestionOperationPage)
      )
    )
  })

  return { container, root }
}

function findButtonByText(container: HTMLElement, text: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
    (button) => button.textContent?.includes(text)
  )
}

function getSubmitButton(container: HTMLElement) {
  const button = container.querySelector<HTMLButtonElement>(
    '[data-ingestion-action-bar="true"] button'
  )
  if (!button) throw new Error('submit button not found')
  return button
}

async function chooseSource(container: HTMLElement, label: string) {
  const button = findButtonByText(container, label)
  if (!button) throw new Error(`source option not found: ${label}`)
  await act(async () => {
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

async function chooseExecutionMode(container: HTMLElement, value: string) {
  const input = container.querySelector<HTMLInputElement>(
    `input[name="ingestion-execution-mode"][value="${value}"]`
  )
  if (!input) throw new Error(`execution mode not found: ${value}`)
  await act(async () => {
    input.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

async function setFileInputFiles(
  container: HTMLElement,
  files: File[],
  options?: { folder?: boolean }
) {
  const input = Array.from(
    container.querySelectorAll<HTMLInputElement>('input[type="file"]')
  ).find((candidate) =>
    options?.folder
      ? candidate.hasAttribute('webkitdirectory')
      : !candidate.hasAttribute('webkitdirectory')
  )
  if (!input) throw new Error('file input not found')
  Object.defineProperty(input, 'files', {
    configurable: true,
    value: files,
  })
  await act(async () => {
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

async function setTextareaValue(
  container: HTMLElement,
  placeholder: string,
  value: string
) {
  const input = Array.from(
    container.querySelectorAll<HTMLTextAreaElement>('textarea')
  ).find((node) => node.getAttribute('placeholder') === placeholder)
  if (!input) throw new Error(`textarea not found: ${placeholder}`)
  const descriptor = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    'value'
  )
  if (!descriptor?.set) throw new Error('textarea value setter not found')
  await act(async () => {
    descriptor.set?.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

async function waitForDatasetBootstrap(container: HTMLElement) {
  await act(async () => {
    await vi.waitFor(() => expect(container.textContent).toContain('Dataset One'))
  })
}

async function setInputValue(
  container: HTMLElement,
  placeholder: string,
  value: string
) {
  const input = Array.from(
    container.querySelectorAll<HTMLInputElement>('input')
  ).find((node) => node.getAttribute('placeholder') === placeholder)
  if (!input) throw new Error(`input not found: ${placeholder}`)
  const descriptor = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    'value'
  )
  if (!descriptor?.set) throw new Error('input value setter not found')
  await act(async () => {
    descriptor.set?.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

beforeEach(() => {
  ;(
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true

  routeState.search = 'datasetId=ds-1'
  settingsState.urlIngestEnabled = false
  clientStorageState.raw = ''

  routerMock.push.mockReset()
  routerMock.replace.mockReset()

  toastMock.success.mockReset()
  toastMock.error.mockReset()
  toastMock.warning.mockReset()

  datasetApiMock.listAll.mockResolvedValue([
    { id: 'ds-1', name: 'Dataset One' },
  ])
  datasetApiMock.getIngestionStats.mockResolvedValue({
    total_documents: 4,
    total_chunks: 12,
    total_size: 4096,
  })

  documentApiMock.list.mockResolvedValue({ items: [] })
  documentApiMock.folders.mockResolvedValue({ root: null })
  documentApiMock.uploadBatch.mockResolvedValue({
    total: 1,
    successful_count: 1,
    failed_count: 0,
    successful: [{ document_id: 'doc-1', filename: 'manual.pdf', status: 'queued' }],
    failed: [],
  })
  documentApiMock.createFromChunks.mockResolvedValue({
    id: 'doc-api-1',
    status: 'completed',
  })

  connectorApiMock.createRun.mockResolvedValue({
    id: 'run-1',
    status: 'queued',
  })
  settingsApiMock.get.mockImplementation(async () => ({
    url_ingest: { enabled: settingsState.urlIngestEnabled },
  }))

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

describe('knowledge ingestion operation page behavior', () => {
  it('keeps all five source options reachable', async () => {
    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('添加文件到本次任务')
      )
    })

    await chooseSource(container, '文件夹')
    expect(container.textContent).toContain('选择本地文件夹')

    await chooseSource(container, 'URL列表')
    expect(container.textContent).toContain('URL 列表')

    await chooseSource(container, '对象存储')
    expect(container.textContent).toContain('Bucket（可选）')

    await chooseSource(container, 'API导入')
    expect(container.textContent).toContain('API Payload')

    await chooseSource(container, '本地文件')
    expect(container.textContent).toContain('添加文件到本次任务')

    act(() => root.unmount())
  })

  it('enables the CTA after selecting a local file', async () => {
    const { container, root } = renderPage()

    await waitForDatasetBootstrap(container)

    expect(getSubmitButton(container).disabled).toBe(true)

    const file = new File(['pdf'], 'manual.pdf', {
      type: 'application/pdf',
      lastModified: 1724630400000,
    })
    await setFileInputFiles(container, [file])

    await act(async () => {
      await vi.waitFor(() => expect(getSubmitButton(container).disabled).toBe(false))
    })

    expect(container.textContent).toContain('本次文件 · 1')
    expect(container.textContent).toContain('manual.pdf')

    act(() => root.unmount())
  })

  it('submits parse-only local ingestion through uploadBatch and opens the execution monitor', async () => {
    const { container, root } = renderPage()

    await waitForDatasetBootstrap(container)

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain('1 个阶段'))
    })

    await chooseExecutionMode(container, 'parse_only')

    const file = new File(['pdf'], 'manual.pdf', {
      type: 'application/pdf',
      lastModified: 1724630400000,
    })
    await setFileInputFiles(container, [file])

    await act(async () => {
      await vi.waitFor(() => expect(container.textContent).toContain('2 个阶段'))
    })
    expect(getSubmitButton(container).textContent).toContain('登记并解析')

    await act(async () => {
      getSubmitButton(container).dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
      await vi.waitFor(() =>
        expect(documentApiMock.uploadBatch).toHaveBeenCalledTimes(1)
      )
    })

    expect(documentApiMock.uploadBatch).toHaveBeenCalledWith(
      [file],
      expect.objectContaining({
        dataset_id: 'ds-1',
        upload_only: false,
        pipeline: expect.objectContaining({
          persist_parsed_content: true,
          chunk_vector_enabled: false,
          bm25_index_enabled: false,
        }),
      })
    )
    expect(routerMock.push).toHaveBeenCalledWith(
      '/knowledge/ingestion?mode=execution-monitor'
    )

    act(() => root.unmount())
  })

  it('keeps disabled URL ingestion blocked even with valid URLs entered', async () => {
    const { container, root } = renderPage()

    await waitForDatasetBootstrap(container)
    await chooseSource(container, 'URL列表')
    await setTextareaValue(
      container,
      'https://example.com/manual.pdf\nhttps://example.com/guide.md',
      'https://example.com/manual.pdf'
    )

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('当前环境未启用 URL/对象存储导入')
      )
    })

    expect(getSubmitButton(container).disabled).toBe(true)
    expect(connectorApiMock.createRun).not.toHaveBeenCalled()

    act(() => root.unmount())
  })

  it('creates a url_batch connector run when URL ingestion is enabled', async () => {
    settingsState.urlIngestEnabled = true

    const { container, root } = renderPage()

    await waitForDatasetBootstrap(container)
    await chooseSource(container, 'URL列表')
    await chooseExecutionMode(container, 'parse_only')
    await setTextareaValue(
      container,
      'https://example.com/manual.pdf\nhttps://example.com/guide.md',
      'https://example.com/manual.pdf'
    )
    await setInputValue(container, 'remote-documents.md', 'remote-documents.md')

    await act(async () => {
      await vi.waitFor(() => expect(getSubmitButton(container).disabled).toBe(false))
    })

    await act(async () => {
      getSubmitButton(container).dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
      await vi.waitFor(() =>
        expect(connectorApiMock.createRun).toHaveBeenCalledTimes(1)
      )
    })

    expect(connectorApiMock.createRun).toHaveBeenCalledWith(
      expect.objectContaining({
        connector_id: 'url_batch',
        dataset_id: 'ds-1',
        config: expect.objectContaining({
          urls: ['https://example.com/manual.pdf'],
          filename: 'remote-documents.md',
          pipeline: expect.objectContaining({
            persist_parsed_content: true,
            chunk_vector_enabled: false,
          }),
        }),
      })
    )
    expect(routerMock.push).toHaveBeenCalledWith(
      '/knowledge/ingestion?mode=execution-monitor'
    )

    act(() => root.unmount())
  })

  it('writes API payload ingestion through createFromChunks in full-index mode', async () => {
    const { container, root } = renderPage()

    await waitForDatasetBootstrap(container)
    await chooseSource(container, 'API导入')
    await chooseExecutionMode(container, 'full_index')
    await setInputValue(container, 'api-payload.json', 'faq.json')
    await setTextareaValue(
      container,
      '{"title":"产品说明","content":"这里粘贴接口推送内容"}',
      '{"title":"FAQ","content":"answer"}'
    )

    await act(async () => {
      await vi.waitFor(() => expect(getSubmitButton(container).disabled).toBe(false))
    })

    await act(async () => {
      getSubmitButton(container).dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
      await vi.waitFor(() =>
        expect(documentApiMock.createFromChunks).toHaveBeenCalledTimes(1)
      )
    })

    expect(documentApiMock.createFromChunks).toHaveBeenCalledWith(
      expect.objectContaining({
        dataset_id: 'ds-1',
        filename: 'faq.json',
        metadata: expect.objectContaining({
          source: 'api',
        }),
        pipeline: expect.objectContaining({
          persist_parsed_content: true,
          chunk_vector_enabled: true,
          bm25_index_enabled: true,
        }),
      })
    )

    act(() => root.unmount())
  })

  it('renders the advanced settings section', async () => {
    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(
          container.querySelector('[data-ingestion-advanced-settings="true"]')
        ).not.toBeNull()
      )
    })

    expect(container.textContent).toContain('高级设置')
    expect(container.textContent).toContain('入库模式')
    expect(container.textContent).toContain('目标目录')
    expect(container.textContent).toContain('重复处理')

    act(() => root.unmount())
  })
})
