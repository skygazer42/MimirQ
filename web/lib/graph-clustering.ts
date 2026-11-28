import type { GraphData, GraphLink } from '@/lib/graph-types'

type GraphEndpoint = GraphLink['source'] | GraphLink['target'] | { id?: unknown } | null | undefined

export type GraphClusterResult = Readonly<{
  nodeToCluster: Record<string, number>
  clusterCount: number
  clusterSizes: number[]
}>

function coerceEndpointId(endpoint: GraphEndpoint): string {
  if (typeof endpoint === 'string' || typeof endpoint === 'number') return String(endpoint)
  const id = endpoint?.id
  return typeof id === 'string' || typeof id === 'number' ? String(id) : ''
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

export function computeConnectedComponents(graph: Readonly<Pick<GraphData, 'nodes' | 'links'>>): GraphClusterResult {
  const { nodes, links } = graph

  const nodeIds = nodes.map((node) => node.id.trim()).filter(Boolean)
  const idToIndex = new Map<string, number>()
  nodeIds.forEach((id, index) => idToIndex.set(id, index))

  const disjointSet = new DisjointSet(nodeIds.length)
  for (const link of links) {
    const sourceId = coerceEndpointId(link.source)
    const targetId = coerceEndpointId(link.target)
    if (!sourceId || !targetId) continue
    const sourceIndex = idToIndex.get(sourceId)
    const targetIndex = idToIndex.get(targetId)
    if (sourceIndex === undefined || targetIndex === undefined) continue
    disjointSet.union(sourceIndex, targetIndex)
  }

  const rootToCount = new Map<number, number>()
  const roots: number[] = []
  for (let index = 0; index < nodeIds.length; index += 1) {
    const root = disjointSet.find(index)
    roots[index] = root
    rootToCount.set(root, (rootToCount.get(root) ?? 0) + 1)
  }

  const sortedRoots = Array.from(rootToCount.entries())
    .map(([root, size]) => ({ root, size }))
    .sort((a, b) => b.size - a.size || a.root - b.root)

  const clusterIndexByRoot: number[] = []
  sortedRoots.forEach(({ root }, index) => {
    clusterIndexByRoot[root] = index + 1
  })

  const nodeToCluster: Record<string, number> = Object.create(null)
  for (const [index, id] of nodeIds.entries()) {
    nodeToCluster[id] = clusterIndexByRoot[roots[index]]
  }

  return {
    nodeToCluster,
    clusterCount: sortedRoots.length,
    clusterSizes: sortedRoots.map((row) => row.size),
  }
}
