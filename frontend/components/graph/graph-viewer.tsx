'use client'

import dynamic from 'next/dynamic'
import { useRef, useEffect, useState, forwardRef, useImperativeHandle, useCallback, useMemo } from 'react'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import { Loader2 } from 'lucide-react'

// Dynamically import ForceGraph2D via wrapper to handle Ref correctly
const ForceGraph2DNoSSR = dynamic(
  () => import('./force-graph-2d-wrapper'),
  { ssr: false }
)

export interface GraphViewerRef {
  zoomIn: () => void
  zoomOut: () => void
  zoomToFit: () => void
  focusNode: (nodeId: string) => void
}

export type LayoutMode = 'force' | 'tree' | 'radial'

interface GraphViewerProps {
  data: {
    nodes: any[]
    links: any[]
  }
  onNodeClick?: (node: any) => void
  onBackgroundClick?: () => void
  highlightedNodeIds?: Set<string>
  highlightedLinkIds?: Set<string>
  showEdgeLabels?: boolean
  layoutMode?: LayoutMode
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
  const fgRef = useRef<any>()
  const { width, height } = useResizeObserver(containerRef)
  const [mounted, setMounted] = useState(false)

  // Sanitize data to ensure fresh 2D simulation
  // 1. Clone nodes/links to break references (especially when switching from 3D)
  // 2. Convert link source/target objects back to IDs so d3 re-resolves them against the new node array
  // 3. Clear 3D-specific props or fixed positions
  const sanitizedData = useMemo(() => {
    return {
      nodes: data.nodes.map(node => {
        // Destructure to remove 3D specific or fixed position props
        const { fx, fy, fz, vz, vy, vx, z, ...rest } = node
        return { ...rest }
      }),
      links: data.links.map(link => ({
        ...link,
        // Reset source/target to IDs if they are objects (from previous d3 simulation)
        source: (typeof link.source === 'object' && link.source !== null && 'id' in link.source) 
          ? (link.source as any).id 
          : link.source,
        target: (typeof link.target === 'object' && link.target !== null && 'id' in link.target)
          ? (link.target as any).id
          : link.target
      }))
    }
  }, [data])

  // Debug: Log dimensions
  useEffect(() => {
    // Only log if dimensions change or on mount
    if (mounted) {
       console.log('[GraphViewer] Dimensions check:', { width, height })
    }
  }, [width, height, mounted])

  useEffect(() => {
    setMounted(true)
  }, [])

  // Expose methods to parent
  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      console.log('[GraphViewer] zoomIn called. fgRef:', fgRef.current)
      if (fgRef.current) {
        // Inspect available methods
        console.log('[GraphViewer] fgRef methods:', Object.keys(fgRef.current))
        const currentZoom = fgRef.current.zoom()
        console.log('[GraphViewer] currentZoom:', currentZoom)
        fgRef.current.zoom(currentZoom * 1.2, 400)
      } else {
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
    
    const tryZoom = () => {
      if (fgRef.current && sanitizedData.nodes.length > 0) {
        console.log('[GraphViewer] Zooming to fit...')
        fgRef.current.zoomToFit(400, 20)
      } else if (attempts < maxAttempts) {
        attempts++
        setTimeout(tryZoom, 200)
      }
    }
    
    // Initial delay to allow render
    setTimeout(tryZoom, 300)
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
    const colors = [
      '#6366f1', // Indigo 500
      '#ec4899', // Pink 500
      '#10b981', // Emerald 500
      '#f59e0b', // Amber 500
      '#8b5cf6', // Violet 500
      '#3b82f6', // Blue 500
    ]
    const index = typeof node.group === 'number' ? node.group : 0
    return colors[index % colors.length]
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
                 <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                 <span className="text-xs">Initializing Layout... ({Math.round(width)}x{Math.round(height)})</span>
              </div>
           ) : (
              <Loader2 className="w-8 h-8 animate-spin" />
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
          nodeRelSize={6}
          // Layout Config
          dagMode={getDagMode()}
          dagLevelDistance={50}
          
          // Link styling
          linkColor={(link: any) => {
             const linkId = link.id || (link.index !== undefined ? `link-${link.index}` : null)
             if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) {
                return '#f59e0b' // Amber 500 (Path Highlight)
             }
             if (highlightedNodeIds.size > 0) {
               const sourceId = typeof link.source === 'object' ? link.source.id : link.source
               const targetId = typeof link.target === 'object' ? link.target.id : link.target
               if (highlightedNodeIds.has(sourceId) && highlightedNodeIds.has(targetId)) {
                 return '#94a3b8' 
               }
               return '#e2e8f0' 
             }
             return '#cbd5e1'
          }}
          linkWidth={(link: any) => {
            const linkId = link.id || (link.index !== undefined ? `link-${link.index}` : null)
            if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) {
                return 4 
             }
             if (highlightedNodeIds.size > 0) return 1
             return 1.5
          }}
          linkDirectionalArrowLength={3.5}
          linkDirectionalArrowRelPos={1}
          cooldownTicks={100}
          onNodeClick={handleNodeClick}
          onBackgroundClick={onBackgroundClick}
          onNodeDragEnd={(node: any) => {
            node.fx = node.x;
            node.fy = node.y;
          }}
          
          // Custom Node Painting
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const isHighlighted = highlightedNodeIds.size > 0 && highlightedNodeIds.has(node.id)
            const isPathNode = highlightedLinkIds.size > 0 && highlightedNodeIds.has(node.id)
            const isDimmed = (highlightedNodeIds.size > 0 || highlightedLinkIds.size > 0) && !isHighlighted
            
            const label = node.label || node.id;
            const fontSize = isHighlighted ? 14 / globalScale : 12 / globalScale;
            
            // Draw Node Circle
            const color = getNodeColor(node)
            ctx.beginPath();
            const radius = isHighlighted ? 7 : 5
            ctx.arc(node.x || 0, node.y || 0, radius, 0, 2 * Math.PI, false);
            ctx.fillStyle = color;
            ctx.fill();
            
            // Halo/Border for highlighted nodes
            if (isHighlighted) {
               ctx.strokeStyle = '#fff';
               ctx.lineWidth = 4 / globalScale;
               ctx.stroke();
               
               // Double border for path nodes
               if (isPathNode) {
                 ctx.strokeStyle = '#f59e0b'; // Amber border for path
               } else {
                 ctx.strokeStyle = color;
               }
               
               ctx.lineWidth = 2 / globalScale;
               ctx.stroke();
            } else {
               ctx.strokeStyle = '#fff';
               ctx.lineWidth = 1.5 / globalScale;
               ctx.stroke();
            }

            // Draw Label
            const shouldShowLabel = isHighlighted || globalScale > 1.5 || (!isDimmed && globalScale > 1.2)
            
            if (shouldShowLabel) {
              ctx.font = `${isHighlighted ? 'bold ' : ''}${fontSize}px Sans-Serif`;
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              
              // Text Shadow
              ctx.strokeStyle = 'rgba(255,255,255,0.9)';
              ctx.lineWidth = 3 / globalScale;
              ctx.strokeText(label, node.x || 0, (node.y || 0) + radius + 4);
              
              ctx.fillStyle = isDimmed ? '#94a3b8' : '#1e293b'; 
              ctx.fillText(label, node.x || 0, (node.y || 0) + radius + 4);
            }
          }}

          // Custom Link Label Painting
          linkCanvasObjectMode={() => 'after'}
          linkCanvasObject={(link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
            const start = link.source
            const end = link.target

            // Check if source/target are objects (handled by d3) or raw strings
            if (typeof start !== 'object' || typeof end !== 'object') return

            const linkId = link.id || (link.index !== undefined ? `link-${link.index}` : null)
            const isPathLink = highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)

            if (!showEdgeLabels && !isPathLink) return
            if (globalScale < 2 && !isPathLink) return

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

            ctx.fillStyle = isPathLink ? '#f59e0b' : 'rgba(255, 255, 255, 0.8)';
            ctx.fillRect(-textWidth / 2 - 2, -fontSize / 2 - 1, textWidth + 4, fontSize + 2);

            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = isPathLink ? '#ffffff' : '#64748b'; 
            ctx.fillText(label, 0, 0);
            
            ctx.restore();
          }}
        />
      )}
    </div>
  )
})

GraphViewer.displayName = 'GraphViewer'
