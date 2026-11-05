// @vitest-environment happy-dom

import fs from 'node:fs'
import path from 'node:path'
import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken, setAuthSession } from '@/lib/auth-storage'
import type { Document } from '@/types'

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
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
const dialogState = vi.hoisted(() => ({ controlled: false }))
const routeState = vi.hoisted(() => ({ search: '' }))

vi.mock('next/navigation', () => ({
  useSearchParams: () => {
    const search = routeState.search
    return React.useMemo(() => new URLSearchParams(search), [search])
  },
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
vi.mock('@/lib/api/documents', () => ({ documentApi: documentApiMock }))

vi.mock('@/store/document-view', () => ({
  useDocumentView: () => documentViewMock,
}))
vi.mock('sonner', () => ({
  toast: notices,
}))
vi.mock('next/image', () => ({
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => React.createElement('img', props),
}))

vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
}))
vi.mock('@/components/ui/page-scaffold', () => ({
  PageScaffold: ({ top, children }: { top?: React.ReactNode; children: React.ReactNode }) =>
    React.createElement('div', null, top, children),
}))
vi.mock('@/components/ui/page-title-icon', () => ({
  PageTitleIcon: () => React.createElement('div', null, 'icon'),
}))
vi.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
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
      onInput: (event: Event) => onValueChange((event.target as HTMLInputElement).value),
    }),
}))
vi.mock('@/components/ui/input', () => ({
  Input: ({ value, onChange, ...props }: React.InputHTMLAttributes<HTMLInputElement>) =>
    React.createElement('input', {
      value,
      onChange,
      ...props,
    }),
}))
vi.mock('@/components/ui/switch', () => ({
  Switch: ({ checked, onCheckedChange }: { checked: boolean; onCheckedChange: (checked: boolean) => void }) =>
    React.createElement('input', {
      type: 'checkbox',
      checked,
      onChange: (event: Event) => onCheckedChange((event.target as HTMLInputElement).checked),
    }),
}))
vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children: React.ReactNode }) => React.createElement('span', null, children),
}))
vi.mock('@/components/ui/label', () => ({
  Label: ({ children }: { children: React.ReactNode }) => React.createElement('label', null, children),
}))
vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  SelectContent: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) =>
    React.createElement('div', { 'data-value': value }, children),
  SelectTrigger: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) =>
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
    acting,
    onRelease,
    onRetry,
    onTune,
    onDelete,
    onOpenChange,
  }: React.ComponentProps<typeof import('./components/quarantine-review-drawer').QuarantineReviewDrawer>) =>
    open && selected ? (
      <div data-review-drawer="true">
        {selected.filename}
        <button onClick={() => onOpenChange(false)}>close review</button>
        <button disabled={acting?.id === selected.id} onClick={() => onRelease(selected)}>
          release selected
        </button>
        <button disabled={acting?.id === selected.id} onClick={() => onRetry(selected)}>
          retry selected
        </button>
        <button disabled={acting?.id === selected.id} onClick={() => onTune(selected)}>
          tune selected
        </button>
        <button disabled={acting?.id === selected.id} onClick={() => onDelete(selected)}>
          delete selected
        </button>
      </div>
    ) : null,
}))
vi.mock('@/components/knowledge/quarantine/summary-cards', () => ({
  SummaryStatCard: ({ label, value }: { label: string; value: number }) =>
    React.createElement('div', null, `${label}:${value}`),
  DonutSummaryCard: ({ title }: { title: string }) => React.createElement('div', null, title),
  QuickActionCard: ({ title, onClick }: { title: string; onClick: () => void }) =>
    React.createElement('button', { onClick }, title),
}))
vi.mock('@/app/knowledge/quarantine/components/quarantine-empty-state', () => ({
  QuarantineEmptyState: () => React.createElement('div', null, 'empty'),
}))
vi.mock('@/app/knowledge/quarantine/components/status-pill', () => ({
  StatusPill: ({ status }: { status: string }) => React.createElement('span', null, status),
}))
vi.mock('@/app/knowledge/quarantine/components/file-kind-glyph', () => ({
  FileKindGlyph: () => React.createElement('div', null, 'glyph'),
}))
vi.mock('@/components/ingestion/monitor-utils', () => ({
  getDocumentKind: () => 'pdf',
}))
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    open,
    onOpenChange,
    children,
  }: {
    open: boolean
    onOpenChange: (value: boolean) => void
    children: React.ReactNode
  }) =>
    !dialogState.controlled ? (
      <>{children}</>
    ) : open ? (
      <div>
        <button onClick={() => onOpenChange(false)}>close tune</button>
        {children}
      </div>
    ) : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  DialogDescription: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  DialogFooter: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  DialogHeader: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  DialogTitle: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
}))
vi.mock('@/components/ui/confirm-dialog', () => ({
  ConfirmDialog: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
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
      React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(QuarantineQueuePage)),
    )
  })

  const rerender = () =>
    root.render(
      React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(QuarantineQueuePage)),
    )
  return { container, root, queryClient, rerender }
}

describe('QuarantineQueuePage behavior', () => {
  it('shows the same document pending action when rule management opens its tune visit', async () => {
    const first = pending()
    documentApiMock.retry.mockReturnValueOnce(first.promise)
    const { container, root } = await startActionView()
    try {
      await act(async () => button(container, 'retry selected').click())
      await act(async () => button(container, 'close review').click())
      await act(async () => button(container, '规则管理').click())
      expect(button(container, '保存配置').disabled).toBe(true)
      await act(async () => first.resolve(realDocument(1)))
      expect(button(container, '保存配置').disabled).toBe(false)
    } finally {
      await act(async () => first.resolve(realDocument(1)))
      act(() => root.unmount())
    }
  })

  it('keeps document B busy when the accepted action for document A finishes', async () => {
    const first = pending()
    const second = pending()
    documentApiMock.retry.mockImplementation((id: string) => (id === 'doc-1' ? first.promise : second.promise))
    const { container, root } = await startActionView()
    try {
      await act(async () => button(container, 'retry selected').click())
      await act(async () => button(container, 'quarantine-2.pdf').click())
      await act(async () => button(container, 'retry selected').click())
      expect(documentApiMock.retry).toHaveBeenCalledWith('doc-2')
      expect(button(container, 'retry selected').disabled).toBe(true)
      await act(async () => first.resolve(realDocument(1)))
      expect(button(container, 'retry selected').disabled).toBe(true)
      await act(async () => second.resolve(realDocument(2)))
      expect(button(container, 'retry selected').disabled).toBe(false)
    } finally {
      await act(async () => {
        first.resolve(realDocument(1))
        second.resolve(realDocument(2))
      })
      act(() => root.unmount())
    }
  })

  it('submits only one retry for two synchronous clicks on the same document', async () => {
    const first = pending()
    documentApiMock.retry.mockReturnValueOnce(first.promise)
    const { container, root } = await startActionView()
    try {
      await act(async () => {
        button(container, 'retry selected').click()
        button(container, 'retry selected').click()
      })
      expect(documentApiMock.retry).toHaveBeenCalledTimes(1)
      await act(async () => first.resolve(realDocument(1)))
      expect(button(container, 'retry selected').disabled).toBe(false)
    } finally {
      await act(async () => first.resolve(realDocument(1)))
      act(() => root.unmount())
    }
  })

  it('keeps tune saves scoped to their target document and each pending action', async () => {
    const first = pending()
    const second = pending()
    documentApiMock.patchPipeline.mockImplementation((id: string) => (id === 'doc-1' ? first.promise : second.promise))
    const { container, root } = await startActionView()
    try {
      await act(async () => button(container, 'tune selected').click())
      await act(async () => button(container, '保存配置').click())
      await act(async () => button(container, 'close tune').click())
      await act(async () => button(container, 'quarantine-2.pdf').click())
      await act(async () => button(container, 'tune selected').click())
      expect(button(container, '保存配置').disabled).toBe(false)
      await act(async () => button(container, '保存配置').click())
      expect(documentApiMock.patchPipeline).toHaveBeenLastCalledWith('doc-2', expect.any(Object))
      await act(async () => first.resolve(realDocument(1)))
      expect(container.textContent).toContain('调参回放')
      expect(button(container, '保存配置').disabled).toBe(true)
      await act(async () => second.resolve(realDocument(2)))
      expect(container.textContent).not.toContain('调参回放')
    } finally {
      await act(async () => {
        first.resolve(realDocument(1))
        second.resolve(realDocument(2))
      })
      act(() => root.unmount())
    }
  })

  const session = {
    token: { access_token: 'token-a', token_type: 'bearer', expires_in: 3600 },
    user: { id: 'user-a', email: 'a@example.org', username: 'A', is_active: true, created_at: '2026-11-05T00:00:00Z' },
  }
  function realDocument(index: number): Document {
    return {
      ...createDocument(index),
      status: 'quarantined',
      file_type: 'pdf',
      processing_progress: 100,
      processing_attempts: 1,
      chunk_count: 0,
      total_characters: 0,
      publication_status: 'published',
      created_at: '2026-08-01T00:00:00Z',
      governance: {
        enabled: true,
        documents: 1,
        changed_documents: 0,
        rules_applied: 1,
        dropped_documents: 1,
        drop_reasons: { outline_only: 1 },
      },
    }
  }
  function button(container: HTMLElement, text: string) {
    const item = Array.from(container.querySelectorAll('button')).find((node) =>
      node.textContent?.trim().includes(text),
    )
    if (!item) throw new Error(`button missing: ${text}`)
    return item
  }
  function pending() {
    let resolve!: (value: Document) => void
    const promise = new Promise<Document>((yes) => {
      resolve = yes
    })
    return { promise, resolve }
  }
  async function startActionView() {
    dialogState.controlled = true
    setAuthSession(session)
    documentApiMock.list.mockReset().mockImplementation(async ({ status }: { status: string }) => ({
      items: status === 'quarantined' ? [realDocument(1), realDocument(2)] : [],
      total: status === 'quarantined' ? 2 : 0,
    }))
    const view = renderPage()
    await act(async () => {
      await vi.waitFor(() => expect(view.container.textContent).toContain('quarantine-1.pdf'))
    })
    await act(async () => button(view.container, 'quarantine-1.pdf').click())
    return view
  }

  it.each(['release', 'retry', 'tune'] as const)(
    'stops the remaining %s mutations after login replacement',
    async (action) => {
      const first = pending()
      if (action === 'retry') documentApiMock.retry.mockReturnValueOnce(first.promise)
      else documentApiMock.patchPipeline.mockReturnValueOnce(first.promise)
      const { container, root } = await startActionView()
      try {
        if (action === 'tune') {
          await act(async () => button(container, 'tune selected').click())
          await act(async () => button(container, '保存并重试').click())
        } else await act(async () => button(container, `${action} selected`).click())
        setAuthSession(session)
        await act(async () => first.resolve(realDocument(1)))
        expect(documentApiMock.patchUserMetadata).not.toHaveBeenCalled()
        expect(documentApiMock.retry).toHaveBeenCalledTimes(action === 'retry' ? 1 : 0)
        expect(notices.success).not.toHaveBeenCalled()
        expect(documentApiMock.list).toHaveBeenCalledTimes(2)
      } finally {
        act(() => root.unmount())
      }
    },
  )

  it('submits one compound release for two synchronous clicks', async () => {
    const first = pending()
    documentApiMock.patchPipeline.mockReturnValue(first.promise)
    const { container, root } = await startActionView()
    try {
      await act(async () => {
        button(container, 'release selected').click()
        button(container, 'release selected').click()
      })
      expect(documentApiMock.patchPipeline).toHaveBeenCalledTimes(1)
      await act(async () => first.resolve(realDocument(1)))
    } finally {
      act(() => root.unmount())
    }
  })

  it('keeps a newly opened tune visit after an accepted old save completes', async () => {
    const first = pending()
    documentApiMock.patchPipeline.mockReturnValueOnce(first.promise)
    const { container, root } = await startActionView()
    try {
      await act(async () => button(container, 'tune selected').click())
      await act(async () => button(container, '保存配置').click())
      await act(async () => button(container, 'close tune').click())
      await act(async () => button(container, 'quarantine-2.pdf').click())
      await act(async () => button(container, 'tune selected').click())
      await act(async () => first.resolve(realDocument(1)))
      expect(container.textContent).toContain('调参回放')
      expect(documentApiMock.list).toHaveBeenCalledTimes(4)
      await act(async () => button(container, '保存配置').click())
      expect(documentApiMock.patchPipeline).toHaveBeenLastCalledWith('doc-2', expect.any(Object))
    } finally {
      act(() => root.unmount())
    }
  })

  it('preserves release order and accepted refresh through a token refresh', async () => {
    const first = pending()
    const steps: string[] = []
    documentApiMock.patchPipeline.mockImplementationOnce(() => {
      steps.push('patch')
      return first.promise
    })
    documentApiMock.retry.mockImplementationOnce(async () => {
      steps.push('retry')
      return realDocument(1)
    })
    documentApiMock.patchUserMetadata.mockImplementationOnce(async () => {
      steps.push('review')
      return realDocument(1)
    })
    const { container, root } = await startActionView()
    try {
      await act(async () => button(container, 'release selected').click())
      setAccessToken({ access_token: 'refresh-token', token_type: 'bearer', expires_in: 3600 })
      await act(async () => first.resolve(realDocument(1)))
      expect(steps).toEqual(['patch', 'retry', 'review'])
      expect(documentApiMock.list).toHaveBeenCalledTimes(4)
      expect(notices.success).toHaveBeenCalledWith('已放行并重试')
    } finally {
      act(() => root.unmount())
    }
  })

  it('keeps a newly selected review open when an old deletion completes', async () => {
    const first = pending()
    documentApiMock.delete.mockReturnValueOnce(first.promise)
    const { container, root } = await startActionView()
    try {
      await act(async () => button(container, 'delete selected').click())
      await act(async () => button(container, 'quarantine-2.pdf').click())
      await act(async () => first.resolve(realDocument(1)))
      expect(container.querySelector('[data-review-drawer]')?.textContent ?? '').toContain('quarantine-2.pdf')
    } finally {
      act(() => root.unmount())
    }
  })

  it('refreshes the accepted mutation scope after the query observer moves to another scope', async () => {
    const first = pending()
    documentApiMock.retry.mockReturnValueOnce(first.promise)
    const { container, root, rerender } = await startActionView()
    try {
      await act(async () => button(container, 'retry selected').click())
      routeState.search = 'datasetId=ds-1'
      await act(async () => rerender())
      await act(async () => {
        await vi.waitFor(() =>
          expect(documentApiMock.list.mock.calls.filter(([params]) => params.dataset_id === 'ds-1')).toHaveLength(2),
        )
      })
      await act(async () => {
        first.resolve(realDocument(1))
        await vi.waitFor(() =>
          expect(documentApiMock.list.mock.calls.filter(([params]) => params.dataset_id === undefined)).toHaveLength(4),
        )
      })
      expect(documentApiMock.list.mock.calls.filter(([params]) => params.dataset_id === 'ds-1')).toHaveLength(2)
    } finally {
      act(() => root.unmount())
    }
  })

  it('uses the project quarantine raster mark instead of PageTitleIcon', () => {
    const pagePath = path.resolve(__dirname, 'page.tsx')
    const assetPath = path.resolve(__dirname, '../../../public/brand/mimirq-quarantine-mark.png')
    const src = fs.readFileSync(pagePath, 'utf8')

    expect(fs.existsSync(assetPath)).toBe(true)
    expect(src).toContain("import Image from 'next/image'")
    expect(src).toContain('data-quarantine-title-mark="true"')
    expect(src).toContain('src="/brand/mimirq-quarantine-mark.png"')
    expect(src).toContain('size-7 shrink-0 items-center justify-center')
    expect(src).toContain('dark:bg-info/[0.14]')
    expect(src).not.toContain('<PageTitleIcon name="quarantine-queue"')
  })

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    routerMock.replace.mockReset()
    dialogState.controlled = false
    routeState.search = ''
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
      await vi.waitFor(() => expect(container.textContent).toContain('异常隔离审查表'))
      await vi.waitFor(() => expect(container.textContent).toContain('quarantine-1.pdf'))
    })

    const fileButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
      button.textContent?.includes('quarantine-1.pdf'),
    )
    expect(fileButton).not.toBeUndefined()

    await act(async () => {
      fileButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(container.querySelector('[data-review-drawer="true"]')?.textContent).toContain('quarantine-1.pdf')

    expect(container.textContent).toContain('quarantine-6.pdf')
    expect(container.textContent).not.toContain('quarantine-7.pdf')

    const nextButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (button) => button.textContent === '2',
    )
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
      await vi.waitFor(() => expect(container.textContent).toContain('规则管理'))
    })

    const ruleManagerButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
      button.textContent?.includes('规则管理'),
    )
    expect(ruleManagerButton).not.toBeUndefined()

    await act(async () => {
      ruleManagerButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(container.textContent).toContain('调参回放')
    expect(container.textContent).toContain('保存配置')
    expect(container.textContent).toContain('保存并重试')

    act(() => root.unmount())
  })

  it('root unrelated quarantine document remains actionable while another document retry is pending', async () => {
    const first = pending()
    const second = pending()
    documentApiMock.retry.mockImplementation((id: string) => (id === 'doc-1' ? first.promise : second.promise))
    const { container, root } = await startActionView()
    try {
      await act(async () => button(container, 'retry selected').click())
      expect(documentApiMock.retry).toHaveBeenCalledWith('doc-1')
      await act(async () => button(container, 'quarantine-2.pdf').click())
      const retrySecond = button(container, 'retry selected') as HTMLButtonElement
      expect(retrySecond.disabled).toBe(false)
      await act(async () => retrySecond.click())
      expect(documentApiMock.retry).toHaveBeenCalledWith('doc-2')
    } finally {
      await act(async () => {
        first.resolve(realDocument(1))
        second.resolve(realDocument(2))
      })
      act(() => root.unmount())
    }
  })
})
