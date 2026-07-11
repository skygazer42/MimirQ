'use client'

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from 'react'

import { Network, PanelRightClose, PanelRightOpen, Rows3 } from 'lucide-react'
import dynamic from 'next/dynamic'

import type { Remote } from 'comlink'

import { GraphLoadingIndicator } from '@/components/graph/graph-loading-indicator'
import { GraphViewer, type GraphViewerRef, type LayoutMode } from '@/components/graph/graph-viewer'
import type { KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { reportClientWarning } from '@/lib/client-logging'
import type { GraphClusterResult } from '@/lib/graph-clustering'
import type { GraphData } from '@/lib/graph-parser'
import { detachPromise } from '@/lib/utils'
import type { GraphClusteringWorkerApi } from '@/workers/graph-clustering.worker'

import type { GraphLinkLike, GraphNodeLike } from '../graph-page-utils'
import { getNextKeyboardRovingIndex } from './graph-keyboard-roving'

const SEMANTIC_LIST_ITEM_LIMIT = 200
const FRONTEND_TRACE_MIN_DURATION_MS = 12
const SEMANTIC_PANEL_MIN_TOP = 16
const SEMANTIC_PANEL_SIDE_MARGIN = 16
const SEMANTIC_PANEL_TOP_OFFSET = 84
const SEMANTIC_NODE_TONES = ['#89dfe6', '#b6e3ff', '#d3f3b8', '#f3dfb3', '#d7dcff', '#f8cfd8'] as const

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function getSemanticNodeTone(seed: string) {
  let hash = 0
  for (let index = 0; index < seed.length; index += 1) {
    hash = Math.trunc((hash * 31 + (seed.codePointAt(index) ?? 0)) % 0x7fffffff)
  }
  return SEMANTIC_NODE_TONES[Math.abs(hash) % SEMANTIC_NODE_TONES.length]
}

function primitiveText(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

function getCanvasBackdropStyle(isDark: boolean) {
  if (isDark) {
    return {
      backgroundColor: '#0f1722',
      backgroundImage: [
        'radial-gradient(circle at 18% 16%, rgba(56, 189, 248, 0.08), transparent 26%)',
        'radial-gradient(circle at 82% 20%, rgba(59, 130, 246, 0.07), transparent 24%)',
        'linear-gradient(rgba(148, 163, 184, 0.055) 1px, transparent 1px)',
        'linear-gradient(90deg, rgba(148, 163, 184, 0.055) 1px, transparent 1px)',
        'linear-gradient(rgba(96, 165, 250, 0.11) 1px, transparent 1px)',
        'linear-gradient(90deg, rgba(96, 165, 250, 0.11) 1px, transparent 1px)',
      ].join(','),
      backgroundSize: '100% 100%, 100% 100%, 22px 22px, 22px 22px, 110px 110px, 110px 110px',
      backgroundPosition: '0 0, 0 0, -1px -1px, -1px -1px, -1px -1px, -1px -1px',
    } as const
  }

  return {
    backgroundColor: '#f8faff',
    backgroundImage: [
      'radial-gradient(circle at 44% 38%, rgba(96, 165, 250, 0.105), transparent 34%)',
      'radial-gradient(circle at 72% 18%, rgba(139, 92, 246, 0.055), transparent 30%)',
      'radial-gradient(circle at 22% 18%, rgba(255, 255, 255, 0.92), transparent 28%)',
      'linear-gradient(180deg, rgba(250, 252, 255, 0.98) 0%, rgba(245, 248, 253, 0.98) 100%)',
    ].join(','),
    backgroundSize: '100% 100%, 100% 100%, 100% 100%, 100% 100%',
    backgroundPosition: '0 0, 0 0, 0 0, 0 0',
  } as const
}

function getNowMs(): number {
  if (typeof globalThis.performance?.now === 'function') {
    return globalThis.performance.now()
  }
  return Date.now()
}

function getFrontendTracePage(): string {
  if (globalThis.window === undefined) return '/graph'
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
      reportClientWarning('Failed to report graph canvas trace', error)
    })
}

const KnowledgeGraph3D = dynamic(
  () => import('@/components/graph/force-graph-3d').then((mod) => mod.KnowledgeGraph3D),
  {
    ssr: false,
    loading: () => (
      <div className="absolute inset-0 z-10 flex items-center justify-center">
        <div className="flex w-full max-w-lg flex-col items-center gap-3 rounded-2xl border border-border/60 bg-card/90 p-6 shadow-soft backdrop-blur-sm">
          <GraphLoadingIndicator
            className="min-h-0"
            message="正在构建 3D 图谱..."
            srMessage="Loading graph canvas"
            hint="正在同步节点布局与交互层"
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
  hasActiveScope: boolean
  onNodeClick: (node: GraphNodeLike) => void
  onNodeRightClick: (node: GraphNodeLike, event: MouseEvent) => void
  onLinkClick: (link: GraphLinkLike) => void
  onLinkRightClick: (link: GraphLinkLike, event: MouseEvent) => void
  onBackgroundClick: () => void
  onBackgroundRightClick: (event: MouseEvent) => void
  onOpenGraphPicker: () => void
  onTriggerManualKgUpload: () => void
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
  hasActiveScope,
  onNodeClick,
  onNodeRightClick,
  onLinkClick,
  onLinkRightClick,
  onBackgroundClick,
  onBackgroundRightClick,
  onOpenGraphPicker,
  onTriggerManualKgUpload,
}: GraphCanvasProps) {
  const [isSemanticListVisible, setIsSemanticListVisible] = useState(viewMode === '3d')
  const [clusterResult, setClusterResult] = useState<GraphClusterResult | null>(null)
  const [effectiveGraphRenderData, setEffectiveGraphRenderData] = useState<GraphData>(graphRenderData)
  const [keyboardRovingIndex, setKeyboardRovingIndex] = useState(-1)
  const [semanticPanelPosition, setSemanticPanelPosition] = useState<{ x: number; y: number } | null>(null)
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
  const semanticPanelRef = useRef<HTMLDivElement | null>(null)
  const semanticPanelDragStateRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    originX: number
    originY: number
  } | null>(null)

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
        reportClientWarning('Failed to compute graph clusters; falling back to null', e)
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
        reportClientWarning('Graph clustering worker failed; falling back to main thread', e)
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
        const nodeRecord = node as unknown as Record<string, unknown>
        const meta = (nodeRecord.meta ?? {}) as Record<string, unknown>
        const nodeId =
          typeof nodeRecord.id === 'string' && nodeRecord.id.trim().length > 0 ? nodeRecord.id : `node-${index + 1}`
        const type = primitiveText(meta.type ?? nodeRecord.type, 'unknown').trim() || 'unknown'
        const kind = primitiveText(meta.kind, 'entity').trim() || 'entity'
        return {
          id: nodeId,
          label: normalizeNodeLabel(nodeRecord, nodeId),
          type,
          kind,
          raw: node,
        }
      }),
    [graphRenderData.nodes]
  )
  const semanticLinks = useMemo(
    () =>
      graphRenderData.links.slice(0, SEMANTIC_LIST_ITEM_LIMIT).map((link, index) => {
        const linkRecord = link as unknown as Record<string, unknown>
        const meta = (linkRecord.meta ?? {}) as Record<string, unknown>
        const source = normalizeLinkEndpoint(linkRecord.source)
        const target = normalizeLinkEndpoint(linkRecord.target)
        const relation = primitiveText(linkRecord.label ?? linkRecord.relation ?? meta.kind, '关联').trim() || '关联'
        return {
          id: `${source}-${target}-${index}`,
          source,
          target,
          relation,
        }
      }),
    [graphRenderData.links]
  )
  const semanticRelationSummary = useMemo(() => {
    const counts = new Map<string, number>()
    for (const link of semanticLinks) {
      counts.set(link.relation, (counts.get(link.relation) ?? 0) + 1)
    }

    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([relation, count]) => ({ relation, count }))
  }, [semanticLinks])
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

  const clampSemanticPanelPosition = useCallback((position: { x: number; y: number }) => {
    if (graphViewportWidth <= 0 || graphViewportHeight <= 0) {
      return position
    }

    const panelWidth = semanticPanelRef.current?.offsetWidth ?? (isSemanticListVisible ? 352 : 52)
    const panelHeight = semanticPanelRef.current?.offsetHeight ?? (isSemanticListVisible ? 360 : 48)
    const maxX = Math.max(SEMANTIC_PANEL_SIDE_MARGIN, graphViewportWidth - panelWidth - SEMANTIC_PANEL_SIDE_MARGIN)
    const maxY = Math.max(SEMANTIC_PANEL_MIN_TOP, graphViewportHeight - panelHeight - SEMANTIC_PANEL_SIDE_MARGIN)

    return {
      x: clampNumber(position.x, SEMANTIC_PANEL_SIDE_MARGIN, maxX),
      y: clampNumber(position.y, SEMANTIC_PANEL_MIN_TOP, maxY),
    }
  }, [graphViewportHeight, graphViewportWidth, isSemanticListVisible])

  const handleSemanticPanelPointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return

    const panelElement = semanticPanelRef.current
    semanticPanelDragStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: semanticPanelPosition?.x ?? panelElement?.offsetLeft ?? SEMANTIC_PANEL_SIDE_MARGIN,
      originY: semanticPanelPosition?.y ?? panelElement?.offsetTop ?? SEMANTIC_PANEL_TOP_OFFSET,
    }

    event.currentTarget.setPointerCapture(event.pointerId)
    event.preventDefault()
  }, [semanticPanelPosition])

  const handleSemanticPanelPointerMove = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const dragState = semanticPanelDragStateRef.current
    if (dragState?.pointerId !== event.pointerId) return

    const nextPosition = clampSemanticPanelPosition({
      x: dragState.originX + (event.clientX - dragState.startX),
      y: dragState.originY + (event.clientY - dragState.startY),
    })

    setSemanticPanelPosition((current) => {
      if (current?.x === nextPosition.x && current.y === nextPosition.y) {
        return current
      }
      return nextPosition
    })
  }, [clampSemanticPanelPosition])

  const handleSemanticPanelPointerUp = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (semanticPanelDragStateRef.current?.pointerId !== event.pointerId) return
    semanticPanelDragStateRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }, [])

  useEffect(() => {
    setKeyboardRovingIndex((currentIndex) => {
      if (!semanticNodes.length) return -1
      return currentIndex >= semanticNodes.length ? semanticNodes.length - 1 : currentIndex
    })
  }, [semanticNodes.length])

  useEffect(() => {
    if (!semanticPanelPosition) return

    const frame = globalThis.window.requestAnimationFrame(() => {
      setSemanticPanelPosition((current) => {
        if (!current) return current
        const next = clampSemanticPanelPosition(current)
        if (next.x === current.x && next.y === current.y) {
          return current
        }
        return next
      })
    })

    return () => {
      globalThis.window.cancelAnimationFrame(frame)
    }
  }, [clampSemanticPanelPosition, graphViewportHeight, graphViewportWidth, isSemanticListVisible, semanticPanelPosition])

  return (
    <div
      ref={viewportRef}
      className="relative h-full min-h-0 w-full flex-1 overflow-hidden bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
      tabIndex={0}
      role="grid"
      aria-label="知识图谱画布，按 Tab 浏览节点"
      aria-describedby={viewMode === '3d' ? `${semanticPanelId}-keyboard-help ${semanticPanelId}-keyboard-status` : undefined}
      onKeyDown={handleCanvasKeyDown}
    >
      <div
        className="absolute inset-0 z-0"
        style={getCanvasBackdropStyle(isDark)}
      />
      <div className="pointer-events-none absolute inset-0 z-0 bg-[radial-gradient(circle_at_center,transparent_52%,rgba(59,130,246,0.025)_100%)] dark:bg-[radial-gradient(circle_at_center,transparent_42%,rgba(2,6,23,0.36)_100%)]" />

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
                showEdgeLabels={showEdgeLabels}
                layoutMode={layoutMode}
              />
            ) : (
              <div className="absolute inset-0 z-10 flex items-center justify-center">
                <GraphLoadingIndicator
                  className="rounded-2xl border border-border/60 bg-card/82 px-6 py-5 shadow-soft backdrop-blur-sm"
                  message="正在准备图谱画布..."
                  srMessage="Loading graph viewport"
                />
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
          <aside
            className="absolute z-20 pointer-events-none"
            style={
              semanticPanelPosition
                ? { left: semanticPanelPosition.x, top: semanticPanelPosition.y }
                : { right: SEMANTIC_PANEL_SIDE_MARGIN, top: SEMANTIC_PANEL_TOP_OFFSET }
            }
          >
            <div
              ref={semanticPanelRef}
              className={`pointer-events-auto overflow-hidden border border-border/60 bg-[rgba(250,252,255,0.72)] shadow-[12px_18px_46px_-28px_rgba(15,23,42,0.44)] backdrop-blur-xl supports-[backdrop-filter]:bg-[rgba(250,252,255,0.62)] ${
                isSemanticListVisible ? 'w-[min(16.75rem,calc(100vw-2rem))] rounded-[1.35rem]' : 'rounded-[1.35rem]'
              }`}
            >
              <div
                className={`flex items-center gap-2 px-3 py-2.5 ${isSemanticListVisible ? 'border-b border-border/55' : ''}`}
              >
                <button
                  type="button"
                  className="flex h-8 w-8 shrink-0 cursor-grab appearance-none items-center justify-center rounded-xl border border-border/60 bg-card/55 p-0 text-muted-foreground touch-none select-none active:cursor-grabbing"
                  aria-label="拖动语义图谱列表"
                  onPointerDown={handleSemanticPanelPointerDown}
                  onPointerMove={handleSemanticPanelPointerMove}
                  onPointerUp={handleSemanticPanelPointerUp}
                  onPointerCancel={handleSemanticPanelPointerUp}
                >
                  <div className="grid grid-cols-2 gap-[3px]">
                    {Array.from({ length: 6 }, (_, dotIndex) => dotIndex).map((dotIndex) => (
                      <span key={`semantic-drag-dot-${dotIndex}`} className="h-1 w-1 rounded-full bg-current/60" />
                    ))}
                  </div>
                </button>

                {isSemanticListVisible ? (
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <div className="flex h-7 w-7 items-center justify-center rounded-xl border border-border/70 bg-card/60 shadow-[0_10px_20px_-16px_rgba(15,23,42,0.45)]">
                        <div className="grid grid-cols-2 gap-1">
                          {SEMANTIC_NODE_TONES.slice(0, 4).map((tone) => (
                            <span
                              key={tone}
                              className="h-1.5 w-1.5 rounded-full"
                              style={{ backgroundColor: tone }}
                            />
                          ))}
                        </div>
                      </div>
                      <div className="min-w-0">
                        <h2 className="truncate text-sm font-medium text-foreground">语义索引</h2>
                        <p className="truncate text-[11px] text-muted-foreground">
                          当前数据：{semanticNodeCount} 个节点，{semanticLinkCount} 条连线
                        </p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="pr-1 text-[11px] text-muted-foreground">
                    语义列表
                  </div>
                )}

                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-8 w-8 shrink-0 rounded-lg px-0 text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                  aria-label={isSemanticListVisible ? '隐藏语义列表' : '显示语义列表'}
                  title={isSemanticListVisible ? '隐藏语义列表' : '显示语义列表'}
                  aria-expanded={isSemanticListVisible}
                  aria-controls={semanticPanelId}
                  onClick={() => setIsSemanticListVisible((visible) => !visible)}
                >
                  {isSemanticListVisible ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
                  <span className="sr-only">{isSemanticListVisible ? '隐藏语义列表' : '显示语义列表'}</span>
                </Button>
              </div>

              {viewMode === '3d' ? (
                <p
                  id={`${semanticPanelId}-keyboard-help`}
                  className="sr-only"
                >
                  3D 视图为视觉展示，语义列表提供可读结构，便于键盘与屏幕阅读器访问；按 Tab 键可逐个聚焦节点，Shift + Tab 可反向切换。
                </p>
              ) : null}
              <p
                id={`${semanticPanelId}-keyboard-status`}
                aria-live="polite"
                className="sr-only"
              >
                {keyboardRovingIndex >= 0 && semanticNodes[keyboardRovingIndex]
                  ? `键盘当前聚焦：${semanticNodes[keyboardRovingIndex].label}（${keyboardRovingIndex + 1}/${semanticNodes.length}）`
                  : '键盘当前聚焦：尚未选中节点'}
              </p>
              <section
                id={semanticPanelId}
                hidden={!isSemanticListVisible}
                aria-label="知识图谱语义化结构列表"
                className="space-y-3 px-3 py-3 max-h-[min(22rem,calc(100vh-12rem))] overflow-auto"
              >
                {isSemanticListVisible ? (
                  <>
                    <section aria-labelledby={`${semanticPanelId}-nodes`}>
                      <div className="flex items-center justify-between gap-2">
                        <h3 id={`${semanticPanelId}-nodes`} className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                          节点
                        </h3>
                        <div className="inline-flex items-center gap-1 rounded-full border border-border/65 bg-card/55 px-2 py-0.5 text-[11px] text-muted-foreground">
                          <Rows3 className="h-3 w-3" />
                          {semanticNodeCount}
                        </div>
                      </div>
                      <TooltipProvider delayDuration={100}>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {semanticNodes.map((node, index) => {
                            const tone = getSemanticNodeTone(`${node.id}:${node.type}:${node.kind}`)
                            const isActive = selectedNodeId === node.id || keyboardRovingIndex === index

                            return (
                              <Tooltip key={node.id}>
                                <TooltipTrigger asChild>
                                  <button
                                     ref={(element) => setSemanticNodeButtonRef(node.id, element)}
                                     type="button"
                                     className="group/node relative flex h-7 w-7 items-center justify-center rounded-xl border border-border/65 bg-card/52 shadow-[0_10px_22px_-18px_rgba(15,23,42,0.45)] backdrop-blur-sm transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.04] hover:border-foreground/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25"
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
                                    <span
                                      className="absolute inset-[5px] rounded-full opacity-20 transition-opacity duration-200 group-hover/node:opacity-35"
                                      style={{ backgroundColor: tone }}
                                    />
                                    <span
                                      className="relative h-2.5 w-2.5 rounded-full shadow-[0_0_0_4px_rgba(255,255,255,0.5)]"
                                      style={{
                                        backgroundColor: tone,
                                        boxShadow: isActive
                                          ? `0 0 0 4px rgba(255,255,255,0.62), 0 0 0 1px ${tone}`
                                          : '0 0 0 4px rgba(255,255,255,0.5)',
                                      }}
                                    />
                                  </button>
                                </TooltipTrigger>
                                <TooltipContent
                                  side="left"
                                  align="center"
                                  className="rounded-2xl border-border/55 bg-[rgba(250,252,255,0.9)] px-3 py-2 text-[11px] text-foreground shadow-[12px_18px_42px_-24px_rgba(15,23,42,0.38)] backdrop-blur-xl"
                                >
                                  <div className="flex items-start gap-2">
                                    <span className="mt-1 h-2.5 w-2.5 rounded-full" style={{ backgroundColor: tone }} />
                                    <div className="space-y-1">
                                      <div className="font-semibold leading-4 text-foreground">{node.label}</div>
                                      <div className="text-[11px] leading-4 text-muted-foreground">
                                        ID {node.id} · {node.kind} · {node.type}
                                      </div>
                                    </div>
                                  </div>
                                </TooltipContent>
                              </Tooltip>
                            )
                          })}
                        </div>
                      </TooltipProvider>
                    </section>
                    <section aria-labelledby={`${semanticPanelId}-links`}>
                      <div className="flex items-center justify-between gap-2">
                        <h3 id={`${semanticPanelId}-links`} className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                          关系
                        </h3>
                        <div className="inline-flex items-center gap-1 rounded-full border border-border/65 bg-card/55 px-2 py-0.5 text-[11px] text-muted-foreground">
                          {semanticLinkCount}
                        </div>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {semanticRelationSummary.map((item) => (
                          <span
                            key={item.relation}
                            className="inline-flex items-center gap-1 rounded-full border border-border/65 bg-card/58 px-2 py-1 text-[11px] text-muted-foreground shadow-[0_8px_20px_-18px_rgba(15,23,42,0.35)]"
                          >
                            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/80" />
                            {item.relation}
                            <span className="text-muted-foreground">{item.count}</span>
                          </span>
                        ))}
                        {isSemanticListTruncated ? (
                          <span className="inline-flex items-center rounded-full border border-dashed border-border/70 bg-card/42 px-2 py-1 text-[11px] text-muted-foreground">
                            仅显示前 {SEMANTIC_LIST_ITEM_LIMIT} 项
                          </span>
                        ) : null}
                      </div>
                    </section>
                    {keyboardRovingIndex >= 0 && semanticNodes[keyboardRovingIndex] ? (
                      <div className="rounded-2xl border border-border/60 bg-card/48 px-2.5 py-2 text-[11px] text-muted-foreground shadow-[0_10px_26px_-22px_rgba(15,23,42,0.38)]">
                        当前聚焦：<span className="font-semibold text-foreground">{semanticNodes[keyboardRovingIndex].label}</span>
                      </div>
                    ) : null}
                  </>
                ) : null}
              </section>
            </div>
          </aside>
        </>
      ) : (
        <div className="absolute inset-x-0 bottom-0 top-16 z-10 flex items-center justify-center px-6 py-6 pr-28">
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
            <section className="mx-auto flex w-full max-w-[36rem] flex-col items-center justify-center px-8 py-14 text-center md:px-10 md:py-16">
              <div className="mb-7 flex items-center justify-center">
                <svg
                  aria-hidden="true"
                  viewBox="0 0 180 72"
                  className="h-[76px] w-[190px] md:h-[82px] md:w-[204px]"
                >
                  <path
                    d="M36 46H90M90 46H144M90 46V22"
                    fill="none"
                    stroke="hsl(var(--border) / 0.85)"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                  <circle cx="36" cy="46" r="8.7" fill="hsl(var(--background))" stroke="hsl(var(--border) / 0.9)" strokeWidth="1.5" />
                  <circle cx="144" cy="46" r="8.7" fill="hsl(var(--background))" stroke="hsl(var(--border) / 0.9)" strokeWidth="1.5" />
                  <circle cx="90" cy="22" r="10.2" fill="hsl(var(--primary) / 0.08)" stroke="hsl(var(--primary) / 0.45)" strokeWidth="1.6" />
                  <circle cx="90" cy="46" r="8.7" fill="hsl(var(--background))" stroke="hsl(var(--border) / 0.9)" strokeWidth="1.5" />
                  <circle cx="36" cy="46" r="2" fill="hsl(var(--foreground) / 0.45)" />
                  <circle cx="90" cy="46" r="2" fill="hsl(var(--foreground) / 0.45)" />
                  <circle cx="144" cy="46" r="2" fill="hsl(var(--foreground) / 0.45)" />
                  <circle cx="90" cy="22" r="2.7" fill="hsl(var(--primary))" />
                </svg>
              </div>
              <h2 className="mx-auto w-full max-w-[19rem] text-balance text-[1.42rem] font-semibold  text-foreground md:text-[1.56rem]">
                {hasActiveScope ? '当前范围暂无图谱' : '选择知识库图谱'}
              </h2>
              <div className="mx-auto mt-3 w-full max-w-[30rem] text-pretty text-sm leading-7 text-muted-foreground md:text-[15px]">
                {hasActiveScope ? (
                  '当前知识库范围还没有可视化结果。请先执行 KG 抽取，或切换到其他已有图谱的范围。'
                ) : (
                  '优先查看已有知识库 KG；外部图谱统一使用 KG JSON / JSONL 导入。'
                )}
              </div>
              <div className="mx-auto mt-7 flex w-full max-w-[30rem] flex-wrap items-center justify-center gap-3">
                <Button
                  size="lg"
                  className="h-10 rounded-lg px-4 text-[13px] font-semibold shadow-soft hover:bg-primary hover:opacity-96"
                  onClick={onTriggerManualKgUpload}
                >
                  <Network className="h-4 w-4" />
                  导入 KG JSON / JSONL
                </Button>
                <Button
                  size="lg"
                  variant="outline"
                  className="h-10 rounded-lg px-4 text-[13px] font-semibold shadow-soft hover:bg-primary hover:opacity-96"
                  onClick={onOpenGraphPicker}
                >
                  选择图谱
                </Button>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
