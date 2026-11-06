import type { GraphData } from '@/lib/graph-parser'
import { kgApi, metaApi } from '@/lib/api'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

type GraphRequestOptions = {
  includeEntityLinks?: boolean
  includeRelationLinks?: boolean
  minSharedEvents?: number
  maxEntityLinks?: number
  documentIds?: string[]
  datasetId?: string
  pipelineHash?: string
}

async function isKgEnabled(): Promise<boolean> {
  try {
    const meta = await metaApi.details()
    return meta.features?.kg_enabled !== false
  } catch {
    return true
  }
}

export async function fetchInitialGraph(options: GraphRequestOptions = {}): Promise<GraphData> {
  if (!(await isKgEnabled())) {
    return { nodes: [], links: [] }
  }

  // The live graph has no demo-data fallback when the current scope has no KG data.
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
      return structuredClone({ nodes, links })
    }
  } catch {
    // Preserve the existing empty-graph result for unavailable live data.
  }

  // Small delay for empty live graph loading so UI transitions remain stable.
  await new Promise((resolve) => setTimeout(resolve, 200))
  return { nodes: [], links: [] }
}

export async function expandGraphNode(nodeId: string, options?: GraphRequestOptions): Promise<GraphData> {
  // Live expansion only accepts backend KG IDs.
  if (!UUID_RE.test(String(nodeId || '').trim())) {
    return { nodes: [], links: [] }
  }
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
      return structuredClone({ nodes: data.nodes, links: data.links })
    }
  } catch {
    // Preserve the existing empty expansion for unavailable live data.
  }

  return { nodes: [], links: [] }
}
