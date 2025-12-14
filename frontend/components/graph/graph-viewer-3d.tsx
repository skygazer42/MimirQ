'use client'

import dynamic from 'next/dynamic'
import { useRef, useEffect, useState, forwardRef, useImperativeHandle, useCallback } from 'react'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import { Loader2 } from 'lucide-react'
import { LayoutMode } from './graph-viewer'
import SpriteText from 'three-spritetext'

// Dynamically import ForceGraph3D via wrapper to handle Ref correctly
const ForceGraph3DNoSSR = dynamic(
  () => import('./force-graph-3d-wrapper'),
  { ssr: false }
)

export interface GraphViewer3DRef {
  zoomIn: () => void
  zoomOut: () => void
  zoomToFit: () => void
  focusNode: (nodeId: string) => void
}

interface GraphViewer3DProps {
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

export const GraphViewer3D = forwardRef<GraphViewer3DRef, GraphViewer3DProps>(({ 
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

  useEffect(() => {
    setMounted(true)
  }, [])

  // Expose methods to parent
  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      // 3D graph uses camera position, not zoom level directly
      if (fgRef.current) {
        const currentPos = fgRef.current.cameraPosition();
        fgRef.current.cameraPosition(
          { x: currentPos.x * 0.8, y: currentPos.y * 0.8, z: currentPos.z * 0.8 },
          currentPos,
          1000
        );
      }
    },
    zoomOut: () => {
      if (fgRef.current) {
        const currentPos = fgRef.current.cameraPosition();
        fgRef.current.cameraPosition(
          { x: currentPos.x * 1.2, y: currentPos.y * 1.2, z: currentPos.z * 1.2 },
          currentPos,
          1000
        );
      }
    },
    zoomToFit: () => {
      if (fgRef.current) {
        fgRef.current.zoomToFit(1000, 20)
      }
    },
    focusNode: (nodeId: string) => {
      const node = data.nodes.find(n => n.id === nodeId)
      if (node && fgRef.current) {
        const distRatio = 1 + 50/Math.hypot(node.x, node.y, node.z);
        fgRef.current.cameraPosition(
          { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio }, // new position
          node, // lookAt ({ x, y, z })
          2000  // ms transition duration
        );
      }
    }
  }))

  const handleNodeClick = useCallback((node: any) => {
    if (fgRef.current) {
        const distRatio = 1 + 50/Math.hypot(node.x, node.y, node.z);
        fgRef.current.cameraPosition(
          { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
          node,
          2000
        );
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
    const hasHighlights = highlightedNodeIds.size > 0
    if (hasHighlights && !highlightedNodeIds.has(node.id)) {
      return '#cbd5e1' // Dimmed
    }
    if (node.color) return node.color
    const colors = ['#6366f1', '#ec4899', '#10b981', '#f59e0b', '#8b5cf6', '#3b82f6']
    const index = typeof node.group === 'number' ? node.group : 0
    return colors[index % colors.length]
  }

  const getDagMode = () => {
    switch (layoutMode) {
      case 'tree': return 'td'
      case 'radial': return 'radialout'
      default: return undefined
    }
  }

  return (
    <div ref={containerRef} className="w-full h-full relative bg-slate-50/50">
      {width > 0 && height > 0 && (
        <ForceGraph3DNoSSR
          graphRef={fgRef}
          width={width}
          height={height}
          graphData={data}
          backgroundColor="rgba(0,0,0,0)" // Transparent to show parent BG
          nodeLabel="label"
          nodeColor={getNodeColor}
          nodeRelSize={6}
          dagMode={getDagMode()}
          dagLevelDistance={50}
          
          // Link styling
          linkColor={(link: any) => {
             const linkId = link.id || (link.index !== undefined ? `link-${link.index}` : null)
             if (highlightedLinkIds.size > 0 && linkId && highlightedLinkIds.has(linkId)) {
                return '#f59e0b'
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
                return 2
             }
             if (highlightedNodeIds.size > 0) return 0.5
             return 1
          }}
          
          onNodeClick={handleNodeClick}
          onBackgroundClick={onBackgroundClick}
          
          // 3D Objects
          nodeThreeObject={(node: any) => {
             const isHighlighted = highlightedNodeIds.size > 0 && highlightedNodeIds.has(node.id)
             const label = node.label || node.id;
             
             if (isHighlighted) {
                const sprite = new SpriteText(label);
                sprite.color = getNodeColor(node);
                sprite.textHeight = 8;
                return sprite;
             }
             // Default render (sphere) is handled if return null/undefined, but we want text sometimes
             return false; // Use default sphere
          }}
          
          nodeThreeObjectExtend={true} // Add text on top of sphere
        />
      )}
    </div>
  )
})

GraphViewer3D.displayName = 'GraphViewer3D'
