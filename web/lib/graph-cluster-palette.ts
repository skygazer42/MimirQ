import { NODE_COLOR_PALETTE } from '@/components/graph/graph-colors'
import type { GraphClusterResult } from '@/lib/graph-clustering'
import type { GraphData } from '@/lib/graph-types'

function hashString32(value: string): number {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.codePointAt(index) ?? 0
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

export function applyClusterPalette(args: {
  graphRenderData: GraphData
  paletteSeed?: string | null
  clusterResult: GraphClusterResult | null
}): GraphData {
  const { graphRenderData, paletteSeed = null, clusterResult } = args
  if (!paletteSeed) return graphRenderData
  if (clusterResult === null) return graphRenderData

  const palette = NODE_COLOR_PALETTE
  const paletteOffset = hashString32(paletteSeed) % palette.length
  const nodeToCluster = clusterResult.nodeToCluster

  const nodes = graphRenderData.nodes.map((node) => {
    if (node.color) return node

    const rawKind = node.meta?.kind ?? node.kind
    const kind = typeof rawKind === 'string' ? rawKind.trim().toLowerCase() : undefined
    if (kind === 'event' || kind === 'trace' || kind === 'step' || kind === 'citation') return node

    const nodeId = node.id.trim()
    if (!Object.hasOwn(nodeToCluster, nodeId)) return node
    const clusterIndex = nodeToCluster[nodeId]
    const color = palette[(paletteOffset + (clusterIndex - 1)) % palette.length]
    return { ...node, color }
  })

  return { nodes, links: graphRenderData.links }
}
