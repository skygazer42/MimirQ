// @vitest-environment happy-dom

import React, { act, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { GraphData } from '@/lib/graph-parser'
import type {
  KGEntityDetailResponse,
  KGEventDetailResponse,
  KGManualImportRequest,
  KGStatsResponse,
  RagTrace,
} from '@/types'

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
vi.mock('@/lib/api/graph', () => ({ kgApi: controlled.kg }))
vi.mock('sonner', () => ({ toast: controlled.toast }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: controlled.reportClientError }))

import type { GraphNodeLike } from './graph-page-utils'
import { useGraphDataLoading } from './use-graph-data-loading'

const liveGraph: GraphData = { nodes: [{ id: 'live-node', label: 'Live graph' }], links: [] }
const liveStats: KGStatsResponse = { events: 2, entities: 3, links: 4, entity_types: [] }
const importStats = { entities: 1, relations: 1, events: 1, chunks: 1, aliases: 0, warnings: 0 }
const noop = () => {}

type SurfaceState = {
  nodes: string[]
  fileName: string | null
  dataSource: 'live' | 'file'
  viewMode: '2d' | '3d'
  isLoading: boolean
  traceId: string | null
  stats: KGStatsResponse | null
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((fulfill) => {
    resolve = fulfill
  })
  return { promise, resolve }
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
  const [traceReplay, setTraceReplay] = useState<RagTrace | null>(null)
  const [kgStats, setKgStats] = useState<KGStatsResponse | null>(null)
  const [, setKgNodeDetail] = useState<KGEntityDetailResponse | KGEventDetailResponse | null>(null)
  const [, setIsDetailOpen] = useState(false)
  const [, setSelectedNode] = useState<GraphNodeLike | null>(null)
  const traceFileInputRef = useRef<HTMLInputElement>(null)
  const manualKgFileInputRef = useRef<HTMLInputElement>(null)
  const loading = useGraphDataLoading({
    scope,
    scopedDocumentIds,
    scopedDatasetDocIdsLoading: false,
    scopeParams,
    includeEntityLinks: true,
    includeRelationLinks: false,
    minSharedEvents: 2,
    maxEntityLinks: 500,
    setGraphData,
    setFileName,
    setDataSource,
    setTraceReplay,
    setKgStats,
    setKgNodeDetail,
    setIsLoading,
    setIsDetailOpen,
    setSelectedNode,
    setViewMode,
    traceFileInputRef,
    manualKgFileInputRef,
    resetPathMode: noop,
    resetConnectMode: noop,
    resetExplainMode: noop,
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
          stats: kgStats,
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
    controlled.kg.getStats.mockResolvedValue(liveStats)
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

  it('discards earlier live stats after a Trace replaces the live graph', async () => {
    const stats = deferred<KGStatsResponse>()
    controlled.kg.getStats.mockReturnValueOnce(stats.promise)
    await mount()
    expect(controlled.kg.getStats).toHaveBeenCalledOnce()
    await selectFile('Trace file', 'trace.json', traceText('stats-owner'))
    await act(async () => stats.resolve(liveStats))

    expect(surface()).toMatchObject({ dataSource: 'file', traceId: 'stats-owner', stats: null, isLoading: false })
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
    expect(controlled.kg.getGraph).toHaveBeenLastCalledWith(expect.objectContaining({ document_ids: ['new-document'] }))
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

    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(expected)
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

    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(payload)
    expect(controlled.kg.importManualGraph).toHaveBeenCalledExactlyOnceWith(payload)
    expect(controlled.toast.error).not.toHaveBeenCalled()
  })

  it('continues accepting a JSON array in a JSONL-named file', async () => {
    await mount()
    const entity = { name: 'Alice', type: 'person' }
    await selectFile('KG file', 'array.jsonl', JSON.stringify([entity]))
    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith({
      name: 'array',
      entities: [entity],
      relations: [],
    })
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

  it('rejects malformed JSONL before either backend import action', async () => {
    await mount()
    await selectFile('KG file', 'broken.jsonl', '{"name":"Alice","type":"person"}\n{bad JSON}')
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
    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(expected)
    expect(controlled.kg.importManualGraph).toHaveBeenCalledExactlyOnceWith(expected)
  })

  it('imports a relation from a single-line JSONL file', async () => {
    await mount()
    const relation = { kind: 'relation', subject: 'alice', predicate: 'knows', object: 'bob' }
    await selectFile('KG file', 'single-relation.JSONL', JSON.stringify(relation) + '\n')
    const expected = { name: 'single-relation', entities: [], relations: [relation] }
    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(expected)
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
    expect(controlled.kg.previewManualImport).toHaveBeenCalledExactlyOnceWith(payload)
    expect(controlled.kg.importManualGraph).toHaveBeenCalledExactlyOnceWith(payload)
  })
})
