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
    const typeMeta = {
      concept: { label: '概念 / Concept', color: '#4f7cff', group: 1 },
      technology: { label: '技术 / Technology', color: '#19b8c6', group: 2 },
      method: { label: '方法 / Method', color: '#8b5cf6', group: 3 },
      model: { label: '模型 / Model', color: '#a78bfa', group: 4 },
      application: { label: '应用 / Application', color: '#f472b6', group: 5 },
      domain: { label: '领域 / Domain', color: '#22c55e', group: 6 },
    } as const

    const createNode = (
      id: string,
      label: string,
      type: keyof typeof typeMeta,
      val: number
    ): GraphNode => {
      const meta = typeMeta[type]
      return {
        id,
        label,
        type: meta.label,
        group: meta.group,
        val,
        color: meta.color,
        meta: {
          type: meta.label,
          domain: 'AI Knowledge Demo',
        },
      }
    }

    const nodes: GraphNode[] = [
      createNode('ai', 'Artificial Intelligence', 'concept', 34),
      createNode('machine-learning', 'Machine Learning', 'concept', 24),
      createNode('deep-learning', 'Deep Learning', 'model', 24),
      createNode('nlp', 'NLP', 'technology', 23),
      createNode('computer-vision', 'Computer Vision', 'technology', 23),
      createNode('reinforcement-learning', 'Reinforcement Learning', 'application', 22),

      createNode('supervised-learning', 'Supervised Learning', 'method', 12),
      createNode('unsupervised-learning', 'Unsupervised Learning', 'method', 12),
      createNode('feature-engineering', 'Feature Engineering', 'method', 11),
      createNode('model-evaluation', 'Model Evaluation', 'method', 11),

      createNode('neural-networks', 'Neural Networks', 'model', 13),
      createNode('cnn', 'Convolutional Neural Network', 'model', 11),
      createNode('rnn', 'Recurrent Neural Network', 'model', 11),

      createNode('named-entity-recognition', 'Named Entity Recognition', 'technology', 11),
      createNode('text-generation', 'Text Generation', 'technology', 11),
      createNode('sentiment-analysis', 'Sentiment Analysis', 'technology', 10),
      createNode('machine-translation', 'Machine Translation', 'technology', 10),
      createNode('text-classification', 'Text Classification', 'technology', 10),

      createNode('image-recognition', 'Image Recognition', 'domain', 11),
      createNode('object-detection', 'Object Detection', 'domain', 11),
      createNode('face-recognition', 'Face Recognition', 'domain', 10),
      createNode('image-segmentation', 'Image Segmentation', 'domain', 10),

      createNode('q-learning', 'Q-Learning', 'application', 10),
      createNode('policy-gradient', 'Policy Gradient', 'application', 10),
      createNode('deep-q-network', 'Deep Q-Network', 'application', 10),
    ]

    const createLink = (
      source: string,
      target: string,
      label: string,
      color: string,
      confidence = 0.86
    ): GraphLink => ({
      source,
      target,
      label,
      color,
      confidence,
      kind: 'entity_relation',
      meta: {
        kind: 'entity_relation',
        label,
        confidence,
      },
    })

    const links: GraphLink[] = [
      createLink('ai', 'machine-learning', '子领域', '#4f7cff', 0.96),
      createLink('ai', 'deep-learning', '子领域', '#8b5cf6', 0.94),
      createLink('ai', 'nlp', '子领域', '#19b8c6', 0.93),
      createLink('ai', 'computer-vision', '子领域', '#22c55e', 0.93),
      createLink('ai', 'reinforcement-learning', '子领域', '#f472b6', 0.91),

      createLink('machine-learning', 'supervised-learning', '包含', '#8b5cf6'),
      createLink('machine-learning', 'unsupervised-learning', '包含', '#8b5cf6'),
      createLink('machine-learning', 'feature-engineering', '依赖', '#8b5cf6', 0.78),
      createLink('machine-learning', 'model-evaluation', '评估', '#8b5cf6', 0.82),

      createLink('deep-learning', 'neural-networks', '基础', '#a78bfa', 0.92),
      createLink('deep-learning', 'cnn', '算法', '#a78bfa'),
      createLink('deep-learning', 'rnn', '算法', '#a78bfa'),

      createLink('nlp', 'named-entity-recognition', '应用于', '#19b8c6'),
      createLink('nlp', 'text-generation', '应用于', '#19b8c6'),
      createLink('nlp', 'sentiment-analysis', '应用于', '#19b8c6'),
      createLink('nlp', 'machine-translation', '应用于', '#19b8c6'),
      createLink('nlp', 'text-classification', '应用于', '#19b8c6'),

      createLink('computer-vision', 'image-recognition', '应用于', '#22c55e'),
      createLink('computer-vision', 'object-detection', '应用于', '#22c55e'),
      createLink('computer-vision', 'face-recognition', '应用于', '#22c55e'),
      createLink('computer-vision', 'image-segmentation', '应用于', '#22c55e'),

      createLink('reinforcement-learning', 'q-learning', '算法', '#f472b6'),
      createLink('reinforcement-learning', 'policy-gradient', '算法', '#f472b6'),
      createLink('reinforcement-learning', 'deep-q-network', '算法', '#f472b6'),

      createLink('deep-learning', 'computer-vision', '应用于', '#60a5fa', 0.76),
      createLink('deep-learning', 'nlp', '应用于', '#60a5fa', 0.76),
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
