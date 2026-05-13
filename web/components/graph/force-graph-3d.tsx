"use client"

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react"
import dynamic from "next/dynamic"
import { useTheme } from "next-themes"
import {
  Group,
  type Object3D,
} from "three"
import SpriteText from "three-spritetext"

import type { GraphEndpointRef, GraphLinkLike, GraphNodeLike } from "@/app/graph/graph-page-utils"
import { getCssHslColor } from "@/lib/css-vars"
import { buildGraphLinkProvenanceTooltipHtml } from "@/lib/graph-provenance"
import { GraphLoadingIndicator } from "./graph-loading-indicator"
import {
  buildTypeColorMap,
  EDGE_KIND_COLORS,
  EVENT_COLOR,
  mixHexColors,
  NODE_COLOR_PALETTE,
  truncateGraphLabel,
  type LayoutMode,
  withAlpha,
} from "./graph-viewer"

function hashCode(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0
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
  curvature?: number
  curveRotation?: number
  isSelfLoop?: boolean
}

type GraphRenderData = Readonly<{
  nodes: GraphNodeDatum[]
  links: GraphLinkDatum[]
}>

type GraphSpriteLike = Object3D & {
  position: { set: (x: number, y: number, z: number) => void }
}

function getLinkKind(link: GraphLinkDatum): string {
  return String(link?.meta?.kind ?? link?.kind ?? "").trim()
}

function getLinkConfidence(link: GraphLinkDatum): number | null {
  const raw = link?.meta?.confidence ?? link?.confidence ?? link?.weight
  const num = Number(raw)
  return Number.isFinite(num) ? num : null
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

function getPrimaryCanvas(root: ParentNode | null): HTMLCanvasElement | null {
  if (!root) return null
  const canvases = Array.from(root.querySelectorAll("canvas")) as HTMLCanvasElement[]
  if (!canvases.length) return null
  return canvases
    .filter((canvas) => Number.isFinite(canvas.width) && Number.isFinite(canvas.height))
    .sort((a, b) => b.width * b.height - a.width * a.height)[0] ?? null
}

// Dynamic import to avoid SSR issues with Three.js
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center bg-background/70 px-6">
      <GraphLoadingIndicator
        className="rounded-2xl border border-border/60 bg-background/88 px-6 py-5 shadow-soft"
        message="正在加载 3D 引擎..."
        srMessage="Loading 3D graph engine"
      />
    </div>
  ),
}) as any

export interface KnowledgeGraph3DRef {
  zoomIn: () => void
  zoomOut: () => void
  zoomToFit: () => void
  focusNode: (nodeId: string) => void
  exportPngDataUrl: () => string | null
  exportSvgString: () => string | null
}

interface ForceGraph3DProps {
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

export const KnowledgeGraph3D = forwardRef<KnowledgeGraph3DRef, ForceGraph3DProps>(
  (
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
      layoutMode = "force",
      width,
      height,
    },
    ref
  ) => {
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === "dark"
    const containerRef = useRef<HTMLDivElement>(null)
    const fgRef = useRef<any>(null)
    const [mounted, setMounted] = useState(false)
    const [hoveredLinkId, setHoveredLinkId] = useState<string | null>(null)
    const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
    const [isCanvasPanning, setIsCanvasPanning] = useState(false)

    useEffect(() => {
      setMounted(true)
    }, [])

    const typeColorMap = useMemo(() => buildTypeColorMap(data.nodes), [data.nodes])
    const neighborSet = useMemo(() => {
      if (!selectedNodeId) return null
      const set = new Set<string>()
      set.add(String(selectedNodeId))
      for (const link of data.links || []) {
        const src = typeof link.source === "object" ? link.source?.id : link.source
        const tgt = typeof link.target === "object" ? link.target?.id : link.target
        if (src === selectedNodeId) set.add(String(tgt))
        if (tgt === selectedNodeId) set.add(String(src))
      }
      return set
    }, [selectedNodeId, data.links])

    const dimNodeColor = isDark ? "#334155" : "#cbd5e1"
    const dimLinkColor = isDark ? "rgba(148, 163, 184, 0.18)" : "#e2e8f0"
    const hoverLinkColor = getCssHslColor("--primary", isDark ? "#38bdf8" : "#0284c7")
    const labelBgColor = isDark ? "rgba(2, 6, 23, 0.84)" : "rgba(255, 254, 249, 0.92)"
    const labelStrokeColor = isDark ? "rgba(15, 23, 42, 0.72)" : "rgba(255, 255, 255, 0.96)"
    const graphCursor = isCanvasPanning ? "grabbing" : (hoveredNodeId || hoveredLinkId ? "pointer" : "grab")
    const isLargeGraph = data.nodes.length > 180 || data.links.length > 360
    const useCustomNodeObjects = !isLargeGraph && data.nodes.length <= 36
    const allowLinkLabelSprites =
      showEdgeLabels && !isLargeGraph && data.links.length <= 40
    const cooldownTicks = isLargeGraph ? 35 : 90
    const cooldownTime = isLargeGraph ? 2500 : 6500
    const nodeRelSize = isLargeGraph ? 3.8 : GRAPH_3D_NODE_REL_SIZE
    const nodeResolution = isLargeGraph ? 8 : 16

    const dagMode = useMemo(() => {
      switch (layoutMode) {
        case "tree":
          return "td"
        case "radial":
          return "radialout"
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

      root.addEventListener("mousedown", handleMouseDown)
      globalThis.window.addEventListener("mouseup", resetPanning)
      globalThis.window.addEventListener("blur", resetPanning)
      globalThis.window.addEventListener("contextmenu", resetPanning)

      return () => {
        root.removeEventListener("mousedown", handleMouseDown)
        globalThis.window.removeEventListener("mouseup", resetPanning)
        globalThis.window.removeEventListener("blur", resetPanning)
        globalThis.window.removeEventListener("contextmenu", resetPanning)
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
        const id = String(node?.id ?? "").trim()
        const hasHighlights = highlightedNodeIds.size > 0
        const isHighlighted = hasHighlights && highlightedNodeIds.has(id)
        const isSelected = selectedNodeId != null && String(selectedNodeId) === id
        const isNeighbor = neighborSet ? neighborSet.has(id) : false
        const isDimmed =
          (hasHighlights && !isHighlighted) || (selectedNodeId && !isSelected && !isNeighbor)

        if (isDimmed) return dimNodeColor
        if (node.color) return node.color

        const kind = String(node?.meta?.kind ?? "").trim()
        if (kind === "event") return EVENT_COLOR

        const type = String(node?.meta?.type ?? node?.type ?? "").trim()
        if (type && typeColorMap.has(type)) return typeColorMap.get(type)!

        if (typeof node.group === "number" && node.group > 0) {
          return NODE_COLOR_PALETTE[(node.group - 1) % NODE_COLOR_PALETTE.length]
        }
        return NODE_COLOR_PALETTE[Math.abs(hashCode(id || "")) % NODE_COLOR_PALETTE.length]
      },
      [highlightedNodeIds, selectedNodeId, neighborSet, dimNodeColor, typeColorMap]
    )

    const getLookAtTarget = useCallback(() => {
      const g = fgRef.current
      const controls = g?.controls?.()
      const t = (controls as any)?.target
      if (t && typeof t.x === "number" && typeof t.y === "number" && typeof t.z === "number") {
        return { x: t.x, y: t.y, z: t.z }
      }
      return { x: 0, y: 0, z: 0 }
    }, [])

    const focusNode = useCallback(
      (nodeId: string) => {
        const node = (data.nodes || []).find((n) => String(n?.id ?? "") === String(nodeId))
        if (!node || !fgRef.current) return

        const distance = 40
        const distRatio = 1 + distance / Math.hypot(node.x || 0, node.y || 0, node.z || 0)
        fgRef.current.cameraPosition(
          { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
          node,
          900
        )
      },
      [data.nodes]
    )

    const zoomIn = useCallback(() => {
      const g = fgRef.current
      const cam = g?.camera?.()
      if (!cam) return
      const target = getLookAtTarget()
      g.cameraPosition(
        { x: cam.position.x * 0.85, y: cam.position.y * 0.85, z: cam.position.z * 0.85 },
        target,
        400
      )
    }, [getLookAtTarget])

    const zoomOut = useCallback(() => {
      const g = fgRef.current
      const cam = g?.camera?.()
      if (!cam) return
      const target = getLookAtTarget()
      g.cameraPosition(
        { x: cam.position.x * 1.15, y: cam.position.y * 1.15, z: cam.position.z * 1.15 },
        target,
        400
      )
    }, [getLookAtTarget])

    const zoomToFit = useCallback(() => {
      if (fgRef.current) {
        fgRef.current.zoomToFit?.(600, 30)
      }
    }, [])

    useImperativeHandle(
      ref,
      () => ({
        zoomIn,
        zoomOut,
        zoomToFit,
        focusNode,
        exportPngDataUrl: () => {
          const g = fgRef.current
          const el = g?.renderer?.()?.domElement
          if (!el) return null
          try {
            return el.toDataURL("image/png")
          } catch {
            return null
          }
        },
        exportSvgString: () => {
          const g = fgRef.current
          const el = g?.renderer?.()?.domElement
          if (!el) return null
          let png = ""
          try {
            png = el.toDataURL("image/png")
          } catch {
            return null
          }
          if (!png) return null
          const w = Math.max(1, el.width || 1)
          const h = Math.max(1, el.height || 1)
          return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">\n  <image href="${png}" width="${w}" height="${h}" />\n</svg>\n`
        },
      }),
      [zoomIn, zoomOut, zoomToFit, focusNode]
    )

    const handleNodeClick = useCallback(
      (node: GraphNodeDatum) => {
        focusNode(String(node?.id ?? ""))
        onNodeClick?.(node)
      },
      [focusNode, onNodeClick]
    )

    const getNodeDecorationState = useCallback(
      (node: GraphNodeDatum) => {
        const id = String(node?.id ?? "").trim()
        const isHighlighted = highlightedNodeIds.size > 0 && highlightedNodeIds.has(id)
        const isSelected = selectedNodeId != null && String(selectedNodeId) === id
        const isNeighbor = neighborSet ? neighborSet.has(id) : false
        const isDimmed =
          (highlightedNodeIds.size > 0 && !isHighlighted) ||
          (selectedNodeId != null && !isSelected && !isNeighbor)
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
      [highlightedNodeIds, hoveredNodeId, neighborSet, selectedNodeId]
    )

    if (!mounted) return null

    const bgColor = "rgba(0,0,0,0)"
    const mutedFgColor = getCssHslColor("--muted-foreground", isDark ? "#94a3b8" : "#475569")
    const linkColorBase = isDark ? "rgba(255,255,255,0.18)" : "rgba(0,0,0,0.18)"

    return (
      <div ref={containerRef} className="h-full w-full">
        <ForceGraph3D
          ref={fgRef}
          graphData={data}
          width={width}
          height={height}
          backgroundColor={bgColor}
          rendererConfig={{ alpha: true, antialias: true }}
          showNavInfo={false}
          showPointerCursor={false}
          dagMode={dagMode}
          cooldownTicks={cooldownTicks}
          cooldownTime={cooldownTime}

        // Node styling
        nodeLabel="label"
        nodeColor={(node: GraphNodeDatum) => {
          const color = getNodeColor(node)
          return mixHexColors(color, isDark ? "#dbeafe" : "#fffef9", isDark ? 0.04 : 0.18)
        }}
        nodeVal="val"
        nodeRelSize={nodeRelSize}
        nodeOpacity={0.96}
        nodeResolution={nodeResolution}

        // Link styling
        linkColor={(link: GraphLinkDatum) => {
          const linkId = String(link?.id || (link?.index === undefined ? '' : `link-${link.index}`) || '')
          const kind = getLinkKind(link)
          const base = String(link?.color || '').trim() || EDGE_KIND_COLORS[kind] || linkColorBase
          const baseLineColor = withAlpha(base, isDark ? 0.3 : 0.24)
          const activeLineColor = withAlpha(base, isDark ? 0.68 : 0.56)
          if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) return "#f59e0b"
          if (hoveredLinkId && linkId && hoveredLinkId === linkId) return hoverLinkColor
          if (highlightedNodeIds.size > 0) {
            const sourceId = String(typeof link.source === "object" ? link.source?.id ?? "" : link.source ?? "")
            const targetId = String(typeof link.target === "object" ? link.target?.id ?? "" : link.target ?? "")
            if (highlightedNodeIds.has(String(sourceId)) && highlightedNodeIds.has(String(targetId))) return activeLineColor
            return dimLinkColor
          }
          if (selectedNodeId && neighborSet) {
            const sourceId = String(typeof link.source === "object" ? link.source?.id ?? "" : link.source ?? "")
            const targetId = String(typeof link.target === "object" ? link.target?.id ?? "" : link.target ?? "")
            if (neighborSet.has(String(sourceId)) && neighborSet.has(String(targetId))) return activeLineColor
            return dimLinkColor
          }
          return baseLineColor
        }}
        linkWidth={(link: GraphLinkDatum) => {
          const linkId = String(link?.id || (link?.index === undefined ? '' : `link-${link.index}`) || '')
          const base = confidenceToWidth(getLinkConfidence(link))
          if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) return 4
          if (hoveredLinkId && linkId && hoveredLinkId === linkId) return 3
          if (selectedNodeId && neighborSet) {
            const sourceId = String(typeof link.source === "object" ? link.source?.id ?? "" : link.source ?? "")
            const targetId = String(typeof link.target === "object" ? link.target?.id ?? "" : link.target ?? "")
            if (neighborSet.has(String(sourceId)) && neighborSet.has(String(targetId))) {
              return Math.max(1.8, base + 0.6)
            }
            return 0.45
          }
          return Math.min(3.2, Math.max(0.85, base * 0.88))
        }}
        linkDirectionalParticles={(link: GraphLinkDatum) => {
          const linkId = String(link?.id || (link?.index === undefined ? '' : `link-${link.index}`) || '')
          if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) return 3
          if (hoveredLinkId && linkId && hoveredLinkId === linkId) return 2
          if (selectedNodeId && neighborSet) {
            const sourceId = String(typeof link.source === "object" ? link.source?.id ?? "" : link.source ?? "")
            const targetId = String(typeof link.target === "object" ? link.target?.id ?? "" : link.target ?? "")
            return neighborSet.has(String(sourceId)) && neighborSet.has(String(targetId)) ? 1 : 0
          }
          return 0
        }}
        linkDirectionalParticleWidth={(link: GraphLinkDatum) => {
          const linkId = String(link?.id || (link?.index === undefined ? '' : `link-${link.index}`) || '')
          if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) return 3.8
          if (hoveredLinkId && linkId && hoveredLinkId === linkId) return 3.2
          return 2.2
        }}
        linkDirectionalParticleSpeed={0.0036}
        linkLabel={(link: GraphLinkDatum) => buildGraphLinkProvenanceTooltipHtml(link)}
        linkThreeObjectExtend={allowLinkLabelSprites}
        linkThreeObject={
          allowLinkLabelSprites
            ? (link: GraphLinkDatum) => {
                const label = String(link?.label ?? link?.predicate ?? link?.type ?? '').trim()
                if (!label) return new Group()

                const kind = getLinkKind(link)
                const color = String(link?.color || '').trim() || EDGE_KIND_COLORS[kind] || hoverLinkColor
                const sprite = new SpriteText(label)
                sprite.color = isDark ? '#dbeafe' : '#334155'
                sprite.textHeight = 1.75
                sprite.fontFace = '-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif'
                sprite.fontWeight = '700'
                sprite.backgroundColor = withAlpha(mixHexColors(color, isDark ? '#0f172a' : '#fffef9', isDark ? 0.72 : 0.86), isDark ? 0.8 : 0.74)
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
            ? (sprite: GraphSpriteLike, { start, end }: { start: { x?: number; y?: number; z?: number }; end: { x?: number; y?: number; z?: number } }) => {
                const x = (start.x ?? 0) + ((end.x ?? 0) - (start.x ?? 0)) * 0.5
                const y = (start.y ?? 0) + ((end.y ?? 0) - (start.y ?? 0)) * 0.5
                const z = (start.z ?? 0) + ((end.z ?? 0) - (start.z ?? 0)) * 0.5
                sprite.position.set(x, y, z)
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
          const nodeId = node?.id ? String(node.id) : null
          setHoveredNodeId((prev) => (prev === nodeId ? prev : nodeId))
        }}
        onLinkHover={(link: GraphLinkDatum | null) => {
          const linkId = String(link?.id || (link?.index === undefined ? '' : `link-${link.index}`) || '')
          setHoveredLinkId((prev) => (prev === linkId ? prev : linkId))
        }}

        enableNodeDrag={!isLargeGraph}
        enableNavigationControls={true}

        // Text sprites
        nodeThreeObject={useCustomNodeObjects ? (node: GraphNodeDatum) => {
          const { id, isDimmed, isHighlighted, isHovered, isSelected } = getNodeDecorationState(node)
          const emphasis = isSelected || isHighlighted || isHovered
          const color = getNodeColor(node)
          const labelDirection = Number(node?.x ?? 0) >= 0 ? 1 : -1

          const group = new Group()

          const label = new SpriteText(truncateGraphLabel(node.label ?? node.id, 24))
          label.color = isDimmed ? mutedFgColor : (isDark ? "#e5eefc" : "#334155")
          label.textHeight = emphasis ? GRAPH_3D_LABEL_TEXT_HEIGHT + 0.15 : GRAPH_3D_LABEL_TEXT_HEIGHT
          label.fontFace = "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
          label.fontWeight = emphasis ? "700" : "600"
          label.backgroundColor = emphasis
            ? withAlpha(mixHexColors(color, isDark ? "#0f172a" : "#fffef9", isDark ? 0.74 : 0.84), isDark ? 0.92 : 0.9)
            : labelBgColor
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
        } : undefined}
        nodeThreeObjectExtend={useCustomNodeObjects}
        />
      </div>
    )
  }
)

KnowledgeGraph3D.displayName = "KnowledgeGraph3D"
