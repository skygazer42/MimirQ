"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import dynamic from "next/dynamic"
import { useTheme } from "next-themes"
import SpriteText from "three-spritetext"
import { Loader2 } from "lucide-react"

import { getCssHslColor } from "@/lib/css-vars"

// Dynamic import to avoid SSR issues with Three.js
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full w-full bg-background">
      <Loader2 className="h-8 w-8 text-primary animate-spin motion-reduce:animate-none" />
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
  const { resolvedTheme } = useTheme()
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

  const isDark = resolvedTheme === "dark"
  const bgColor = getCssHslColor("--background", isDark ? "#020617" : "#ffffff")
  const primaryColor = getCssHslColor("--primary", isDark ? "#0ea5e9" : "#0284c7")
  const mutedFgColor = getCssHslColor("--muted-foreground", isDark ? "#94a3b8" : "#475569")
  const linkColor = isDark ? "rgba(255,255,255,0.18)" : "rgba(0,0,0,0.18)"

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
      nodeColor={(node: any) => node.color || primaryColor}
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
        sprite.color = mutedFgColor
        sprite.textHeight = 4
        // Adjust text position
        sprite.position.y = 8 
        return sprite
      }}
      nodeThreeObjectExtend={true} // Draw node circle AND text
    />
  )
}
