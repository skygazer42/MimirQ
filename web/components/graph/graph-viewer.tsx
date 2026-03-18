'use client'

import dynamic from 'next/dynamic'
import { useRef, useEffect, useState, forwardRef, useImperativeHandle, useCallback, useMemo } from 'react'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import { decorateLinksForDisplay } from '@/lib/graph-edge-display'
import { buildGraphLinkProvenanceTooltipHtml } from '@/lib/graph-provenance'
import { Loader2 } from 'lucide-react'

// Dynamically import ForceGraph2D via wrapper to handle Ref correctly
const ForceGraph2DNoSSR = dynamic(
  () => import('./force-graph-2d-wrapper'),
  { ssr: false }
)
const isDev = process.env.NODE_ENV !== 'production'
const LARGE_GRAPH_NODE_THRESHOLD = 600
const LARGE_GRAPH_LINK_THRESHOLD = 1200

export interface GraphViewerRef {
  zoomIn: () => void
  zoomOut: () => void
  zoomToFit: () => void
  focusNode: (nodeId: string) => void
}

export type LayoutMode = 'force' | 'tree' | 'radial'

interface GraphViewerProps {
  readonly data: {
    nodes: any[]
    links: any[]
  }
  readonly onNodeClick?: (node: any) => void
  readonly onLinkClick?: (link: any) => void
  readonly onBackgroundClick?: () => void
  readonly highlightedNodeIds?: Set<string>
  readonly highlightedLinkIds?: Set<string>
  readonly selectedNodeId?: string | null
  readonly showEdgeLabels?: boolean
  readonly layoutMode?: LayoutMode
}

export const GraphViewer = forwardRef<GraphViewerRef, GraphViewerProps>(({ 
  data, 
  onNodeClick,
  onLinkClick,
  onBackgroundClick,
  highlightedNodeIds = new Set(),
  highlightedLinkIds = new Set(),
  selectedNodeId = null,
  showEdgeLabels = true,
  layoutMode = 'force'
}, ref) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<any>(null)
  const { width, height } = useResizeObserver(containerRef)
  const [mounted, setMounted] = useState(false)
  const [hoveredLinkId, setHoveredLinkId] = useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)

  const neighborSet = useMemo(() => {
    if (!selectedNodeId) return null
    const set = new Set<string>()
    set.add(selectedNodeId)
    for (const link of data.links) {
      const src = typeof link.source === 'object' ? link.source?.id : link.source
      const tgt = typeof link.target === 'object' ? link.target?.id : link.target
      if (src === selectedNodeId) set.add(String(tgt))
      if (tgt === selectedNodeId) set.add(String(src))
    }
    return set
  }, [selectedNodeId, data.links])

  const nodeDegreeMap = useMemo(() => {
    const map = new Map<string, number>()
    for (const link of data.links) {
      const src = typeof link.source === 'object' ? link.source?.id : link.source
      const tgt = typeof link.target === 'object' ? link.target?.id : link.target
      map.set(String(src), (map.get(String(src)) || 0) + 1)
      map.set(String(tgt), (map.get(String(tgt)) || 0) + 1)
    }
    return map
  }, [data.links])

  // Sanitize data to ensure fresh 2D simulation
  // 1. Clone nodes/links to break references (especially when switching from 3D)
  // 2. Convert link source/target objects back to IDs so d3 re-resolves them against the new node array
  // 3. Clear 3D-specific props or fixed positions
  const sanitizedData = useMemo(() => {
    const nodes = data.nodes.map(node => {
      // Destructure to remove 3D specific or fixed position props
      const { fx, fy, fz, vz, vy, vx, z, ...rest } = node
      return { ...rest }
    })

    const links = data.links.map(link => ({
      ...link,
      // Reset source/target to IDs if they are objects (from previous d3 simulation)
      source: (typeof link.source === 'object' && link.source !== null && 'id' in link.source)
        ? (link.source).id
        : link.source,
      target: (typeof link.target === 'object' && link.target !== null && 'id' in link.target)
        ? (link.target).id
        : link.target
    }))

    // Spread parallel links and draw self-loops deterministically.
    decorateLinksForDisplay(links as any[])

    return { nodes, links }
  }, [data])
  const isLargeGraph = useMemo(
    () =>
      sanitizedData.nodes.length > LARGE_GRAPH_NODE_THRESHOLD ||
      sanitizedData.links.length > LARGE_GRAPH_LINK_THRESHOLD,
    [sanitizedData.links.length, sanitizedData.nodes.length]
  )
  const allowEdgeLabels = showEdgeLabels && !isLargeGraph
  const edgeLabelScale = isLargeGraph ? 2.5 : 2
  const nodeRelSize = isLargeGraph ? 4 : 6
  const arrowLength = isLargeGraph ? 0 : 3.5
  const cooldownTicks = isLargeGraph ? 50 : 100
  const cooldownTime = isLargeGraph ? 4000 : 8000

  // Debug: Log dimensions
  useEffect(() => {
    // Only log if dimensions change or on mount
    if (mounted && isDev) {
      console.log('[GraphViewer] Dimensions check:', { width, height })
    }
  }, [width, height, mounted])

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    if (typeof document === 'undefined') return

    const handleVisibility = () => {
      const isHidden = document.visibilityState === 'hidden'
      const graph = fgRef.current
      if (!graph) return
      if (isHidden) {
        graph.pauseAnimation?.()
      } else {
        graph.resumeAnimation?.()
      }
    }

    handleVisibility()
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  // Expose methods to parent
  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      if (isDev) {
        console.log('[GraphViewer] zoomIn called. fgRef:', fgRef.current)
      }
      if (fgRef.current) {
        if (isDev) {
          console.log('[GraphViewer] fgRef methods:', Object.keys(fgRef.current))
        }
        const currentZoom = fgRef.current.zoom()
        if (isDev) {
          console.log('[GraphViewer] currentZoom:', currentZoom)
        }
        fgRef.current.zoom(currentZoom * 1.2, 400)
      } else if (isDev) {
          console.warn('[GraphViewer] fgRef.current is null/undefined')
        }
    },
    zoomOut: () => {
      if (fgRef.current) {
        const currentZoom = fgRef.current.zoom()
        fgRef.current.zoom(currentZoom / 1.2, 400)
      }
    },
    zoomToFit: () => {
      if (fgRef.current) {
        fgRef.current.zoomToFit(400, 20)
      }
    },
    focusNode: (nodeId: string) => {
      // Use sanitizedData because that's what d3 is updating with x,y coords
      const node = sanitizedData.nodes.find(n => n.id === nodeId)
      if (node && fgRef.current) {
        fgRef.current.centerAt(node.x, node.y, 1000)
        fgRef.current.zoom(3, 1000)
      }
    }
  }))

  // Auto zoom fit on data change
  useEffect(() => {
    let attempts = 0
    const maxAttempts = 10
    let timeoutId: number | null = null
    
    const tryZoom = () => {
      if (fgRef.current && sanitizedData.nodes.length > 0) {
        if (isDev) {
          console.log('[GraphViewer] Zooming to fit...')
        }
        fgRef.current.zoomToFit(400, 20)
      } else if (attempts < maxAttempts) {
        attempts++
        timeoutId = globalThis.window.setTimeout(tryZoom, 200)
      }
    }
    
    // Initial delay to allow render
    timeoutId = globalThis.window.setTimeout(tryZoom, 300)
    return () => {
      if (timeoutId != null) {
        clearTimeout(timeoutId)
      }
    }
  }, [sanitizedData])

  const handleNodeClick = useCallback((node: any) => {
    if (fgRef.current) {
      fgRef.current.centerAt(node.x, node.y, 400)
      fgRef.current.zoom(2.5, 400)
    }
    if (onNodeClick) {
      onNodeClick(node)
    }
  }, [onNodeClick])

  const getNodeColor = (node: any) => {
    // If specific nodes are highlighted (search or path), dim others
    const hasHighlights = highlightedNodeIds.size > 0
    
    if (hasHighlights && !highlightedNodeIds.has(node.id)) {
      return '#cbd5e1' // Dimmed color (slate-300)
    }

    if (node.color) return node.color

    // Keep events visually distinct (they tend to have longer labels and high degree).
    const kind = String(node?.meta?.kind ?? '').trim()
    if (kind === 'event') {
      return '#6366f1' // Indigo 500
    }

    // Use a larger palette so type buckets remain visually distinct.
    const colors = [
      '#ec4899', // Pink 500
      '#10b981', // Emerald 500
      '#f59e0b', // Amber 500
      '#8b5cf6', // Violet 500
      '#3b82f6', // Blue 500
      '#06b6d4', // Cyan 500
      '#84cc16', // Lime 500
      '#f97316', // Orange 500
      '#ef4444', // Red 500
      '#14b8a6', // Teal 500
      '#22c55e', // Green 500
      '#eab308', // Yellow 500
      '#0ea5e9', // Sky 500
      '#a855f7', // Purple 500
      '#fb7185', // Rose 400
      '#4ade80', // Green 400
      '#2dd4bf', // Teal 400
      '#38bdf8', // Sky 400
      '#f472b6', // Pink 400
      '#c084fc', // Purple 400
      '#facc15', // Yellow 400
      '#a3e635', // Lime 400
      '#67e8f9', // Cyan 300
      '#f43f5e', // Rose 500
    ]
    const rawGroup = typeof node.group === 'number' ? node.group : 0
    const idx = rawGroup > 0 ? (rawGroup - 1) % colors.length : 0
    return colors[idx]
  }

  // Determine DAG mode based on layoutMode
  const getDagMode = () => {
    switch (layoutMode) {
      case 'tree': return 'td' // Top-Down
      case 'radial': return 'radialout'
      default: return undefined // Force Directed
    }
  }

  return (
    <div ref={containerRef} className="w-full h-full relative bg-slate-50/50">
      {(!mounted || width === 0 || height === 0) ? (
        <div className="absolute inset-0 flex items-center justify-center text-slate-400">
	           {mounted ? (
	              <div className="flex flex-col items-center gap-2">
	                 <Loader2 className="w-6 h-6 animate-spin motion-reduce:animate-none text-sky-500" />
	                 <span className="text-xs">Initializing Layout... ({Math.round(width)}x{Math.round(height)})</span>
	              </div>
	           ) : (
	              <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none" />
	           )}
        </div>
      ) : (
        <ForceGraph2DNoSSR
          graphRef={fgRef}
          width={width}
          height={height}
          graphData={sanitizedData}
          backgroundColor="rgba(0,0,0,0)"
          nodeLabel="label"
          nodeColor={getNodeColor}
          nodeRelSize={nodeRelSize}
          // Layout Config
          dagMode={getDagMode()}
          dagLevelDistance={50}
          
          // Link styling
          linkCurvature={(link: any) => {
            const v = link?.curvature
            return typeof v === 'number' && Number.isFinite(v) ? v : 0
          }}
          linkCurveRotation={(link: any) => {
            const v = link?.curveRotation
            return typeof v === 'number' && Number.isFinite(v) ? v : 0
          }}
          linkColor={(link: any) => {
             const linkId = link.id || (link.index === undefined ? null : `link-${link.index}`)
             const linkKind = link?.meta?.kind || link?.kind
              if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) {
                 return '#f59e0b'
              }
              if (hoveredLinkId && linkId && hoveredLinkId === linkId) {
                 return '#38bdf8'
              }
              if (highlightedNodeIds.size > 0) {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target
                if (highlightedNodeIds.has(sourceId) && highlightedNodeIds.has(targetId)) {
                  return '#94a3b8' 
                }
                return '#e2e8f0' 
              }
              if (selectedNodeId && !isLargeGraph) {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target
                if (sourceId === selectedNodeId || targetId === selectedNodeId) {
                  return '#e879a0'
                }
                return '#e2e8f0'
              }

              if (linkKind === 'entity_entity') return '#67e8f9'
              return '#cbd5e1'
           }}
          linkWidth={(link: any) => {
             const linkId = link.id || (link.index === undefined ? null : `link-${link.index}`)
             const linkKind = link?.meta?.kind || link?.kind
             if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) {
                 return 4 
              }
              if (hoveredLinkId && linkId && hoveredLinkId === linkId) {
                 return 3
              }
              if (highlightedNodeIds.size > 0) return 1
              if (selectedNodeId && !isLargeGraph) {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target
                if (sourceId === selectedNodeId || targetId === selectedNodeId) return 2.5
                return 0.5
              }
              if (linkKind === 'entity_entity') return 1
              return 1.5
           }}
          linkDirectionalArrowLength={(link: any) => (link?.isSelfLoop ? 0 : arrowLength)}
          linkDirectionalArrowRelPos={1}
          linkLabel={(link: any) => buildGraphLinkProvenanceTooltipHtml(link)}
          cooldownTicks={cooldownTicks}
          cooldownTime={cooldownTime}
          onNodeClick={handleNodeClick}
          onLinkClick={(link: any) => { onLinkClick?.(link) }}
          onBackgroundClick={onBackgroundClick}
          onNodeHover={(node: any) => {
            if (isLargeGraph) return
            const id = node?.id ?? null
            setHoveredNodeId((prev) => (prev === id ? prev : id))
          }}
          onLinkHover={(link: any) => {
            const linkId = link?.id || (link?.index === undefined ? null : `link-${link.index}`)
            setHoveredLinkId((prev) => (prev === linkId ? prev : linkId))
          }}
          onNodeDragEnd={(node: any) => {
            node.fx = node.x;
            node.fy = node.y;
          }}
          
          // Custom Node Painting
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const isHighlighted = highlightedNodeIds.size > 0 && highlightedNodeIds.has(node.id)
            const isPathNode = highlightedLinkIds.size > 0 && highlightedNodeIds.has(node.id)
            const isSelected = selectedNodeId === node.id
            const isNeighbor = neighborSet ? neighborSet.has(node.id) : false
            const isDimmed = (
              ((highlightedNodeIds.size > 0 || highlightedLinkIds.size > 0) && !isHighlighted)
              || (selectedNodeId && !isLargeGraph && !isSelected && !isNeighbor)
            )
            const isHovered = hoveredNodeId === node.id && !isLargeGraph

            const rawLabel = node.label || node.id
            const label = rawLabel.length > 16 ? rawLabel.substring(0, 15) + '\u2026' : rawLabel
            const fontSize = (isHighlighted || isSelected) ? 14 / globalScale : 12 / globalScale

            const color = getNodeColor(node)
            const degree = nodeDegreeMap.get(String(node.id)) || 0
            const baseRadius = isLargeGraph ? 4 : 5
            const degreeBonus = isLargeGraph ? 0 : Math.min(degree * 0.4, 4)
            let radius = baseRadius + degreeBonus
            if (isHighlighted || isSelected) radius += 2
            if (isHovered) radius += 1

            const nx = node.x || 0
            const ny = node.y || 0

            ctx.globalAlpha = isDimmed ? 0.35 : 1

            if (isHovered && !isSelected) {
              ctx.save()
              ctx.beginPath()
              ctx.arc(nx, ny, radius + 4, 0, 2 * Math.PI)
              ctx.fillStyle = color
              ctx.globalAlpha = 0.15
              ctx.fill()
              ctx.restore()
              ctx.globalAlpha = isDimmed ? 0.35 : 1
            }

            ctx.beginPath()
            ctx.arc(nx, ny, radius, 0, 2 * Math.PI, false)
            ctx.fillStyle = color
            ctx.fill()

            if (isSelected) {
              ctx.strokeStyle = '#fff'
              ctx.lineWidth = 4 / globalScale
              ctx.stroke()
              ctx.beginPath()
              ctx.arc(nx, ny, radius + 2 / globalScale, 0, 2 * Math.PI, false)
              ctx.strokeStyle = '#E91E63'
              ctx.lineWidth = 2.5 / globalScale
              ctx.stroke()
            } else if (isHighlighted) {
              ctx.strokeStyle = '#fff'
              ctx.lineWidth = 4 / globalScale
              ctx.stroke()
              ctx.beginPath()
              ctx.arc(nx, ny, radius + 2 / globalScale, 0, 2 * Math.PI, false)
              ctx.strokeStyle = isPathNode ? '#f59e0b' : color
              ctx.lineWidth = 2 / globalScale
              ctx.stroke()
            } else if (isHovered) {
              ctx.strokeStyle = '#333'
              ctx.lineWidth = 2.5 / globalScale
              ctx.stroke()
            } else {
              ctx.strokeStyle = '#fff'
              ctx.lineWidth = 1.5 / globalScale
              ctx.stroke()
            }

            const shouldShowLabel =
              isHighlighted || isSelected || isHovered
              || (!isLargeGraph && (globalScale > 1.5 || (!isDimmed && globalScale > 1.2)))

            if (shouldShowLabel) {
              ctx.font = `${(isHighlighted || isSelected) ? 'bold ' : ''}${fontSize}px Sans-Serif`
              ctx.textAlign = 'center'
              ctx.textBaseline = 'middle'

              ctx.strokeStyle = 'rgba(255,255,255,0.92)'
              ctx.lineWidth = 3.5 / globalScale
              ctx.strokeText(label, nx, ny + radius + 4)

              ctx.fillStyle = isDimmed ? '#94a3b8' : '#1e293b'
              ctx.fillText(label, nx, ny + radius + 4)
            }

            ctx.globalAlpha = 1
          }}

          // Custom Link Label Painting
          linkCanvasObjectMode={() => 'after'}
          linkCanvasObject={(link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const start = link.source
            const end = link.target

            if (typeof start !== 'object' || typeof end !== 'object') return

            const linkId = link.id || (link.index === undefined ? null : `link-${link.index}`)
            const isPathLink = highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)
            const isHoveredLink = hoveredLinkId != null && linkId === hoveredLinkId
            const isAccent = isPathLink || isHoveredLink

            if (!allowEdgeLabels && !isAccent) return
            if (globalScale < edgeLabelScale && !isAccent) return

            const label = link.label
            if (!label) return

            const x1 = start.x || 0
            const y1 = start.y || 0
            const x2 = end.x || 0
            const y2 = end.y || 0

            const textPos = { x: x1 + (x2 - x1) / 2, y: y1 + (y2 - y1) / 2 }

            const relLink = { x: x2 - x1, y: y2 - y1 }
            const maxTextLength = Math.sqrt(relLink.x ** 2 + relLink.y ** 2) - 8

            let textAngle = Math.atan2(relLink.y, relLink.x)
            if (textAngle > Math.PI / 2) textAngle = -(Math.PI - textAngle)
            if (textAngle < -Math.PI / 2) textAngle = -(-Math.PI - textAngle)

            const fontSize = isAccent ? 12 / globalScale : 11 / globalScale
            ctx.font = `${isAccent ? 'bold ' : ''}${fontSize}px Sans-Serif`

            const textWidth = ctx.measureText(label).width
            if (textWidth > maxTextLength) return

            ctx.save()
            ctx.translate(textPos.x, textPos.y)
            ctx.rotate(textAngle)

            const padX = 4
            const padY = 2
            const rx = 3 / globalScale
            const bx = -textWidth / 2 - padX
            const by = -fontSize / 2 - padY
            const bw = textWidth + padX * 2
            const bh = fontSize + padY * 2

            ctx.beginPath()
            ctx.moveTo(bx + rx, by)
            ctx.lineTo(bx + bw - rx, by)
            ctx.quadraticCurveTo(bx + bw, by, bx + bw, by + rx)
            ctx.lineTo(bx + bw, by + bh - rx)
            ctx.quadraticCurveTo(bx + bw, by + bh, bx + bw - rx, by + bh)
            ctx.lineTo(bx + rx, by + bh)
            ctx.quadraticCurveTo(bx, by + bh, bx, by + bh - rx)
            ctx.lineTo(bx, by + rx)
            ctx.quadraticCurveTo(bx, by, bx + rx, by)
            ctx.closePath()

            if (isPathLink) {
              ctx.fillStyle = '#f59e0b'
            } else if (isHoveredLink) {
              ctx.fillStyle = 'rgba(56, 189, 248, 0.15)'
            } else {
              ctx.fillStyle = 'rgba(255, 255, 255, 0.95)'
            }
            ctx.fill()

            ctx.textAlign = 'center'
            ctx.textBaseline = 'middle'
            ctx.fillStyle = isPathLink ? '#ffffff' : isHoveredLink ? '#0c4a6e' : '#475569'
            ctx.fillText(label, 0, 0)

            ctx.restore()
          }}
        />
      )}
    </div>
  )
})

GraphViewer.displayName = 'GraphViewer'
