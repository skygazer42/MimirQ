// @vitest-environment happy-dom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ getDataset: vi.fn(), listSuites: vi.fn(), listItems: vi.fn(), dashboard: vi.fn(), hardcases: vi.fn(), createSuite: vi.fn(), createItem: vi.fn(), retrieve: vi.fn() }))
vi.mock('@/lib/api', () => ({ datasetApi: { get: mocks.getDataset }, evidenceApi: { listSuites: mocks.listSuites, listItems: mocks.listItems, getSuiteDashboard: mocks.dashboard, getSuiteHardcaseCandidates: mocks.hardcases, createSuite: mocks.createSuite, createItem: mocks.createItem }, feedbackApi: {}, ragApi: { retrieveEvidence: mocks.retrieve } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), message: vi.fn() } }))
import { useEvidenceSuiteWorkbenchState } from './use-evidence-suite-workbench-state'

function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
const suite = (id: string) => ({ id, name: id, dataset_id: 'dataset-a', status: 'active', tags: [], config: {} })
const item = (id: string) => ({ id, suite_id: id.endsWith('b') ? 'suite-b' : 'suite-a', query: id, status: 'draft', notes: '', reference_sources: [] })

describe('Evidence workbench request ownership', () => {
  let root: ReturnType<typeof createRoot>
  let container: HTMLDivElement
  let state: ReturnType<typeof useEvidenceSuiteWorkbenchState>
  function Harness({ datasetId }: { datasetId: string }) { state = useEvidenceSuiteWorkbenchState(datasetId); return null }
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    vi.clearAllMocks()
    mocks.getDataset.mockImplementation(async id => ({ id, name: id }))
    mocks.listSuites.mockResolvedValue({ total: 2, items: [suite('suite-a'), suite('suite-b')] })
    mocks.listItems.mockResolvedValue({ total: 0, items: [] })
    mocks.dashboard.mockResolvedValue({ marker: 'current-dashboard' })
    mocks.hardcases.mockResolvedValue({ items: [] })
    container = document.createElement('div'); document.body.append(container); root = createRoot(container)
  })
  afterEach(() => { act(() => root.unmount()); document.body.innerHTML = '' })

  it.each([1, 2, 3])('keeps suite B after a delayed suite A item read (%s)', async () => {
    const old = deferred<{ total: number; items: ReturnType<typeof item>[] }>()
    mocks.listItems.mockImplementation(id => id === 'suite-a' ? old.promise : Promise.resolve({ total: 1, items: [item('item-b')] }))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    expect(state!.selectedSuiteId).toBe('suite-a')
    await act(async () => state!.setSelectedSuiteId('suite-b'))
    expect(state!.filteredItems.map(value => value.id)).toEqual(['item-b'])
    await act(async () => old.resolve({ total: 1, items: [item('item-a')] }))
    expect(state!.selectedSuiteId).toBe('suite-b')
    expect(state!.filteredItems.map(value => value.id)).toEqual(['item-b'])
  })

  it('keeps dataset B metadata after a delayed dataset A read', async () => {
    const old = deferred<{ id: string; name: string }>()
    mocks.getDataset.mockImplementation(id => id === 'dataset-a' ? old.promise : Promise.resolve({ id, name: id }))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => root.render(<Harness datasetId="dataset-b" />))
    expect(state!.dataset?.id).toBe('dataset-b')
    await act(async () => old.resolve({ id: 'dataset-a', name: 'old dataset' }))
    expect(state!.dataset?.id).toBe('dataset-b')
  })

  it('keeps the active suite dashboard when an earlier one finishes later', async () => {
    const old = deferred<{ marker: string }>()
    const current = { marker: 'suite-b-dashboard' }
    mocks.dashboard.mockImplementation(id => id === 'suite-a' ? old.promise : Promise.resolve(current))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => state!.setDashboardOpen(true))
    await act(async () => { state!.setDashboardOpen(false); state!.setSelectedSuiteId('suite-b') })
    await act(async () => state!.setDashboardOpen(true))
    expect(state!.dashboard).toBe(current)
    await act(async () => old.resolve({ marker: 'old-suite-a-dashboard' }))
    expect(state!.dashboard).toBe(current)
  })

  it('keeps a later suite selection and reloads the current filter after creation', async () => {
    const creation = deferred<ReturnType<typeof suite>>()
    const earlierList = deferred<{ total: number; items: ReturnType<typeof suite>[] }>()
    let reads = 0
    mocks.listSuites.mockImplementation(params => {
      if (!params.include_archived) return Promise.resolve({ total: 2, items: [suite('suite-a'), suite('suite-b')] })
      return ++reads === 1 ? earlierList.promise : Promise.resolve({ total: 3, items: [suite('suite-a'), suite('suite-b'), suite('suite-created')] })
    })
    mocks.createSuite.mockReturnValue(creation.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => state!.setSuiteName('created'))
    let pending!: Promise<void>
    await act(async () => { pending = state!.handleCreateSuite() })
    await act(async () => { state!.setSelectedSuiteId('suite-b'); state!.setIncludeArchivedSuites(true) })
    await act(async () => { creation.resolve(suite('suite-created')); await pending })
    await act(async () => earlierList.resolve({ total: 2, items: [suite('suite-a'), suite('suite-b')] }))
    expect(state!.selectedSuiteId).toBe('suite-b')
    expect(state!.filteredSuites.map(value => value.id)).toContain('suite-created')
    expect(mocks.listSuites.mock.calls.at(-1)?.[0].include_archived).toBe(true)
  })

  it('does not place an item created for suite A into suite B after switching', async () => {
    const creation = deferred<ReturnType<typeof item>>()
    mocks.createItem.mockReturnValue(creation.promise)
    mocks.retrieve.mockResolvedValue({ query_for_retrieval: '问题', has_evidence: true, citations: [{ document_id: 'doc', document_name: '文档', chunk_id: 'chunk', chunk_content: '正文', relevance_score: 0.9 }] })
    mocks.listItems.mockImplementation(id => Promise.resolve({ total: id === 'suite-b' ? 1 : 0, items: id === 'suite-b' ? [item('item-b')] : [] }))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => state!.setNewQuery('问题'))
    await act(async () => state!.runRetrieve())
    await act(async () => state!.toggleChunkSelection('chunk', 'retrieve'))
    let pending!: Promise<void>
    await act(async () => { pending = state!.handleCreateItem() })
    expect(mocks.createItem.mock.calls[0][0]).toBe('suite-a')
    await act(async () => state!.setSelectedSuiteId('suite-b'))
    await act(async () => { creation.resolve(item('created-a')); await pending })
    expect(state!.selectedSuiteId).toBe('suite-b')
    expect(state!.filteredItems.map(value => value.id)).toEqual(['item-b'])
    expect(state!.selectedItemId).toBe('')
  })
})
