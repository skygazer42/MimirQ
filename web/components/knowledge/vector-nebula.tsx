'use client'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from '@/components/icons'
import * as THREE from 'three'
import type { ForceGraphMethods } from 'react-force-graph-3d'
import type { Document, DocumentChunk } from '@/types/backend'

import { Button } from '@/components/ui/button'
import { OperationalWorkspace, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { fitNebulaCamera } from './nebula-camera'
import { useMediaQuery } from '@/hooks/use-media-query'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import { Link } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { documentApi } from '@/lib/api/documents'
import { getCssHslColor } from '@/lib/css-vars'
import { queryKeys } from '@/lib/query-keys'

const ForceGraph3D = dynamic(() => import('./nebula-graph').then((module) => module.NebulaGraph), {
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
  geometry: 'sphere' | 'icosahedron' | 'octahedron' | 'dodecahedron'
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
  chunkId: string
  chunkIndex: number
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

type DocumentListItem = Pick<Document, 'id'> &
  Partial<Pick<Document, 'filename' | 'file_type' | 'file_size' | 'status' | 'metadata'>>

type DocumentChunkItem = Pick<DocumentChunk, 'id' | 'content' | 'chunk_index'>

const EMPTY_NEBULA: NebulaData = { nodes: [], links: [], clusters: [] }

const TYPE_STYLES = {
  pdf: {
    label: 'PDF 文档',
    color: '#2563eb',
    style: {
      spread: 58,
      sizeRange: [0.8, 1.9],
      halo: { scale: 1.8, opacity: 0.22 },
      geometry: 'icosahedron',
      densityLabel: '版面切片',
      shapeLabel: '蓝色棱核',
    },
  },
  xlsx: {
    label: '表格文档',
    color: '#10b981',
    style: {
      spread: 42,
      sizeRange: [0.9, 2.2],
      halo: { scale: 1.65, opacity: 0.2 },
      geometry: 'octahedron',
      densityLabel: '结构切片',
      shapeLabel: '绿色菱核',
    },
  },
  html: {
    label: '网页 / HTML',
    color: '#f97316',
    style: {
      spread: 46,
      sizeRange: [0.8, 1.7],
      halo: { scale: 1.7, opacity: 0.2 },
      geometry: 'dodecahedron',
      densityLabel: '标记切片',
      shapeLabel: '橙色面核',
    },
  },
  default: {
    label: '其他文档',
    color: '#8b5cf6',
    style: {
      spread: 52,
      sizeRange: [0.75, 1.6],
      halo: { scale: 1.55, opacity: 0.18 },
      geometry: 'sphere',
      densityLabel: '通用切片',
      shapeLabel: '紫色云核',
    },
  },
} satisfies Record<string, Omit<ClusterDefinition, 'count' | 'chunkCount' | 'center'>>

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.codePointAt(i) ?? 0
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function unitFromHash(value: string, salt: string): number {
  return (hashString(`${salt}:${value}`) % 10000) / 10000
}

function getDocumentType(document: DocumentListItem): keyof typeof TYPE_STYLES {
  const fileType = document.file_type
  const type = fileType === undefined || fileType === '' ? document.filename?.split('.').pop() : fileType
  const normalizedType = type?.toLowerCase()
  if (normalizedType?.includes('pdf')) return 'pdf'
  if (normalizedType?.includes('xls') || normalizedType?.includes('csv')) return 'xlsx'
  if (normalizedType?.includes('htm')) return 'html'
  return 'default'
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

function createClusterGeometry(geometry: ClusterVisualStyle['geometry'], size: number): THREE.BufferGeometry {
  if (geometry === 'icosahedron') return new THREE.IcosahedronGeometry(size, 0)
  if (geometry === 'octahedron') return new THREE.OctahedronGeometry(size, 0)
  if (geometry === 'dodecahedron') return new THREE.DodecahedronGeometry(size, 0)
  return new THREE.SphereGeometry(size, 10, 10)
}

export function buildNebula(
  documents: DocumentListItem[],
  chunksByDocument: Map<string, DocumentChunkItem[]>,
): NebulaData {
  const clusterByKey = new Map<keyof typeof TYPE_STYLES, ClusterDefinition>()
  const nodes: NebulaNode[] = []
  const links: NebulaLink[] = []

  for (const document of documents) {
    const clusterKey = getDocumentType(document)
    let cluster = clusterByKey.get(clusterKey)
    if (cluster === undefined) {
      cluster = { ...TYPE_STYLES[clusterKey], count: 0, chunkCount: 0, center: clusterCenter(clusterByKey.size) }
      clusterByKey.set(clusterKey, cluster)
    }
    cluster.count += 1

    const chunks = chunksByDocument.get(document.id)
    if (chunks === undefined) continue
    cluster.chunkCount += chunks.length
    const documentName = document.filename === undefined || document.filename === '' ? document.id : document.filename
    chunks.forEach((chunk, index) => {
      const [minSize, maxSize] = cluster.style.sizeRange
      const spread = cluster.style.spread
      const nodeId = `${document.id}:${chunk.id}`
      const sizeByLength = Math.min(1, Math.max(0.15, chunk.content.length / 1600))
      nodes.push({
        id: nodeId,
        group: cluster.label,
        color: cluster.color,
        val: minSize + sizeByLength * (maxSize - minSize),
        x: cluster.center.x + (unitFromHash(nodeId, 'x') - 0.5) * spread,
        y: cluster.center.y + (unitFromHash(nodeId, 'y') - 0.5) * spread,
        z: cluster.center.z + (unitFromHash(nodeId, 'z') - 0.5) * spread,
        content: chunk.content,
        documentId: document.id,
        documentName,
        chunkId: chunk.id,
        chunkIndex: chunk.chunk_index,
        style: cluster.style,
      })

      if (index > 0) {
        const previous = chunks[index - 1]
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

async function loadVectorNebulaData(signal: AbortSignal): Promise<NebulaData> {
  const { items: documents } = await documentApi.list({ limit: 8, status: 'completed' }, { signal })
  const chunksByDocument = await Promise.all(
    documents.map(async (document) => {
      const { items: chunks } = await documentApi.listChunks(document.id, { limit: 80 }, { signal })
      return [document.id, chunks] as const
    }),
  )
  return buildNebula(documents, new Map(chunksByDocument))
}

export function VectorNebula() {
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined)
  const viewportRef = useRef<HTMLDivElement>(null)
  const size = useResizeObserver(viewportRef)
  const [canvasColor, setCanvasColor] = useState('#ffffff')
  const [linkColor, setLinkColor] = useState('#64748b')
  const [panel, setPanel] = useState<'legend' | 'node' | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
  const nebulaQuery = useQuery({
    queryKey: queryKeys.documents.nebula,
    queryFn: ({ signal }) => loadVectorNebulaData(signal),
  })
  const data = nebulaQuery.data ?? EMPTY_NEBULA
  const loading = nebulaQuery.isFetching
  const error = nebulaQuery.error ? formatApiError(nebulaQuery.error, '语义星云数据读取失败') : null
  const selectedNode = data.nodes.find((node) => node.id === selectedId)
  const totalDocuments = data.clusters.reduce((sum, cluster) => sum + cluster.count, 0)
  useLayoutEffect(() => {
    const update = () => {
      setCanvasColor(getCssHslColor('--background', '#ffffff'))
      setLinkColor(getCssHslColor('--muted-foreground', '#64748b'))
    }
    const observer = new MutationObserver(update)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'style', 'data-surface-theme'],
    })
    update()
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (selectedId && !data.nodes.some((node) => node.id === selectedId)) {
      setSelectedId(null)
      if (panel === 'node') setPanel(null)
    }
  }, [data.nodes, selectedId, panel])
  const fitCamera = useCallback(() => {
    const graph = fgRef.current
    if (!graph || !size.width || !size.height) return
    const camera = graph.camera() as THREE.PerspectiveCamera
    const view = fitNebulaCamera(
      data.nodes.map((node) => ({ x: node.x, y: node.y, z: node.z, radius: node.val * node.style.halo.scale })),
      size.width,
      size.height,
      camera.fov,
    )
    if (view) graph.cameraPosition(view.position, view.target, 0)
  }, [data.nodes, size.width, size.height])
  const selectNode = useCallback(
    (node: NebulaNode) => {
      viewportRef.current?.focus()
      setSelectedId(node.id)
      setPanel('node')
      const ratio = 1 + 40 / Math.max(1, Math.hypot(node.x, node.y, node.z))
      fgRef.current?.cameraPosition(
        { x: node.x * ratio, y: node.y * ratio, z: node.z * ratio },
        node,
        reducedMotion ? 0 : 600,
      )
    },
    [reducedMotion],
  )
  return (
    <OperationalWorkspace
      title="语义星云"
      icon="knowledge-graph"
      mode="canvas"
      context={loading && !nebulaQuery.data ? '正在读取切片…' : `${totalDocuments} 文档 · ${data.nodes.length} 切片`}
      actions={
        <>
          <Button variant="outline" onClick={() => setPanel('legend')}>
            图例与定位
          </Button>
          <Button
            variant="ghost"
            disabled={loading}
            onClick={() => {
              void nebulaQuery.refetch()
            }}
          >
            {loading ? '正在读取…' : '重新读取'}
          </Button>
        </>
      }
      toolbar={
        <>
          <p className="text-[13px] text-muted-foreground">拖动旋转，滚轮缩放；选择切片查看正文。</p>
          <Button variant="ghost" className="ml-auto" disabled={!data.nodes.length} onClick={fitCamera}>
            重置视角
          </Button>
        </>
      }
    >
      {error ? (
        <div className="px-4">
          <WorkspaceNotice
            retry={() => {
              void nebulaQuery.refetch()
            }}
            pending={loading}
          >
            {error}
            {data.nodes.length ? '。当前仍显示上次读取的切片。' : ''}
          </WorkspaceNotice>
        </div>
      ) : null}
      <div
        ref={viewportRef}
        role="region"
        tabIndex={0}
        aria-label="三维切片画布"
        className="relative min-h-0 min-w-0 flex-1 overflow-hidden outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        data-canvas-background={canvasColor}
      >
        {size.width > 0 && size.height > 0 ? (
          <ForceGraph3D
            graphRef={fgRef}
            onReady={fitCamera}
            onEngineStop={fitCamera}
            width={size.width}
            height={size.height}
            graphData={data}
            backgroundColor={canvasColor}
            showNavInfo={false}
            nodeLabel={(raw: unknown) => {
              const node = raw as NebulaNode
              const label = document.createElement('span')
              label.textContent = `${node.documentName} · 切片 ${node.chunkIndex}`
              return label.outerHTML
            }}
            nodeColor="color"
            nodeRelSize={1.2}
            nodeOpacity={0.9}
            nodeResolution={10}
            linkColor={() => linkColor}
            linkOpacity={0.7}
            enableNodeDrag={false}
            cooldownTicks={0}
            onNodeClick={(raw: unknown) => selectNode(raw as NebulaNode)}
            nodeThreeObject={renderNebulaNode}
          />
        ) : null}
        {!data.nodes.length ? (
          <div className="absolute inset-0 flex items-center justify-center px-6">
            <div className="max-w-md text-left">
              <h2 className="text-lg font-semibold">
                {loading ? '正在读取文档切片' : error ? '暂时无法生成星云' : '当前没有可视化切片'}
              </h2>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                {error
                  ? '重新读取成功后，将在这里显示切片。'
                  : loading
                    ? '读取完成后可浏览切片和原文。'
                    : '在知识库完成文档入库后，可在这里浏览切片。'}
              </p>
              {!loading && !error ? (
                <Button asChild variant="outline" className="mt-5">
                  <Link href="/knowledge">打开知识库</Link>
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
      <Dialog
        open={panel !== null}
        onOpenChange={(open) => {
          if (!open) setPanel(null)
        }}
      >
        <DialogContent className={ws.dialog} aria-describedby={undefined}>
          <DialogHeader className={ws.dialogHeader}>
            <DialogTitle>{panel === 'node' ? '切片详情' : '图例与定位'}</DialogTitle>
          </DialogHeader>
          <div className={ws.dialogBody}>
            {panel === 'node' && selectedNode ? (
              <article>
                <h2 className="break-words text-base font-semibold leading-7">{selectedNode.documentName}</h2>
                <p className="mt-2 text-[13px] text-muted-foreground">
                  {selectedNode.group} · 切片 {selectedNode.chunkIndex}
                </p>
                <p className="mt-5 whitespace-pre-wrap break-words text-sm leading-7">{selectedNode.content}</p>
                <details className="mt-5 border-t border-border pt-4 text-[13px]">
                  <summary className="cursor-pointer">文档与切片标识</summary>
                  <p className="mt-3 break-all font-mono text-xs leading-6">
                    {selectedNode.documentId}
                    <br />
                    {selectedNode.chunkId}
                  </p>
                </details>
              </article>
            ) : null}
            {panel === 'legend' ? (
              <div className="space-y-5">
                <p className="text-sm leading-7 text-muted-foreground">
                  节点代表已读取的文档切片；连线连接同一文档的相邻切片。空间位置用于浏览，不代表向量距离。当前最多载入 8
                  份文档，每份最多 80 个切片。
                </p>
                <dl className="divide-y divide-border">
                  {data.clusters.map((cluster) => (
                    <div key={cluster.label} className="flex justify-between gap-4 py-4 text-sm">
                      <dt className="flex items-center gap-2">
                        <span className="size-2 rounded-full" style={{ backgroundColor: cluster.color }} />
                        {cluster.label}
                      </dt>
                      <dd>
                        {cluster.count} 文档 · {cluster.chunkCount} 切片
                      </dd>
                    </div>
                  ))}
                </dl>
                <label className="block space-y-2 text-sm">
                  定位切片
                  <select
                    className="h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm"
                    value=""
                    disabled={!data.nodes.length}
                    onChange={(event) => {
                      const node = data.nodes.find((item) => item.id === event.target.value)
                      if (node) selectNode(node)
                    }}
                  >
                    <option value="">选择文档与切片</option>
                    {data.nodes.map((node) => (
                      <option value={node.id} key={node.id}>
                        {node.documentName} · 切片 {node.chunkIndex}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            ) : null}
          </div>
          <DialogFooter className={ws.dialogFooter}>
            {panel === 'node' && selectedNode ? (
              <Button asChild variant="outline">
                <Link href={`/knowledge/${selectedNode.documentId}/health`}>查看文档审计</Link>
              </Button>
            ) : null}
            <Button onClick={() => setPanel(null)}>完成</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </OperationalWorkspace>
  )
}

function renderNebulaNode(rawNode: unknown) {
  const node = rawNode as NebulaNode
  const [minSize] = node.style.sizeRange
  const coreSize = Math.max(node.val, minSize)
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
}
