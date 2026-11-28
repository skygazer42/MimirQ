// @vitest-environment happy-dom

import { act, type PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { GraphData } from '@/lib/graph-types'
import { renderHook, waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({ expand: vi.fn(), error: vi.fn() }))
vi.mock('@/lib/graph-service', () => ({ expandGraphNode: api.expand }))
vi.mock('@/lib/api/graph', () => ({ kgApi: {} }))
vi.mock('sonner', () => ({ toast: { error: api.error } }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn() }))

import { useGraphNodeOperations } from './use-graph-node-operations'

function graphRequest() {
  let resolve!: (graph: GraphData) => void
  let reject!: (error: Error) => void
  const promise = new Promise<GraphData>((fulfill, fail) => {
    resolve = fulfill
    reject = fail
  })
  return { promise, resolve, reject }
}

function operationProps(datasetId: string): Parameters<typeof useGraphNodeOperations>[0] {
  return {
    dataSource: 'live',
    isDetailOpen: false,
    selectedNode: null,
    scopeParams: { dataset_id: datasetId },
    includeEntityLinks: true,
    includeRelationLinks: false,
    minSharedEvents: 2,
    maxEntityLinks: 100,
    scopedDocumentIds: null,
    pipelineHash: null,
    deleteNodeTarget: null,
    setGraphData: vi.fn(),
    setDeleteNodeOpen: vi.fn(),
    setDeleteNodeTarget: vi.fn(),
    setSelectedNode: vi.fn(),
    setIsDetailOpen: vi.fn(),
  }
}

const cleanups = new Set<() => void>()
let queryClient: QueryClient

function QueryWrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.resetAllMocks()
  queryClient = new QueryClient()
})
afterEach(() => {
  for (const cleanup of cleanups) cleanup()
  cleanups.clear()
  queryClient.clear()
})

describe('graph expansion request ownership', () => {
  it('reports a current expansion failure and clears its busy state', async () => {
    api.expand.mockRejectedValue(new Error('Expansion unavailable'))
    const props = operationProps('dataset-a')
    const hook = renderHook(() => useGraphNodeOperations(props), { wrapper: QueryWrapper })
    cleanups.add(hook.unmount)
    act(() => hook.result.current.handleExpandNodeById('node-a'))
    await waitForAssertion(() => expect(api.error).toHaveBeenCalledWith('Expansion unavailable'))
    expect(hook.result.current.isExpanding).toBe(false)
    expect(props.setGraphData).not.toHaveBeenCalled()
  })

  it('does not merge a completed expansion into another dataset', async () => {
    const request = graphRequest()
    api.expand.mockReturnValue(request.promise)
    let props = operationProps('dataset-a')
    const hook = renderHook(() => useGraphNodeOperations(props), { wrapper: QueryWrapper })
    cleanups.add(hook.unmount)
    act(() => hook.result.current.handleExpandNodeById('node-a'))
    props = { ...props, scopeParams: { dataset_id: 'dataset-b' } }
    hook.rerender()
    await act(async () => request.resolve({ nodes: [{ id: 'late-node', label: 'Late' }], links: [] }))
    expect(props.setGraphData).not.toHaveBeenCalled()
    expect(hook.result.current.isExpanding).toBe(false)
  })

  it('ignores an expansion failure after unmount', async () => {
    const request = graphRequest()
    api.expand.mockReturnValue(request.promise)
    const props = operationProps('dataset-a')
    const hook = renderHook(() => useGraphNodeOperations(props), { wrapper: QueryWrapper })
    cleanups.add(hook.unmount)
    act(() => hook.result.current.handleExpandNodeById('node-a'))
    hook.unmount()
    cleanups.delete(hook.unmount)
    await act(async () => request.reject(new Error('Late expansion')))
    expect(api.error).not.toHaveBeenCalled()
  })

  it('stays busy until both current expansions complete', async () => {
    const first = graphRequest(),
      second = graphRequest()
    api.expand.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const props = operationProps('dataset-a')
    const hook = renderHook(() => useGraphNodeOperations(props), { wrapper: QueryWrapper })
    cleanups.add(hook.unmount)
    act(() => {
      hook.result.current.handleExpandNodeById('node-a')
      hook.result.current.handleExpandNodeById('node-b')
    })
    expect(hook.result.current.isExpanding).toBe(true)
    await act(async () => first.resolve({ nodes: [], links: [] }))
    expect(hook.result.current.isExpanding).toBe(true)
    await act(async () => second.resolve({ nodes: [], links: [] }))
    expect(hook.result.current.isExpanding).toBe(false)
  })
})
