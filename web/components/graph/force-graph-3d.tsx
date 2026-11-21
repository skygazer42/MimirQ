'use client'

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type Ref,
} from 'react'
import dynamic from 'next/dynamic'
import { useTheme } from 'next-themes'
import { Group, type Object3D } from 'three'
import SpriteText from 'three-spritetext'

import {
  getGraphLinkDisplayWeight,
  getGraphLinkEndpointId,
  type GraphEndpointRef,
  type GraphLinkLike,
  type GraphNodeLike,
} from '@/app/graph/graph-page-utils'
import { getCssHslColor } from '@/lib/css-vars'
import { buildGraphLinkProvenanceTooltipHtml } from '@/lib/graph-provenance'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { buildTypeColorMap, EVENT_COLOR, NODE_COLOR_PALETTE } from './graph-colors'
import { GraphLoadingIndicator } from './graph-loading-indicator'
import {
  EDGE_KIND_COLORS,
  mixHexColors,
  reportGraphLayoutCycle,
  truncateGraphLabel,
  type LayoutMode,
  withAlpha,
} from './graph-viewer'

function hashCode(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = Math.trunc((h * 31 + (s.codePointAt(i) ?? 0)) % 0x7fffffff)
  return h
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

type GraphNodeDatum = GraphNodeLike & {
  id: string
  label: string
  color?: string
  group?: number
  x?: number
  y?: number
  z?: number
  fx?: number | null
  fy?: number | null
  fz?: number | null
}

type GraphLinkDatum = GraphLinkLike & {
  source: GraphEndpointRef | GraphNodeDatum
  target: GraphEndpointRef | GraphNodeDatum
  color?: string
  type?: unknown
  curvature?: number
  curveRotation?: number
  isSelfLoop?: boolean
}

type GraphRenderData = Readonly<{
  nodes: GraphNodeDatum[]
  links: GraphLinkDatum[]
}>

type GraphPosition = { x: number; y: number; z: number }

function primitiveText(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

function getLinkKind(link: GraphLinkDatum): string {
  return primitiveText(link.meta?.kind ?? link.kind).trim()
}

function getRenderLinkId(link: GraphLinkDatum): string | null {
  return link.id == null || link.id === '' ? null : String(link.id)
}

function hasLinkEndpoints(link: GraphLinkDatum, nodeIds: ReadonlySet<string>): boolean {
  return nodeIds.has(getGraphLinkEndpointId(link.source)) && nodeIds.has(getGraphLinkEndpointId(link.target))
}

function confidenceToWidth(confidence: number | null): number {
  const c = confidence == null ? 0.55 : clamp01(confidence)
  return 0.75 + c * 2.25
}

const GRAPH_3D_PAN_SPEED = 0.2
const GRAPH_3D_NODE_REL_SIZE = 5.2
const GRAPH_3D_LABEL_TEXT_HEIGHT = 2.6
const GRAPH_3D_LABEL_Y_OFFSET = 5.8
const GRAPH_3D_LABEL_X_OFFSET = 6.2

function getGraphCursor({
  isCanvasPanning,
  hasHoverTarget,
}: {
  isCanvasPanning: boolean
  hasHoverTarget: boolean
}): string {
  if (isCanvasPanning) return 'grabbing'
  if (hasHoverTarget) return 'pointer'
  return 'grab'
}

function getGraphLabelTextColor({
  isDimmed,
  isDark,
  mutedFgColor,
}: {
  isDimmed: boolean
  isDark: boolean
  mutedFgColor: string
}): string {
  if (isDimmed) return mutedFgColor
  return isDark ? '#e5eefc' : '#334155'
}

function getGraphLabelBackgroundColor({
  emphasis,
  color,
  isDark,
  labelBgColor,
}: {
  emphasis: boolean
  color: string
  isDark: boolean
  labelBgColor: string
}): string {
  if (!emphasis) return labelBgColor
  const canvasColor = isDark ? '#0f172a' : '#fffef9'
  const mixWeight = isDark ? 0.74 : 0.84
  const alpha = isDark ? 0.92 : 0.9
  return withAlpha(mixHexColors(color, canvasColor, mixWeight), alpha)
}

function getPrimaryCanvas(root: ParentNode | null): HTMLCanvasElement | null {
  if (root === null) return null
  let largestCanvas: HTMLCanvasElement | null = null
  for (const canvas of root.querySelectorAll('canvas')) {
    if (largestCanvas === null || canvas.width * canvas.height > largestCanvas.width * largestCanvas.height) {
      largestCanvas = canvas
    }
  }
  return largestCanvas
}

type ForceGraph3DComponentProps = Record<string, unknown> & {
  ref?: Ref<unknown>
}

type ForceGraph3DHandle = {
  d3ReheatSimulation?: () => void
  controls?: () => {
    panSpeed?: number
    target?: { x: number; y: number; z: number }
  } | null
  camera?: () => {
    position: GraphPosition
  } | null
  cameraPosition?: (position: GraphPosition, lookAt?: { x?: number; y?: number; z?: number }, ms?: number) => void
  zoomToFit?: (ms?: number, padding?: number) => void
  renderer?: () => { domElement?: HTMLCanvasElement } | null
}

// Dynamic import to avoid SSR issues with Three.js
const ForceGraph3D = dynamic(() => import('react-force-graph-3d'), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center bg-background/70 px-6">
      <GraphLoadingIndicator
        className="rounded-2xl border border-border/60 bg-background/88 px-6 py-5 shadow-soft"
        message="正在加载 3D 引擎…"
      />
    </div>
  ),
}) as unknown as ComponentType<ForceGraph3DComponentProps>

export type KnowledgeGraph3DRef = {
  zoomIn: () => void
  zoomOut: () => void
  zoomToFit: () => void
  focusNode: (nodeId: string) => void
  exportPngDataUrl: () => string | null
  exportSvgString: () => string | null
}

type ForceGraph3DProps = {
  readonly data: GraphRenderData
  readonly onNodeClick?: (node: GraphNodeDatum) => void
  readonly onNodeRightClick?: (node: GraphNodeDatum, event: MouseEvent) => void
  readonly onLinkClick?: (link: GraphLinkDatum) => void
  readonly onLinkRightClick?: (link: GraphLinkDatum, event: MouseEvent) => void
  readonly onBackgroundClick?: () => void
  readonly onBackgroundRightClick?: (event: MouseEvent) => void
  readonly highlightedNodeIds?: Set<string>
  readonly highlightedLinkIds?: Set<string>
  readonly selectedNodeId?: string | null
  readonly showEdgeLabels?: boolean
  readonly layoutMode?: LayoutMode
  readonly width?: number
  readonly height?: number
}

export const KnowledgeGraph3D = forwardRef<KnowledgeGraph3DRef, ForceGraph3DProps>(function KnowledgeGraph3D(
  {
    data,
    onNodeClick,
    onNodeRightClick,
    onLinkClick,
    onLinkRightClick,
    onBackgroundClick,
    onBackgroundRightClick,
    highlightedNodeIds = new Set(),
    highlightedLinkIds = new Set(),
    selectedNodeId = null,
    showEdgeLabels = false,
    layoutMode = 'force',
    width,
    height,
  },
  ref,
) {
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === 'dark'
  const containerRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<ForceGraph3DHandle | null>(null)
  const graphData = useMemo(
    () => ({
      nodes: data.nodes.map((node) => ({ ...node })),
      links: data.links.map((link) => ({
        ...link,
        source: getGraphLinkEndpointId(link.source),
        target: getGraphLinkEndpointId(link.target),
      })),
    }),
    [data],
  )
  const [mounted, setMounted] = useState(false)
  const fitRequest = useMemo(() => ({ width, height, layoutMode, data }), [data, height, layoutMode, width])
  const [fittedView, setFittedView] = useState<typeof fitRequest | null>(null)
  const fittedViewRef = useRef<typeof fitRequest | null>(null)
  useEffect(() => {
    fgRef.current?.d3ReheatSimulation?.()
  }, [fitRequest])
  const [hoveredLinkId, setHoveredLinkId] = useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [isCanvasPanning, setIsCanvasPanning] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const typeColorMap = useMemo(() => buildTypeColorMap(data.nodes), [data.nodes])
  const neighborSet = useMemo(() => {
    if (!selectedNodeId) return null
    const neighbors = new Set([selectedNodeId])
    for (const link of data.links) {
      const sourceId = getGraphLinkEndpointId(link.source)
      const targetId = getGraphLinkEndpointId(link.target)
      if (sourceId === selectedNodeId && targetId !== '') neighbors.add(targetId)
      if (targetId === selectedNodeId && sourceId !== '') neighbors.add(sourceId)
    }
    return neighbors
  }, [selectedNodeId, data.links])

  const dimNodeColor = isDark ? '#334155' : '#cbd5e1'
  const dimLinkColor = isDark ? 'rgba(148, 163, 184, 0.18)' : '#e2e8f0'
  const hoverLinkColor = getCssHslColor('--primary', isDark ? '#38bdf8' : '#0284c7')
  const labelBgColor = isDark ? 'rgba(2, 6, 23, 0.84)' : 'rgba(255, 254, 249, 0.92)'
  const labelStrokeColor = isDark ? 'rgba(15, 23, 42, 0.72)' : 'rgba(255, 255, 255, 0.96)'
  const graphCursor = getGraphCursor({
    isCanvasPanning,
    hasHoverTarget: Boolean(hoveredNodeId || hoveredLinkId),
  })
  const isLargeGraph = data.nodes.length > 180 || data.links.length > 360
  const useCustomNodeObjects = !isLargeGraph && data.nodes.length <= 36
  const allowLinkLabelSprites = showEdgeLabels && !isLargeGraph && data.links.length <= 40
  const cooldownTicks = isLargeGraph ? 35 : 90
  const cooldownTime = isLargeGraph ? 2500 : 6500
  const nodeRelSize = isLargeGraph ? 3.8 : GRAPH_3D_NODE_REL_SIZE
  const nodeResolution = isLargeGraph ? 8 : 16

  const dagMode = useMemo(() => {
    switch (layoutMode) {
      case 'tree':
        return 'td'
      case 'radial':
        return 'radialout'
      default:
        return undefined
    }
  }, [layoutMode])

  useEffect(() => {
    // Smooth layout transitions: reheat simulation when changing dagMode.
    fgRef.current?.d3ReheatSimulation?.()
  }, [layoutMode])

  useEffect(() => {
    const controls = fgRef.current?.controls?.()
    if (!controls) return

    controls.panSpeed = GRAPH_3D_PAN_SPEED
  }, [height, mounted, width])

  useEffect(() => {
    if (!mounted) return

    const root = containerRef.current
    if (!root) return

    const resetPanning = () => setIsCanvasPanning(false)
    const handleMouseDown = (event: MouseEvent) => {
      if (!(event.target instanceof HTMLCanvasElement)) return
      setIsCanvasPanning(true)
    }

    root.addEventListener('mousedown', handleMouseDown)
    globalThis.window.addEventListener('mouseup', resetPanning)
    globalThis.window.addEventListener('blur', resetPanning)
    globalThis.window.addEventListener('contextmenu', resetPanning)

    return () => {
      root.removeEventListener('mousedown', handleMouseDown)
      globalThis.window.removeEventListener('mouseup', resetPanning)
      globalThis.window.removeEventListener('blur', resetPanning)
      globalThis.window.removeEventListener('contextmenu', resetPanning)
    }
  }, [mounted])

  useEffect(() => {
    const root = containerRef.current
    const primaryCanvas = getPrimaryCanvas(root)
    if (root) {
      root.style.cursor = graphCursor
    }
    if (primaryCanvas) {
      primaryCanvas.style.cursor = graphCursor
    }
  }, [graphCursor, height, mounted, width, data.links.length, data.nodes.length])

  const getNodeColor = useCallback(
    (node: GraphNodeDatum) => {
      const id = node.id.trim()
      const hasHighlights = highlightedNodeIds.size > 0
      const isHighlighted = hasHighlights && highlightedNodeIds.has(id)
      const isSelected = selectedNodeId === id
      const isNeighbor = neighborSet ? neighborSet.has(id) : false
      const isDimmed = (hasHighlights && !isHighlighted) || (selectedNodeId && !isSelected && !isNeighbor)

      if (isDimmed) return dimNodeColor
      if (node.color) return node.color

      const kind = primitiveText(node.meta?.kind).trim()
      if (kind === 'event') return EVENT_COLOR

      const type = primitiveText(node.meta?.type ?? node.type).trim()
      const typeColor = typeColorMap.get(type)
      if (typeColor !== undefined) return typeColor

      if (typeof node.group === 'number' && node.group > 0) {
        return NODE_COLOR_PALETTE[(node.group - 1) % NODE_COLOR_PALETTE.length]
      }
      return NODE_COLOR_PALETTE[Math.abs(hashCode(id)) % NODE_COLOR_PALETTE.length]
    },
    [highlightedNodeIds, selectedNodeId, neighborSet, dimNodeColor, typeColorMap],
  )

  const getLookAtTarget = useCallback(() => {
    const g = fgRef.current
    const controls = g?.controls?.()
    const t = controls?.target
    if (t && typeof t.x === 'number' && typeof t.y === 'number' && typeof t.z === 'number') {
      return { x: t.x, y: t.y, z: t.z }
    }
    return { x: 0, y: 0, z: 0 }
  }, [])

  const focusNode = useCallback(
    (nodeId: string) => {
      const graph = fgRef.current
      const node = graphData.nodes.find((item) => item.id === nodeId)
      if (node === undefined || !graph?.cameraPosition) return

      const { x, y, z } = node
      if (x === undefined || y === undefined || z === undefined) return
      const distanceFromOrigin = Math.hypot(x, y, z)
      if (!Number.isFinite(distanceFromOrigin)) return

      const cameraDistance = 40
      const cameraPosition =
        distanceFromOrigin === 0
          ? { x, y, z: cameraDistance }
          : {
              x: x + (x / distanceFromOrigin) * cameraDistance,
              y: y + (y / distanceFromOrigin) * cameraDistance,
              z: z + (z / distanceFromOrigin) * cameraDistance,
            }
      graph.cameraPosition(cameraPosition, { x, y, z }, 900)
    },
    [graphData.nodes],
  )

  const zoomCamera = useCallback(
    (factor: number) => {
      const graph = fgRef.current
      const camera = graph?.camera?.()
      if (!camera || !graph?.cameraPosition) return
      const target = getLookAtTarget()
      const { x, y, z } = camera.position
      graph.cameraPosition(
        {
          x: target.x + (x - target.x) * factor,
          y: target.y + (y - target.y) * factor,
          z: target.z + (z - target.z) * factor,
        },
        target,
        400,
      )
    },
    [getLookAtTarget],
  )

  const zoomToFit = useCallback(() => {
    if (fgRef.current) {
      fgRef.current.zoomToFit?.(600, 30)
    }
  }, [])

  useImperativeHandle(
    ref,
    () => ({
      zoomIn: () => zoomCamera(0.85),
      zoomOut: () => zoomCamera(1.15),
      zoomToFit,
      focusNode,
      exportPngDataUrl: () => {
        const g = fgRef.current
        const el = g?.renderer?.()?.domElement
        if (!el) return null
        try {
          return el.toDataURL('image/png')
        } catch {
          return null
        }
      },
      exportSvgString: () => {
        const g = fgRef.current
        const el = g?.renderer?.()?.domElement
        if (!el) return null
        let png = ''
        try {
          png = el.toDataURL('image/png')
        } catch {
          return null
        }
        if (!png) return null
        const w = Math.max(1, el.width || 1)
        const h = Math.max(1, el.height || 1)
        return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">\n  <image href="${png}" width="${w}" height="${h}" />\n</svg>\n`
      },
    }),
    [zoomCamera, zoomToFit, focusNode],
  )

  const handleNodeClick = useCallback(
    (node: GraphNodeDatum) => {
      focusNode(node.id)
      onNodeClick?.(node)
    },
    [focusNode, onNodeClick],
  )

  const getNodeDecorationState = useCallback(
    (node: GraphNodeDatum) => {
      const id = node.id.trim()
      const isHighlighted = highlightedNodeIds.size > 0 && highlightedNodeIds.has(id)
      const isSelected = selectedNodeId === id
      const isNeighbor = neighborSet ? neighborSet.has(id) : false
      const isDimmed =
        (highlightedNodeIds.size > 0 && !isHighlighted) || (selectedNodeId != null && !isSelected && !isNeighbor)
      const isHovered = hoveredNodeId === id
      return {
        id,
        isDimmed,
        isHighlighted,
        isHovered,
        isNeighbor,
        isSelected,
      }
    },
    [highlightedNodeIds, hoveredNodeId, neighborSet, selectedNodeId],
  )

  if (!mounted) return null

  const bgColor = 'rgba(0,0,0,0)'
  const mutedFgColor = getCssHslColor('--muted-foreground', isDark ? '#94a3b8' : '#475569')
  const linkColorBase = isDark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.18)'

  return (
    <div ref={containerRef} className="h-full w-full" data-graph-renderer="3d" aria-busy={fittedView !== fitRequest}>
      <ForceGraph3D
        ref={fgRef}
        graphData={graphData}
        width={width}
        height={height}
        backgroundColor={bgColor}
        rendererConfig={{ alpha: true, antialias: true }}
        showNavInfo={false}
        showPointerCursor={false}
        dagMode={dagMode}
        onDagError={reportGraphLayoutCycle}
        cooldownTicks={cooldownTicks}
        cooldownTime={cooldownTime}
        onEngineStop={() => {
          const viewWidth = width ?? containerRef.current?.clientWidth ?? 0
          const viewHeight = height ?? containerRef.current?.clientHeight ?? 0
          const graph = fgRef.current
          if (!graph?.zoomToFit || fittedViewRef.current === fitRequest || viewWidth <= 0 || viewHeight <= 0) return
          graph.zoomToFit(0, Math.min(70, viewWidth * 0.12, viewHeight * 0.12))
          fittedViewRef.current = fitRequest
          setFittedView(fitRequest)
        }}

        // Node styling
        nodeLabel={(node: GraphNodeDatum) => {
          const tooltip = document.createElement('span')
          tooltip.textContent = node.label
          return tooltip.outerHTML
        }}
        nodeColor={(node: GraphNodeDatum) => {
          const color = getNodeColor(node)
          return mixHexColors(color, isDark ? '#dbeafe' : '#fffef9', isDark ? 0.04 : 0.18)
        }}
        nodeVal="val"
        nodeRelSize={nodeRelSize}
        nodeOpacity={0.96}
        nodeResolution={nodeResolution}

        // Link styling
        linkColor={(link: GraphLinkDatum) => {
          const linkId = getRenderLinkId(link)
          const kind = getLinkKind(link)
          const base = link.color?.trim() || EDGE_KIND_COLORS[kind] || linkColorBase
          const baseLineColor = withAlpha(base, isDark ? 0.3 : 0.24)
          const activeLineColor = withAlpha(base, isDark ? 0.68 : 0.56)
          if (linkId !== null && highlightedLinkIds.has(linkId)) return '#f59e0b'
          if (linkId !== null && hoveredLinkId === linkId) return hoverLinkColor
          if (highlightedNodeIds.size > 0) {
            return hasLinkEndpoints(link, highlightedNodeIds) ? activeLineColor : dimLinkColor
          }
          if (neighborSet !== null) {
            return hasLinkEndpoints(link, neighborSet) ? activeLineColor : dimLinkColor
          }
          return baseLineColor
        }}
        linkWidth={(link: GraphLinkDatum) => {
          const linkId = getRenderLinkId(link)
          const base = confidenceToWidth(getGraphLinkDisplayWeight(link))
          if (linkId !== null && highlightedLinkIds.has(linkId)) return 4
          if (linkId !== null && hoveredLinkId === linkId) return 3
          if (neighborSet !== null) {
            return hasLinkEndpoints(link, neighborSet) ? Math.max(1.8, base + 0.6) : 0.45
          }
          return Math.min(3.2, Math.max(0.85, base * 0.88))
        }}
        linkDirectionalParticles={(link: GraphLinkDatum) => {
          const linkId = getRenderLinkId(link)
          if (linkId !== null && highlightedLinkIds.has(linkId)) return 3
          if (linkId !== null && hoveredLinkId === linkId) return 2
          return neighborSet !== null && hasLinkEndpoints(link, neighborSet) ? 1 : 0
        }}
        linkDirectionalParticleWidth={(link: GraphLinkDatum) => {
          const linkId = getRenderLinkId(link)
          if (linkId !== null && highlightedLinkIds.has(linkId)) return 3.8
          if (linkId !== null && hoveredLinkId === linkId) return 3.2
          return 2.2
        }}
        linkDirectionalParticleSpeed={0.0036}
        linkLabel={(link: GraphLinkDatum) => buildGraphLinkProvenanceTooltipHtml(link)}
        linkThreeObjectExtend={allowLinkLabelSprites}
        linkThreeObject={
          allowLinkLabelSprites
            ? (link: GraphLinkDatum) => {
                const label = toTrimmedPrimitiveString(link.label ?? link.predicate ?? link.type)
                if (!label) return new Group()

                const kind = getLinkKind(link)
                const color = link.color?.trim() || EDGE_KIND_COLORS[kind] || hoverLinkColor
                const sprite = new SpriteText(label)
                sprite.color = isDark ? '#dbeafe' : '#334155'
                sprite.textHeight = 1.75
                sprite.fontFace = 'Ragvia Manrope, Ragvia Sans SC, sans-serif'
                sprite.fontWeight = '700'
                sprite.backgroundColor = withAlpha(
                  mixHexColors(color, isDark ? '#0f172a' : '#fffef9', isDark ? 0.72 : 0.86),
                  isDark ? 0.8 : 0.74,
                )
                sprite.borderColor = withAlpha(color, 0.5)
                sprite.borderWidth = 0.55
                sprite.borderRadius = 3
                sprite.padding = [1.5, 0.75]
                sprite.material.depthWrite = false
                sprite.material.depthTest = false
                return sprite
              }
            : undefined
        }
        linkPositionUpdate={
          allowLinkLabelSprites
            ? (sprite: Object3D, { start, end }: { start: GraphPosition; end: GraphPosition }) => {
                sprite.position.set((start.x + end.x) / 2, (start.y + end.y) / 2, (start.z + end.z) / 2)
                return true
              }
            : undefined
        }

        // Interaction
        onNodeClick={handleNodeClick}
        onNodeRightClick={(node: GraphNodeDatum, event: MouseEvent) => onNodeRightClick?.(node, event)}
        onLinkClick={(link: GraphLinkDatum) => onLinkClick?.(link)}
        onLinkRightClick={(link: GraphLinkDatum, event: MouseEvent) => onLinkRightClick?.(link, event)}
        onBackgroundClick={() => onBackgroundClick?.()}
        onBackgroundRightClick={(event: MouseEvent) => onBackgroundRightClick?.(event)}
        onNodeHover={(node: GraphNodeDatum | null) => {
          setHoveredNodeId(node?.id ?? null)
        }}
        onLinkHover={(link: GraphLinkDatum | null) => {
          setHoveredLinkId(link === null ? null : getRenderLinkId(link))
        }}

        enableNodeDrag={!isLargeGraph}
        enableNavigationControls={true}

        // Text sprites
        nodeThreeObject={
          useCustomNodeObjects
            ? (node: GraphNodeDatum) => {
                const { isDimmed, isHighlighted, isHovered, isSelected } = getNodeDecorationState(node)
                const emphasis = isSelected || isHighlighted || isHovered
                const color = getNodeColor(node)
                const labelDirection = (node.x ?? 0) >= 0 ? 1 : -1

                const group = new Group()

                const label = new SpriteText(truncateGraphLabel(node.label, 24))
                label.color = getGraphLabelTextColor({
                  isDimmed,
                  isDark,
                  mutedFgColor,
                })
                label.textHeight = emphasis ? GRAPH_3D_LABEL_TEXT_HEIGHT + 0.15 : GRAPH_3D_LABEL_TEXT_HEIGHT
                label.fontFace = 'Ragvia Manrope, Ragvia Sans SC, sans-serif'
                label.fontWeight = emphasis ? '700' : '600'
                label.backgroundColor = getGraphLabelBackgroundColor({
                  emphasis,
                  color,
                  isDark,
                  labelBgColor,
                })
                label.borderColor = withAlpha(color, emphasis ? 0.72 : 0.38)
                label.borderWidth = 0.85
                label.borderRadius = 4
                label.padding = [2.6, 1.15]
                label.strokeWidth = isDark ? 0.82 : 0.58
                label.strokeColor = labelStrokeColor
                label.center.set(labelDirection === 1 ? 0 : 1, 0.5)
                label.position.set(labelDirection * GRAPH_3D_LABEL_X_OFFSET, GRAPH_3D_LABEL_Y_OFFSET, 0)
                label.material.depthWrite = false
                label.material.depthTest = false
                group.add(label)

                return group
              }
            : undefined
        }
        nodeThreeObjectExtend={useCustomNodeObjects}
      />
    </div>
  )
})

KnowledgeGraph3D.displayName = 'KnowledgeGraph3D'
