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
  readonly onBackgroundClick?: () => void
  readonly highlightedNodeIds?: Set<string>
  readonly highlightedLinkIds?: Set<string>
  readonly showEdgeLabels?: boolean
  readonly layoutMode?: LayoutMode
}

export const GraphViewer = forwardRef<GraphViewerRef, GraphViewerProps>(({ 
  data, 
  onNodeClick,
  onBackgroundClick,
  highlightedNodeIds = new Set(),
  highlightedLinkIds = new Set(),
  showEdgeLabels = true,
  layoutMode = 'force'
}, ref) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<any>(null)
  const { width, height } = useResizeObserver(containerRef)
  const [mounted, setMounted] = useState(false)
  const [hoveredLinkId, setHoveredLinkId] = useState<string | null>(null)

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
    const hasHighlights = highlightedNodeIds.size > 0
    
    if (hasHighlights && !highlightedNodeIds.has(node.id)) {
      return '#334155'
    }

    if (node.color) return node.color

    const kind = String(node?.meta?.kind ?? '').trim()
    if (kind === 'event') {
      return '#6366f1'
    }

    const colors = [
      '#8b5cf6', // Violet
      '#3b82f6', // Blue
      '#10b981', // Emerald
      '#f59e0b', // Amber
      '#ef4444', // Red
      '#ec4899', // Pink
      '#06b6d4', // Cyan
      '#84cc16', // Lime
      '#f97316', // Orange
      '#14b8a6', // Teal
      '#a855f7', // Purple
      '#0ea5e9', // Sky
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
    <div ref={containerRef} className="w-full h-full relative bg-background">
      {(!mounted || width === 0 || height === 0) ? (
        <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
	           {mounted ? (
	              <div className="flex flex-col items-center gap-2">
	                 <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none text-primary" />
	                 <span className="text-xs text-muted-foreground">Initializing...</span>
	              </div>
	           ) : (
	              <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none text-primary" />
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
                 return '#f59e0b' // Amber 500 (Path Highlight)
              }
              if (hoveredLinkId && linkId && hoveredLinkId === linkId) {
                 return '#38bdf8' // Sky 400 (Hover Highlight)
              }
              if (highlightedNodeIds.size > 0) {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source
                const targetId = typeof link.target === 'object' ? link.target.id : link.target
                if (highlightedNodeIds.has(sourceId) && highlightedNodeIds.has(targetId)) {
                  return 'rgba(148, 163, 184, 0.5)' 
                }
                return 'rgba(51, 65, 85, 0.2)' 
              }

              if (linkKind === 'entity_entity') return 'rgba(99, 102, 241, 0.4)'
              return 'rgba(100, 116, 139, 0.25)'
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
              if (linkKind === 'entity_entity') return 1
              return 1.5
           }}
          linkDirectionalArrowLength={(link: any) => (link?.isSelfLoop ? 0 : arrowLength)}
          linkDirectionalArrowRelPos={1}
          linkLabel={(link: any) => buildGraphLinkProvenanceTooltipHtml(link)}
          cooldownTicks={cooldownTicks}
          cooldownTime={cooldownTime}
          onNodeClick={handleNodeClick}
          onBackgroundClick={onBackgroundClick}
          onLinkHover={(link: any) => {
            const linkId = link?.id || (link?.index === undefined ? null : `link-${link.index}`)
            setHoveredLinkId((prev) => (prev === linkId ? prev : linkId))
          }}
          onNodeDragEnd={(node: any) => {
            node.fx = node.x;
            node.fy = node.y;
          }}
          
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const isHighlighted = highlightedNodeIds.size > 0 && highlightedNodeIds.has(node.id)
            const isPathNode = highlightedLinkIds.size > 0 && highlightedNodeIds.has(node.id)
            const isDimmed = (highlightedNodeIds.size > 0 || highlightedLinkIds.size > 0) && !isHighlighted
            const kind = String(node?.meta?.kind ?? '').trim()
            const isEvent = kind === 'event'
            
            const label = node.label || node.id
            const fontSize = isHighlighted ? 13 / globalScale : 11 / globalScale
            const color = getNodeColor(node)
            const baseRadius = isLargeGraph ? 3.5 : 4.5
            const radius = isHighlighted ? baseRadius + 2 : baseRadius
            const x = node.x || 0
            const y = node.y || 0

            ctx.save()

            if (isHighlighted && !isDimmed) {
              ctx.shadowColor = color
              ctx.shadowBlur = 12
            }

            if (isEvent) {
              ctx.save()
              ctx.translate(x, y)
              ctx.rotate(Math.PI / 4)
              const s = radius * 0.85
              ctx.fillStyle = isDimmed ? '#1e293b' : color
              ctx.globalAlpha = isDimmed ? 0.3 : 1
              ctx.fillRect(-s, -s, s * 2, s * 2)
              ctx.restore()
            } else {
              ctx.beginPath()
              ctx.arc(x, y, radius, 0, 2 * Math.PI, false)
              ctx.fillStyle = isDimmed ? '#1e293b' : color
              ctx.globalAlpha = isDimmed ? 0.3 : 0.9
              ctx.fill()
            }

            ctx.globalAlpha = 1
            ctx.shadowBlur = 0

            if (isHighlighted) {
              ctx.beginPath()
              ctx.arc(x, y, radius + 2, 0, 2 * Math.PI, false)
              ctx.strokeStyle = isPathNode ? '#f59e0b' : color
              ctx.lineWidth = 2 / globalScale
              ctx.stroke()
            }

            const shouldShowLabel =
              isHighlighted || (!isLargeGraph && (globalScale > 1.5 || (!isDimmed && globalScale > 1.0)))
            
            if (shouldShowLabel) {
              ctx.font = `${isHighlighted ? '600 ' : ''}${fontSize}px Inter, system-ui, sans-serif`
              ctx.textAlign = 'center'
              ctx.textBaseline = 'middle'
              
              ctx.strokeStyle = 'rgba(0,0,0,0.7)'
              ctx.lineWidth = 2.5 / globalScale
              ctx.strokeText(label, x, y + radius + 4)
              
              ctx.fillStyle = isDimmed ? '#475569' : '#e2e8f0'
              ctx.fillText(label, x, y + radius + 4)
            }

            ctx.restore()
          }}

          // Custom Link Label Painting
          linkCanvasObjectMode={() => 'after'}
          linkCanvasObject={(link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const start = link.source
            const end = link.target

            // Check if source/target are objects (handled by d3) or raw strings
            if (typeof start !== 'object' || typeof end !== 'object') return

            const linkId = link.id || (link.index === undefined ? null : `link-${link.index}`)
            const isPathLink = highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)

            if (!allowEdgeLabels && !isPathLink) return
            if (globalScale < edgeLabelScale && !isPathLink) return

            const label = link.label
            if (!label) return

            // Fallback to 0 if coords missing
            const x1 = start.x || 0
            const y1 = start.y || 0
            const x2 = end.x || 0
            const y2 = end.y || 0

            // Calculate middle point
            const textPos = { x: x1 + (x2 - x1) / 2, y: y1 + (y2 - y1) / 2 }

            const relLink = { x: x2 - x1, y: y2 - y1 };
            const maxTextLength = Math.sqrt(Math.pow(relLink.x, 2) + Math.pow(relLink.y, 2)) - 8;

            let textAngle = Math.atan2(relLink.y, relLink.x);
            if (textAngle > Math.PI / 2) textAngle = -(Math.PI - textAngle);
            if (textAngle < -Math.PI / 2) textAngle = -(-Math.PI - textAngle);

            const fontSize = isPathLink ? 12/globalScale : 10 / globalScale;
            ctx.font = `${isPathLink ? 'bold ':''}${fontSize}px Sans-Serif`;
            
            const textWidth = ctx.measureText(label).width;
            if (textWidth > maxTextLength) return;

            ctx.save();
            ctx.translate(textPos.x, textPos.y);
            ctx.rotate(textAngle);

            ctx.fillStyle = isPathLink ? 'rgba(245, 158, 11, 0.9)' : 'rgba(15, 23, 42, 0.8)';
            ctx.fillRect(-textWidth / 2 - 3, -fontSize / 2 - 1, textWidth + 6, fontSize + 2);

            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = isPathLink ? '#ffffff' : '#94a3b8'; 
            ctx.fillText(label, 0, 0);
            
            ctx.restore();
          }}
        />
      )}
    </div>
  )
})

GraphViewer.displayName = 'GraphViewer'
