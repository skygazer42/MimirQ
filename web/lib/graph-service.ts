import { GraphData, GraphNode, GraphLink } from '@/lib/graph-parser'
import { kgApi } from '@/lib/api'

// Mock delay to simulate network request
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function cloneGraphData(data: GraphData): GraphData {
  return structuredClone(data)
}

function hashString32(value: string): number {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    const codePoint = value.codePointAt(index) ?? 0
    hash ^= codePoint
    hash = Math.imul(hash, 16777619)
    if (codePoint > 0xffff) {
      index += 1
    }
  }
  return hash >>> 0
}

function seededIndex(seed: string, size: number): number {
  return size > 0 ? hashString32(seed) % size : 0
}

export class GraphService {
  static getMockGraph(): GraphData {
    const nodes: GraphNode[] = [
      { id: '1', label: 'Artificial Intelligence', group: 1, val: 20 },
      { id: '2', label: 'Machine Learning', group: 1, val: 15 },
      { id: '3', label: 'Deep Learning', group: 1, val: 10 },
      { id: '4', label: 'NLP', group: 2, val: 12 },
      { id: '5', label: 'Computer Vision', group: 3, val: 12 },
      { id: '6', label: 'Reinforcement Learning', group: 1, val: 10 },
    ]

    const links: GraphLink[] = [
      { source: '1', target: '2', label: 'includes' },
      { source: '2', target: '3', label: 'includes' },
      { source: '1', target: '4', label: 'application' },
      { source: '1', target: '5', label: 'application' },
      { source: '2', target: '6', label: 'includes' },
    ]

    return cloneGraphData({ nodes, links })
  }

  /**
   * Fetch the initial graph data (e.g., top entities or root nodes)
   */
  static async fetchInitialGraph(
    options: {
      preferMock?: boolean
      includeEntityLinks?: boolean
      includeRelationLinks?: boolean
      minSharedEvents?: number
      maxEntityLinks?: number
      documentIds?: string[]
      pipelineHash?: string
    } = {}
  ): Promise<GraphData> {
    if (options.preferMock) {
      await delay(200)
      return GraphService.getMockGraph()
    }

    // Try KG live graph first; when no KG data is available, return an empty graph so the
    // UI can clearly communicate "no result in current scope" instead of showing demo data.
    try {
      const data = await kgApi.getGraph({
        document_ids: options.documentIds,
        pipeline_hash: options.pipelineHash,
        include_entity_links: options.includeEntityLinks,
        include_relation_links: options.includeRelationLinks,
        min_shared_events: options.minSharedEvents,
        max_entity_links: options.maxEntityLinks,
      })
      const nodes = Array.isArray(data?.nodes) ? data.nodes : []
      const links = Array.isArray(data?.links) ? data.links : []
      if (nodes.length > 0) {
        return cloneGraphData({ nodes, links })
      }
    } catch {
      // ignore and return empty graph below
    }

    await delay(200) // keep a tiny delay for UI consistency
    return { nodes: [], links: [] }
  }

  /**
   * Fetch neighbors for a specific node (Lazy Loading)
   */
  static async expandNode(
    nodeId: string,
    options?: {
      includeEntityLinks?: boolean
      includeRelationLinks?: boolean
      minSharedEvents?: number
      maxEntityLinks?: number
      documentIds?: string[]
      pipelineHash?: string
    }
  ): Promise<GraphData> {
    // Prefer backend KG expansion for UUID-like nodes; otherwise fallback to mock expansion
    if (UUID_RE.test(String(nodeId || '').trim())) {
      try {
        const data = await kgApi.expandGraph({
          node_id: nodeId,
          document_ids: options?.documentIds,
          pipeline_hash: options?.pipelineHash,
          max_events: 50,
          max_entities: 400,
          max_links: 5000,
          include_entity_links: options?.includeEntityLinks,
          include_relation_links: options?.includeRelationLinks,
          min_shared_events: options?.minSharedEvents,
          max_entity_links: options?.maxEntityLinks,
        })
        if (data?.nodes && data?.links) {
          return cloneGraphData({ nodes: data.nodes, links: data.links })
        }
      } catch {
        // ignore and fallback
      }
    }

    await delay(600)

    // Generate deterministic mock neighbors from the node id so expansion remains stable.
    const count = seededIndex(`${nodeId}:count`, 3) + 2 // 2 to 4 new neighbors
    const nodes: GraphNode[] = []
    const links: GraphLink[] = []
    const labels = ['Concept', 'Tool', 'Person', 'Paper', 'Organization']

    for (let i = 0; i < count; i++) {
      const seedBase = `${nodeId}:${i}`
      const labelType = labels[seededIndex(`${seedBase}:label-type`, labels.length)]
      const labelNumber = seededIndex(`${seedBase}:label-number`, 100)
      const group = seededIndex(`${seedBase}:group`, 5)
      const newId = `${nodeId}-${Date.now().toString(36)}-${hashString32(seedBase).toString(36)}`

      nodes.push({
        id: newId,
        label: `${labelType} ${labelNumber}`,
        group,
        val: 5,
      })

      links.push({
        source: nodeId,
        target: newId,
        label: 'related_to',
      })
    }

    return { nodes, links }
  }

  /**
   * Search for nodes by query
   */
  static async searchNodes(query: string): Promise<GraphNode[]> {
    const q = (query || '').trim()
    if (!q) return []

    try {
      const nodes = await kgApi.searchGraphNodes({ q, kind: 'all', limit: 20 })
      return Array.isArray(nodes) ? (nodes as GraphNode[]) : []
    } catch {
      return []
    }
  }
}
