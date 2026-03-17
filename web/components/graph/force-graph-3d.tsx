"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import dynamic from "next/dynamic"
import { useTheme } from "next-themes"
import SpriteText from "three-spritetext"
import { Loader2 } from "lucide-react"

import { buildGraphLinkProvenanceTooltipHtml } from "@/lib/graph-provenance"

const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full w-full bg-background">
      <Loader2 className="h-5 w-5 text-primary animate-spin motion-reduce:animate-none" />
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

const NODE_COLORS = [
  '#8b5cf6', '#3b82f6', '#10b981', '#f59e0b',
  '#ef4444', '#ec4899', '#06b6d4', '#84cc16',
]

export function KnowledgeGraph3D({ data, onNodeClick, width, height }: Readonly<ForceGraph3DProps>) {
  const { resolvedTheme } = useTheme()
  const fgRef = useRef<any>(null)
  const [mounted, setMounted] = useState(false)
  const [hoveredLinkId, setHoveredLinkId] = useState<string | null>(null)

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    if (!fgRef.current) return
    const renderer = fgRef.current.renderer?.()
    if (renderer) {
      renderer.setClearColor(0x0a0a14, 1)
    }

    const scene = fgRef.current.scene?.()
    if (scene) {
      const THREE = (globalThis as any).THREE
      if (THREE?.FogExp2) {
        scene.fog = new THREE.FogExp2(0x0a0a14, 0.002)
      }
    }
  }, [mounted])

  const handleNodeClick = useCallback(
    (node: any) => {
      const distance = 40
      const distRatio = 1 + distance / Math.hypot(node.x, node.y, node.z)

      fgRef.current.cameraPosition(
        { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
        node,
        1500
      )
      
      onNodeClick?.(node)
    },
    [onNodeClick]
  )

  if (!mounted) return null

  const isDark = resolvedTheme === "dark"
  const bgColor = isDark ? "#0a0a14" : "#fafafa"
  const linkColor = isDark ? "rgba(139, 92, 246, 0.15)" : "rgba(0,0,0,0.12)"
  const hoverLinkColor = isDark ? "#8b5cf6" : "#6366f1"

  return (
    <ForceGraph3D
      ref={fgRef}
      graphData={data}
      width={width}
      height={height}
      backgroundColor={bgColor}
      showNavInfo={false}
      
      nodeLabel="label"
      nodeColor={(node: any) => {
        if (node.color) return node.color
        const g = typeof node.group === 'number' ? node.group : 0
        return NODE_COLORS[g % NODE_COLORS.length]
      }}
      nodeRelSize={5}
      nodeOpacity={0.85}
      nodeResolution={20}
      
      linkColor={(link: any) => {
        const linkId = link?.id || (link?.index === undefined ? null : `link-${link.index}`)
        if (hoveredLinkId && linkId && hoveredLinkId === linkId) return hoverLinkColor
        return linkColor
      }}
      linkWidth={(link: any) => {
        const linkId = link?.id || (link?.index === undefined ? null : `link-${link.index}`)
        if (hoveredLinkId && linkId && hoveredLinkId === linkId) return 2
        return 0.5
      }}
      linkDirectionalParticles={2}
      linkDirectionalParticleWidth={1.5}
      linkDirectionalParticleSpeed={0.004}
      linkDirectionalParticleColor={() => isDark ? '#8b5cf680' : '#6366f180'}
      linkLabel={(link: any) => buildGraphLinkProvenanceTooltipHtml(link)}
      
      onNodeClick={handleNodeClick}
      onLinkHover={(link: any) => {
        const linkId = link?.id || (link?.index === undefined ? null : `link-${link.index}`)
        setHoveredLinkId((prev) => (prev === linkId ? prev : linkId))
      }}
      
      nodeThreeObject={(node: any) => {
        const sprite = new SpriteText(node.label)
        sprite.color = isDark ? '#e2e8f0' : '#1e293b'
        sprite.textHeight = 3.5
        sprite.fontFace = 'Inter, system-ui, sans-serif'
        sprite.fontWeight = '500'
        sprite.backgroundColor = isDark ? 'rgba(10,10,20,0.6)' : 'rgba(255,255,255,0.6)'
        sprite.padding = 1.5
        sprite.borderRadius = 2
        sprite.position.y = 8 
        return sprite
      }}
      nodeThreeObjectExtend={true}
    />
  )
}
