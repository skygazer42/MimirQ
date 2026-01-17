"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import dynamic from "next/dynamic"
import { useTheme } from "next-themes"
import * as THREE from "three"
import SpriteText from "three-spritetext"
import { Loader2 } from "lucide-react"

// Dynamic import to avoid SSR issues with Three.js
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full w-full bg-slate-950">
      <Loader2 className="h-8 w-8 text-cyan-500 animate-spin" />
    </div>
  ),
})

interface GraphNode {
  id: string
  label: string
  group?: number
  val?: number
  color?: string
}

interface GraphLink {
  source: string
  target: string
  value?: number
}

interface GraphData {
  nodes: GraphNode[]
  links: GraphLink[]
}

interface ForceGraph3DProps {
  data: GraphData
  onNodeClick?: (node: GraphNode) => void
  width?: number
  height?: number
}

export function KnowledgeGraph3D({ data, onNodeClick, width, height }: ForceGraph3DProps) {
  const { theme } = useTheme()
  const fgRef = useRef<any>()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const handleNodeClick = useCallback(
    (node: any) => {
      // Aim at node from outside it
      const distance = 40
      const distRatio = 1 + distance / Math.hypot(node.x, node.y, node.z)

      fgRef.current.cameraPosition(
        { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio }, // new position
        node, // lookAt ({ x, y, z })
        3000 // ms transition duration
      )
      
      onNodeClick?.(node)
    },
    [onNodeClick]
  )

  if (!mounted) return null

  const isDark = theme === 'dark'
  const bgColor = isDark ? "#020617" : "#ffffff" // slate-950 or white
  const linkColor = isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)"

  return (
    <ForceGraph3D
      ref={fgRef}
      graphData={data}
      width={width}
      height={height}
      backgroundColor={bgColor}
      showNavInfo={false}
      
      // Node Styling
      nodeLabel="label"
      nodeColor={(node: any) => node.color || (isDark ? "#0ea5e9" : "#0284c7")}
      nodeRelSize={6}
      nodeOpacity={0.9}
      nodeResolution={16}
      
      // Link Styling
      linkColor={() => linkColor}
      linkWidth={1}
      linkDirectionalParticles={2}
      linkDirectionalParticleWidth={2}
      linkDirectionalParticleSpeed={0.005}
      
      // Interaction
      onNodeClick={handleNodeClick}
      
      // Custom Objects (Text Sprites)
      nodeThreeObject={(node: any) => {
        const sprite = new SpriteText(node.label)
        sprite.color = isDark ? "#fff" : "#333"
        sprite.textHeight = 4
        // Adjust text position
        sprite.position.y = 8 
        return sprite
      }}
      nodeThreeObjectExtend={true} // Draw node circle AND text
    />
  )
}
