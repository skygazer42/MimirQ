import { AxiosError } from 'axios'

import type { GraphData } from '@/lib/graph-types'
import { kgApi } from '@/lib/api/graph'
import { metaApi } from '@/lib/api/meta'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

type GraphRequestOptions = {
  includeEntityLinks?: boolean
  includeRelationLinks?: boolean
  minSharedEvents?: number
  maxEntityLinks?: number
  documentIds?: string[]
  datasetId?: string
  pipelineHash?: string
  preferOntology?: boolean
}

async function isKgEnabled(signal?: AbortSignal): Promise<boolean> {
  try {
    const meta = await metaApi.details({ signal })
    return meta.features.kg_enabled
  } catch (error) {
    if (error instanceof AxiosError && error.response?.status === 403) return true
    throw error
  }
}

function buildGraphParams(options: GraphRequestOptions) {
  return {
    document_ids: options.documentIds,
    dataset_id: options.datasetId,
    pipeline_hash: options.pipelineHash,
    prefer_ontology: options.preferOntology,
    include_entity_links: options.includeEntityLinks,
    include_relation_links: options.includeRelationLinks,
    min_shared_events: options.minSharedEvents,
    max_entity_links: options.maxEntityLinks,
  }
}

export async function fetchInitialGraph(options: GraphRequestOptions = {}, signal?: AbortSignal): Promise<GraphData> {
  if (!(await isKgEnabled(signal))) {
    return { nodes: [], links: [] }
  }

  const { nodes, links, stats } = await kgApi.getGraph(buildGraphParams(options), { signal })
  const ontologyVersionId = stats?.ontology_version_id
  return structuredClone(
    typeof ontologyVersionId === 'string'
      ? {
          nodes,
          links: links.map((link) => ({ ...link, id: typeof link.meta?.id === 'string' ? link.meta.id : undefined })),
          ontologyVersionId,
        }
      : { nodes, links },
  )
}

export async function expandGraphNode(
  nodeId: string,
  options: GraphRequestOptions = {},
  signal?: AbortSignal,
): Promise<GraphData> {
  // Live expansion only accepts backend KG IDs.
  const normalizedNodeId = nodeId.trim()
  if (!UUID_RE.test(normalizedNodeId)) {
    return { nodes: [], links: [] }
  }
  if (!(await isKgEnabled(signal))) {
    return { nodes: [], links: [] }
  }

  const data = await kgApi.expandGraph(
    {
      ...buildGraphParams(options),
      node_id: normalizedNodeId,
      max_events: 50,
      max_entities: 400,
      max_links: 5000,
    },
    { signal },
  )
  return structuredClone({ nodes: data.nodes, links: data.links })
}
