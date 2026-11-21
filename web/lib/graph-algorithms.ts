import type { GraphNode, GraphLink } from './graph-types'

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

type Neighbor = { nodeId: string; linkId: string }
type PathStep = { nodeId: string; previous?: { step: PathStep; linkId: string } }

export function findShortestPath(
  nodes: readonly GraphNode[],
  links: readonly GraphLinkLike[],
  startNodeId: string,
  endNodeId: string,
): { nodeIds: string[]; linkIds: string[] } | null {
  if (startNodeId === endNodeId) return { nodeIds: [startNodeId], linkIds: [] }

  const adjacency = new Map<string, Neighbor[]>(nodes.map(({ id }) => [id, []]))
  function addNeighbor(nodeId: string, neighbor: Neighbor) {
    const neighbors = adjacency.get(nodeId)
    if (neighbors === undefined) adjacency.set(nodeId, [neighbor])
    else neighbors.push(neighbor)
  }

  for (const [index, link] of links.entries()) {
    const sourceId = getGraphEndpointId(link.source)
    const targetId = getGraphEndpointId(link.target)
    if (sourceId === '' || targetId === '') continue
    const linkId = getGraphLinkId(link, index)
    addNeighbor(sourceId, { nodeId: targetId, linkId })
    addNeighbor(targetId, { nodeId: sourceId, linkId })
  }

  const queue: PathStep[] = [{ nodeId: startNodeId }]
  const visited = new Set([startNodeId])
  for (const step of queue) {
    if (step.nodeId === endNodeId) {
      const nodeIds = [endNodeId]
      const linkIds: string[] = []
      let current = step
      while (current.previous !== undefined) {
        linkIds.push(current.previous.linkId)
        current = current.previous.step
        nodeIds.push(current.nodeId)
      }
      return { nodeIds: nodeIds.reverse(), linkIds: linkIds.reverse() }
    }

    for (const { nodeId, linkId } of adjacency.get(step.nodeId) ?? []) {
      if (visited.has(nodeId)) continue
      visited.add(nodeId)
      queue.push({ nodeId, previous: { step, linkId } })
    }
  }

  return null
}
