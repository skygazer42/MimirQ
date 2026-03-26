import { GraphNode, GraphLink } from './graph-parser'

type GraphEndpoint = string | number | { id?: string | number | null } | null | undefined
type GraphLinkLike = Omit<GraphLink, 'source' | 'target'> & {
  source: GraphEndpoint
  target: GraphEndpoint
  id?: string | number | null
}

function getGraphEndpointId(endpoint: GraphEndpoint): string {
  if (endpoint == null) return ''
  if (typeof endpoint === 'string' || typeof endpoint === 'number') return String(endpoint)
  if (typeof endpoint === 'object') {
    const rawId = 'id' in endpoint ? endpoint.id : undefined
    if (typeof rawId === 'string' || typeof rawId === 'number') {
      return String(rawId)
    }
  }
  return ''
}

function getGraphLinkId(link: GraphLinkLike, index: number): string {
  if (typeof link.id === 'string' || typeof link.id === 'number') {
    return String(link.id)
  }
  return `link-${index}`
}

/**
 * Finds the shortest path between two nodes using Breadth-First Search (BFS).
 * Returns a set of Node IDs and Link IDs that make up the path.
 */
export const findShortestPath = (
  nodes: GraphNode[],
  links: GraphLinkLike[],
  startNodeId: string,
  endNodeId: string
): { nodeIds: string[]; linkIds: string[] } | null => {
  if (startNodeId === endNodeId) return { nodeIds: [startNodeId], linkIds: [] }

  // Build Adjacency List
  const adj: { [key: string]: { neighbor: string; linkId: string }[] } = {}
  
  nodes.forEach(node => {
    adj[node.id] = []
  })

  links.forEach((link, index) => {
    // Handle both object ref (d3-force after init) and string ref (raw data)
    const sourceId = getGraphEndpointId(link.source)
    const targetId = getGraphEndpointId(link.target)
    if (!sourceId || !targetId) return
    
    // Assuming undirected graph for path finding convenience, or directed if preferred.
    // Let's treat it as Undirected for easier navigation in knowledge graphs.
    if (!adj[sourceId]) adj[sourceId] = []
    if (!adj[targetId]) adj[targetId] = []

    // Store index or a unique ID if available. Using index as ID fallback.
    const linkId = getGraphLinkId(link, index)
    // Ensure we attach this ID to the link object in the main component if not present
    
    adj[sourceId].push({ neighbor: targetId, linkId })
    adj[targetId].push({ neighbor: sourceId, linkId })
  })

  // BFS
  const queue: string[] = [startNodeId]
  const visited = new Set<string>([startNodeId])
  const parent: { [key: string]: { id: string; linkId: string } } = {}

  while (queue.length > 0) {
    const curr = queue.shift()
    if (!curr) continue

    if (curr === endNodeId) {
      // Path found, reconstruct it
      const pathNodeIds: string[] = []
      const pathLinkIds: string[] = []
      let temp = endNodeId
      
      while (temp !== startNodeId) {
        pathNodeIds.unshift(temp)
        const p = parent[temp]
        pathLinkIds.unshift(p.linkId)
        temp = p.id
      }
      pathNodeIds.unshift(startNodeId)
      
      return { nodeIds: pathNodeIds, linkIds: pathLinkIds }
    }

    if (adj[curr]) {
      for (const edge of adj[curr]) {
        if (!visited.has(edge.neighbor)) {
          visited.add(edge.neighbor)
          parent[edge.neighbor] = { id: curr, linkId: edge.linkId }
          queue.push(edge.neighbor)
        }
      }
    }
  }

  return null // No path found
}
