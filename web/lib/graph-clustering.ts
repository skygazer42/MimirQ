import type { GraphData, GraphLink, GraphNode } from '@/lib/graph-parser'

type GraphEndpoint = GraphLink['source'] | GraphLink['target'] | { id?: unknown } | null | undefined

export type GraphClusterResult = Readonly<{
  nodeToCluster: Record<string, number>
  clusterCount: number
  clusterSizes: number[]
}>

function coerceEndpointId(endpoint: GraphEndpoint): string {
  if (endpoint == null) return ''
  if (typeof endpoint === 'string' || typeof endpoint === 'number') return String(endpoint)
  if (typeof endpoint === 'object' && 'id' in endpoint) {
    const id = endpoint.id
    if (typeof id === 'string' || typeof id === 'number') return String(id)
  }
  return ''
}

class DisjointSet {
  private readonly parent: number[]
  private readonly rank: number[]

  constructor(size: number) {
    this.parent = Array.from({ length: size }, (_, i) => i)
    this.rank = Array.from({ length: size }, () => 0)
  }

  find(x: number): number {
    let p = this.parent[x]
    if (p === x) return x
    // Path compression.
    this.parent[x] = this.find(p)
    return this.parent[x]
  }

  union(a: number, b: number) {
    const ra = this.find(a)
    const rb = this.find(b)
    if (ra === rb) return

    const rka = this.rank[ra]
    const rkb = this.rank[rb]
    if (rka < rkb) {
      this.parent[ra] = rb
      return
    }
    if (rka > rkb) {
      this.parent[rb] = ra
      return
    }
    this.parent[rb] = ra
    this.rank[ra] += 1
  }
}

export function computeConnectedComponents(
  graph: Readonly<Pick<GraphData, 'nodes' | 'links'>>
): GraphClusterResult {
  const nodes: GraphNode[] = Array.isArray(graph.nodes) ? graph.nodes : []
  const links: GraphLink[] = Array.isArray(graph.links) ? graph.links : []

  const nodeIds = nodes.map((n) => String(n.id || '').trim()).filter(Boolean)
  const idToIndex = new Map<string, number>()
  nodeIds.forEach((id, idx) => idToIndex.set(id, idx))

  const dsu = new DisjointSet(nodeIds.length)
  for (const link of links) {
    const sourceId = coerceEndpointId(link.source)
    const targetId = coerceEndpointId(link.target)
    if (!sourceId || !targetId) continue
    const si = idToIndex.get(sourceId)
    const ti = idToIndex.get(targetId)
    if (si == null || ti == null) continue
    dsu.union(si, ti)
  }

  const rootToCount = new Map<number, number>()
  const roots: number[] = []
  for (let i = 0; i < nodeIds.length; i += 1) {
    const r = dsu.find(i)
    roots[i] = r
    rootToCount.set(r, (rootToCount.get(r) || 0) + 1)
  }

  const sortedRoots = Array.from(rootToCount.entries())
    .map(([root, size]) => ({ root, size }))
    .sort((a, b) => b.size - a.size || a.root - b.root)

  const rootToClusterIndex = new Map<number, number>()
  sortedRoots.forEach((row, idx) => rootToClusterIndex.set(row.root, idx + 1))

  const nodeToCluster: Record<string, number> = {}
  for (let i = 0; i < nodeIds.length; i += 1) {
    const id = nodeIds[i]
    const clusterIndex = rootToClusterIndex.get(roots[i]) || 1
    nodeToCluster[id] = clusterIndex
  }

  return {
    nodeToCluster,
    clusterCount: sortedRoots.length,
    clusterSizes: sortedRoots.map((row) => row.size),
  }
}
