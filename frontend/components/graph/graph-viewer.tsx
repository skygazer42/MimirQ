'use client'

import dynamic from 'next/dynamic'
import { useRef, useEffect, useState, forwardRef, useImperativeHandle, useCallback } from 'react'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import { Loader2 } from 'lucide-react'

// Dynamically import ForceGraph2D
const ForceGraph2DNoSSR = dynamic(
  () => import('react-force-graph-2d'),
  { ssr: false }
)

export interface GraphViewerRef {
  zoomIn: () => void
  zoomOut: () => void
  zoomToFit: () => void
  focusNode: (nodeId: string) => void
}

interface GraphViewerProps {
  data: {
    nodes: any[]
    links: any[]
  }
  onNodeClick?: (node: any) => void
  onBackgroundClick?: () => void
  highlightedNodeIds?: Set<string>
  showEdgeLabels?: boolean
}

export const GraphViewer = forwardRef<GraphViewerRef, GraphViewerProps>(({ 
  data, 
  onNodeClick,
  onBackgroundClick,
  highlightedNodeIds = new Set(),
  showEdgeLabels = true
}, ref) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<any>()
  const { width, height } = useResizeObserver(containerRef)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  // Expose methods to parent
  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      if (fgRef.current) {
        const currentZoom = fgRef.current.zoom()
        fgRef.current.zoom(currentZoom * 1.2, 400)
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
      const node = data.nodes.find(n => n.id === nodeId)
      if (node && fgRef.current) {
        fgRef.current.centerAt(node.x, node.y, 1000)
        fgRef.current.zoom(3, 1000)
      }
    }
  }))

  // Auto zoom fit on data change
  useEffect(() => {
    if (fgRef.current && data.nodes.length > 0) {
      setTimeout(() => {
        fgRef.current.zoomToFit(400, 20)
      }, 500)
    }
  }, [data])

  const handleNodeClick = useCallback((node: any) => {
    if (fgRef.current) {
      fgRef.current.centerAt(node.x, node.y, 400)
      fgRef.current.zoom(2.5, 400)
    }
    if (onNodeClick) {
      onNodeClick(node)
    }
  }, [onNodeClick])

  if (!mounted) {
    return (
      <div className="flex items-center justify-center h-full w-full bg-slate-50 text-slate-400">
        <Loader2 className="w-8 h-8 animate-spin" />
      </div>
    )
  }

  const getNodeColor = (node: any) => {
    // If specific nodes are highlighted, dim others
    if (highlightedNodeIds.size > 0 && !highlightedNodeIds.has(node.id)) {
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

  return (
    <div ref={containerRef} className="w-full h-full relative bg-slate-50/50">
      {width > 0 && height > 0 && (
        <ForceGraph2DNoSSR
          ref={fgRef}
          width={width}
          height={height}
          graphData={data}
          backgroundColor="rgba(0,0,0,0)"
          nodeLabel="label"
          nodeColor={getNodeColor}
          nodeRelSize={6}
          // Link styling
          linkColor={(link: any) => {
             if (highlightedNodeIds.size > 0) {
               // If both source/target are highlighted, keep link bright, else dim
               const sourceId = typeof link.source === 'object' ? link.source.id : link.source
               const targetId = typeof link.target === 'object' ? link.target.id : link.target
               if (highlightedNodeIds.has(sourceId) && highlightedNodeIds.has(targetId)) {
                 return '#94a3b8'
               }
               return '#e2e8f0' // Very light dim
             }
             return '#cbd5e1'
          }}
          linkWidth={link => (highlightedNodeIds.size > 0 ? 1 : 1.5)}
          linkDirectionalArrowLength={3.5}
          linkDirectionalArrowRelPos={1}
          cooldownTicks={100}
          onNodeClick={handleNodeClick}
          onBackgroundClick={onBackgroundClick}
          onNodeDragEnd={node => {
            node.fx = node.x;
            node.fy = node.y;
          }}
          
          // Custom Node Painting
          nodeCanvasObject={(node: any, ctx, globalScale) => {
            const isHighlighted = highlightedNodeIds.size > 0 && highlightedNodeIds.has(node.id)
            const isDimmed = highlightedNodeIds.size > 0 && !isHighlighted
            
            const label = node.label || node.id;
            const fontSize = isHighlighted ? 14 / globalScale : 12 / globalScale;
            
            // Draw Node Circle
            const color = getNodeColor(node)
            ctx.beginPath();
            const radius = isHighlighted ? 7 : 5
            ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
            ctx.fillStyle = color;
            ctx.fill();
            
            // Halo/Border for highlighted nodes
            if (isHighlighted) {
               ctx.strokeStyle = '#fff';
               ctx.lineWidth = 4 / globalScale;
               ctx.stroke();
               ctx.strokeStyle = color;
               ctx.lineWidth = 1 / globalScale;
               ctx.stroke();
            } else {
               ctx.strokeStyle = '#fff';
               ctx.lineWidth = 1.5 / globalScale;
               ctx.stroke();
            }

            // Draw Label
            // Show label if: Highlighted OR Global Scale is large enough OR No highlight active (default view)
            const shouldShowLabel = isHighlighted || globalScale > 1.5 || (highlightedNodeIds.size === 0 && globalScale > 1.2)
            
            if (shouldShowLabel) {
              ctx.font = `${isHighlighted ? 'bold ' : ''}${fontSize}px Sans-Serif`;
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              
              // Text Shadow
              ctx.strokeStyle = 'rgba(255,255,255,0.9)';
              ctx.lineWidth = 3 / globalScale;
              ctx.strokeText(label, node.x, node.y + radius + 4);
              
              ctx.fillStyle = isDimmed ? '#94a3b8' : '#1e293b'; 
              ctx.fillText(label, node.x, node.y + radius + 4);
            }
          }}

          // Custom Link Label Painting
          linkCanvasObjectMode={() => 'after'}
          linkCanvasObject={(link: any, ctx, globalScale) => {
            if (!showEdgeLabels) return
            // Only show edge labels when zoomed in
            if (globalScale < 2) return

            const label = link.label
            if (!label) return

            const start = link.source
            const end = link.target

            // Ignore unbound links
            if (typeof start !== 'object' || typeof end !== 'object') return

            // Calculate middle point
            const textPos = Object.assign({}, start, { x: start.x + (end.x - start.x) / 2, y: start.y + (end.y - start.y) / 2 })

            const relLink = { x: end.x - start.x, y: end.y - start.y };

            const maxTextLength = Math.sqrt(Math.pow(relLink.x, 2) + Math.pow(relLink.y, 2)) - 8;

            let textAngle = Math.atan2(relLink.y, relLink.x);
            // Maintain label vertical orientation for readability
            if (textAngle > Math.PI / 2) textAngle = -(Math.PI - textAngle);
            if (textAngle < -Math.PI / 2) textAngle = -(-Math.PI - textAngle);

            const fontSize = 10 / globalScale;
            ctx.font = `${fontSize}px Sans-Serif`;
            
            // Measure text to potentially truncate or background
            const textWidth = ctx.measureText(label).width;
            if (textWidth > maxTextLength) return; // Hide if link is too short

            ctx.save();
            ctx.translate(textPos.x, textPos.y);
            ctx.rotate(textAngle);

            // Label Background
            ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
            ctx.fillRect(-textWidth / 2 - 2, -fontSize / 2 - 1, textWidth + 4, fontSize + 2);

            // Label Text
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = '#64748b'; // Slate 500
            ctx.fillText(label, 0, 0);
            
            ctx.restore();
          }}
        />
      )}
    </div>
  )
})

GraphViewer.displayName = 'GraphViewer'
