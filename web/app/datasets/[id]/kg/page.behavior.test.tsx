// @vitest-environment happy-dom

import React, { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { queryKeys } from '@/lib/query-keys'

const graph = vi.hoisted(() => ({ load: vi.fn(async () => ({ nodes: [], links: [] })) }))
vi.mock('next/navigation', () => ({ useParams: () => ({ id: 'dataset-a' }) }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/components/app-frame', () => ({ AppFrame: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/components/graph/graph-viewer', () => ({ GraphViewer: () => null }))
vi.mock('@/components/ui/page-loading', () => ({
  PageLoading: ({ message }: { message: string }) => <p role="status">{message}</p>,
}))
vi.mock('@/lib/graph-service', () => ({ fetchInitialGraph: graph.load }))
vi.mock('@/lib/api', () => ({
  datasetApi: { get: vi.fn() },
  documentApi: { list: vi.fn() },
  kgApi: { getStats: vi.fn(async () => ({ entity_count: 0, event_count: 0 })) },
}))

import DatasetKGWorkbenchPage from '@/components/datasets/dataset-kg-workbench-page'

const filename = '长名称的售后服务知识与设备维护操作手册.pdf'
const cleanups: Array<() => void> = []

function renderWorkbench() {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  client.setQueryData(queryKeys.datasets.detail('dataset-a'), { id: 'dataset-a', name: '设备资料' })
  client.setQueryData(
    queryKeys.documents.list({
      dataset_id: 'dataset-a',
      skip: 0,
      limit: 100,
      order_by: 'created_at',
      order_dir: 'desc',
      q: null,
    }),
    {
      items: ['completed', 'pending', 'processing', 'failed', 'quarantined', 'cancelled', 'deleting'].map((status) => ({
        id: status,
        filename: status === 'completed' ? filename : `${status}.pdf`,
        status,
        file_type: 'pdf',
      })),
      total: 7,
    },
  )
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <DatasetKGWorkbenchPage />
      </QueryClientProvider>,
    ),
  )
  cleanups.push(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
  })
  return container
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
})

afterEach(() => {
  cleanups
    .splice(0)
    .reverse()
    .forEach((cleanup) => cleanup())
})

describe('dataset graph document stages', () => {
  it('labels every document status in Chinese and preserves the complete filename', () => {
    const view = renderWorkbench()
    for (const label of ['文档已就绪', '等待入库', '入库处理中', '入库失败', '已隔离', '已取消', '删除中']) {
      expect(view.textContent).toContain(label)
    }
    expect(view.querySelector(`[title="${filename}"]`)?.textContent).toBe(filename)
    const row = view.querySelector(`[aria-label="选择文档 ${filename}"]`)!.closest('label')!.parentElement!
    expect(row.textContent).not.toContain('completed')
    expect(row.textContent).toContain('抽取')
  })

  it('explains that ready documents still require graph extraction when the graph is empty', async () => {
    const view = renderWorkbench()
    const checkbox = view.querySelector<HTMLButtonElement>(`[aria-label="选择文档 ${filename}"]`)!
    await act(async () => checkbox.click())
    const load = Array.from(view.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === '加载图谱',
    )!
    await act(async () => load.click())
    expect(graph.load).toHaveBeenCalledWith(expect.objectContaining({ documentIds: ['completed'] }))
    expect(view.textContent).toContain('当前范围暂无图谱数据')
    expect(view.textContent).toContain('文档就绪后，执行图谱抽取，再重新加载图谱。')
    expect(view.textContent).toContain('当前范围 · 1 份文档')
    const extract = Array.from(view.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === '执行图谱抽取',
    )!
    expect(extract.parentElement?.textContent).toContain('重新加载图谱')
    await act(async () => extract.click())
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('当前范围 1 份文档')
    expect(checkbox.getAttribute('aria-checked')).toBe('true')
  })

  it('keeps graph errors and a single retry beside the current scope', async () => {
    graph.load.mockRejectedValueOnce(new Error('图谱读取暂不可用'))
    const view = renderWorkbench()
    const checkbox = view.querySelector<HTMLButtonElement>(`[aria-label="选择文档 ${filename}"]`)!
    await act(async () => checkbox.click())
    const load = Array.from(view.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === '加载图谱',
    )!
    await act(async () => load.click())
    const retries = Array.from(view.querySelectorAll('button')).filter(
      (button) => button.textContent?.trim() === '重试加载图谱',
    )
    expect(retries).toHaveLength(1)
    expect(retries[0].parentElement?.parentElement?.textContent).toContain('当前范围 · 1 份文档')
    expect(retries[0].parentElement?.parentElement?.querySelector('[role="alert"]')?.textContent).toContain(
      '图谱读取暂不可用',
    )
    expect(
      Array.from(view.querySelectorAll('button')).some((button) => button.textContent?.trim() === '加载图谱'),
    ).toBe(false)
    await act(async () => retries[0].click())
    expect(view.textContent).toContain('当前范围暂无图谱数据')
    expect(checkbox.getAttribute('aria-checked')).toBe('true')
    expect(graph.load).toHaveBeenLastCalledWith(expect.objectContaining({ documentIds: ['completed'] }))
  })
})
