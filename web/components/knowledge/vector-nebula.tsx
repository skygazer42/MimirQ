"use client"

import { useEffect, useRef, useState, useMemo } from "react"
import dynamic from "next/dynamic"
import { useTheme } from "next-themes"
import { Loader2, Info } from "lucide-react"
import * as THREE from "three"
import { useDocumentView } from "@/store/document-view"

// Dynamic import
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full w-full bg-slate-950">
      <Loader2 className="h-8 w-8 text-cyan-500 animate-spin" />
    </div>
  ),
})

// Mock Data Generator
const CLUSTERS = [
  { label: "法律合同", color: "#ef4444", count: 150, center: { x: 100, y: 0, z: 0 } },
  { label: "技术文档", color: "#3b82f6", count: 200, center: { x: -80, y: 80, z: 50 } },
  { label: "财务报表", color: "#eab308", count: 120, center: { x: -50, y: -100, z: -30 } },
  { label: "会议纪要", color: "#10b981", count: 80, center: { x: 50, y: 50, z: -80 } },
]

function generateMockData() {
  const nodes = []
  for (const cluster of CLUSTERS) {
    for (let i = 0; i < cluster.count; i++) {
      // Gaussian distribution around center
      const spread = 40
      nodes.push({
        id: `${cluster.label}-${i}`,
        group: cluster.label,
        color: cluster.color,
        val: 1, // size
        x: cluster.center.x + (Math.random() - 0.5) * spread,
        y: cluster.center.y + (Math.random() - 0.5) * spread,
        z: cluster.center.z + (Math.random() - 0.5) * spread,
        content: `Here is a snippet of text from ${cluster.label} document #${i}...`,
        documentId: "mock-doc-id" // In real app, this would be real ID
      })
    }
  }
  return { nodes, links: [] }
}

export function VectorNebula() {
  const { theme } = useTheme()
  const fgRef = useRef<any>()
  const [data, setData] = useState<any>({ nodes: [], links: [] })
  const { openDocument } = useDocumentView()

  useEffect(() => {
    // Simulate async loading
    setTimeout(() => {
        setData(generateMockData())
    }, 500)
  }, [])

  const isDark = theme === 'dark'
  const bgColor = isDark ? "#020617" : "#ffffff"

  return (
    <div className="relative w-full h-full">
        <ForceGraph3D
            ref={fgRef}
            graphData={data}
            backgroundColor={bgColor}
            showNavInfo={false}
            
            // Nodes as glowing particles
            nodeLabel={(node: any) => `[${node.group}]\n${node.content}`}
            nodeColor="color"
            nodeRelSize={2}
            nodeOpacity={0.8}
            nodeResolution={8}
            
            // Disable physics engine for static layout
            enableNodeDrag={false}
            cooldownTicks={0} // Freeze layout immediately
            
            onNodeClick={(node: any) => {
                // Focus camera
                const distance = 40
                const distRatio = 1 + distance / Math.hypot(node.x, node.y, node.z)
                fgRef.current.cameraPosition(
                    { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
                    node,
                    2000
                )
                // Open document viewer (using mock ID for now)
                // In a real app, you'd pass node.documentId
                // openDocument(node.documentId) 
            }}

            // Custom particle rendering (Optional: for bloom effect)
            nodeThreeObject={(node: any) => {
                const geometry = new THREE.SphereGeometry(Math.random() * 1.5 + 0.5, 8, 8)
                const material = new THREE.MeshBasicMaterial({ color: node.color })
                return new THREE.Mesh(geometry, material)
            }}
        />
        
        {/* Legend / Info Overlay */}
        <div className="absolute top-4 left-4 p-4 bg-background/80 backdrop-blur-md border border-border rounded-xl shadow-lg max-w-xs">
            <h3 className="font-bold text-lg mb-2 flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
                语义星云
            </h3>
            <p className="text-xs text-muted-foreground mb-4">
                这是知识库中所有切片的语义分布图。距离越近的点，表示它们的内容越相似。
            </p>
            <div className="space-y-2">
                {CLUSTERS.map(c => (
                    <div key={c.label} className="flex items-center justify-between text-xs">
                        <span className="flex items-center gap-2">
                            <span className="w-3 h-3 rounded-full" style={{ backgroundColor: c.color }} />
                            {c.label}
                        </span>
                        <span className="text-muted-foreground">{c.count} 碎片</span>
                    </div>
                ))}
            </div>
        </div>
    </div>
  )
}
