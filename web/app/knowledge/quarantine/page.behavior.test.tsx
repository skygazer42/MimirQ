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
vi.mock('./components/quarantine-review-drawer', () => ({
  QuarantineReviewDrawer: ({
    open,
    selected,
  }: {
    open: boolean
    selected: { filename?: string } | null
  }) =>
    open && selected
      ? React.createElement(
          'div',
          { 'data-review-drawer': 'true' },
          selected.filename
        )
      : null,
}))
vi.mock('@/components/knowledge/quarantine/summary-cards', () => ({
  SummaryStatCard: ({ label, value }: { label: string; value: number }) =>
    React.createElement('div', null, `${label}:${value}`),
  DonutSummaryCard: ({ title }: { title: string }) =>
    React.createElement('div', null, title),
  QuickActionCard: ({
    title,
    onClick,
  }: {
    title: string
    onClick: () => void
  }) => React.createElement('button', { onClick }, title),
}))
vi.mock('@/app/knowledge/quarantine/components/quarantine-empty-state', () => ({
  QuarantineEmptyState: () => React.createElement('div', null, 'empty'),
}))
vi.mock('@/app/knowledge/quarantine/components/status-pill', () => ({
  StatusPill: ({ status }: { status: string }) =>
    React.createElement('span', null, status),
}))
vi.mock('@/app/knowledge/quarantine/components/file-kind-glyph', () => ({
  FileKindGlyph: () => React.createElement('div', null, 'glyph'),
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
    id: `doc-${index}`,
    filename: `quarantine-${index}.pdf`,
    dataset_id: 'ds-1',
    status: 'quarantined',
    file_size: 1024 * index,
    updated_at: `2026-08-${String(index).padStart(2, '0')}T00:00:00Z`,
    metadata: {},
    governance: { drop_reasons: { outline_only: 1 } },
  }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  act(() => {
    root.render(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(QuarantineQueuePage)
      )
    )
  })

  return { container, root }
}

describe('QuarantineQueuePage behavior', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    routerMock.replace.mockReset()
    documentViewMock.openDocument.mockReset()
    documentApiMock.list.mockReset()
    documentApiMock.retry.mockResolvedValue(undefined)
    documentApiMock.delete.mockResolvedValue(undefined)
    documentApiMock.patchPipeline.mockResolvedValue(undefined)
    documentApiMock.patchUserMetadata.mockResolvedValue(undefined)
    documentApiMock.list
      .mockResolvedValueOnce({
        items: Array.from({ length: 7 }, (_, index) => createDocument(index + 1)),
        total: 7,
      })
      .mockResolvedValueOnce({
        items: [],
        total: 0,
      })
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('opens the review drawer from a filename button and paginates rows', async () => {
    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('异常隔离审查表')
      )
      await vi.waitFor(() =>
        expect(container.textContent).toContain('quarantine-1.pdf')
      )
    })

    const fileButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button')
    ).find((button) => button.textContent?.includes('quarantine-1.pdf'))
    expect(fileButton).not.toBeUndefined()

    await act(async () => {
      fileButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(container.querySelector('[data-review-drawer="true"]')?.textContent).toContain(
      'quarantine-1.pdf'
    )

    expect(container.textContent).toContain('quarantine-6.pdf')
    expect(container.textContent).not.toContain('quarantine-7.pdf')

    const nextButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button')
    ).find((button) => button.textContent === '2')
    expect(nextButton).not.toBeUndefined()

    await act(async () => {
      nextButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(container.textContent).toContain('quarantine-7.pdf')

    act(() => root.unmount())
  })

  it('opens the tune dialog from the rule manager quick action', async () => {
    const { container, root } = renderPage()

    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain('规则管理')
      )
    })

    const ruleManagerButton = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button')
    ).find((button) => button.textContent?.includes('规则管理'))
    expect(ruleManagerButton).not.toBeUndefined()

    await act(async () => {
      ruleManagerButton?.dispatchEvent(
        new MouseEvent('click', { bubbles: true })
      )
    })

    expect(container.textContent).toContain('调参回放')
    expect(container.textContent).toContain('保存配置')
    expect(container.textContent).toContain('保存并重试')

    act(() => root.unmount())
  })
})
