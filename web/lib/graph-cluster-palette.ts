import { NODE_COLOR_PALETTE } from '@/components/graph/graph-viewer'
import type { GraphClusterResult } from '@/lib/graph-clustering'
import type { GraphData } from '@/lib/graph-parser'

function hashString32(value: string): number {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.codePointAt(index) ?? 0
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function getPaletteOffset(seed: string | null | undefined, size: number): number {
  if (!seed || size <= 0) return 0
  return hashString32(String(seed)) % size
}

export function applyClusterPalette(args: {
  graphRenderData: GraphData
  paletteSeed?: string | null
  clusterResult: GraphClusterResult | null
}): GraphData {
  const { graphRenderData, paletteSeed = null, clusterResult } = args
  if (!paletteSeed) return graphRenderData
  if (!clusterResult?.nodeToCluster) return graphRenderData

  const palette = NODE_COLOR_PALETTE
  const paletteOffset = getPaletteOffset(paletteSeed, palette.length)
  const nodeToCluster = clusterResult.nodeToCluster

  const nodes = graphRenderData.nodes.map((node) => {
    if (node.color) return node

    const record = node as Record<string, unknown>
    const meta = (record.meta ?? {}) as Record<string, unknown>
    const kind = String(meta.kind ?? record.kind ?? '').trim().toLowerCase()
    if (kind === 'event' || kind === 'trace' || kind === 'step' || kind === 'citation') return node

    const nodeId = String(node.id || '').trim()
    if (!nodeId) return node

    const clusterIndex = Math.max(1, Math.floor(Number(nodeToCluster[nodeId] || 1)))
    const color = palette[(paletteOffset + (clusterIndex - 1)) % palette.length]
    return { ...node, color }
  })

  return { nodes, links: graphRenderData.links }
}
