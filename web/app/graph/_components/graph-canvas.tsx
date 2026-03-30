'use client'

import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from 'react'

import { Share2, Upload } from 'lucide-react'
import dynamic from 'next/dynamic'

import type { Remote } from 'comlink'

import { GraphViewer, type GraphViewerRef, type LayoutMode } from '@/components/graph/graph-viewer'
import type { KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { PageLoading } from '@/components/ui/page-loading'
import { Skeleton } from '@/components/ui/skeleton'
import type { GraphClusterResult } from '@/lib/graph-clustering'
import type { GraphData } from '@/lib/graph-parser'
import { detachPromise } from '@/lib/utils'
import type { GraphClusteringWorkerApi } from '@/workers/graph-clustering.worker'

import type { GraphLinkLike, GraphNodeLike } from '../graph-page-utils'
import { getNextKeyboardRovingIndex } from './graph-keyboard-roving'

const SEMANTIC_LIST_ITEM_LIMIT = 200
const FRONTEND_TRACE_MIN_DURATION_MS = 12

function getNowMs(): number {
  if (typeof globalThis.performance?.now === 'function') {
    return globalThis.performance.now()
  }
  return Date.now()
}

function getFrontendTracePage(): string {
  if (typeof globalThis.window === 'undefined') return '/graph'
  return globalThis.window.location?.pathname || '/graph'
}

function reportGraphCanvasTrace(payload: {
  event: 'graph_cluster_compute' | 'graph_cluster_palette'
  duration_ms: number
  input_node_count: number
  input_link_count: number
  output_node_count: number
  output_link_count: number
}) {
  if (payload.duration_ms < FRONTEND_TRACE_MIN_DURATION_MS) return

  void import('@/lib/frontend-trace')
    .then(({ reportFrontendTrace }) =>
      reportFrontendTrace(
        {
          ...payload,
          component: 'graph-canvas',
          page: getFrontendTracePage(),
        },
        { keepalive: true }
      )
    )
    .catch((error) => {
      console.warn('Failed to report graph canvas trace', error)
    })
}

const KnowledgeGraph3D = dynamic(
  () => import('@/components/graph/force-graph-3d').then((mod) => mod.KnowledgeGraph3D),
  {
    ssr: false,
    loading: () => (
      <div className="absolute inset-0 z-10 flex items-center justify-center">
        <div className="flex w-full max-w-lg flex-col items-center gap-3 rounded-2xl border border-border/60 bg-card/90 p-6 shadow-soft backdrop-blur-sm">
          <PageLoading
            className="min-h-0"
            message="正在构建 3D 图谱..."
            srMessage="Loading graph canvas"
          />
          <div className="grid w-full gap-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-3 w-[60%]" />
          </div>
        </div>
      </div>
    ),
  }
)

type GraphCanvasProps = Readonly<{
  viewportRef: RefObject<HTMLDivElement | null>
  graph2dRef: RefObject<GraphViewerRef | null>
  graph3dRef: RefObject<KnowledgeGraph3DRef | null>
  isDark: boolean
  graphRenderData: GraphData
  paletteSeed?: string | null
  viewMode: '2d' | '3d'
  graphViewportWidth: number
  graphViewportHeight: number
  selectedNodeId: string | null
  highlightedNodeIds: Set<string>
  highlightedLinkIds: Set<string>
  showEdgeLabels: boolean
  layoutMode: LayoutMode
  isLoading: boolean
  onNodeClick: (node: GraphNodeLike) => void
  onNodeRightClick: (node: GraphNodeLike, event: MouseEvent) => void
  onLinkClick: (link: GraphLinkLike) => void
  onLinkRightClick: (link: GraphLinkLike, event: MouseEvent) => void
  onBackgroundClick: () => void
  onBackgroundRightClick: (event: MouseEvent) => void
  onLoadMock: () => void
  onTriggerFileUpload: () => void
}>

function normalizeNodeLabel(node: Record<string, unknown>, fallback: string) {
  const candidate = [node.label, node.name, node.title, node.id].find(
    (value) => typeof value === 'string' && value.trim().length > 0
  )
  return typeof candidate === 'string' ? candidate : fallback
}

function normalizeLinkEndpoint(endpoint: unknown) {
  if (typeof endpoint === 'string' && endpoint.trim()) return endpoint
  if (typeof endpoint === 'number') return String(endpoint)
  if (endpoint && typeof endpoint === 'object' && 'id' in endpoint) {
    const value = (endpoint as { id?: unknown }).id
    if (typeof value === 'string' && value.trim()) return value
    if (typeof value === 'number') return String(value)
  }
  return 'unknown'
}

export function GraphCanvas({
  viewportRef,
  graph2dRef,
  graph3dRef,
  isDark,
  graphRenderData,
  paletteSeed = null,
  viewMode,
  graphViewportWidth,
  graphViewportHeight,
  selectedNodeId,
  highlightedNodeIds,
  highlightedLinkIds,
  showEdgeLabels,
  layoutMode,
  isLoading,
  onNodeClick,
  onNodeRightClick,
  onLinkClick,
  onLinkRightClick,
  onBackgroundClick,
  onBackgroundRightClick,
  onLoadMock,
  onTriggerFileUpload,
}: GraphCanvasProps) {
  const [isSemanticListVisible, setIsSemanticListVisible] = useState(viewMode === '3d')
  const [clusterResult, setClusterResult] = useState<GraphClusterResult | null>(null)
  const [effectiveGraphRenderData, setEffectiveGraphRenderData] = useState<GraphData>(graphRenderData)
  const [keyboardRovingIndex, setKeyboardRovingIndex] = useState(-1)
  const semanticPanelId = useId()
  const semanticNodeCount = graphRenderData.nodes.length
  const semanticLinkCount = graphRenderData.links.length
  const isSemanticListTruncated =
    semanticNodeCount > SEMANTIC_LIST_ITEM_LIMIT || semanticLinkCount > SEMANTIC_LIST_ITEM_LIMIT

  const clusteringSeqRef = useRef(0)
  const clusteringWorkerRef = useRef<Worker | null>(null)
  const clusteringApiRef = useRef<Remote<GraphClusteringWorkerApi> | null>(null)
  const clusteringDisabledRef = useRef(false)
  const lastClusterTraceKeyRef = useRef<string | null>(null)
  const lastPaletteTraceKeyRef = useRef<string | null>(null)
  const semanticNodeButtonRefs = useRef(new Map<string, HTMLButtonElement>())

  useEffect(() => {
    if (viewMode === '3d') {
      setIsSemanticListVisible(true)
    }
  }, [viewMode])

  useEffect(() => {
    const seq = ++clusteringSeqRef.current
    const nodeCount = graphRenderData.nodes.length
    let cancelled = false
    if (!nodeCount) {
      setClusterResult(null)
      return
    }

    const nodes = graphRenderData.nodes.map((n) => ({ id: n.id, label: n.label }))
    const links = graphRenderData.links.map((l) => ({ source: l.source, target: l.target, label: l.label }))

    const computeOnMainThread = async () => {
      try {
        const startedAt = getNowMs()
        const { computeConnectedComponents } = await import('@/lib/graph-clustering')
        if (cancelled) return
        const res = computeConnectedComponents({ nodes, links })
        if (clusteringSeqRef.current === seq) {
          setClusterResult(res)
        }
        const durationMs = Math.max(0, getNowMs() - startedAt)
        const traceKey = ['main', nodeCount, links.length, res.clusterCount, Math.round(durationMs)].join(':')
        if (lastClusterTraceKeyRef.current !== traceKey) {
          lastClusterTraceKeyRef.current = traceKey
          reportGraphCanvasTrace({
            event: 'graph_cluster_compute',
            duration_ms: durationMs,
            input_node_count: nodeCount,
            input_link_count: links.length,
            output_node_count: nodes.length,
            output_link_count: links.length,
          })
        }
      } catch (e) {
        console.warn('Failed to compute graph clusters; falling back to null', e)
        if (clusteringSeqRef.current === seq) {
          setClusterResult(null)
        }
      }
    }

    if (clusteringDisabledRef.current || typeof Worker === 'undefined') {
      detachPromise(computeOnMainThread())
      return () => {
        cancelled = true
      }
    }

    detachPromise((async () => {
      try {
        const startedAt = getNowMs()
        if (!clusteringWorkerRef.current || !clusteringApiRef.current) {
          const { wrap } = await import('comlink')
          if (cancelled) return
          clusteringWorkerRef.current = new Worker(
            new URL('../../../workers/graph-clustering.worker.ts', import.meta.url),
            { type: 'module' }
          )
          clusteringApiRef.current = wrap<GraphClusteringWorkerApi>(clusteringWorkerRef.current)
        }

        const res = await clusteringApiRef.current.computeConnectedComponents({
          nodes,
          links,
        })

        if (cancelled) return
        if (clusteringSeqRef.current !== seq) return
        setClusterResult(res)
        const durationMs = Math.max(0, getNowMs() - startedAt)
        const traceKey = ['worker', nodeCount, links.length, res.clusterCount, Math.round(durationMs)].join(':')
        if (lastClusterTraceKeyRef.current !== traceKey) {
          lastClusterTraceKeyRef.current = traceKey
          reportGraphCanvasTrace({
            event: 'graph_cluster_compute',
            duration_ms: durationMs,
            input_node_count: nodeCount,
            input_link_count: links.length,
            output_node_count: nodes.length,
            output_link_count: links.length,
          })
        }
      } catch (e) {
        console.warn('Graph clustering worker failed; falling back to main thread', e)
        clusteringDisabledRef.current = true
        detachPromise(computeOnMainThread())
      }
    })())

    return () => {
      cancelled = true
    }
  }, [graphRenderData.links, graphRenderData.nodes])

  useEffect(() => {
    let cancelled = false

    if (!paletteSeed || !clusterResult?.nodeToCluster) {
      setEffectiveGraphRenderData(graphRenderData)
      return
    }

    detachPromise((async () => {
      const startedAt = getNowMs()
      const { applyClusterPalette } = await import('@/lib/graph-cluster-palette')
      if (cancelled) return
      const next = applyClusterPalette({
        graphRenderData,
        paletteSeed,
        clusterResult,
      })
      if (!cancelled) {
        setEffectiveGraphRenderData(next)
      }
      const durationMs = Math.max(0, getNowMs() - startedAt)
      const traceKey = [
        paletteSeed,
        graphRenderData.nodes.length,
        graphRenderData.links.length,
        clusterResult.clusterCount,
        Math.round(durationMs),
      ].join(':')
      if (lastPaletteTraceKeyRef.current !== traceKey) {
        lastPaletteTraceKeyRef.current = traceKey
        reportGraphCanvasTrace({
          event: 'graph_cluster_palette',
          duration_ms: durationMs,
          input_node_count: graphRenderData.nodes.length,
          input_link_count: graphRenderData.links.length,
          output_node_count: next.nodes.length,
          output_link_count: next.links.length,
        })
      }
    })())

    return () => {
      cancelled = true
    }
  }, [clusterResult, graphRenderData, paletteSeed])

  const semanticNodes = useMemo(
    () =>
      graphRenderData.nodes.slice(0, SEMANTIC_LIST_ITEM_LIMIT).map((node, index) => {
        const nodeRecord = node as Record<string, unknown>
        const meta = (nodeRecord.meta ?? {}) as Record<string, unknown>
        const nodeId =
          typeof nodeRecord.id === 'string' && nodeRecord.id.trim().length > 0 ? nodeRecord.id : `node-${index + 1}`
        const type = String(meta.type ?? nodeRecord.type ?? 'unknown').trim() || 'unknown'
        const kind = String(meta.kind ?? 'entity').trim() || 'entity'
        return {
          id: nodeId,
          label: normalizeNodeLabel(nodeRecord, nodeId),
          type,
          kind,
          raw: node as GraphNodeLike,
        }
      }),
    [graphRenderData.nodes]
  )
  const semanticLinks = useMemo(
    () =>
      graphRenderData.links.slice(0, SEMANTIC_LIST_ITEM_LIMIT).map((link, index) => {
        const linkRecord = link as Record<string, unknown>
        const meta = (linkRecord.meta ?? {}) as Record<string, unknown>
        const source = normalizeLinkEndpoint(linkRecord.source)
        const target = normalizeLinkEndpoint(linkRecord.target)
        const relation = String(linkRecord.label ?? linkRecord.relation ?? meta.kind ?? '关联').trim() || '关联'
        return {
          id: `${source}-${target}-${index}`,
          source,
          target,
          relation,
        }
      }),
    [graphRenderData.links]
  )
  const focusSemanticNode = useCallback(
    (nodeId: string) => {
      graph3dRef.current?.focusNode(nodeId)
      graph2dRef.current?.focusNode(nodeId)
    },
    [graph2dRef, graph3dRef]
  )
  const setSemanticNodeButtonRef = useCallback((nodeId: string, element: HTMLButtonElement | null) => {
    if (element) {
      semanticNodeButtonRefs.current.set(nodeId, element)
      return
    }
    semanticNodeButtonRefs.current.delete(nodeId)
  }, [])

  const moveKeyboardRovingFocus = useCallback((direction: 1 | -1) => {
    if (!semanticNodes.length) return

    const nextIndex = getNextKeyboardRovingIndex(keyboardRovingIndex, semanticNodes.length, direction)
    if (nextIndex < 0) return

    const nextNode = semanticNodes[nextIndex]
    const focusNextNode = () => {
      setKeyboardRovingIndex(nextIndex)
      focusSemanticNode(nextNode.id)
      onNodeClick(nextNode.raw)
      semanticNodeButtonRefs.current.get(nextNode.id)?.focus()
    }

    if (!isSemanticListVisible) {
      setIsSemanticListVisible(true)
      globalThis.window.requestAnimationFrame(focusNextNode)
      return
    }

    focusNextNode()
  }, [focusSemanticNode, isSemanticListVisible, keyboardRovingIndex, onNodeClick, semanticNodes])

  const handleCanvasKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (viewMode !== '3d') return
    if (event.key !== 'Tab') return
    if (event.altKey || event.ctrlKey || event.metaKey) return
    if (event.target !== event.currentTarget) return

    event.preventDefault()
    moveKeyboardRovingFocus(event.shiftKey ? -1 : 1)
  }, [moveKeyboardRovingFocus, viewMode])

  useEffect(() => {
    setKeyboardRovingIndex((currentIndex) => {
      if (!semanticNodes.length) return -1
      return currentIndex >= semanticNodes.length ? semanticNodes.length - 1 : currentIndex
    })
  }, [semanticNodes.length])

  return (
    <div
      ref={viewportRef}
      className="flex-1 w-full relative bg-background overflow-hidden min-h-[500px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
      tabIndex={viewMode === '3d' && semanticNodes.length > 0 ? 0 : undefined}
      role={viewMode === '3d' ? 'region' : undefined}
      aria-label={viewMode === '3d' ? '3D 知识图谱画布' : undefined}
      aria-describedby={viewMode === '3d' ? `${semanticPanelId}-keyboard-help ${semanticPanelId}-keyboard-status` : undefined}
      onKeyDown={handleCanvasKeyDown}
    >
      <div
        className="absolute inset-0 z-0 opacity-[0.4]"
        style={{
          backgroundImage: isDark
            ? 'radial-gradient(rgba(148, 163, 184, 0.16) 1px, transparent 1px)'
            : 'radial-gradient(rgba(203, 213, 225, 0.9) 1px, transparent 1px)',
          backgroundSize: '24px 24px',
        }}
      />

      {graphRenderData.nodes.length > 0 ? (
        <>
          {viewMode === '3d' ? (
            graphViewportWidth > 0 && graphViewportHeight > 0 ? (
              <KnowledgeGraph3D
                ref={graph3dRef}
                data={effectiveGraphRenderData}
                width={graphViewportWidth}
                height={graphViewportHeight}
                onNodeClick={onNodeClick}
                onNodeRightClick={onNodeRightClick}
                onLinkClick={onLinkClick}
                onLinkRightClick={onLinkRightClick}
                onBackgroundClick={onBackgroundClick}
                onBackgroundRightClick={onBackgroundRightClick}
                highlightedNodeIds={highlightedNodeIds}
                highlightedLinkIds={highlightedLinkIds}
                selectedNodeId={selectedNodeId}
                layoutMode={layoutMode}
              />
            ) : (
              <div className="absolute inset-0 z-10 flex items-center justify-center text-muted-foreground">
                Loading graph...
              </div>
            )
          ) : (
            <GraphViewer
              ref={graph2dRef}
              data={effectiveGraphRenderData}
              onNodeClick={onNodeClick}
              onNodeRightClick={onNodeRightClick}
              onLinkClick={onLinkClick}
              onLinkRightClick={onLinkRightClick}
              onBackgroundClick={onBackgroundClick}
              onBackgroundRightClick={onBackgroundRightClick}
              highlightedNodeIds={highlightedNodeIds}
              highlightedLinkIds={highlightedLinkIds}
              selectedNodeId={selectedNodeId}
              showEdgeLabels={showEdgeLabels}
              layoutMode={layoutMode}
            />
          )}
          <aside className="absolute top-4 left-4 z-20 w-[min(28rem,calc(100%-2rem))] pointer-events-none">
            <div className="pointer-events-auto rounded-xl border border-border/80 bg-card/90 shadow-soft backdrop-blur-sm supports-[backdrop-filter]:bg-card/75">
              <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-border/60">
                <div className="min-w-0">
                  <h2 className="text-sm font-medium text-foreground">语义图谱列表</h2>
                  <p className="text-xs text-muted-foreground">
                    当前数据：{semanticNodeCount} 个节点，{semanticLinkCount} 条连线
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 shrink-0"
                  aria-expanded={isSemanticListVisible}
                  aria-controls={semanticPanelId}
                  onClick={() => setIsSemanticListVisible((visible) => !visible)}
                >
                  {isSemanticListVisible ? '隐藏语义列表' : '显示语义列表'}
                </Button>
              </div>
              {viewMode === '3d' ? (
                <p id={`${semanticPanelId}-keyboard-help`} className="px-3 pt-2 text-xs text-muted-foreground">
                  3D 视图为视觉展示，语义列表提供可读结构，便于键盘与屏幕阅读器访问；按 Tab 键可逐个聚焦节点，Shift + Tab 可反向切换。
                </p>
              ) : null}
              <p
                id={`${semanticPanelId}-keyboard-status`}
                aria-live="polite"
                className="px-3 pt-1 text-xs text-muted-foreground"
              >
                {keyboardRovingIndex >= 0 && semanticNodes[keyboardRovingIndex]
                  ? `键盘当前聚焦：${semanticNodes[keyboardRovingIndex].label}（${keyboardRovingIndex + 1}/${semanticNodes.length}）`
                  : '键盘当前聚焦：尚未选中节点'}
              </p>
              <div
                id={semanticPanelId}
                hidden={!isSemanticListVisible}
                role="region"
                aria-label="知识图谱语义化结构列表"
                className="space-y-3 px-3 py-3 max-h-72 overflow-auto"
              >
                {isSemanticListVisible ? (
                  <>
                    {isSemanticListTruncated ? (
                      <p className="text-xs text-muted-foreground">
                        为避免大图谱阻塞页面，语义列表仅展示前 {SEMANTIC_LIST_ITEM_LIMIT} 个节点和前{' '}
                        {SEMANTIC_LIST_ITEM_LIMIT} 条连线。
                      </p>
                    ) : null}
                    <section aria-labelledby={`${semanticPanelId}-nodes`}>
                      <h3 id={`${semanticPanelId}-nodes`} className="text-xs font-semibold uppercase text-muted-foreground">
                        节点
                      </h3>
                      <ul className="mt-2 space-y-1.5 text-sm text-foreground">
                        {semanticNodes.map((node, index) => (
                          <li key={node.id}>
                            <button
                              ref={(element) => setSemanticNodeButtonRef(node.id, element)}
                              type="button"
                              className="w-full rounded-lg border border-transparent px-2 py-1.5 text-left transition-colors hover:border-border/70 hover:bg-muted/50 focus-visible:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
                              aria-label={`聚焦节点：${node.label}`}
                              aria-pressed={selectedNodeId === node.id}
                              onFocus={() => {
                                setKeyboardRovingIndex(index)
                                focusSemanticNode(node.id)
                              }}
                              onClick={() => {
                                setKeyboardRovingIndex(index)
                                focusSemanticNode(node.id)
                                onNodeClick(node.raw)
                              }}
                            >
                              <span className="font-medium">{node.label}</span>
                              <span className="text-muted-foreground">（ID: {node.id}，类型: {node.type}，类别: {node.kind}）</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    </section>
                    <section aria-labelledby={`${semanticPanelId}-links`}>
                      <h3 id={`${semanticPanelId}-links`} className="text-xs font-semibold uppercase text-muted-foreground">
                        连线
                      </h3>
                      <ol className="mt-2 space-y-1.5 text-sm text-foreground">
                        {semanticLinks.map((link) => (
                          <li key={link.id}>
                            <span className="font-medium">{link.source}</span>
                            <span className="text-muted-foreground"> → {link.target}（关系: {link.relation}）</span>
                          </li>
                        ))}
                      </ol>
                    </section>
                  </>
                ) : null}
              </div>
            </div>
          </aside>
        </>
      ) : (
        <div className="absolute inset-0 z-10 flex items-center justify-center p-6">
          {isLoading ? (
            <div className="w-full max-w-2xl rounded-2xl border border-border/60 bg-card/70 p-6 shadow-soft">
              <div className="flex items-center gap-3">
                <Skeleton className="h-11 w-11 rounded-xl" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-5 w-44" />
                  <Skeleton className="h-4 w-72" />
                </div>
              </div>
              <div className="mt-6 grid gap-3">
                <Skeleton className="h-20 w-full rounded-xl" />
                <Skeleton className="h-20 w-full rounded-xl" />
                <Skeleton className="h-20 w-full rounded-xl" />
              </div>
              <div className="mt-6 flex items-center gap-3">
                <Skeleton className="h-10 w-32 rounded-xl" />
                <Skeleton className="h-10 w-28 rounded-xl" />
              </div>
            </div>
          ) : (
            <EmptyState
              icon={Share2}
              iconClassName="text-sky-500 dark:text-sky-300"
              title="探索知识网络"
              description={
                <>
                  连接知识孤岛，发现潜在关联。<br />
                  支持实时数据加载、搜索与深度分析。
                </>
              }
              className="w-full max-w-2xl bg-card/80 border-border"
            >
              <Button
                size="lg"
                variant="outline"
                onClick={onLoadMock}
                disabled={isLoading}
                className="border-border hover:bg-muted hover:text-foreground"
              >
                加载示例数据
              </Button>
              <Button
                size="lg"
                className="bg-primary text-primary-foreground hover:bg-primary/90 shadow-soft"
                onClick={onTriggerFileUpload}
              >
                <Upload className="w-5 h-5" />
                开始上传
              </Button>
            </EmptyState>
          )}
        </div>
      )}
    </div>
  )
}
