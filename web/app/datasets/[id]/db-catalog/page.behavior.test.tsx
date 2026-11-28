// @vitest-environment happy-dom

import React, { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { queryKeys } from '@/lib/query-keys'

vi.mock('next/navigation', () => ({ useParams: () => ({ id: 'dataset-a' }) }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/components/app-frame', () => ({ AppFrame: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/lib/api', () => ({ datasetApi: {}, connectorApi: {} }))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))

import DatasetDbCatalogPage from './page'

const createdAt = '2026-11-23T14:00:00Z'
const cleanups: Array<() => void> = []

function renderCatalog() {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  client.setQueryData(queryKeys.datasets.detail('dataset-a'), { id: 'dataset-a', name: '设备资料' })
  client.setQueryData(
    queryKeys.datasets.dbCatalogTables('dataset-a', { skip: 0, limit: 200, engine: undefined, q: undefined }),
    { items: [], total: 0 },
  )
  client.setQueryData(queryKeys.connectors.runs({ dataset_id: 'dataset-a', limit: 10 }), {
    items: [
      {
        id: 'run-a',
        connector_id: 'mysql_catalog',
        status: 'completed',
        created_at: createdAt,
        stats: { result: { tables: 4 } },
      },
    ],
  })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <DatasetDbCatalogPage />
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
})
afterEach(() =>
  cleanups
    .splice(0)
    .reverse()
    .forEach((cleanup) => cleanup()),
)

async function click(button: HTMLButtonElement) {
  await act(async () => {
    button.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }))
    button.click()
  })
}

describe('database catalog presentation', () => {
  it('labels synchronization totals as connector scoped and preserves ISO timestamps in titles', async () => {
    const view = renderCatalog()
    expect(view.textContent).toContain('连接器 mysql_catalog')
    expect(view.textContent).toContain('该连接器本次同步 4 张表')
    await click(
      Array.from(view.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find(
        (button) => button.textContent === '同步记录',
      )!,
    )
    const time = view.querySelector('table time')!
    expect(time.getAttribute('title')).toBe(createdAt)
    expect(time.getAttribute('datetime')).toBe(createdAt)
    expect(time.textContent).toContain('2026/11/23')
    expect(time.textContent).toMatch(/\d{2}:\d{2}:\d{2}/)
    expect(time.textContent).not.toBe(createdAt)
    expect(view.textContent).toContain('当前数据集各连接器的目录同步运行记录。')
  })

  it('retains all authentication fields and both form actions', async () => {
    const view = renderCatalog()
    await click(
      Array.from(view.querySelectorAll('button')).find((button) => button.textContent?.trim() === '新建同步')!,
    )
    const dialog = document.querySelector('[role="dialog"]')!
    for (const field of ['host', 'database', 'username', 'password']) {
      expect(dialog.querySelector(`#db-catalog-sync-${field}`)).toBeTruthy()
    }
    expect(dialog.querySelector('button[type="submit"]')?.getAttribute('form')).toBe('db-catalog-sync')
    expect(dialog.textContent).toContain('取消')
    expect(dialog.textContent).toContain('开始同步')
  })
})
