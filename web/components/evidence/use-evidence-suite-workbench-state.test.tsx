// @vitest-environment happy-dom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getDataset: vi.fn(),
  listSuites: vi.fn(),
  listItems: vi.fn(),
  dashboard: vi.fn(),
  hardcases: vi.fn(),
  driftAudit: vi.fn(),
  createSuite: vi.fn(),
  createItem: vi.fn(),
  retrieve: vi.fn(),
  exportSuite: vi.fn(),
  syncSuite: vi.fn(),
  toEvidenceItem: vi.fn(),
  archiveItem: vi.fn(),
  reviewItem: vi.fn(),
  approveItem: vi.fn(),
  downloadBlob: vi.fn(),
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), message: vi.fn() },
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({
  datasetApi: { get: mocks.getDataset },
  evidenceApi: {
    listSuites: mocks.listSuites,
    listItems: mocks.listItems,
    getSuiteDashboard: mocks.dashboard,
    getSuiteHardcaseCandidates: mocks.hardcases,
    getSuiteDriftAudit: mocks.driftAudit,
    createSuite: mocks.createSuite,
    createItem: mocks.createItem,
    exportSuite: mocks.exportSuite,
    syncSuiteToRegression: mocks.syncSuite,
    archiveItem: mocks.archiveItem,
    reviewItem: mocks.reviewItem,
    approveItem: mocks.approveItem,
  },
  feedbackApi: { toEvidenceItem: mocks.toEvidenceItem },
  ragApi: { retrieveEvidence: mocks.retrieve },
}))
vi.mock('sonner', () => ({ toast: mocks.toast }))
vi.mock('@/lib/download', () => ({ downloadBlob: mocks.downloadBlob }))
import { useEvidenceSuiteWorkbenchState } from './use-evidence-suite-workbench-state'
import { clearAuthSession } from '@/lib/auth-storage'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
const suite = (id: string) => ({ id, name: id, dataset_id: 'dataset-a', status: 'active', tags: [], config: {} })
const item = (id: string) => ({
  id,
  suite_id: id.endsWith('b') ? 'suite-b' : 'suite-a',
  query: id,
  status: 'draft',
  notes: '',
  reference_sources: [],
})

function dashboardFixture(marker = 'current-dashboard') {
  const duration = { count: 0, p50_sec: null, p90_sec: null, mean_sec: null }
  return {
    marker,
    generated_at: '2026-11-16T00:00:00Z',
    throughput: {
      window_days: 7,
      last_window: { created: 0, reviewed: 0, approved: 0 },
      draft_to_reviewed: duration,
      reviewed_to_approved: duration,
      draft_to_approved: duration,
    },
    coverage: { language: [], file_type: [], quality_bucket: [], channel: [], heatmaps: {} },
  }
}

function hardcaseFixture() {
  return {
    generated_at: '2026-11-16T00:00:00Z',
    enabled: true,
    window_minutes: 10080,
    max_bytes: 100000,
    truncated: false,
    feedback_scanned: 0,
    trace_index_size: 0,
    candidates: [],
  }
}

describe('Evidence workbench request ownership', () => {
  let root: ReturnType<typeof createRoot>
  let container: HTMLDivElement
  let state: ReturnType<typeof useEvidenceSuiteWorkbenchState>
  function Harness({ datasetId }: { datasetId: string }) {
    state = useEvidenceSuiteWorkbenchState(datasetId)
    return null
  }
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    vi.resetAllMocks()
    mocks.getDataset.mockImplementation(async (id) => ({ id, name: id }))
    mocks.listSuites.mockResolvedValue({ total: 2, items: [suite('suite-a'), suite('suite-b')] })
    mocks.listItems.mockResolvedValue({ total: 0, items: [] })
    mocks.dashboard.mockResolvedValue(dashboardFixture())
    mocks.hardcases.mockResolvedValue(hardcaseFixture())
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    document.body.innerHTML = ''
  })

  it.each([1, 2, 3])('keeps suite B after a delayed suite A item read (%s)', async () => {
    const old = deferred<{ total: number; items: ReturnType<typeof item>[] }>()
    mocks.listItems.mockImplementation((id) =>
      id === 'suite-a' ? old.promise : Promise.resolve({ total: 1, items: [item('item-b')] }),
    )
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    expect(state!.selectedSuiteId).toBe('suite-a')
    await act(async () => state!.setSelectedSuiteId('suite-b'))
    expect(state!.filteredItems.map((value) => value.id)).toEqual(['item-b'])
    await act(async () => old.resolve({ total: 1, items: [item('item-a')] }))
    expect(state!.selectedSuiteId).toBe('suite-b')
    expect(state!.filteredItems.map((value) => value.id)).toEqual(['item-b'])
  })

  it('keeps dataset B metadata after a delayed dataset A read', async () => {
    const old = deferred<{ id: string; name: string }>()
    mocks.getDataset.mockImplementation((id) => (id === 'dataset-a' ? old.promise : Promise.resolve({ id, name: id })))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => root.render(<Harness datasetId="dataset-b" />))
    expect(state!.dataset?.id).toBe('dataset-b')
    await act(async () => old.resolve({ id: 'dataset-a', name: 'old dataset' }))
    expect(state!.dataset?.id).toBe('dataset-b')
  })

  it('keeps the active suite dashboard when an earlier one finishes later', async () => {
    const old = deferred<ReturnType<typeof dashboardFixture>>()
    const current = dashboardFixture('suite-b-dashboard')
    mocks.dashboard.mockImplementation((id) => (id === 'suite-a' ? old.promise : Promise.resolve(current)))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => state!.setDashboardOpen(true))
    await act(async () => {
      state!.setDashboardOpen(false)
      state!.setSelectedSuiteId('suite-b')
    })
    await act(async () => state!.setDashboardOpen(true))
    expect(state!.dashboardSnapshot?.data).toEqual(current)
    await act(async () => old.resolve(dashboardFixture('old-suite-a-dashboard')))
    expect(state!.dashboardSnapshot?.data).toEqual(current)
  })

  it('keeps a later suite selection and reloads the current filter after creation', async () => {
    const creation = deferred<ReturnType<typeof suite>>()
    const earlierList = deferred<{ total: number; items: ReturnType<typeof suite>[] }>()
    let reads = 0
    mocks.listSuites.mockImplementation((params) => {
      if (!params.include_archived) return Promise.resolve({ total: 2, items: [suite('suite-a'), suite('suite-b')] })
      return ++reads === 1
        ? earlierList.promise
        : Promise.resolve({ total: 3, items: [suite('suite-a'), suite('suite-b'), suite('suite-created')] })
    })
    mocks.createSuite.mockReturnValue(creation.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.openCreateSuite())
    await act(async () => state!.setSuiteName('created'))
    let pending!: Promise<void>
    await act(async () => {
      pending = state!.handleCreateSuite()
    })
    await act(async () => {
      state!.setSelectedSuiteId('suite-b')
      state!.setIncludeArchivedSuites(true)
    })
    await act(async () => {
      creation.resolve(suite('suite-created'))
      await pending
    })
    await act(async () => earlierList.resolve({ total: 2, items: [suite('suite-a'), suite('suite-b')] }))
    expect(state!.selectedSuiteId).toBe('suite-b')
    expect(state!.filteredSuites.map((value) => value.id)).toContain('suite-created')
    expect(mocks.listSuites.mock.calls.at(-1)?.[0].include_archived).toBe(true)
  })

  it('does not place an item created for suite A into suite B after switching', async () => {
    const creation = deferred<ReturnType<typeof item>>()
    mocks.createItem.mockReturnValue(creation.promise)
    mocks.retrieve.mockResolvedValue({
      query_for_retrieval: '问题',
      has_evidence: true,
      citations: [
        { document_id: 'doc', document_name: '文档', chunk_id: 'chunk', chunk_content: '正文', relevance_score: 0.9 },
      ],
    })
    mocks.listItems.mockImplementation((id) =>
      Promise.resolve({ total: id === 'suite-b' ? 1 : 0, items: id === 'suite-b' ? [item('item-b')] : [] }),
    )
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.openCreateItem())
    await act(async () => state!.setNewQuery('问题'))
    await act(async () => state!.runRetrieve())
    await act(async () => state!.toggleChunkSelection('chunk', 'retrieve'))
    let pending!: Promise<void>
    await act(async () => {
      pending = state!.handleCreateItem()
    })
    expect(mocks.createItem.mock.calls[0][0]).toBe('suite-a')
    await act(async () => state!.setSelectedSuiteId('suite-b'))
    await act(async () => {
      creation.resolve(item('created-a'))
      await pending
    })
    expect(state!.selectedSuiteId).toBe('suite-b')
    expect(state!.filteredItems.map((value) => value.id)).toEqual(['item-b'])
    expect(state!.selectedItemId).toBe('')
  })

  it('retires an in-flight retrieval when the create-item dialog closes', async () => {
    const request = deferred<{ query_for_retrieval: string; citations: never[]; has_evidence: boolean }>()
    mocks.retrieve.mockReturnValue(request.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.openCreateItem())
    act(() => state!.setNewQuery('current question'))
    let pending!: Promise<void>
    act(() => {
      pending = state!.runRetrieve()
    })
    act(() => state!.setCreateItemOpen(false))
    await act(async () => {
      request.resolve({ query_for_retrieval: 'old question', citations: [], has_evidence: false })
      await pending
    })
    expect(state!.retrieveRes).toBeNull()
    expect(state!.retrieving).toBe(false)
    expect(mocks.toast.message).not.toHaveBeenCalled()
  })

  it('does not commit a dashboard response after its dialog closes', async () => {
    const request = deferred<ReturnType<typeof dashboardFixture>>()
    mocks.dashboard.mockReturnValue(request.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => state!.setDashboardOpen(true))
    act(() => state!.setDashboardOpen(false))
    await act(async () => request.resolve(dashboardFixture('retired dashboard')))
    expect(state!.dashboardSnapshot).toBeNull()
    expect(state!.dashboardLoading).toBe(false)
  })

  it('does not commit hardcase candidates after the candidate dialog closes', async () => {
    const request = deferred<ReturnType<typeof hardcaseFixture>>()
    mocks.hardcases.mockReturnValue(request.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => state!.setHardcaseOpen(true))
    act(() => state!.setHardcaseOpen(false))
    await act(async () => request.resolve(hardcaseFixture()))
    expect(state!.hardcaseSnapshot).toBeNull()
    expect(state!.hardcaseLoading).toBe(false)
  })

  it('ignores server metadata and notifications from a retired login', async () => {
    const request = deferred<{ id: string; name: string }>()
    mocks.getDataset
      .mockReturnValueOnce(request.promise)
      .mockResolvedValue({ id: 'dataset-a', name: 'current session' })
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => clearAuthSession())
    await act(async () => request.resolve({ id: 'dataset-a', name: 'retired session' }))
    expect(state!.dataset?.name).not.toBe('retired session')
  })

  it('keeps a newly reopened create-suite draft when an old submission completes', async () => {
    const request = deferred<ReturnType<typeof suite>>()
    mocks.createSuite.mockReturnValue(request.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.openCreateSuite())
    act(() => state!.setSuiteName('first draft'))
    let pending!: Promise<void>
    act(() => {
      pending = state!.handleCreateSuite()
    })
    act(() => state!.setCreateSuiteOpen(false))
    act(() => state!.openCreateSuite())
    act(() => state!.setSuiteName('second draft'))
    await act(async () => {
      request.resolve(suite('created'))
      await pending
    })
    expect(state!.createSuiteOpen).toBe(true)
    expect(state!.suiteName).toBe('second draft')
    expect(mocks.toast.success).not.toHaveBeenCalled()
  })

  it('claims a create-suite submission synchronously before React disables its button', async () => {
    const request = deferred<ReturnType<typeof suite>>()
    mocks.createSuite.mockReturnValue(request.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.openCreateSuite())
    act(() => state!.setSuiteName('single operation'))
    let first!: Promise<void>
    let second!: Promise<void>
    act(() => {
      first = state!.handleCreateSuite()
      second = state!.handleCreateSuite()
    })
    expect(mocks.createSuite).toHaveBeenCalledTimes(1)
    await act(async () => {
      request.resolve(suite('created'))
      await Promise.all([first, second])
    })
  })

  it('retains a valid imported pack and its selection when the replacement file is invalid', async () => {
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.openCreateItem())
    const pack = {
      version: 1,
      citations: [
        { document_id: 'doc', document_name: 'name', chunk_id: 'chunk', chunk_content: 'source', relevance_score: 0 },
      ],
    }
    await act(async () => state!.handlePickPackFile(new File([JSON.stringify(pack)], 'valid.json')))
    act(() => state!.toggleChunkSelection('chunk', 'import'))
    const previous = state!.importPack
    await act(async () => state!.handlePickPackFile(new File(['{'], 'invalid.json')))
    expect(state!.importError).not.toBeNull()
    expect(state!.importPack).toBe(previous)
    expect(state!.importSelectedChunkIds).toEqual(['chunk'])
  })

  it('copies exact source text without trimming the caller data', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    const clipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    try {
      await act(async () => root.render(<Harness datasetId="dataset-a" />))
      await act(async () => state!.copyText('source', '  原文\n\n'))
      expect(writeText).toHaveBeenCalledExactlyOnceWith('  原文\n\n')
    } finally {
      if (clipboard === undefined) Reflect.deleteProperty(navigator, 'clipboard')
      else Object.defineProperty(navigator, 'clipboard', clipboard)
    }
  })

  it('reads every suite page instead of hiding all suites after the first 200', async () => {
    const all = Array.from({ length: 201 }, (_, index) => suite('suite-' + index))
    mocks.listSuites.mockImplementation((params) => ({
      total: all.length,
      items: all.slice(params.skip ?? 0, (params.skip ?? 0) + params.limit),
    }))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    expect(state!.filteredSuites).toHaveLength(201)
    expect(state!.filteredSuites.at(-1)?.id).toBe('suite-200')
  })

  it('reads all item pages once and filters the accepted collection locally', async () => {
    const all = Array.from({ length: 201 }, (_, index) => ({
      ...item('item-' + index),
      status: index === 200 ? 'approved' : 'draft',
    }))
    mocks.listItems.mockImplementation((_id, params) => ({
      total: all.length,
      items: all.slice(params.skip, params.skip + params.limit),
    }))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    expect(state!.filteredItems).toHaveLength(201)
    act(() => state!.setStatusFilter('approved'))
    expect(state!.filteredItems.map((entry) => entry.id)).toEqual(['item-200'])
    expect(mocks.listItems).toHaveBeenCalledTimes(2)
  })

  it('retains the draft and exact source snapshot after a failed item creation', async () => {
    mocks.createItem.mockRejectedValue(new Error('保存失败'))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.openCreateItem())
    const pack = {
      citations: [
        { document_id: 'doc', chunk_id: 'chunk', chunk_content: '  原文\n\n', relevance_score: 0, extra: false },
      ],
      selected_chunk_ids: ['chunk'],
      metadata: { text: '' },
    }
    act(() => {
      state!.setCreateItemTab('import')
      state!.setNewQuery('问题')
      state!.setNewExpected('')
      state!.setNewNotes('  备注\n')
    })
    await act(async () => state!.handlePickPackFile(new File([JSON.stringify(pack)], 'pack.json')))
    await act(async () => state!.handleCreateItem())
    expect(state!.createItemOpen).toBe(true)
    expect(state!.newNotes).toBe('  备注\n')
    expect(state!.importPack).toEqual(pack)
    expect(state!.creatingItem).toBe(false)
    expect(mocks.createItem.mock.calls[0][1]).toMatchObject({
      expected_answer: '',
      notes: '  备注\n',
      retrieval_snapshot: pack,
    })
    expect(state!.createItemError).toContain('保存失败')
  })

  it('does not download a retired suite export', async () => {
    const request = deferred<{ exported_at: string }>()
    mocks.exportSuite.mockReturnValue(request.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    let pending!: Promise<void>
    act(() => {
      pending = state!.handleExportSuite()
    })
    act(() => state!.setSelectedSuiteId('suite-b'))
    await act(async () => {
      request.resolve({ exported_at: '2026-11-16T00:00:00Z' })
      await pending
    })
    expect(mocks.downloadBlob).not.toHaveBeenCalled()
    expect(mocks.toast.success).not.toHaveBeenCalled()
    expect(state!.exportingSuite).toBe(false)
  })

  it('retries only reads after synchronization succeeded but refreshing failed', async () => {
    mocks.syncSuite.mockResolvedValue({ created: 1, updated: 0, skipped: 0, errors: [] })
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    mocks.listItems.mockRejectedValueOnce(new Error('列表读取失败'))
    await act(async () => {
      await expect(state!.handleSyncSuite()).rejects.toThrow('只刷新列表')
    })
    expect(state!.syncNeedsRefresh).toBe(true)
    expect(mocks.syncSuite).toHaveBeenCalledTimes(1)
    await act(async () => state!.handleSyncSuite())
    expect(mocks.syncSuite).toHaveBeenCalledTimes(1)
    expect(state!.syncNeedsRefresh).toBe(false)
    expect(state!.itemsError).toBeNull()
  })

  it('does not clear a newer feedback request when an earlier conversion finishes', async () => {
    const request = deferred<ReturnType<typeof item>>()
    mocks.toEvidenceItem.mockReturnValue(request.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.setPendingFeedbackId('old-feedback'))
    let pending!: Promise<void>
    act(() => {
      pending = state!.handleConvertFeedbackToEvidence('old-feedback', undefined, { source: 'chat_feedback_action' })
    })
    act(() => state!.setPendingFeedbackId('new-feedback'))
    await act(async () => {
      request.resolve(item('converted'))
      await pending
    })
    expect(state!.pendingFeedbackId).toBe('new-feedback')
    expect(state!.convertingFeedbackIds.size).toBe(0)
  })

  it('claims each feedback conversion synchronously without blocking other feedback', async () => {
    const firstRequest = deferred<ReturnType<typeof item>>()
    const secondRequest = deferred<ReturnType<typeof item>>()
    mocks.toEvidenceItem.mockImplementation((id) => (id === 'first' ? firstRequest.promise : secondRequest.promise))
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    let operations!: Promise<void>[]
    act(() => {
      operations = [
        state!.handleConvertFeedbackToEvidence('first'),
        state!.handleConvertFeedbackToEvidence('first'),
        state!.handleConvertFeedbackToEvidence('second'),
      ]
    })
    expect(mocks.toEvidenceItem).toHaveBeenCalledTimes(2)
    expect([...state!.convertingFeedbackIds]).toEqual(['first', 'second'])
    await act(async () => {
      firstRequest.resolve(item('first'))
      secondRequest.resolve(item('second'))
      await Promise.all(operations)
    })
  })

  it.each([
    ['handleReviewItem', 'reviewItem', 'reviewed'],
    ['handleApproveItem', 'approveItem', 'approved'],
    ['handleArchiveItem', 'archiveItem', 'archived'],
  ] as const)(
    'keeps a committed %s result when an earlier item refresh arrives later',
    async (handler, api, status) => {
      const original = item('current-item')
      const updated = { ...original, status }
      mocks.listItems.mockResolvedValue({ total: 1, items: [original] })
      mocks[api].mockResolvedValue(updated)
      await act(async () => root.render(<Harness datasetId="dataset-a" />))
      act(() => state!.setSelectedItemId(original.id))
      const earlier = deferred<{ total: number; items: (typeof original)[] }>()
      mocks.listItems.mockReturnValueOnce(earlier.promise).mockResolvedValue({ total: 1, items: [updated] })
      let refresh!: Promise<boolean>
      act(() => {
        refresh = state!.loadItems()
      })
      await act(async () => state![handler](original.id))
      await act(async () => {
        earlier.resolve({ total: 1, items: [original] })
        await refresh
      })
      expect(state!.selectedItem?.status).toBe(status)
      expect(state!.itemsLoading).toBe(false)
    },
  )

  it('keeps item A busy and commits its status after visiting item B in the same suite', async () => {
    const original = item('item-a')
    const other = item('item-b')
    const request = deferred<ReturnType<typeof item>>()
    mocks.listItems.mockResolvedValue({ total: 2, items: [original, other] })
    mocks.reviewItem.mockReturnValue(request.promise)
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.setSelectedItemId(original.id))
    let first!: Promise<void>
    let second!: Promise<void>
    act(() => {
      first = state!.handleReviewItem(original.id)
    })
    act(() => state!.setSelectedItemId(other.id))
    expect(state!.itemAction).toBeNull()
    act(() => state!.setSelectedItemId(original.id))
    act(() => {
      second = state!.handleReviewItem(original.id)
    })
    const calls = mocks.reviewItem.mock.calls.length
    const statusWhilePending = state!.itemAction
    const updated = { ...original, status: 'reviewed' }
    mocks.listItems.mockResolvedValue({ total: 2, items: [updated, other] })
    await act(async () => {
      request.resolve(updated)
      await Promise.all([first, second])
    })
    expect(calls).toBe(1)
    expect(statusWhilePending).toBe('review')
    expect(state!.selectedItem?.status).toBe('reviewed')
  })

  it.each([
    { total_items: 1, details_truncated: true, drift_references: 1, drifted_references: [] },
    { total_items: 0, details_truncated: false, drift_references: 0, drifted_references: [] },
    { total_items: 1, details_truncated: false, drift_references: 1, drifted_references: [] },
  ])('marks uncovered drift references unknown while preserving actual retrieval information (%j)', async (audit) => {
    const target = { ...item('target'), reference_sources: [{ document_id: 'doc', chunk_id: 'chunk', chunk_index: 0 }] }
    mocks.listItems.mockResolvedValue({ total: 1, items: [target] })
    mocks.driftAudit.mockResolvedValue(audit)
    mocks.retrieve.mockResolvedValue({
      citations: [{ document_id: 'doc', chunk_id: 'chunk', retrieval_score: 0 }],
      has_evidence: true,
    })
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.setSelectedItemId(target.id))
    await act(async () => state!.openWhyMissed())
    await act(async () => state!.runWhyMissedRetrieve())
    expect(state!.whyMissedReport?.summary.unknown_references).toBe(1)
    expect(state!.whyMissedReport?.references[0]).toMatchObject({ status: 'unknown', retrieval: { rank: 1, score: 0 } })
    expect(state!.whyMissedDriftError).toContain('待确认')
  })

  it('includes archived items when confirming an archived reference drift audit', async () => {
    const target = {
      ...item('archived-target'),
      status: 'archived',
      reference_sources: [{ document_id: 'doc', chunk_id: 'chunk' }],
    }
    mocks.listItems.mockResolvedValue({ total: 1, items: [target] })
    mocks.driftAudit.mockResolvedValue({
      total_items: 1,
      details_truncated: false,
      drift_references: 0,
      drifted_references: [],
    })
    mocks.retrieve.mockResolvedValue({ citations: [], has_evidence: false })
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.setSelectedItemId(target.id))
    await act(async () => state!.openWhyMissed())
    await act(async () => state!.runWhyMissedRetrieve())
    expect(mocks.driftAudit.mock.calls[0][1].include_archived_items).toBe(true)
    expect(state!.whyMissedReport?.references[0].status).toBe('missing')
    expect(state!.whyMissedReport?.summary.unknown_references).toBe(0)
  })

  it('retains the accepted dashboard and its original filter after another filter fails', async () => {
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => state!.setDashboardOpen(true))
    const accepted = state!.dashboardSnapshot
    mocks.dashboard.mockRejectedValueOnce(new Error('统计读取失败'))
    await act(async () => state!.setDashboardIncludeArchived(true))
    expect(state!.dashboardIncludeArchived).toBe(true)
    expect(state!.dashboardSnapshot).toBe(accepted)
    expect(state!.dashboardSnapshot?.includeArchived).toBe(false)
    expect(state!.dashboardError).toContain('统计读取失败')
    await act(async () => state!.loadDashboard())
    expect(state!.dashboardSnapshot?.includeArchived).toBe(true)
    expect(state!.dashboardError).toBeNull()
  })

  it('retains accepted hardcase conditions after a new candidate query fails', async () => {
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => state!.setHardcaseOpen(true))
    const accepted = state!.hardcaseSnapshot
    mocks.hardcases.mockRejectedValueOnce(new Error('候选读取失败'))
    await act(async () => state!.setHardcaseIncludeExisting(true))
    expect(state!.hardcaseSnapshot).toBe(accepted)
    expect(state!.hardcaseSnapshot?.includeExisting).toBe(false)
    expect(state!.hardcaseError).toContain('候选读取失败')
    await act(async () => state!.loadHardcases())
    expect(state!.hardcaseSnapshot?.includeExisting).toBe(true)
  })

  it('keeps accepted statistics when a successful HTTP response has invalid consumed fields', async () => {
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    await act(async () => state!.setDashboardOpen(true))
    const accepted = state!.dashboardSnapshot
    const invalid = dashboardFixture()
    mocks.dashboard.mockResolvedValueOnce({
      ...invalid,
      throughput: { ...invalid.throughput, last_window: { created: false, reviewed: 0, approved: 0 } },
    })
    await act(async () => state!.loadDashboard())
    expect(state!.dashboardSnapshot).toBe(accepted)
    expect(state!.dashboardError).toContain('created')
    expect(state!.dashboardLoading).toBe(false)
  })
  it('leaves a first reference diagnosis unconfirmed when drift identity is malformed', async () => {
    const target = { ...item('target'), reference_sources: [{ document_id: 'doc', chunk_id: 'chunk' }] }
    mocks.listItems.mockResolvedValue({ total: 1, items: [target] })
    mocks.driftAudit.mockResolvedValue({
      total_items: 1,
      details_truncated: false,
      drift_references: 1,
      drifted_references: [
        { item_id: 'target', document_id: 'doc', chunk_id: 'chunk', reason: 'chunk_index_mismatch', expected: {} },
      ],
    })
    mocks.retrieve.mockResolvedValue({
      citations: [{ document_id: 'doc', chunk_id: 'chunk', retrieval_score: 0 }],
      has_evidence: true,
    })
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    act(() => state!.setSelectedItemId(target.id))
    await act(async () => state!.openWhyMissed())
    await act(async () => state!.runWhyMissedRetrieve())
    expect(state!.whyMissedDriftError).toContain('expected')
    expect(state!.whyMissedReport?.summary.unknown_references).toBe(1)
  })
  it('keeps conversion failures with their feedback until the next attempt', async () => {
    await act(async () => root.render(<Harness datasetId="dataset-a" />))
    mocks.toEvidenceItem.mockRejectedValueOnce(new Error('反馈尚未保存'))
    await act(async () => state!.handleConvertFeedbackToEvidence('feedback'))
    expect(state!.feedbackErrors.get('feedback')).toContain('反馈尚未保存')
    expect(state!.convertingFeedbackIds.has('feedback')).toBe(false)
    mocks.toEvidenceItem.mockResolvedValueOnce(item('converted'))
    await act(async () => state!.handleConvertFeedbackToEvidence('feedback'))
    expect(state!.feedbackErrors.has('feedback')).toBe(false)
  })
})
