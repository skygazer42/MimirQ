/**
 * GraphML Parser for Knowledge Graph Visualization
 * Parses .graphml XML content into { nodes, links } format for react-force-graph
 */

export interface GraphNode {
  id: string
  label: string
  val?: number // size
  color?: string
  group?: number
  kind?: unknown
  type?: unknown
  source?: unknown
  meta?: Record<string, unknown>
  x?: number
  y?: number
  z?: number
  fx?: number | null
  fy?: number | null
  fz?: number | null
  vx?: number | null
  vy?: number | null
  vz?: number | null
}

export interface GraphLink {
  source: string
  target: string
  id?: string | number | null
  label?: string
  kind?: unknown
  type?: unknown
  predicate?: unknown
  confidence?: unknown
  weight?: unknown
  value?: unknown
  score?: unknown
  color?: string
  index?: number
  meta?: Record<string, unknown>
}

export interface GraphData {
  nodes: GraphNode[]
  links: GraphLink[]
}

export const parseGraphML = (xmlContent: string): GraphData => {
  const parser = new DOMParser()
  const xmlDoc = parser.parseFromString(xmlContent, 'text/xml')

  const nodes: GraphNode[] = []
  const links: GraphLink[] = []

  // Get all keys to map IDs to attribute names (e.g., d0 -> label, d1 -> weight)
  const keys: { [id: string]: { name: string, type: string } } = {}
  xmlDoc.querySelectorAll('key').forEach((key) => {
    const id = key.getAttribute('id')
    const name = key.getAttribute('attr.name')
    const type = key.getAttribute('attr.type')
    if (id && name) {
      keys[id] = { name, type: type || 'string' }
    }
  })

  // Parse Nodes
  xmlDoc.querySelectorAll('node').forEach((node) => {
    const id = node.getAttribute('id')
    if (!id) return

    const nodeData: GraphNode & Record<string, unknown> = { id, label: id }

    // Parse data attributes
    node.querySelectorAll('data').forEach((data) => {
      const keyId = data.getAttribute('key')
      if (keyId && keys[keyId]) {
        const { name } = keys[keyId]
        nodeData[name] = data.textContent

        // Map common names to visual properties
        if (name.toLowerCase() === 'label' || name.toLowerCase() === 'name') {
          nodeData.label = data.textContent || id
        }
      }
    })

    // Default label if missing
    if (!nodeData.label) nodeData.label = id

    // Random color assignment if not present (can be improved)
    if (!nodeData.color) {
      // nodeData.color = ... 
    }

    nodes.push(nodeData)
  })

  // Parse Edges
  xmlDoc.querySelectorAll('edge').forEach((edge) => {
    const source = edge.getAttribute('source')
    const target = edge.getAttribute('target')

    if (source && target) {
      const linkData: GraphLink & Record<string, unknown> = { source, target }

      // Parse data attributes for edges
      edge.querySelectorAll('data').forEach((data) => {
        const keyId = data.getAttribute('key')
        if (keyId && keys[keyId]) {
          const { name } = keys[keyId]
          linkData[name] = data.textContent
        }
      })

      links.push(linkData)
    }
  })

  return { nodes, links }
}
