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
import SpriteText from "three-spritetext"
import { Loader2 } from "lucide-react"

import { getCssHslColor } from "@/lib/css-vars"
import { buildGraphLinkProvenanceTooltipHtml } from "@/lib/graph-provenance"
import { buildTypeColorMap, EDGE_KIND_COLORS, EVENT_COLOR, NODE_COLOR_PALETTE, type LayoutMode } from "./graph-viewer"

function hashCode(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0
  return h
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

function getLinkKind(link: any): string {
  return String(link?.meta?.kind ?? link?.kind ?? "").trim()
}

function getLinkConfidence(link: any): number | null {
  const raw = link?.meta?.confidence ?? link?.confidence ?? link?.weight
  const num = Number(raw)
  return Number.isFinite(num) ? num : null
}

function confidenceToWidth(confidence: number | null): number {
  const c = confidence == null ? 0.55 : clamp01(confidence)
  return 0.75 + c * 2.25
}

// Dynamic import to avoid SSR issues with Three.js
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full w-full bg-background">
      <Loader2 className="h-8 w-8 text-primary animate-spin motion-reduce:animate-none" />
    </div>
  ),
})

export interface KnowledgeGraph3DRef {
  zoomIn: () => void
  zoomOut: () => void
  zoomToFit: () => void
  focusNode: (nodeId: string) => void
  exportPngDataUrl: () => string | null
  exportSvgString: () => string | null
}

interface ForceGraph3DProps {
  readonly data: {
    nodes: any[]
    links: any[]
  }
  readonly onNodeClick?: (node: any) => void
  readonly onNodeRightClick?: (node: any, event: MouseEvent) => void
  readonly onLinkClick?: (link: any) => void
  readonly onLinkRightClick?: (link: any, event: MouseEvent) => void
  readonly onBackgroundClick?: () => void
  readonly onBackgroundRightClick?: (event: MouseEvent) => void
  readonly highlightedNodeIds?: Set<string>
  readonly highlightedLinkIds?: Set<string>
  readonly selectedNodeId?: string | null
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
      layoutMode = "force",
      width,
      height,
    },
    ref
  ) => {
    const { resolvedTheme } = useTheme()
    const isDark = resolvedTheme === "dark"
    const fgRef = useRef<any>(null)
    const [mounted, setMounted] = useState(false)
    const [hoveredLinkId, setHoveredLinkId] = useState<string | null>(null)

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
    const midLinkColor = isDark ? "#64748b" : "#94a3b8"
    const hoverLinkColor = getCssHslColor("--primary", isDark ? "#38bdf8" : "#0284c7")

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

    const getNodeColor = useCallback(
      (node: any) => {
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
        const node = (data.nodes || []).find((n: any) => String(n?.id ?? "") === String(nodeId))
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
      (node: any) => {
        focusNode(String(node?.id ?? ""))
        onNodeClick?.(node)
      },
      [focusNode, onNodeClick]
    )

    if (!mounted) return null

    const bgColor = getCssHslColor("--background", isDark ? "#020617" : "#ffffff")
    const mutedFgColor = getCssHslColor("--muted-foreground", isDark ? "#94a3b8" : "#475569")
    const linkColorBase = isDark ? "rgba(255,255,255,0.18)" : "rgba(0,0,0,0.18)"

    return (
      <ForceGraph3D
        ref={fgRef}
        graphData={data}
        width={width}
        height={height}
        backgroundColor={bgColor}
        showNavInfo={false}
        dagMode={dagMode}

        // Node styling
        nodeLabel="label"
        nodeColor={(node: any) => getNodeColor(node)}
        nodeRelSize={6}
        nodeOpacity={0.92}
        nodeResolution={16}

        // Link styling
        linkColor={(link: any) => {
          const linkId = link?.id || (link?.index === undefined ? null : `link-${link.index}`)
          const kind = getLinkKind(link)
          const base = EDGE_KIND_COLORS[kind] || linkColorBase
          if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) return "#f59e0b"
          if (hoveredLinkId && linkId && hoveredLinkId === linkId) return hoverLinkColor
          if (highlightedNodeIds.size > 0) {
            const sourceId = typeof link.source === "object" ? link.source.id : link.source
            const targetId = typeof link.target === "object" ? link.target.id : link.target
            if (highlightedNodeIds.has(String(sourceId)) && highlightedNodeIds.has(String(targetId))) return midLinkColor
            return dimLinkColor
          }
          if (selectedNodeId && neighborSet) {
            const sourceId = typeof link.source === "object" ? link.source.id : link.source
            const targetId = typeof link.target === "object" ? link.target.id : link.target
            if (neighborSet.has(String(sourceId)) && neighborSet.has(String(targetId))) return base
            return dimLinkColor
          }
          return base
        }}
        linkWidth={(link: any) => {
          const linkId = link?.id || (link?.index === undefined ? null : `link-${link.index}`)
          const base = confidenceToWidth(getLinkConfidence(link))
          if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) return 4
          if (hoveredLinkId && linkId && hoveredLinkId === linkId) return 3
          return base
        }}
        linkDirectionalParticles={2}
        linkDirectionalParticleWidth={2}
        linkDirectionalParticleSpeed={0.005}
        linkLabel={(link: any) => buildGraphLinkProvenanceTooltipHtml(link)}

        // Interaction
        onNodeClick={handleNodeClick}
        onNodeRightClick={(node: any, event: MouseEvent) => onNodeRightClick?.(node, event)}
        onLinkClick={(link: any) => onLinkClick?.(link)}
        onLinkRightClick={(link: any, event: MouseEvent) => onLinkRightClick?.(link, event)}
        onBackgroundClick={() => onBackgroundClick?.()}
        onBackgroundRightClick={(event: MouseEvent) => onBackgroundRightClick?.(event)}
        onLinkHover={(link: any) => {
          const linkId = link?.id || (link?.index === undefined ? null : `link-${link.index}`)
          setHoveredLinkId((prev) => (prev === linkId ? prev : linkId))
        }}

        enableNodeDrag={true}
        enableNavigationControls={true}

        // Text sprites
        nodeThreeObject={(node: any) => {
          const sprite = new SpriteText(String(node.label ?? node.id ?? ""))
          sprite.color = mutedFgColor
          sprite.textHeight = 4
          sprite.position.y = 8
          return sprite
        }}
        nodeThreeObjectExtend={true}
      />
    )
  }
)

KnowledgeGraph3D.displayName = "KnowledgeGraph3D"
