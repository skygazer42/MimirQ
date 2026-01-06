import { GraphData, GraphNode, GraphLink } from '@/lib/graph-parser'
import { API_V1_BASE_URL } from '@/lib/env'
import { getAuthHeaders } from '@/lib/auth-headers'

// Mock delay to simulate network request
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

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

    return JSON.parse(JSON.stringify({ nodes, links }))
  }

  /**
   * Fetch the initial graph data (e.g., top entities or root nodes)
   */
  static async fetchInitialGraph(options: { preferMock?: boolean } = {}): Promise<GraphData> {
    if (options.preferMock) {
      await delay(200)
      return GraphService.getMockGraph()
    }

    // Try KG live graph first; fallback to mock data (so the page remains usable when KG is disabled).
    try {
      const res = await fetch(`${API_V1_BASE_URL}/kg/graph`, {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
        },
      })
      if (res.ok) {
        const data = (await res.json()) as GraphData
        const nodes = Array.isArray(data?.nodes) ? data.nodes : []
        const links = Array.isArray(data?.links) ? data.links : []
        if (nodes.length > 0) {
          return JSON.parse(JSON.stringify({ nodes, links }))
        }
      }
    } catch {
      // ignore and fallback
    }

    await delay(200) // keep a tiny delay for UI consistency
    return GraphService.getMockGraph()
  }

  /**
   * Fetch neighbors for a specific node (Lazy Loading)
   */
  static async expandNode(nodeId: string): Promise<GraphData> {
    // Prefer backend KG expansion for UUID-like nodes; otherwise fallback to mock expansion
    if (UUID_RE.test(String(nodeId || '').trim())) {
      try {
        const res = await fetch(
          `${API_V1_BASE_URL}/kg/graph/expand?node_id=${encodeURIComponent(nodeId)}&max_events=50&max_entities=400&max_links=5000`,
          {
            method: 'GET',
            headers: {
              ...getAuthHeaders(),
            },
          }
        )
        if (res.ok) {
          const data = (await res.json()) as GraphData
          if (data?.nodes && data?.links) {
            return JSON.parse(JSON.stringify(data))
          }
        }
      } catch {
        // ignore and fallback
      }
    }

    await delay(600)

    // Generate pseudo-random neighbors based on ID to be deterministic but look dynamic
    const count = Math.floor(Math.random() * 3) + 2 // 2 to 4 new neighbors
    const nodes: GraphNode[] = []
    const links: GraphLink[] = []

    for (let i = 0; i < count; i++) {
      const newId = `${nodeId}-${Date.now()}-${i}`
      const labels = ['Concept', 'Tool', 'Person', 'Paper', 'Organization']
      const labelType = labels[Math.floor(Math.random() * labels.length)]
      
      nodes.push({
        id: newId,
        label: `${labelType} ${Math.floor(Math.random() * 100)}`,
        group: Math.floor(Math.random() * 5),
        val: 5
      })

      links.push({
        source: nodeId,
        target: newId,
        label: 'related_to'
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
      const res = await fetch(
        `${API_V1_BASE_URL}/kg/graph/search?q=${encodeURIComponent(q)}&kind=all&limit=20`,
        {
          method: 'GET',
          headers: {
            ...getAuthHeaders(),
          },
        }
      )
      if (!res.ok) return []
      const nodes = (await res.json()) as GraphNode[]
      return Array.isArray(nodes) ? nodes : []
    } catch {
      return []
    }
  }
}
