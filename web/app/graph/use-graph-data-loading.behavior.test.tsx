// @vitest-environment happy-dom

import React, { act, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { GraphData } from '@/lib/graph-types'
import type { KGManualImportRequest, RagTrace } from '@/types'

const controlled = vi.hoisted(() => ({
  kg: {
    getGraph: vi.fn(),
    getStats: vi.fn(),
    previewManualImport: vi.fn(),
    importManualGraph: vi.fn(),
  },
  meta: { details: vi.fn() },
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
  reportClientError: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ kgApi: controlled.kg, metaApi: controlled.meta }))
vi.mock('@/lib/api/meta', () => ({ metaApi: controlled.meta }))
vi.mock('@/lib/api/graph', () => ({ kgApi: controlled.kg }))
vi.mock('sonner', () => ({ toast: controlled.toast }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: controlled.reportClientError }))

import type { GraphTraceReplay } from './graph-page-utils'
import { useGraphDataLoading } from './use-graph-data-loading'

const liveGraph: GraphData = { nodes: [{ id: 'live-node', label: 'Live graph' }], links: [] }
const importStats = { entities: 1, relations: 1, events: 1, chunks: 1, aliases: 0, warnings: 0 }
const noop = () => {}

type SurfaceState = {
  nodes: string[]
  fileName: string | null
  dataSource: 'live' | 'file'
  viewMode: '2d' | '3d'
  isLoading: boolean
  traceId: string | null
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((fulfill, fail) => {
    resolve = fulfill
    reject = fail
  })
  return { promise, resolve, reject }
}

function traceText(requestId: string): string {
  return JSON.stringify({
    schema_version: 1,
    ts_ms: 1,
    request_id: requestId,
    retrieval: {},
    rerank: { enabled: false },
    citations: [],
    citations_count: 0,
    steps: [{ key: 'retrieve', label: 'Retrieve' }],
  } satisfies RagTrace)
}

function LoadingSurface() {
  const [scopeId, setScopeId] = useState('')
  const scope = useMemo(
    () => ({
      hasScope: Boolean(scopeId),
      directDocIds: scopeId ? [scopeId] : [],
      datasetId: null,
      pipelineHash: null,
      docLimit: 200,
    }),
    [scopeId],
  )
  const scopedDocumentIds = useMemo(() => (scopeId ? [scopeId] : null), [scopeId])
  const scopeParams = useMemo(() => (scopeId ? { document_ids: [scopeId] } : null), [scopeId])
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] })
  const [fileName, setFileName] = useState<string | null>(null)
  const [dataSource, setDataSource] = useState<'live' | 'file'>('live')
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('3d')
  const [isLoading, setIsLoading] = useState(false)
  const [traceReplay, setTraceReplay] = useState<GraphTraceReplay | null>(null)
  const traceFileInputRef = useRef<HTMLInputElement>(null)
  const manualKgFileInputRef = useRef<HTMLInputElement>(null)
  const loading = useGraphDataLoading({
    scope,
    scopedDocumentIds,
    scopedDatasetDocIdsLoading: false,
    refetchScopedDocuments: vi.fn(),
    scopeParams,
    includeEntityLinks: true,
    includeRelationLinks: false,
    minSharedEvents: 2,
    maxEntityLinks: 500,
    setGraphData,
    setFileName,
    setDataSource,
    setTraceReplay,
    setIsLoading,
    setViewMode,
    traceFileInputRef,
    manualKgFileInputRef,
    resetGraphSurface: noop,
  })

  return (
    <>
      <button type="button" onClick={loading.triggerTraceUpload}>
        Trace
      </button>
      <input ref={traceFileInputRef} aria-label="Trace file" type="file" onChange={loading.handleTraceFileUpload} />
      <button type="button" disabled={isLoading} onClick={loading.triggerManualKgUpload}>
        Import KG
      </button>
      <input ref={manualKgFileInputRef} aria-label="KG file" type="file" onChange={loading.handleManualKgFileUpload} />
      <button type="button" onClick={() => setScopeId('new-document')}>
        Change scope
      </button>
      <output>
        {JSON.stringify({
          nodes: graphData.nodes.map((node) => node.id),
          fileName,
          dataSource,
          viewMode,
          isLoading,
          traceId: traceReplay?.request_id ?? null,
        } satisfies SurfaceState)}
      </output>
    </>
  )
}

describe('graph data loading through React DOM file inputs', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    vi.resetAllMocks()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Unexpected HTTP in controlled test')))
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    controlled.meta.details.mockResolvedValue({ features: { kg_enabled: true } })
    controlled.kg.getGraph.mockResolvedValue(liveGraph)
    controlled.kg.previewManualImport.mockResolvedValue({ valid: true, issues: [], stats: importStats })
    controlled.kg.importManualGraph.mockResolvedValue({ valid: true, issues: [], stats: importStats })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  async function mount() {
    await act(async () => root.render(<LoadingSurface />))
  }

  it('reports a current live graph failure without replacing it with an empty success', async () => {
    controlled.kg.getGraph.mockRejectedValueOnce(new Error('Graph unavailable'))
    await mount()
    expect(controlled.toast.error).toHaveBeenCalledWith(expect.stringContaining('Graph unavailable'))
    expect(surface().isLoading).toBe(false)
  })

  it('discards the old graph when another scope fails to load', async () => {
    await mount()
    expect(surface().nodes).toEqual(['live-node'])
    controlled.kg.getGraph.mockRejectedValueOnce(new Error('New scope unavailable'))
    await changeScope()
    expect(surface().nodes).toEqual([])
  })

  it('does not report a request failure after the graph page unmounts', async () => {
    const request = deferred<GraphData>()
    controlled.kg.getGraph.mockReturnValueOnce(request.promise)
    await mount()
    act(() => root.unmount())
    await act(async () => request.reject(new Error('Late graph failure')))
    expect(controlled.toast.error).not.toHaveBeenCalled()
  })

  it('finishes the active load after StrictMode effect replay', async () => {
    await act(async () =>
      root.render(
        <React.StrictMode>
          <LoadingSurface />
        </React.StrictMode>,
      ),
    )
    expect(surface().nodes).toEqual(['live-node'])
    expect(surface().isLoading).toBe(false)
  })

  function surface(): SurfaceState {
    return JSON.parse(container.querySelector('output')!.textContent!) as SurfaceState
  }

  async function selectFile(label: string, name: string, text: string | Promise<string>) {
    const input = container.querySelector(`input[aria-label="${label}"]`) as HTMLInputElement
    const file = new File([], name)
    Object.defineProperty(file, 'text', { value: () => Promise.resolve(text) })
    Object.defineProperty(input, 'files', { configurable: true, value: [file] })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    return input
  }

  async function changeScope() {
    const button = Array.from(container.querySelectorAll('button')).find(
      (element) => element.textContent === 'Change scope',
    )!
    await act(async () => button.click())
  }

  it('keeps an imported Trace when an earlier live graph finishes later', async () => {
    const graph = deferred<GraphData>()
    controlled.kg.getGraph.mockReturnValueOnce(graph.promise)
    await mount()
    expect(surface().isLoading).toBe(true)
    expect(
      Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Trace')?.disabled,
    ).toBe(false)

    await selectFile('Trace file', 'trace.json', traceText('current-trace'))
    const imported = surface()
    expect(imported).toMatchObject({ dataSource: 'file', viewMode: '2d', traceId: 'current-trace', isLoading: false })
    await act(async () => graph.resolve(liveGraph))

    expect(surface()).toEqual(imported)
    expect(controlled.kg.getStats).not.toHaveBeenCalled()
  })

  it('keeps the selected graph when an earlier import completes', async () => {
    const imported = deferred<{ valid: boolean; issues: []; stats: typeof importStats }>()
    controlled.kg.importManualGraph.mockReturnValueOnce(imported.promise)
    await mount()
    await selectFile('KG file', 'earlier.json', JSON.stringify([{ name: 'Alice', type: 'person' }]))
    expect(controlled.kg.importManualGraph).toHaveBeenCalledOnce()
    await changeScope()
    const selected = surface()
    await act(async () => imported.resolve({ valid: true, issues: [], stats: importStats }))

    expect(surface()).toEqual(selected)
    expect(controlled.kg.getGraph).toHaveBeenCalledTimes(2)
  })

  it('keeps the latest Trace when file reads complete in reverse order', async () => {
    await mount()
    const older = deferred<string>()
    await selectFile('Trace file', 'older.json', older.promise)
    await selectFile('Trace file', 'newer.json', traceText('newer'))
    const current = surface()
    await act(async () => older.resolve(traceText('older')))

    expect(surface()).toEqual(current)
  })

  it('keeps loading while the current Trace is still being read', async () => {
    await mount()
    const older = deferred<string>()
    const current = deferred<string>()
    await selectFile('Trace file', 'older.json', older.promise)
    await selectFile('Trace file', 'current.json', current.promise)
    await act(async () => older.resolve(traceText('older')))
    expect(surface().isLoading).toBe(true)
    await act(async () => current.resolve(traceText('current')))
    expect(surface()).toMatchObject({ isLoading: false, traceId: 'current' })
  })

  it('ignores a stale invalid Trace without clearing the newer replay or showing its error', async () => {
    await mount()
    const older = deferred<string>()
    await selectFile('Trace file', 'older.json', older.promise)
    await selectFile('Trace file', 'current.json', traceText('current'))
    await act(async () => older.resolve('invalid JSON'))

    expect(surface().traceId).toBe('current')
    expect(controlled.toast.error).not.toHaveBeenCalled()
    expect(controlled.reportClientError).not.toHaveBeenCalled()
  })

  it('keeps a newer scope load when an older Trace read finishes afterward', async () => {
    await mount()
    const older = deferred<string>()
    await selectFile('Trace file', 'older.json', older.promise)
    await changeScope()
    expect(controlled.kg.getGraph).toHaveBeenLastCalledWith(
      expect.objectContaining({ document_ids: ['new-document'] }),
      { signal: expect.any(AbortSignal) },
    )
    const current = surface()
    await act(async () => older.resolve(traceText('older')))

    expect(surface()).toEqual(current)
    expect(surface()).toMatchObject({ dataSource: 'live', viewMode: '2d', traceId: null })
  })

  it('retains the existing latest-live-load ownership control', async () => {
    const older = deferred<GraphData>()
    controlled.kg.getGraph.mockReturnValueOnce(older.promise)
    await mount()
    await changeScope()
    const current = surface()
    await act(async () => older.resolve({ nodes: [{ id: 'older-live', label: 'Older' }], links: [] }))
    expect(surface()).toEqual(current)
  })

  it('imports typed rows from a multi-line JSONL file through preview and commit', async () => {
    await mount()
    const entity = { kind: 'entity', key: 'alice', name: 'Alice', type: 'person' }
    const relation = { kind: 'relation', subject: 'alice', predicate: 'knows', object: 'bob' }
    const input = await selectFile(
      'KG file',
      'people.JSONL',
      `${JSON.stringify(entity)}\n${JSON.stringify(relation)}\n`,
    )
    const expected = { name: 'people', entities: [entity], relations: [relation] }

    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(expected, {
      signal: expect.any(AbortSignal),
    })
    expect(controlled.kg.importManualGraph).toHaveBeenCalledExactlyOnceWith(expected)
    expect(controlled.kg.getGraph).toHaveBeenCalledTimes(2)
    expect(input.value).toBe('')
    expect(surface().isLoading).toBe(false)
  })

  it('preserves complete JSON request options and backend validation', async () => {
    await mount()
    const payload: KGManualImportRequest = {
      name: 'Named import',
      import_id: 'import-id',
      dataset_id: 'dataset-id',
      dataset_name: 'Dataset',
      pipeline_hash: 'pipeline',
      replace_existing: false,
      upsert_entities: false,
      allow_label_truncation: true,
      index_vectors: false,
      entities: [{ name: 'Alice', type: 'person' }],
      relations: [],
    }
    await selectFile('KG file', 'request.json', JSON.stringify(payload))

    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(payload, {
      signal: expect.any(AbortSignal),
    })
    expect(controlled.kg.importManualGraph).toHaveBeenCalledExactlyOnceWith(payload)
    expect(controlled.toast.error).not.toHaveBeenCalled()
  })

  it('continues accepting a JSON array in a JSONL-named file', async () => {
    await mount()
    const entity = { name: 'Alice', type: 'person' }
    await selectFile('KG file', 'array.jsonl', JSON.stringify([entity]))
    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(
      { name: 'array', entities: [entity], relations: [] },
      { signal: expect.any(AbortSignal) },
    )
  })

  it('does not commit when the backend rejects the preview', async () => {
    await mount()
    controlled.kg.previewManualImport.mockResolvedValue({
      valid: false,
      issues: [{ level: 'error', message: 'Invalid reference' }],
    })
    await selectFile('KG file', 'rejected.json', JSON.stringify([{ name: 'Alice', type: 'person' }]))
    expect(controlled.kg.importManualGraph).not.toHaveBeenCalled()
    expect(controlled.toast.error).toHaveBeenCalledWith('KG 导入预检失败：Invalid reference')
    expect(surface().isLoading).toBe(false)
  })

  it.each([
    ['broken.jsonl', '{"name":"Alice","type":"person"}\n{bad JSON}'],
    ['unknown.jsonl', '{"name":"Alice","type":"person"}\n{"kind":"unrecognized"}'],
    ['bad-bundle.json', '{"entities":[{"name":"Alice","type":"person"}],"relations":{}}'],
  ])('rejects a malformed import %s before either backend action', async (fileName, text) => {
    await mount()
    await selectFile('KG file', fileName, text)
    expect(controlled.kg.previewManualImport).not.toHaveBeenCalled()
    expect(controlled.kg.importManualGraph).not.toHaveBeenCalled()
    expect(controlled.toast.error).toHaveBeenCalledOnce()
    expect(surface().isLoading).toBe(false)
  })

  it('imports an entity from a single-line JSONL file', async () => {
    await mount()
    const entity = { kind: 'entity', key: 'alice', name: 'Alice', type: 'person' }
    await selectFile('KG file', 'single-entity.jsonl', JSON.stringify(entity) + '\n')
    const expected = { name: 'single-entity', entities: [entity], relations: [] }
    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(expected, {
      signal: expect.any(AbortSignal),
    })
    expect(controlled.kg.importManualGraph).toHaveBeenCalledExactlyOnceWith(expected)
  })

  it('imports a relation from a single-line JSONL file', async () => {
    await mount()
    const relation = { kind: 'relation', subject: 'alice', predicate: 'knows', object: 'bob' }
    await selectFile('KG file', 'single-relation.JSONL', JSON.stringify(relation) + '\n')
    const expected = { name: 'single-relation', entities: [], relations: [relation] }
    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(expected, {
      signal: expect.any(AbortSignal),
    })
    expect(controlled.kg.importManualGraph).toHaveBeenCalledExactlyOnceWith(expected)
  })

  it('preserves complete JSON bundle options in a JSONL-named file', async () => {
    await mount()
    const payload: KGManualImportRequest = {
      name: 'Explicit bundle',
      import_id: 'import-id',
      dataset_id: 'dataset-id',
      dataset_name: 'Dataset',
      pipeline_hash: 'pipeline',
      replace_existing: false,
      upsert_entities: false,
      allow_label_truncation: true,
      index_vectors: false,
      entities: [{ name: 'Alice', type: 'person' }],
      relations: [],
    }
    await selectFile('KG file', 'bundle.jsonl', JSON.stringify(payload))
    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(payload, {
      signal: expect.any(AbortSignal),
    })
    expect(controlled.kg.importManualGraph).toHaveBeenCalledExactlyOnceWith(payload)
  })
})
