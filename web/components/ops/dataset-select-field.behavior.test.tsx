// @vitest-environment happy-dom

import React, { act, type ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Dataset } from '@/types/datasets'
import { queryKeys } from '@/lib/query-keys'
import { waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({ listAll: vi.fn() }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: api }))

import { DatasetSelectField } from './dataset-select-field'

const dataset: Dataset = { id: 'dataset-a', tenant_id: 'tenant-a', name: 'Knowledge', permission: 'all_team_members' }
const cleanups = new Set<() => void>()

function renderField(props: ComponentProps<typeof DatasetSelectField>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  act(() => {
    root.render(
      <QueryClientProvider client={client}>
        <DatasetSelectField {...props} />
      </QueryClientProvider>,
    )
  })
  cleanups.add(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
  })
  return { container, client }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  api.listAll.mockReset()
})

afterEach(() => {
  for (const cleanup of cleanups) cleanup()
  cleanups.clear()
})

describe('dataset selection query feedback', () => {
  it('shows an initial failure and retries before automatically selecting a returned dataset', async () => {
    api.listAll.mockRejectedValueOnce(new Error('Dataset service unavailable')).mockResolvedValueOnce([dataset])
    const onChange = vi.fn()
    const { container } = renderField({ value: '', onChange, autoSelectFirst: true })
    await waitForAssertion(() =>
      expect(container.querySelector('[role="alert"]')?.textContent).toContain('unavailable'),
    )
    expect(onChange).not.toHaveBeenCalled()
    const retry = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === '重试')
    expect(retry).toBeDefined()

    act(() => retry?.click())

    await waitForAssertion(() => expect(onChange).toHaveBeenCalledWith('dataset-a'))
    expect(api.listAll).toHaveBeenCalledTimes(2)
    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(container.querySelector('[role="combobox"]')?.getAttribute('aria-label')).toBe('数据集')
  })

  it('keeps a cached dataset selectable when refresh fails', async () => {
    api.listAll.mockResolvedValueOnce([dataset]).mockRejectedValueOnce(new Error('Refresh unavailable'))
    const { container, client } = renderField({ value: 'dataset-a', onChange: vi.fn() })
    const queryKey = queryKeys.datasets.exhaustive()
    await waitForAssertion(() => expect(client.getQueryState(queryKey)?.status).toBe('success'))

    await act(async () => client.refetchQueries({ queryKey }))

    await waitForAssertion(() =>
      expect(container.querySelector('[role="alert"]')?.textContent).toContain('unavailable'),
    )
    expect(client.getQueryData(queryKey)).toEqual([dataset])
    expect(container.querySelector<HTMLButtonElement>('[role="combobox"]')?.disabled).toBe(false)
  })

  it('distinguishes a successful empty collection from a failed request', async () => {
    api.listAll.mockResolvedValue([])
    const onChange = vi.fn()
    const { container, client } = renderField({ value: '', onChange, autoSelectFirst: true })
    await waitForAssertion(() => expect(client.getQueryState(queryKeys.datasets.exhaustive())?.status).toBe('success'))

    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(container.querySelector<HTMLButtonElement>('[role="combobox"]')?.disabled).toBe(true)
    expect(onChange).not.toHaveBeenCalled()
  })
})
