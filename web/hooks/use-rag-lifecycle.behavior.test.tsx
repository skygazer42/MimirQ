// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ConnectorRunOut } from '@/types/connectors'
import { waitForAssertion } from '@/test/hook-harness'

const authStorage = vi.hoisted(() => ({
  clearAuthSession: vi.fn(),
  getAccessToken: vi.fn(() => null as string | null),
  getAuthSessionRevision: vi.fn(() => 0),
  getStoredUser: vi.fn(() => null),
  setStoredUser: vi.fn(),
}))

const documentApiMock = vi.hoisted(() => ({
  get: vi.fn(),
  getStatus: vi.fn(),
}))

const miniSearchMock = vi.hoisted(() => ({
  addAll: vi.fn(),
  instances: 0,
  removeAll: vi.fn(),
  search: vi.fn((_term: string) => []),
}))

const indexAuditApi = vi.hoisted(() => ({
  getIndexAudit: vi.fn(),
  reconcileIndexAudit: vi.fn(),
  getIndexAuditReconcileStatus: vi.fn(),
}))
const connectorApi = vi.hoisted(() => ({
  listRuns: vi.fn(),
  cancelRun: vi.fn(),
  retryFailed: vi.fn(),
  resumeRun: vi.fn(),
}))
const notifications = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))

vi.mock('@/lib/auth-storage', () => authStorage)
vi.mock('@/lib/api/auth', () => ({ authApi: { me: vi.fn() } }))
vi.mock('@/lib/api/documents', () => ({ documentApi: documentApiMock }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn(), reportClientWarning: vi.fn() }))
vi.mock('@/lib/api/observability', () => ({ observabilityApi: indexAuditApi }))
vi.mock('@/lib/api/connectors', () => ({ connectorApi }))
vi.mock('sonner', () => ({ toast: notifications }))
vi.mock('minisearch', () => ({
  default: class MiniSearchMock {
    constructor() {
      miniSearchMock.instances += 1
    }

    addAll(data: unknown[]) {
      miniSearchMock.addAll(data)
    }

    removeAll() {
      miniSearchMock.removeAll()
    }

    search(term: string) {
      return miniSearchMock.search(term)
    }
  },
}))

import { useAuth } from './use-auth'
import { useConnectorRuns } from './use-connector-runs'
import { useDocumentPolling } from './use-document-polling'
import { useLocalSearch } from './use-local-search'
import { useIndexAudit } from './use-index-audit'

type HookHarness<T> = {
  current: () => T
  render: (hook: () => T) => void
  unmount: () => void
}

function renderHook<T>(hook: () => T, wrapper?: (children: React.ReactNode) => React.ReactElement): HookHarness<T> {
  let value: T
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root: Root = createRoot(container)

  function Probe({ callback }: { callback: () => T }) {
    value = callback()
    return null
  }

  const render = (callback: () => T) => {
    const probe = React.createElement(Probe, { callback })
    act(() => root.render(wrapper ? wrapper(probe) : probe))
  }

  render(hook)
  return {
    current: () => value,
    render,
    unmount: () => {
      act(() => root.unmount())
      container.remove()
    },
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function renderIndexAudit(selectedDocumentIds = ['doc-a']) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderHook(
    () => useIndexAudit({ selectedDatasetId: 'dataset-a', selectedDocumentIds }),
    (children) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
  )
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  miniSearchMock.instances = 0
  authStorage.getAccessToken.mockReturnValue(null)
  indexAuditApi.reconcileIndexAudit.mockResolvedValue({ task_id: 'task-a' })
  indexAuditApi.getIndexAuditReconcileStatus.mockResolvedValue({ status: 'ready' })
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('RAG hook lifecycle behavior', () => {
  it('clears every cached query when logging out', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['private', 'documents'], { secret: true })
    const harness = renderHook(useAuth, (children) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ))

    act(() => harness.current().logout())

    expect(authStorage.clearAuthSession).toHaveBeenCalledOnce()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    harness.unmount()
  })

  it('does not register another polling timer after unmount', async () => {
    let resolveStatus: (value: { status: string }) => void = () => undefined
    documentApiMock.getStatus.mockReturnValue(
      new Promise((resolve) => {
        resolveStatus = resolve
      }),
    )
    const setTimeoutSpy = vi.spyOn(window, 'setTimeout')
    const options = {
      captureDocumentListOperation: () => ({
        params: {},
        isActive: () => true,
        isCurrent: () => true,
        updateCachedDocuments: vi.fn(),
        refresh: async () => undefined,
      }),
    }
    const harness = renderHook(() => useDocumentPolling(options))

    act(() => harness.current().pollDocumentStatus('doc-1'))
    setTimeoutSpy.mockClear()
    harness.unmount()
    await act(async () => {
      resolveStatus({ status: 'processing' })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(setTimeoutSpy).not.toHaveBeenCalled()
  })

  it('does not rebuild MiniSearch for equal field arrays', () => {
    const data = [{ id: '1', title: 'Alpha' }]
    const harness = renderHook(() => useLocalSearch(data, { fields: ['title'], storeFields: ['title'] }))

    harness.render(() => useLocalSearch(data, { fields: ['title'], storeFields: ['title'] }))

    expect(miniSearchMock.instances).toBe(1)
    expect(miniSearchMock.addAll).toHaveBeenCalledOnce()
    harness.unmount()
  })

  it('discards a reconciliation submission after selecting another document in the same dataset', async () => {
    const submission = deferred<{ task_id: string }>()
    indexAuditApi.reconcileIndexAudit.mockReturnValue(submission.promise)
    const harness = renderIndexAudit()
    let completion!: Promise<void>
    act(() => {
      completion = harness.current().reconcileIndexAudit()
    })
    harness.render(() => useIndexAudit({ selectedDatasetId: 'dataset-a', selectedDocumentIds: ['doc-b'] }))

    await act(async () => {
      submission.resolve({ task_id: 'task-a' })
      await completion
    })

    expect(harness.current().indexAuditReconcileState.status).toBe('idle')
    expect(harness.current().indexAuditReconcileState.taskId).toBeNull()
    expect(indexAuditApi.getIndexAuditReconcileStatus).not.toHaveBeenCalled()
    harness.unmount()
  })

  it.each(['resolve', 'reject'] as const)(
    'discards a late reconciliation status %s after selecting another document',
    async (settlement) => {
      const status = deferred<{ status: 'ready' }>()
      indexAuditApi.getIndexAuditReconcileStatus.mockReturnValue(status.promise)
      const harness = renderIndexAudit()
      let completion!: Promise<void>
      await act(async () => {
        completion = harness.current().reconcileIndexAudit()
        await Promise.resolve()
      })
      expect(indexAuditApi.getIndexAuditReconcileStatus).toHaveBeenCalledOnce()
      harness.render(() => useIndexAudit({ selectedDatasetId: 'dataset-a', selectedDocumentIds: ['doc-b'] }))

      await act(async () => {
        if (settlement === 'resolve') status.resolve({ status: 'ready' })
        else status.reject(new Error('old document status failed'))
        await completion
      })

      expect(harness.current().indexAuditReconcileState.status).toBe('idle')
      expect(harness.current().indexAuditReconcileState.taskId).toBeNull()
      harness.unmount()
    },
  )

  it('keeps the newer reconciliation when an earlier submission completes last', async () => {
    const earlier = deferred<{ task_id: string }>()
    const latest = deferred<{ task_id: string }>()
    indexAuditApi.reconcileIndexAudit.mockReturnValueOnce(earlier.promise).mockReturnValueOnce(latest.promise)
    const harness = renderIndexAudit()
    let earlierCompletion!: Promise<void>
    let latestCompletion!: Promise<void>
    act(() => {
      earlierCompletion = harness.current().reconcileIndexAudit()
      latestCompletion = harness.current().reconcileIndexAudit()
    })
    await act(async () => {
      latest.resolve({ task_id: 'task-latest' })
      await latestCompletion
    })
    await act(async () => {
      earlier.resolve({ task_id: 'task-earlier' })
      await earlierCompletion
    })

    expect(harness.current().indexAuditReconcileState.status).toBe('success')
    expect(harness.current().indexAuditReconcileState.taskId).toBe('task-latest')
    harness.unmount()
  })

  it.each(['resolve', 'reject'] as const)('does not publish a submission %s after unmount', async (settlement) => {
    const submission = deferred<{ task_id: string }>()
    indexAuditApi.reconcileIndexAudit.mockReturnValue(submission.promise)
    const harness = renderIndexAudit()
    let completion!: Promise<void>
    act(() => {
      completion = harness.current().reconcileIndexAudit()
    })
    harness.unmount()

    await act(async () => {
      if (settlement === 'resolve') submission.resolve({ task_id: 'task-a' })
      else submission.reject(new Error('old submission failed'))
      await completion
    })

    expect(notifications.success).not.toHaveBeenCalled()
    expect(notifications.error).not.toHaveBeenCalled()
    expect(indexAuditApi.getIndexAuditReconcileStatus).not.toHaveBeenCalled()
  })

  it('rejects a retained reconciliation callback after leaving and returning to a document', async () => {
    const harness = renderIndexAudit()
    const previousReconcile = harness.current().reconcileIndexAudit
    harness.render(() => useIndexAudit({ selectedDatasetId: 'dataset-a', selectedDocumentIds: ['doc-b'] }))
    harness.render(() => useIndexAudit({ selectedDatasetId: 'dataset-a', selectedDocumentIds: ['doc-a'] }))

    await act(async () => previousReconcile())

    expect(harness.current().indexAuditReconcileState.status).toBe('idle')
    expect(indexAuditApi.reconcileIndexAudit).not.toHaveBeenCalled()
    harness.unmount()
  })

  it.each([
    ['cancelConnectorRun', 'cancelRun', 'running', 'cancelled'],
    ['retryFailedConnectorRun', 'retryFailed', 'failed', 'pending'],
    ['resumeConnectorRun', 'resumeRun', 'failed', 'pending'],
  ] as const)(
    'keeps the selected dataset visible when %s from the previous dataset completes',
    async (actionName, apiMethod, initialStatus, nextStatus) => {
      const action = deferred<ConnectorRunOut>()
      const runA: ConnectorRunOut = {
        id: 'run-a',
        tenant_id: 'tenant-a',
        dataset_id: 'dataset-a',
        connector_id: 'url_batch',
        status: initialStatus,
        created_at: '2026-11-04T00:00:00Z',
      }
      const runB: ConnectorRunOut = { ...runA, id: 'run-b', dataset_id: 'dataset-b', status: 'completed' }
      const nextRun: ConnectorRunOut = {
        ...runA,
        id: apiMethod === 'cancelRun' ? 'run-a' : 'run-a-next',
        status: nextStatus,
      }
      let serverRunsA = [runA]
      connectorApi.listRuns.mockImplementation(async ({ dataset_id }: { dataset_id: string }) => ({
        total: 1,
        items: dataset_id === 'dataset-a' ? serverRunsA : [runB],
      }))
      connectorApi[apiMethod].mockReturnValue(action.promise)
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 10_000 } } })
      const harness = renderHook(
        () => useConnectorRuns({ selectedDatasetId: 'dataset-a' }),
        (children) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
      )
      await act(async () => harness.current().loadConnectorRuns())
      await waitForAssertion(() => expect(harness.current().connectorRuns).toEqual([runA]))
      let completion!: Promise<void>
      act(() => {
        completion = harness.current()[actionName]('run-a')
      })

      harness.render(() => useConnectorRuns({ selectedDatasetId: 'dataset-b' }))
      await act(async () => harness.current().loadConnectorRuns())
      await waitForAssertion(() => expect(harness.current().connectorRuns).toEqual([runB]))
      const originalQueryKey = ['connectors', 'runs', { datasetId: 'dataset-a', limit: 20 }]
      queryClient.setQueryData(originalQueryKey, [runA], { updatedAt: Date.now() - 10_001 })
      serverRunsA = [nextRun]

      await act(async () => {
        action.resolve(nextRun)
        await completion
      })
      await waitForAssertion(() => expect(queryClient.getQueryData(originalQueryKey)).toEqual([nextRun]))
      await waitForAssertion(() => expect(harness.current().connectorRuns).toEqual([runB]))
      harness.unmount()
    },
  )
})
