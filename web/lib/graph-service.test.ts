import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GraphData } from '@/lib/graph-parser'

const api = vi.hoisted(() => ({
  details: vi.fn(),
  getGraph: vi.fn(),
  expandGraph: vi.fn(),
  searchGraphNodes: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  metaApi: { details: api.details },
  kgApi: {
    getGraph: api.getGraph,
    expandGraph: api.expandGraph,
    searchGraphNodes: api.searchGraphNodes,
  },
}))

import { GraphService } from './graph-service'

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

    await expect(GraphService.fetchInitialGraph()).rejects.toBe(error)
  })

  it('keeps expansion failures visible to the caller', async () => {
    const error = new Error('Expansion failed')
    api.expandGraph.mockRejectedValue(error)

    await expect(GraphService.expandNode(nodeId)).rejects.toBe(error)
  })

  it('keeps search failures distinct from no matches', async () => {
    const error = new Error('Search failed')
    api.searchGraphNodes.mockRejectedValue(error)

    await expect(GraphService.searchNodes('knowledge')).rejects.toBe(error)
  })

  it('does not treat an unavailable feature probe as enabled', async () => {
    const error = new Error('Metadata service unavailable')
    api.details.mockRejectedValue(error)

    await expect(GraphService.fetchInitialGraph()).rejects.toBe(error)
    expect(api.getGraph).not.toHaveBeenCalled()
  })

  it('lets the graph endpoint authorize users who cannot read admin metadata', async () => {
    const error = new AxiosError('Forbidden')
    error.response = { status: 403 } as AxiosError['response']
    api.details.mockRejectedValue(error)

    await expect(GraphService.fetchInitialGraph()).resolves.toEqual(graph)
    expect(api.getGraph).toHaveBeenCalledOnce()
  })
})

describe('graph result boundaries', () => {
  it('returns an independent graph so renderer mutations cannot change the API result', async () => {
    const source = structuredClone(graph)
    api.getGraph.mockResolvedValue(source)

    const result = await GraphService.fetchInitialGraph()
    result.nodes[0].label = 'Changed by renderer'
    expect(source).toEqual(graph)
  })

  it('returns a genuine empty response as an empty graph', async () => {
    api.getGraph.mockResolvedValue({ nodes: [], links: [] })

    await expect(GraphService.fetchInitialGraph()).resolves.toEqual({ nodes: [], links: [] })
  })

  it('skips graph requests when the feature is explicitly disabled', async () => {
    api.details.mockResolvedValue({ features: { kg_enabled: false } })

    await expect(GraphService.fetchInitialGraph()).resolves.toEqual({ nodes: [], links: [] })
    await expect(GraphService.expandNode(nodeId)).resolves.toEqual({ nodes: [], links: [] })
    expect(api.getGraph).not.toHaveBeenCalled()
    expect(api.expandGraph).not.toHaveBeenCalled()
  })

  it('keeps imported node IDs and blank search queries local', async () => {
    await expect(GraphService.expandNode('local-node')).resolves.toEqual({ nodes: [], links: [] })
    await expect(GraphService.searchNodes('   ')).resolves.toEqual([])
    expect(api.details).not.toHaveBeenCalled()
    expect(api.searchGraphNodes).not.toHaveBeenCalled()
  })
})
