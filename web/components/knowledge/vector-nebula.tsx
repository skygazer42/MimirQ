"use client"

import { useEffect, useRef, useState } from "react"
import dynamic from "next/dynamic"
import { useTheme } from "next-themes"
import { Loader2 } from "lucide-react"
import * as THREE from "three"

import { getCssHslColor } from "@/lib/css-vars"

// Dynamic import
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full w-full bg-background">
      <Loader2 className="h-8 w-8 text-primary animate-spin motion-reduce:animate-none" />
    </div>
  ),
})

type ClusterVisualStyle = {
  spread: number
  sizeRange: [number, number]
  halo: {
    scale: number
    opacity: number
  }
  geometry: "sphere" | "icosahedron" | "octahedron" | "dodecahedron"
  densityLabel: string
  shapeLabel: string
}

type ClusterDefinition = {
  label: string
  color: string
  count: number
  center: { x: number; y: number; z: number }
  style: ClusterVisualStyle
}

// Mock Data Generator
const CLUSTERS: ClusterDefinition[] = [
  {
    label: "法律合同",
    color: "#ef4444",
    count: 150,
    center: { x: 100, y: 0, z: 0 },
    style: {
      spread: 32,
      sizeRange: [1.1, 2.1],
      halo: { scale: 2.15, opacity: 0.32 },
      geometry: "dodecahedron",
      densityLabel: "高密度条款簇",
      shapeLabel: "棱面核",
    },
  },
  {
    label: "技术文档",
    color: "#3b82f6",
    count: 200,
    center: { x: -80, y: 80, z: 50 },
    style: {
      spread: 52,
      sizeRange: [0.8, 1.6],
      halo: { scale: 1.55, opacity: 0.18 },
      geometry: "sphere",
      densityLabel: "广域探索簇",
      shapeLabel: "圆形云核",
    },
  },
  {
    label: "财务报表",
    color: "#eab308",
    count: 120,
    center: { x: -50, y: -100, z: -30 },
    style: {
      spread: 24,
      sizeRange: [1.4, 2.5],
      halo: { scale: 2.35, opacity: 0.4 },
      geometry: "icosahedron",
      densityLabel: "紧凑高权重簇",
      shapeLabel: "钻石核",
    },
  },
  {
    label: "会议纪要",
    color: "#10b981",
    count: 80,
    center: { x: 50, y: 50, z: -80 },
    style: {
      spread: 68,
      sizeRange: [0.65, 1.3],
      halo: { scale: 1.75, opacity: 0.24 },
      geometry: "octahedron",
      densityLabel: "轻量发散簇",
      shapeLabel: "菱锥核",
    },
  },
]

let _fallbackSeed = 0x12345678

function randomFloat01(): number {
  const cryptoObj = globalThis.crypto
  if (cryptoObj && typeof cryptoObj.getRandomValues === "function") {
    const buf = new Uint32Array(1)
    cryptoObj.getRandomValues(buf)
    return buf[0] / 2 ** 32
  }

  // Deterministic LCG fallback (avoids Math.random hotspots).
  _fallbackSeed = (_fallbackSeed * 9301 + 49297) % 233280
  return _fallbackSeed / 233280
}

function createClusterGeometry(geometry: ClusterVisualStyle["geometry"], size: number): THREE.BufferGeometry {
  if (geometry === "icosahedron") {
    return new THREE.IcosahedronGeometry(size, 0)
  }
  if (geometry === "octahedron") {
    return new THREE.OctahedronGeometry(size, 0)
  }
  if (geometry === "dodecahedron") {
    return new THREE.DodecahedronGeometry(size, 0)
  }
  return new THREE.SphereGeometry(size, 10, 10)
}

function generateMockData() {
  const nodes = []
  for (const cluster of CLUSTERS) {
    for (let i = 0; i < cluster.count; i++) {
      const [minSize, maxSize] = cluster.style.sizeRange
      const spread = cluster.style.spread
      nodes.push({
        id: `${cluster.label}-${i}`,
        group: cluster.label,
        color: cluster.color,
        val: minSize + randomFloat01() * (maxSize - minSize),
        x: cluster.center.x + (randomFloat01() - 0.5) * spread,
        y: cluster.center.y + (randomFloat01() - 0.5) * spread,
        z: cluster.center.z + (randomFloat01() - 0.5) * spread,
        content: `Here is a snippet of text from ${cluster.label} document #${i}...`,
        documentId: "mock-doc-id", // In real app, this would be real ID
        style: cluster.style,
      })
    }
  }
  return { nodes, links: [] }
}

export function VectorNebula() {
  const { resolvedTheme } = useTheme()
  const fgRef = useRef<any>(null)
  const [data, setData] = useState<any>({ nodes: [], links: [] })

  useEffect(() => {
    // Simulate async loading
    setTimeout(() => {
        setData(generateMockData())
    }, 500)
  }, [])

  const isDark = resolvedTheme === "dark"
  const bgColor = getCssHslColor("--background", isDark ? "#020617" : "#ffffff")

  return (
    <div className="relative w-full h-full">
        <ForceGraph3D
            ref={fgRef}
            graphData={data}
            backgroundColor={bgColor}
            showNavInfo={false}
            
            // Nodes as glowing particles
            nodeLabel={(node: any) =>
              `[${node.group}] ${node.style.shapeLabel} / ${node.style.densityLabel}\n${node.content}`
            }
            nodeColor="color"
            nodeRelSize={1.2}
            nodeOpacity={0.9}
            nodeResolution={10}
            
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
                const [minSize] = node.style.sizeRange
                const coreSize = Math.max(node.val ?? minSize, minSize)
                const coreGeometry = createClusterGeometry(node.style.geometry, coreSize)
                const coreMaterial = new THREE.MeshBasicMaterial({ color: node.color })
                const coreMesh = new THREE.Mesh(coreGeometry, coreMaterial)

                const haloGeometry = new THREE.SphereGeometry(coreSize * node.style.halo.scale, 12, 12)
                const haloMaterial = new THREE.MeshBasicMaterial({
                  color: node.color,
                  transparent: true,
                  opacity: node.style.halo.opacity,
                  blending: THREE.AdditiveBlending,
                  depthWrite: false,
                })
                const haloMesh = new THREE.Mesh(haloGeometry, haloMaterial)

                const group = new THREE.Group()
                group.add(haloMesh)
                group.add(coreMesh)
                return group
            }}
        />
        
        {/* Legend / Info Overlay */}
        <div className="absolute top-4 left-4 p-4 bg-background/80 backdrop-blur-md border border-border rounded-xl shadow-lg max-w-xs">
            <h3 className="font-bold text-lg mb-2 flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-primary/60 animate-pulse motion-reduce:animate-none" />
                语义星云
            </h3>
            <p className="text-xs text-muted-foreground mb-4">
                这是知识库中所有切片的语义分布图。不同簇不仅颜色不同，也通过几何核心、扩散半径和光晕强度表达语义组织方式。
            </p>
            <div className="space-y-2">
                {CLUSTERS.map(c => (
                    <div key={c.label} className="rounded-lg border border-border/60 bg-background/40 px-2 py-1.5 text-xs">
                        <div className="flex items-center justify-between gap-3">
                            <span className="flex items-center gap-2 font-medium">
                                <span className="w-3 h-3 rounded-full" style={{ backgroundColor: c.color }} />
                                {c.label}
                            </span>
                            <span className="text-muted-foreground">{c.count} 碎片</span>
                        </div>
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {c.style.shapeLabel} · {c.style.densityLabel}
                        </p>
                        <p className="mt-0.5 text-[11px] text-muted-foreground">
                          扩散 {c.style.spread} / 光晕 {Math.round(c.style.halo.opacity * 100)}%
                        </p>
                    </div>
                ))}
            </div>
        </div>
    </div>
  )
}
