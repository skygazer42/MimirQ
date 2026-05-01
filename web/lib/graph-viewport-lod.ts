export type GraphViewportRect = Readonly<{
  minX: number
  minY: number
  maxX: number
  maxY: number
}>

export type GraphViewportPoint = Readonly<{
  x: number
  y: number
}>

type GraphEndpoint =
  | string
  | number
  | {
      id?: string | number | null
    }
  | null
  | undefined

export type GraphViewportNode = {
  id?: string | number | null
  x?: number | null
  y?: number | null
}

export type GraphViewportLink = {
  id?: string | number | null
  index?: number | null
  source?: GraphEndpoint
  target?: GraphEndpoint
}

export type GraphViewportTier = 'overview' | 'balanced' | 'detail'

export type GraphViewportLod = Readonly<{
  tier: GraphViewportTier
  visibleNodeIds: ReadonlySet<string>
  visibleLinkIds: ReadonlySet<string>
  hiddenNodeCount: number
  hiddenLinkCount: number
}>

type QuadItem = Readonly<{
  node: GraphViewportNode
  id: string
  x: number
  y: number
}>

type QuadNode = {
  bounds: GraphViewportRect
  items: QuadItem[]
  children: QuadNode[] | null
  depth: number
}

const NODE_SPLIT_THRESHOLD = 16
const MAX_QUAD_DEPTH = 9
const DEFAULT_LARGE_GRAPH_NODE_THRESHOLD = 600
const DEFAULT_OVERVIEW_NODE_LIMIT = 420
const DEFAULT_VIEWPORT_OVERSCAN = 0.18

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function normalizeRect(rect: GraphViewportRect): GraphViewportRect {
  const minX = Math.min(rect.minX, rect.maxX)
  const maxX = Math.max(rect.minX, rect.maxX)
  const minY = Math.min(rect.minY, rect.maxY)
  const maxY = Math.max(rect.minY, rect.maxY)
  return { minX, minY, maxX, maxY }
}

function expandRect(rect: GraphViewportRect, ratio: number): GraphViewportRect {
  const normalized = normalizeRect(rect)
  const width = Math.max(1, normalized.maxX - normalized.minX)
  const height = Math.max(1, normalized.maxY - normalized.minY)
  const padX = width * Math.max(0, ratio)
  const padY = height * Math.max(0, ratio)
  return {
    minX: normalized.minX - padX,
    minY: normalized.minY - padY,
    maxX: normalized.maxX + padX,
    maxY: normalized.maxY + padY,
  }
}

function containsPoint(rect: GraphViewportRect, point: GraphViewportPoint): boolean {
  return point.x >= rect.minX && point.x <= rect.maxX && point.y >= rect.minY && point.y <= rect.maxY
}

function intersects(a: GraphViewportRect, b: GraphViewportRect): boolean {
  return a.minX <= b.maxX && a.maxX >= b.minX && a.minY <= b.maxY && a.maxY >= b.minY
}

function coerceNodeId(node: GraphViewportNode): string {
  if (typeof node.id === 'string' && node.id.trim()) return node.id
  if (typeof node.id === 'number') return String(node.id)
  return ''
}

function coerceEndpointId(endpoint: GraphEndpoint): string {
  if (endpoint == null) return ''
  if (typeof endpoint === 'string' || typeof endpoint === 'number') return String(endpoint)
  if (typeof endpoint === 'object' && 'id' in endpoint) {
    const id = endpoint.id
    if (typeof id === 'string' || typeof id === 'number') return String(id)
  }
  return ''
}

function coerceLinkId(link: GraphViewportLink, index: number): string {
  if (typeof link.id === 'string' && link.id.trim()) return link.id
  if (typeof link.id === 'number') return String(link.id)
  if (typeof link.index === 'number' && Number.isFinite(link.index)) return `link-${link.index}`
  return `link-${index}`
}

function makeBounds(items: readonly QuadItem[]): GraphViewportRect {
  if (!items.length) return { minX: 0, minY: 0, maxX: 1, maxY: 1 }

  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const item of items) {
    minX = Math.min(minX, item.x)
    minY = Math.min(minY, item.y)
    maxX = Math.max(maxX, item.x)
    maxY = Math.max(maxY, item.y)
  }

  if (minX === maxX) {
    minX -= 1
    maxX += 1
  }
  if (minY === maxY) {
    minY -= 1
    maxY += 1
  }

  return { minX, minY, maxX, maxY }
}

function makeQuadNode(bounds: GraphViewportRect, depth: number): QuadNode {
  return { bounds, depth, items: [], children: null }
}

function subdivide(node: QuadNode): void {
  const { minX, minY, maxX, maxY } = node.bounds
  const midX = (minX + maxX) / 2
  const midY = (minY + maxY) / 2
  node.children = [
    makeQuadNode({ minX, minY, maxX: midX, maxY: midY }, node.depth + 1),
    makeQuadNode({ minX: midX, minY, maxX, maxY: midY }, node.depth + 1),
    makeQuadNode({ minX, minY: midY, maxX: midX, maxY }, node.depth + 1),
    makeQuadNode({ minX: midX, minY: midY, maxX, maxY }, node.depth + 1),
  ]
}

function childForItem(node: QuadNode, item: QuadItem): QuadNode | null {
  if (!node.children) return null
  return node.children.find((child) => containsPoint(child.bounds, item)) ?? null
}

function insertItem(node: QuadNode, item: QuadItem): void {
  if (node.children) {
    const child = childForItem(node, item)
    if (child) {
      insertItem(child, item)
      return
    }
  }

  node.items.push(item)
  if (node.items.length <= NODE_SPLIT_THRESHOLD || node.depth >= MAX_QUAD_DEPTH) return

  subdivide(node)
  const items = node.items
  node.items = []
  for (const existing of items) {
    insertItem(node, existing)
  }
}

function queryNode(node: QuadNode, rect: GraphViewportRect, out: QuadItem[]): void {
  if (!intersects(node.bounds, rect)) return

  for (const item of node.items) {
    if (containsPoint(rect, item)) {
      out.push(item)
    }
  }

  if (!node.children) return
  for (const child of node.children) {
    queryNode(child, rect, out)
  }
}

export function createGraphSpatialIndex(nodes: readonly GraphViewportNode[]) {
  const items = nodes
    .map((node) => {
      const id = coerceNodeId(node)
      const x = Number(node.x)
      const y = Number(node.y)
      if (!id || !isFiniteNumber(x) || !isFiniteNumber(y)) return null
      return { node, id, x, y } satisfies QuadItem
    })
    .filter((item): item is QuadItem => item != null)

  const root = makeQuadNode(makeBounds(items), 0)
  for (const item of items) {
    insertItem(root, item)
  }

  return {
    query(rect: GraphViewportRect): GraphViewportNode[] {
      const out: QuadItem[] = []
      queryNode(root, normalizeRect(rect), out)
      return out.map((item) => item.node)
    },
    nearest(point: GraphViewportPoint): GraphViewportNode | null {
      let best: QuadItem | null = null
      let bestDistance = Number.POSITIVE_INFINITY
      for (const item of items) {
        const distance = (item.x - point.x) ** 2 + (item.y - point.y) ** 2
        if (distance < bestDistance) {
          best = item
          bestDistance = distance
        }
      }
      return best?.node ?? null
    },
  }
}

export function getGraphViewportTier(args: {
  globalScale: number
  totalNodeCount: number
  largeGraphNodeThreshold?: number
}): GraphViewportTier {
  const threshold = args.largeGraphNodeThreshold ?? DEFAULT_LARGE_GRAPH_NODE_THRESHOLD
  if (args.totalNodeCount <= threshold) return 'detail'
  if (args.globalScale < 0.45) return 'overview'
  if (args.globalScale < 1.45) return 'balanced'
  return 'detail'
}

function buildDegreeMap(links: readonly GraphViewportLink[]): Map<string, number> {
  const degree = new Map<string, number>()
  for (const link of links) {
    const source = coerceEndpointId(link.source)
    const target = coerceEndpointId(link.target)
    if (!source || !target) continue
    degree.set(source, (degree.get(source) ?? 0) + 1)
    degree.set(target, (degree.get(target) ?? 0) + 1)
  }
  return degree
}

export function buildGraphViewportLod(args: {
  nodes: readonly GraphViewportNode[]
  links: readonly GraphViewportLink[]
  viewport: GraphViewportRect
  globalScale: number
  totalNodeCount?: number
  selectedNodeIds?: ReadonlySet<string>
  maxOverviewNodes?: number
  overscanRatio?: number
  largeGraphNodeThreshold?: number
}): GraphViewportLod {
  const totalNodeCount = args.totalNodeCount ?? args.nodes.length
  const tier = getGraphViewportTier({
    globalScale: args.globalScale,
    totalNodeCount,
    largeGraphNodeThreshold: args.largeGraphNodeThreshold,
  })

  if (tier === 'detail' && totalNodeCount <= (args.largeGraphNodeThreshold ?? DEFAULT_LARGE_GRAPH_NODE_THRESHOLD)) {
    return {
      tier,
      visibleNodeIds: new Set(args.nodes.map(coerceNodeId).filter(Boolean)),
      visibleLinkIds: new Set(args.links.map(coerceLinkId)),
      hiddenNodeCount: 0,
      hiddenLinkCount: 0,
    }
  }

  const viewport = expandRect(args.viewport, args.overscanRatio ?? DEFAULT_VIEWPORT_OVERSCAN)
  const index = createGraphSpatialIndex(args.nodes)
  const visibleNodes = index.query(viewport)
  const degree = buildDegreeMap(args.links)
  const selectedNodeIds = args.selectedNodeIds ?? new Set<string>()
  const sortedVisibleNodeIds = visibleNodes
    .map(coerceNodeId)
    .filter(Boolean)
    .sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0) || a.localeCompare(b))

  const maxOverviewNodes = Math.max(1, Math.floor(args.maxOverviewNodes ?? DEFAULT_OVERVIEW_NODE_LIMIT))
  const cappedVisibleNodeIds =
    tier === 'overview' ? sortedVisibleNodeIds.slice(0, maxOverviewNodes) : sortedVisibleNodeIds
  const visibleNodeIds = new Set<string>(cappedVisibleNodeIds)
  for (const id of selectedNodeIds) {
    if (id) visibleNodeIds.add(id)
  }

  const visibleLinkIds = new Set<string>()
  args.links.forEach((link, index) => {
    const source = coerceEndpointId(link.source)
    const target = coerceEndpointId(link.target)
    if (!source || !target) return
    if (visibleNodeIds.has(source) && visibleNodeIds.has(target)) {
      visibleLinkIds.add(coerceLinkId(link, index))
    }
  })

  return {
    tier,
    visibleNodeIds,
    visibleLinkIds,
    hiddenNodeCount: Math.max(0, args.nodes.length - visibleNodeIds.size),
    hiddenLinkCount: Math.max(0, args.links.length - visibleLinkIds.size),
  }
}
