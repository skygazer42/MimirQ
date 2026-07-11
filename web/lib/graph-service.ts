import { GraphData, GraphNode } from '@/lib/graph-parser'
import { kgApi, metaApi } from '@/lib/api'

// Small delay for empty live graph loading so UI transitions remain stable.
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function cloneGraphData(data: GraphData): GraphData {
  return structuredClone(data)
}

async function isKgEnabled(): Promise<boolean> {
  try {
    const meta = await metaApi.details()
    return meta.features?.kg_enabled !== false
  } catch {
    return true
  }
}

export class GraphService {
  /**
   * Fetch the initial graph data (e.g., top entities or root nodes)
   */
  static async fetchInitialGraph(
    options: {
      includeEntityLinks?: boolean
      includeRelationLinks?: boolean
      minSharedEvents?: number
      maxEntityLinks?: number
      documentIds?: string[]
      datasetId?: string
      pipelineHash?: string
    } = {}
  ): Promise<GraphData> {
    if (!(await isKgEnabled())) {
      return { nodes: [], links: [] }
    }

    // Try KG live graph first; when no KG data is available, return an empty graph so the
    // UI can clearly communicate "no result in current scope" instead of showing demo data.
    try {
      const data = await kgApi.getGraph({
        document_ids: options.documentIds,
        dataset_id: options.datasetId,
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
      datasetId?: string
      pipelineHash?: string
    }
  ): Promise<GraphData> {
    // Live graph expansion must only use backend KG data; unsupported ids return an empty expansion.
    if (UUID_RE.test(String(nodeId || '').trim())) {
      if (!(await isKgEnabled())) {
        return { nodes: [], links: [] }
      }

      try {
        const data = await kgApi.expandGraph({
          node_id: nodeId,
          document_ids: options?.documentIds,
          dataset_id: options?.datasetId,
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
        // ignore and return empty graph below
      }
    }

    return { nodes: [], links: [] }
  }

  /**
   * Search for nodes by query
   */
  static async searchNodes(query: string): Promise<GraphNode[]> {
    const q = (query || '').trim()
    if (!q) return []

    try {
      const nodes = await kgApi.searchGraphNodes({ q, kind: 'all', limit: 20 })
      return Array.isArray(nodes) ? nodes : []
    } catch {
      return []
    }
  }
}
