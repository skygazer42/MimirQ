import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GraphData } from '@/lib/graph-types'

const api = vi.hoisted(() => ({
  details: vi.fn(),
  getGraph: vi.fn(),
  expandGraph: vi.fn(),
}))

vi.mock('@/lib/api/meta', () => ({ metaApi: { details: api.details } }))
vi.mock('@/lib/api/graph', () => ({
  kgApi: {
    getGraph: api.getGraph,
    expandGraph: api.expandGraph,
  },
}))

import { expandGraphNode, fetchInitialGraph } from './graph-service'

const nodeId = '123e4567-e89b-42d3-a456-426614174000'
const graph: GraphData = {
  nodes: [{ id: nodeId, label: 'Knowledge', meta: { aliases: ['Ragvia'] } }],
  links: [],
}

beforeEach(() => {
  vi.resetAllMocks()
  api.details.mockResolvedValue({ features: { kg_enabled: true } })
  api.getGraph.mockResolvedValue(structuredClone(graph))
  api.expandGraph.mockResolvedValue(structuredClone(graph))
})

describe('graph request failures', () => {
  it('keeps initial graph failures visible to the caller', async () => {
    const error = new Error('Graph service unavailable')
    api.getGraph.mockRejectedValue(error)

    await expect(fetchInitialGraph()).rejects.toBe(error)
  })

  it('keeps expansion failures visible to the caller', async () => {
    const error = new Error('Expansion failed')
    api.expandGraph.mockRejectedValue(error)

    await expect(expandGraphNode(nodeId)).rejects.toBe(error)
  })

  it('does not treat an unavailable feature probe as enabled', async () => {
    const error = new Error('Metadata service unavailable')
    api.details.mockRejectedValue(error)

    await expect(fetchInitialGraph()).rejects.toBe(error)
    expect(api.getGraph).not.toHaveBeenCalled()
  })

  it('lets the graph endpoint authorize users who cannot read admin metadata', async () => {
    const error = new AxiosError('Forbidden')
    error.response = { status: 403 } as AxiosError['response']
    api.details.mockRejectedValue(error)

    await expect(fetchInitialGraph()).resolves.toEqual(graph)
    expect(api.getGraph).toHaveBeenCalledOnce()
  })
})

describe('graph result boundaries', () => {
  it('returns an independent graph so renderer mutations cannot change the API result', async () => {
    const source = structuredClone(graph)
    api.getGraph.mockResolvedValue(source)

    const result = await fetchInitialGraph()
    result.nodes[0].label = 'Changed by renderer'
    expect(source).toEqual(graph)
  })

  it('returns a genuine empty response as an empty graph', async () => {
    api.getGraph.mockResolvedValue({ nodes: [], links: [] })

    await expect(fetchInitialGraph()).resolves.toEqual({ nodes: [], links: [] })
  })

  it('skips graph requests when the feature is explicitly disabled', async () => {
    api.details.mockResolvedValue({ features: { kg_enabled: false } })

    await expect(fetchInitialGraph()).resolves.toEqual({ nodes: [], links: [] })
    await expect(expandGraphNode(nodeId)).resolves.toEqual({ nodes: [], links: [] })
    expect(api.getGraph).not.toHaveBeenCalled()
    expect(api.expandGraph).not.toHaveBeenCalled()
  })

  it('keeps imported node IDs local', async () => {
    await expect(expandGraphNode('local-node')).resolves.toEqual({ nodes: [], links: [] })
    expect(api.details).not.toHaveBeenCalled()
  })
})
