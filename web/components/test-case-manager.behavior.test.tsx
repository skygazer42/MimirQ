// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { RegressionCase } from '@/types/evaluation'

const ports = vi.hoisted(() => ({
  list: vi.fn(),
  delete: vi.fn(),
  runTests: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}))
vi.mock('@/lib/api', () => ({
  evaluationApi: { listRegressionCaseWindow: ports.list, deleteRegressionCase: ports.delete },
  ragApi: {},
}))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
vi.mock('sonner', () => ({ toast: ports.toast }))

import { TestCaseManager } from './test-case-manager'

const cleanups: Array<() => void> = []

function caseFixture(id: string): RegressionCase {
  return {
    id,
    tenant_id: 'tenant-a',
    dataset_id: 'dataset-a',
    document_ids: [],
    question: `Question ${id}`,
    expected_answer: 'Answer',
    reference_sources: [],
    tags: [],
    reasoning_hops: [],
    evidence_chain: [],
    extra: {},
    created_by: null,
    created_at: '2026-11-13T00:00:00Z',
    updated_at: '2026-11-13T00:00:00Z',
  }
}

function button(label: string, within: ParentNode = document) {
  const element = [...within.querySelectorAll('button')].find((candidate) =>
    candidate.textContent?.trim().startsWith(label),
  )
  if (element === undefined) throw new Error(`Missing button: ${label}`)
  return element
}

async function settle() {
  await act(async () => {})
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10)
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10)
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  vi.clearAllMocks()
})

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  vi.useRealTimers()
})

it('removes confirmed successes and retries only the failed cases from a batch', async () => {
  const cases = new Map(['a', 'b'].map((id) => [id, caseFixture(id)]))
  let blocked = true
  ports.list.mockImplementation(async () => ({ total: cases.size, items: [...cases.values()], fullyLoaded: true }))
  ports.delete.mockImplementation(async (id: string) => {
    if (id === 'b' && blocked) throw new Error('Case b deletion failed')
    if (!cases.delete(id)) throw new Error('Case already deleted: 404')
  })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <TestCaseManager datasetId="dataset-a" onRunTests={ports.runTests} />
      </QueryClientProvider>,
    ),
  )
  cleanups.push(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
  })
  await settle()
  act(() => button('全选当前筛选结果').click())
  act(() => button('删除').click())
  const confirmation = document.querySelector('[role="alertdialog"]')
  if (confirmation === null) throw new Error('Expected the actual batch confirmation')
  await act(async () => {
    button('删除', confirmation).click()
  })
  await settle()

  expect(document.querySelector('[role="alertdialog"]')).not.toBeNull()
  expect(document.body.textContent).not.toContain('Question a')
  expect(document.body.textContent).toContain('Question b')
  expect(document.querySelector('[role="alert"]')?.textContent).toContain('1 个未确认删除')
  expect(confirmation.textContent).toContain('将删除已选的 1 个测试用例')
  expect(ports.toast.success).not.toHaveBeenCalled()

  blocked = false
  await act(async () => {
    button('删除', confirmation).click()
  })
  await settle()

  expect(ports.delete.mock.calls.map(([id]) => id)).toEqual(['a', 'b', 'b'])
  expect(document.querySelector('[role="alertdialog"]')).toBeNull()
  expect(document.body.textContent).not.toContain('Question b')
})

it('does not report deletion success after its panel was unmounted', async () => {
  let resolveDelete!: () => void
  const pending = new Promise<void>((resolve) => {
    resolveDelete = resolve
  })
  ports.list.mockResolvedValue({
    total: 1,
    items: [caseFixture('a')],
    fullyLoaded: true,
  })
  ports.delete.mockReturnValue(pending)
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <TestCaseManager datasetId="dataset-a" onRunTests={ports.runTests} />
      </QueryClientProvider>,
    ),
  )
  cleanups.push(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
  })
  await settle()
  act(() => button('Question a').click())
  expect(button('Question a').getAttribute('aria-pressed')).toBe('true')
  const deleteButton = document.querySelector<HTMLButtonElement>('button[aria-label="删除测试用例"]')
  expect(deleteButton).not.toBeNull()
  act(() => deleteButton?.click())
  const confirmation = document.querySelector('[role="alertdialog"]')
  if (confirmation === null) throw new Error('Expected the case confirmation')
  act(() => button('删除', confirmation).click())
  await settle()
  expect(ports.delete).toHaveBeenCalledExactlyOnceWith('a')
  act(() => root.unmount())
  await act(async () => {
    resolveDelete()
    await pending
  })
  await settle()
  expect(ports.toast.success).not.toHaveBeenCalled()
})
