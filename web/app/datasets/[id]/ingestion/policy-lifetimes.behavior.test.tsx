// @vitest-environment happy-dom
import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitForAssertion } from '@/test/hook-harness'
import { setAccessToken, setAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import type { IngestionPolicy, IngestionRule } from '@/types/processing'

const ports = vi.hoisted(() => ({
  datasets: { get: vi.fn(), getIngestionPolicy: vi.fn(), updateIngestionPolicy: vi.fn(), getIngestionStats: vi.fn() },
  pipeline: { listGovernanceProfiles: vi.fn(), ingestionPreview: vi.fn() },
  toast: { success: vi.fn() },
}))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: ports.datasets }))
vi.mock('@/lib/api/pipeline', () => ({ pipelineApi: ports.pipeline }))
vi.mock('@/contexts/pipeline-capabilities-context', () => ({ usePipelineCapabilities: () => ({ capabilities: null }) }))
vi.mock('sonner', () => ({ toast: ports.toast }))
import { useIngestionPolicy } from './use-ingestion-policy'

function rule(name: string): IngestionRule {
  return { id: 'rule', name, enabled: true, match: { extensions: ['.pdf'] } }
}
function policy(name: string): IngestionPolicy {
  return { version: '1', rules: [rule(name)] }
}
function pending() {
  let resolve!: (value: IngestionPolicy) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<IngestionPolicy>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
function login() {
  setAuthSession({
    token: { access_token: 'token-a', token_type: 'bearer', expires_in: 3600 },
    user: { id: 'user-a', username: 'A', email: 'a@example.org', is_active: true, created_at: '2026-11-05T00:00:00Z' },
  })
}
const cleanup: Array<() => void> = []
let saved: Record<string, IngestionPolicy>
function mount() {
  let datasetId = 'dataset-a'
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } },
  })
  for (const id of ['dataset-a', 'dataset-b']) {
    client.setQueryData(queryKeys.datasets.detail(id), { id, name: id })
    client.setQueryData(queryKeys.datasets.ingestionPolicy(id), saved[id])
    client.setQueryData(queryKeys.datasets.ingestionStats(id), {})
  }
  client.setQueryData(queryKeys.governance.profiles({ include_builtin: true, limit: 200 }), { items: [], total: 0 })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  const hook = renderHook(() => useIngestionPolicy(datasetId), { wrapper: Wrapper })
  cleanup.push(() => {
    hook.unmount()
    client.clear()
  })
  return {
    ...hook,
    client,
    select(id: string) {
      datasetId = id
      hook.rerender()
    },
  }
}
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  login()
  saved = { 'dataset-a': policy('A saved'), 'dataset-b': policy('B saved') }
  ports.datasets.getIngestionPolicy.mockImplementation(async (id: string) => saved[id])
  ports.datasets.updateIngestionPolicy.mockImplementation(async (id: string, next: IngestionPolicy) => {
    saved[id] = next
    return next
  })
})
afterEach(() => {
  cleanup.splice(0).forEach((dispose) => dispose())
})

describe('ingestion policy save ownership', () => {
  it('keeps the selected B draft while an accepted A save refreshes its original cache', async () => {
    const response = pending()
    ports.datasets.updateIngestionPolicy.mockReturnValueOnce(response.promise)
    const hook = mount()
    act(() => hook.result.current.changeRules([rule('A submitted')]))
    let write!: Promise<void>
    act(() => {
      write = hook.result.current.save()
    })
    await waitForAssertion(() => expect(ports.datasets.updateIngestionPolicy).toHaveBeenCalledOnce())
    hook.select('dataset-b')
    act(() => hook.result.current.changeRules([rule('B draft')]))
    saved['dataset-a'] = policy('A accepted')
    await act(async () => {
      response.resolve(saved['dataset-a'])
      await write
    })
    expect(hook.result.current.rules[0].name).toBe('B draft')
    expect(hook.client.getQueryData(queryKeys.datasets.ingestionPolicy('dataset-a'))).toEqual(saved['dataset-a'])
    expect(ports.toast.success).not.toHaveBeenCalled()
  })
  it('preserves a new A visit draft and resets to the accepted baseline after A to B to A', async () => {
    const response = pending()
    ports.datasets.updateIngestionPolicy.mockReturnValueOnce(response.promise)
    const hook = mount()
    act(() => hook.result.current.changeRules([rule('First A draft')]))
    let write!: Promise<void>
    act(() => {
      write = hook.result.current.save()
    })
    await waitForAssertion(() => expect(ports.datasets.updateIngestionPolicy).toHaveBeenCalledOnce())
    hook.select('dataset-b')
    hook.select('dataset-a')
    act(() => hook.result.current.changeRules([rule('New A draft')]))
    saved['dataset-a'] = policy('A accepted')
    await act(async () => {
      response.resolve(saved['dataset-a'])
      await write
    })
    expect(hook.result.current.rules[0].name).toBe('New A draft')
    act(() => hook.result.current.discard())
    expect(hook.result.current.rules[0].name).toBe('A accepted')
  })
  it('does not reread or cache a save after an explicit replacement login', async () => {
    const response = pending()
    ports.datasets.updateIngestionPolicy.mockReturnValueOnce(response.promise)
    const hook = mount()
    act(() => hook.result.current.changeRules([rule('A draft')]))
    let write!: Promise<void>
    act(() => {
      write = hook.result.current.save()
    })
    await waitForAssertion(() => expect(ports.datasets.updateIngestionPolicy).toHaveBeenCalledOnce())
    login()
    await act(async () => {
      response.resolve(policy('retired'))
      await write
    })
    expect(ports.datasets.getIngestionPolicy).not.toHaveBeenCalled()
    expect(hook.client.getQueryData(queryKeys.datasets.ingestionPolicy('dataset-a'))).toEqual(policy('A saved'))
    expect(hook.result.current.saving).toBe(false)
    expect(hook.result.current.rules[0].name).toBe('A draft')
  })
  it('submits once for two synchronous clicks and verifies the server snapshot after token refresh', async () => {
    const response = pending()
    ports.datasets.updateIngestionPolicy.mockReturnValueOnce(response.promise)
    const hook = mount()
    act(() => hook.result.current.changeRules([rule('submitted')]))
    let write!: Promise<void>
    act(() => {
      write = hook.result.current.save()
      void hook.result.current.save()
    })
    await waitForAssertion(() => expect(ports.datasets.updateIngestionPolicy).toHaveBeenCalledOnce())
    setAccessToken({ access_token: 'refreshed', token_type: 'bearer', expires_in: 3600 })
    saved['dataset-a'] = policy('server canonical')
    await act(async () => {
      response.resolve(policy('PUT response'))
      await write
    })
    expect(ports.datasets.getIngestionPolicy).toHaveBeenCalledWith('dataset-a')
    expect(hook.result.current.rules[0].name).toBe('server canonical')
    expect(hook.result.current.dirty).toBe(false)
    expect(ports.toast.success).toHaveBeenCalledOnce()
  })
  it('retains the current editable draft and original baseline after a failed save', async () => {
    ports.datasets.updateIngestionPolicy.mockRejectedValueOnce(new Error('save unavailable'))
    const hook = mount()
    act(() => hook.result.current.changeRules([rule('retain me')]))
    await act(async () => hook.result.current.save())
    expect(hook.result.current.saveError).toContain('save unavailable')
    expect(hook.result.current.saving).toBe(false)
    expect(hook.result.current.rules[0].name).toBe('retain me')
    expect(hook.client.getQueryData(queryKeys.datasets.ingestionPolicy('dataset-a'))).toEqual(policy('A saved'))
  })
})
