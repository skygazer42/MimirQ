// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const routerMock = vi.hoisted(() => ({
  replace: vi.fn(),
}))
const datasetsState = vi.hoisted(() => ({
  datasets: [{ id: 'ds-1', name: 'Dataset One' }],
  isLoading: false,
}))
const documentApiMock = vi.hoisted(() => ({
  list: vi.fn(),
  getParsedContent: vi.fn(),
  retry: vi.fn(),
  delete: vi.fn(),
  patchPipeline: vi.fn(),
  patchUserMetadata: vi.fn(),
}))
const documentViewMock = vi.hoisted(() => ({
  openDocument: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/i18n/navigation', () => ({
  usePathname: () => '/knowledge/quarantine',
  useRouter: () => routerMock,
}))
vi.mock('@/hooks/use-datasets', () => ({
  useDatasets: () => datasetsState,
}))
vi.mock('@/lib/api', () => ({
  documentApi: documentApiMock,
}))
vi.mock('@/store/document-view', () => ({
  useDocumentView: () => documentViewMock,
}))
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))
vi.mock('next/image', () => ({
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) =>
    React.createElement('img', props),
}))

vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
}))
vi.mock('@/components/ui/page-scaffold', () => ({
  PageScaffold: ({
    top,
    children,
  }: {
    top?: React.ReactNode
    children: React.ReactNode
  }) => React.createElement('div', null, top, children),
}))
vi.mock('@/components/ui/page-title-icon', () => ({
  PageTitleIcon: () => React.createElement('div', null, 'icon'),
}))
vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement('button', props, children),
}))
vi.mock('@/components/ui/search-input', () => ({
  SearchInput: ({
    value,
    onValueChange,
    placeholder,
  }: {
    value: string
    onValueChange: (value: string) => void
    placeholder?: string
  }) =>
    React.createElement('input', {
      value,
      placeholder,
      onInput: (event: Event) =>
        onValueChange((event.target as HTMLInputElement).value),
    }),
}))
vi.mock('@/components/ui/input', () => ({
  Input: ({
    value,
    onChange,
    ...props
  }: React.InputHTMLAttributes<HTMLInputElement>) =>
    React.createElement('input', {
      value,
      onChange,
      ...props,
    }),
}))
vi.mock('@/components/ui/switch', () => ({
  Switch: ({
    checked,
    onCheckedChange,
  }: {
    checked: boolean
    onCheckedChange: (checked: boolean) => void
  }) =>
    React.createElement('input', {
      type: 'checkbox',
      checked,
      onChange: (event: Event) =>
        onCheckedChange((event.target as HTMLInputElement).checked),
    }),
}))
vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children: React.ReactNode }) =>
    React.createElement('span', null, children),
}))
vi.mock('@/components/ui/label', () => ({
  Label: ({ children }: { children: React.ReactNode }) =>
    React.createElement('label', null, children),
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
vi.mock('@/components/document-viewer-panel', () => ({
  DocumentViewerPanel: () => React.createElement('div', null, 'viewer'),
}))
vi.mock('@/components/ingestion/ingestion-detail-dialog', () => ({
  IngestionDetailDialog: () => null,
}))
vi.mock('@/components/ingestion/monitor-utils', () => ({
  getDocumentKind: () => 'pdf',
}))
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
  DialogContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  DialogDescription: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  DialogFooter: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  DialogHeader: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  DialogTitle: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
}))
vi.mock('@/components/ui/confirm-dialog', () => ({
  ConfirmDialog: ({
    children,
  }: {
    children: React.ReactNode
  }) => React.createElement(React.Fragment, null, children),
}))

import QuarantineQueuePage from './page'

function createDocument(index: number) {
  return {
    id: `doc-${index}`, filename: `quarantine-${index}.pdf`, dataset_id: 'ds-1',
    status: 'quarantined', file_size: 1024 * index,
    updated_at: '2026-10-22T09:00:00Z', metadata: {},
    governance: { drop_reasons: { outline_only: 1 } },
  }
}

const cleanups: (() => void)[] = []
function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  act(() => root.render(<QueryClientProvider client={queryClient}><QuarantineQueuePage /></QueryClientProvider>))
  cleanups.push(() => { act(() => root.unmount()); queryClient.clear() })
  return container
}
function button(container: HTMLElement, label: string) {
  const target = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(node => node.getAttribute('aria-label') === label || node.textContent?.trim() === label)
  expect(target, label).toBeDefined()
  return target!
}
async function click(target: HTMLElement) {
  await act(async () => target.dispatchEvent(new MouseEvent('click', { bubbles: true })))
}
async function loaded(container: HTMLElement) {
  await act(async () => { await vi.waitFor(() => expect(container.textContent).toContain('quarantine-1.pdf')) })
}

describe('QuarantineQueuePage behavior', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    vi.clearAllMocks()
    documentApiMock.list.mockImplementation(async (params: { status: string }) => ({
      items: params.status === 'quarantined' ? Array.from({ length: 21 }, (_, i) => createDocument(i + 1)) : [], total: params.status === 'quarantined' ? 21 : 0,
    }))
    documentApiMock.getParsedContent.mockResolvedValue({ available: true, original_markdown_content: '原文内容 <script>普通文本</script>', markdown_content: '' })
    documentApiMock.retry.mockResolvedValue(undefined)
    documentApiMock.delete.mockResolvedValue(undefined)
    documentApiMock.patchPipeline.mockResolvedValue(undefined)
    documentApiMock.patchUserMetadata.mockResolvedValue(undefined)
  })
  afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); document.body.innerHTML = '' })

  it('reviews in the current row, keeps source text inert, and closes it when changing pages', async () => {
    const container = renderPage(); await loaded(container)
    expect(container.querySelectorAll('[data-quarantine-row]')).toHaveLength(20)
    expect(documentApiMock.getParsedContent).not.toHaveBeenCalled()
    const source = button(container, '复核 quarantine-1.pdf')
    await click(source)
    expect(source.getAttribute('aria-expanded')).toBe('true')
    await act(async () => { await vi.waitFor(() => expect(container.querySelector('pre')?.textContent).toContain('<script>普通文本</script>')) })
    expect(container.querySelector('pre script')).toBeNull()
    await click(button(container, '查看原文'))
    expect(documentViewMock.openDocument).toHaveBeenCalledWith('doc-1')
    await click(button(container, '下一页'))
    expect(container.querySelectorAll('[data-quarantine-row]')).toHaveLength(1)
    expect(container.textContent).toContain('quarantine-21.pdf')
    expect(container.querySelector('pre')).toBeNull()
    await click(button(container, '上一页'))
    expect(button(container, '复核 quarantine-1.pdf').getAttribute('aria-expanded')).toBe('false')
  })

  it('retains search text on no match and can restore the list', async () => {
    const container = renderPage(); await loaded(container)
    const search = container.querySelector<HTMLInputElement>('input[placeholder="搜索文档、规则或原因"]')!
    await act(async () => { search.value = '不存在的文档'; search.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(container.textContent).toContain('没有符合条件的文档')
    expect(search.value).toBe('不存在的文档')
    await click(button(container, '清除筛选'))
    expect(search.value).toBe('')
    expect(container.querySelectorAll('[data-quarantine-row]')).toHaveLength(20)
  })

  it('does not claim an empty queue while the first requests are pending', async () => {
    documentApiMock.list.mockImplementation(() => new Promise(() => {}))
    const container = renderPage()
    expect(container.textContent).toContain('正在加载隔离队列')
    expect(container.textContent).not.toContain('当前没有待复核文档')
  })

  it('keeps the expanded document and error available after a retry fails', async () => {
    const { toast } = await import('sonner')
    documentApiMock.retry.mockRejectedValueOnce(new Error('重试服务暂时不可用'))
    const container = renderPage(); await loaded(container)
    await click(button(container, '复核 quarantine-1.pdf'))
    await click(button(container, '重试'))
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('重试服务暂时不可用'))
    expect(button(container, '复核 quarantine-1.pdf').getAttribute('aria-expanded')).toBe('true')
    expect(documentApiMock.patchUserMetadata).not.toHaveBeenCalled()
    await click(button(container, '重试'))
    expect(documentApiMock.retry).toHaveBeenCalledTimes(2)
    expect(documentApiMock.patchUserMetadata).toHaveBeenCalledWith('doc-1', expect.objectContaining({ patch: expect.objectContaining({ quarantine_reviewed: true, quarantine_action: 'retry' }) }))
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('opens the existing document tuning form from inline review', async () => {
    const container = renderPage(); await loaded(container)
    await click(button(container, '复核 quarantine-1.pdf'))
    await click(button(container, '调参'))
    expect(container.textContent).toContain('调参回放')
    expect(container.textContent).toContain('保存并重试')
  })
})
