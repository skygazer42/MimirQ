"use client"

import { useEffect, useMemo, useRef } from "react"
import dynamic from "next/dynamic"
import { useTheme } from "next-themes"
import { useQuery } from "@tanstack/react-query"
import { AlertCircle, Database, Loader2, RefreshCw } from "lucide-react"
import * as THREE from "three"

import { Button } from "@/components/ui/button"
import { formatApiError } from "@/lib/api-errors"
import { documentApi } from "@/lib/api/documents"
import { getCssHslColor } from "@/lib/css-vars"
import { queryKeys } from "@/lib/query-keys"

const THREE_CLOCK_DEPRECATION_WARNING = "THREE.THREE.Clock"

function isThreeClockDeprecationWarning(args: unknown[]): boolean {
  return args.some((arg) => String(arg || "").includes(THREE_CLOCK_DEPRECATION_WARNING))
}

async function withSuppressedThreeClockWarning<T>(action: () => Promise<T>): Promise<T> {
  const originalWarn = console.warn
  console.warn = (...args: unknown[]) => {
    if (isThreeClockDeprecationWarning(args)) return
    originalWarn(...args)
  }
  try {
    return await action()
  } finally {
    console.warn = originalWarn
  }
}

const ForceGraph3D = dynamic(() => withSuppressedThreeClockWarning(() => import("react-force-graph-3d")), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center bg-background">
      <Loader2 className="h-8 w-8 animate-spin text-primary motion-reduce:animate-none" />
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
  chunkCount: number
  center: { x: number; y: number; z: number }
  style: ClusterVisualStyle
}

type NebulaNode = {
  id: string
  group: string
  color: string
  val: number
  x: number
  y: number
  z: number
  content: string
  documentId: string
  documentName: string
  chunkIndex: number | null
  style: ClusterVisualStyle
}

type NebulaLink = {
  source: string
  target: string
  color: string
}

type NebulaData = {
  nodes: NebulaNode[]
  links: NebulaLink[]
  clusters: ClusterDefinition[]
}

type DocumentListItem = {
  id: string
  filename?: string | null
  file_type?: string | null
  file_size?: number | null
  status?: string | null
  metadata?: Record<string, unknown> | null
}

type DocumentChunkItem = {
  id: string
  content: string
  chunk_index: number
}

const EMPTY_NEBULA: NebulaData = { nodes: [], links: [], clusters: [] }

const TYPE_STYLES: Record<string, Omit<ClusterDefinition, "count" | "chunkCount" | "center">> = {
  pdf: {
    label: "PDF 文档",
    color: "#2563eb",
    style: {
      spread: 58,
      sizeRange: [0.8, 1.9],
      halo: { scale: 1.8, opacity: 0.22 },
      geometry: "icosahedron",
      densityLabel: "版面切片",
      shapeLabel: "蓝色棱核",
    },
  },
  xlsx: {
    label: "表格文档",
    color: "#10b981",
    style: {
      spread: 42,
      sizeRange: [0.9, 2.2],
      halo: { scale: 1.65, opacity: 0.2 },
      geometry: "octahedron",
      densityLabel: "结构切片",
      shapeLabel: "绿色菱核",
    },
  },
  html: {
    label: "网页 / HTML",
    color: "#f97316",
    style: {
      spread: 46,
      sizeRange: [0.8, 1.7],
      halo: { scale: 1.7, opacity: 0.2 },
      geometry: "dodecahedron",
      densityLabel: "标记切片",
      shapeLabel: "橙色面核",
    },
  },
  default: {
    label: "其他文档",
    color: "#8b5cf6",
    style: {
      spread: 52,
      sizeRange: [0.75, 1.6],
      halo: { scale: 1.55, opacity: 0.18 },
      geometry: "sphere",
      densityLabel: "通用切片",
      shapeLabel: "紫色云核",
    },
  },
}

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function unitFromHash(value: string, salt: string): number {
  return (hashString(`${salt}:${value}`) % 10000) / 10000
}

function getDocumentType(document: DocumentListItem): string {
  const rawType = String(document.file_type || document.filename?.split(".").pop() || "default").toLowerCase()
  if (rawType.includes("pdf")) return "pdf"
  if (rawType.includes("xls") || rawType.includes("csv")) return "xlsx"
  if (rawType.includes("html") || rawType.includes("htm")) return "html"
  return "default"
}

function getChunkCount(document: DocumentListItem): number {
  const metadata = document.metadata || {}
  const stats = metadata.chunking_stats
  if (stats && typeof stats === "object" && "count" in stats) {
    const count = Number((stats as { count?: unknown }).count)
    if (Number.isFinite(count)) return count
  }
  return 0
}

function clusterCenter(index: number): { x: number; y: number; z: number } {
  const angle = index * 2.399963
  const radius = 70 + index * 18
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius,
    z: (index % 2 === 0 ? 1 : -1) * (24 + index * 9),
  }
}

function createClusterGeometry(geometry: ClusterVisualStyle["geometry"], size: number): THREE.BufferGeometry {
  if (geometry === "icosahedron") return new THREE.IcosahedronGeometry(size, 0)
  if (geometry === "octahedron") return new THREE.OctahedronGeometry(size, 0)
  if (geometry === "dodecahedron") return new THREE.DodecahedronGeometry(size, 0)
  return new THREE.SphereGeometry(size, 10, 10)
}

function buildNebula(documents: DocumentListItem[], chunksByDocument: Map<string, DocumentChunkItem[]>): NebulaData {
  const clusterKeys = Array.from(new Set(documents.map(getDocumentType)))
  const clusterByKey = new Map<string, ClusterDefinition>()

  clusterKeys.forEach((key, index) => {
    const style = TYPE_STYLES[key] || TYPE_STYLES.default
    const docs = documents.filter((document) => getDocumentType(document) === key)
    clusterByKey.set(key, {
      ...style,
      count: docs.length,
      chunkCount: docs.reduce((sum, document) => sum + (chunksByDocument.get(document.id)?.length || getChunkCount(document)), 0),
      center: clusterCenter(index),
    })
  })

  const nodes: NebulaNode[] = []
  const links: NebulaLink[] = []

  for (const document of documents) {
    const clusterKey = getDocumentType(document)
    const cluster = clusterByKey.get(clusterKey) || {
      ...TYPE_STYLES.default,
      count: 1,
      chunkCount: 0,
      center: clusterCenter(clusterByKey.size),
    }
    const chunks = chunksByDocument.get(document.id) || []
    const fallbackChunks: DocumentChunkItem[] = chunks.length
      ? chunks
      : [{
          id: `${document.id}:document`,
          content: document.filename || document.id,
          chunk_index: 0,
        }]

    fallbackChunks.forEach((chunk, index) => {
      const [minSize, maxSize] = cluster.style.sizeRange
      const id = String(chunk.id)
      const spread = cluster.style.spread
      const nodeId = `${document.id}:${id}`
      const sizeByLength = Math.min(1, Math.max(0.15, (chunk.content || "").length / 1600))
      nodes.push({
        id: nodeId,
        group: cluster.label,
        color: cluster.color,
        val: minSize + sizeByLength * (maxSize - minSize),
        x: cluster.center.x + (unitFromHash(nodeId, "x") - 0.5) * spread,
        y: cluster.center.y + (unitFromHash(nodeId, "y") - 0.5) * spread,
        z: cluster.center.z + (unitFromHash(nodeId, "z") - 0.5) * spread,
        content: chunk.content,
        documentId: document.id,
        documentName: document.filename || document.id,
        chunkIndex: Number.isFinite(chunk.chunk_index) ? chunk.chunk_index : index,
        style: cluster.style,
      })

      if (index > 0) {
        const previous = fallbackChunks[index - 1]
        links.push({
          source: `${document.id}:${previous.id}`,
          target: nodeId,
          color: cluster.color,
        })
      }
    })
  }

  return {
    nodes,
    links,
    clusters: Array.from(clusterByKey.values()),
  }
}

async function loadVectorNebulaData(): Promise<NebulaData> {
  const documentList = await documentApi.list({ limit: 24, status: "completed" })
  const documents = (documentList.items || []) as DocumentListItem[]
  const chunksByDocument = new Map<string, DocumentChunkItem[]>()

  await Promise.all(
    documents.slice(0, 8).map(async (document) => {
      try {
        const chunkList = await documentApi.listChunks(document.id, { limit: 80 })
        chunksByDocument.set(document.id, (chunkList.items || []) as DocumentChunkItem[])
      } catch {
        chunksByDocument.set(document.id, [])
      }
    })
  )

  return buildNebula(documents, chunksByDocument)
}

export function VectorNebula() {
  const { resolvedTheme } = useTheme()
  const fgRef = useRef<any>(null)
  const nebulaQuery = useQuery({
    queryKey: queryKeys.documents.nebula,
    queryFn: loadVectorNebulaData,
  })
  const data = nebulaQuery.data ?? EMPTY_NEBULA
  const loading = nebulaQuery.isFetching
  const error = nebulaQuery.error
    ? formatApiError(nebulaQuery.error, "语义星云数据加载失败")
    : null

  useEffect(() => {
    const originalWarn = console.warn
    const patchedWarn = (...args: unknown[]) => {
      // react-force-graph-3d still emits this upstream Three.js deprecation in dev.
      if (isThreeClockDeprecationWarning(args)) return
      originalWarn(...args)
    }
    console.warn = patchedWarn
    return () => {
      if (console.warn === patchedWarn) {
        console.warn = originalWarn
      }
    }
  }, [])

  const isDark = resolvedTheme === "dark"
  const bgColor = getCssHslColor("--background", isDark ? "#020617" : "#ffffff")
  const totalChunks = useMemo(() => data.clusters.reduce((sum, cluster) => sum + cluster.chunkCount, 0), [data.clusters])

  return (
    <div className="relative h-full w-full">
      <ForceGraph3D
        ref={fgRef}
        graphData={data}
        backgroundColor={bgColor}
        showNavInfo={false}
        nodeLabel={(rawNode: unknown) => {
          const node = rawNode as NebulaNode
          return `[${node.group}] ${node.documentName}\nChunk ${node.chunkIndex ?? "-"}\n${node.content.slice(0, 220)}`
        }}
        nodeColor="color"
        nodeRelSize={1.2}
        nodeOpacity={0.9}
        nodeResolution={10}
        linkColor={(rawLink: unknown) => (rawLink as NebulaLink).color}
        linkOpacity={0.16}
        enableNodeDrag={false}
        cooldownTicks={0}
        onNodeClick={(rawNode: unknown) => {
          const node = rawNode as NebulaNode
          const distance = 40
          const distRatio = 1 + distance / Math.max(1, Math.hypot(node.x, node.y, node.z))
          fgRef.current?.cameraPosition(
            { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
            node,
            1200
          )
        }}
        nodeThreeObject={(rawNode: unknown) => {
          const node = rawNode as NebulaNode
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

      <div className="absolute left-4 top-4 max-w-xs rounded-xl border border-border bg-background/85 p-4 shadow-lg backdrop-blur-md">
        <h3 className="mb-2 flex items-center gap-2 text-lg font-bold">
          <span className="h-2 w-2 rounded-full bg-primary/60 animate-pulse motion-reduce:animate-none" />
          语义星云
        </h3>
        <p className="mb-4 text-xs text-muted-foreground">
          基于后端文档清单与真实 chunk 接口生成。节点代表入库切片，颜色来自文档类型，大小来自切片长度。
        </p>
        {loading ? (
          <div className="flex items-center gap-2 rounded-lg border border-border/70 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
            正在读取真实切片...
          </div>
        ) : error ? (
          <div className="space-y-2">
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{error}</span>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-xs"
              onClick={() => {
                void nebulaQuery.refetch()
              }}
            >
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              重新加载
            </Button>
          </div>
        ) : data.nodes.length === 0 ? (
          <div className="flex items-start gap-2 rounded-lg border border-border/70 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            <Database className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            后端暂无可视化切片。请先上传并完成文档入库。
          </div>
        ) : (
          <div className="space-y-2">
            <div className="rounded-lg border border-border/60 bg-background/50 px-2 py-1.5 text-xs">
              <div className="flex items-center justify-between gap-3 font-medium">
                <span>真实节点</span>
                <span>{data.nodes.length} chunks</span>
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">来源：/documents 与 /documents/:id/chunks</p>
            </div>
            {data.clusters.map((cluster) => (
              <div key={cluster.label} className="rounded-lg border border-border/60 bg-background/40 px-2 py-1.5 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 font-medium">
                    <span className="h-3 w-3 rounded-full" style={{ backgroundColor: cluster.color }} />
                    {cluster.label}
                  </span>
                  <span className="text-muted-foreground">{cluster.chunkCount} 切片</span>
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {cluster.count} 文档 · {cluster.style.shapeLabel} · {cluster.style.densityLabel}
                </p>
              </div>
            ))}
            <p className="text-[11px] text-muted-foreground">当前共 {totalChunks} 个后端切片参与布局。</p>
          </div>
        )}
      </div>
    </div>
  )
}
