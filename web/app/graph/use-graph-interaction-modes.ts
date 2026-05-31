'use client'

import type { Dispatch, RefObject, SetStateAction } from 'react'
import { useCallback, useEffect, useMemo } from 'react'

import type { LayoutMode } from '@/components/graph/graph-viewer'
import { findShortestPath } from '@/lib/graph-algorithms'
import type { GraphData } from '@/lib/graph-parser'
import type {
  KGEntityDetailResponse,
  KGEventDetailResponse,
  KGStatsResponse,
  RagTrace,
} from '@/types'
import { toast } from 'sonner'

import {
  buildGraphFromTrace,
  getGraphLinkEndpointId,
  type GraphLinkLike,
  type GraphNodeLike,
} from './graph-page-utils'

type GraphViewportApi = {
  focusNode?: (nodeId: string) => void
  zoomToFit?: () => void
} | null

type GraphExplainabilityStep = {
  node: string
  reason: string
}

type UseGraphInteractionModesParams = Readonly<{
  searchInputRef: RefObject<HTMLInputElement | null>
  closeContextMenu: () => void
  handleExpandNode: () => void
  handleDeleteNode: (node?: GraphNodeLike) => void
  getActiveGraph: () => GraphViewportApi
  loadInitialData: (
    source?: 'live',
    opts?: { includeEntityLinks?: boolean; includeRelationLinks?: boolean; minSharedEvents?: number }
  ) => Promise<void>
  selectedNode: GraphNodeLike | null
  isDetailOpen: boolean
  isLinkDetailOpen: boolean
  isPathMode: boolean
  isConnectMode: boolean
  isExplainMode: boolean
  pathStartNode: GraphNodeLike | null
  pathEndNode: GraphNodeLike | null
  connectSourceNode: GraphNodeLike | null
  connectTargetNode: GraphNodeLike | null
  connectLabelDraft: string
  viewMode: '2d' | '3d'
  layoutMode: LayoutMode
  dataSource: 'live' | 'file'
  traceReplay: RagTrace | null
  graphData: GraphData
  displayGraphData: GraphData
  linksWithIds: GraphLinkLike[]
  includeEntityLinks: boolean
  includeRelationLinks: boolean
  minSharedEvents: number
  setIsPathMode: Dispatch<SetStateAction<boolean>>
  setPathStartNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setPathEndNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setHighlightedNodeIds: Dispatch<SetStateAction<Set<string>>>
  setHighlightedLinkIds: Dispatch<SetStateAction<Set<string>>>
  setIsDetailOpen: Dispatch<SetStateAction<boolean>>
  setSelectedNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setIsLinkDetailOpen: Dispatch<SetStateAction<boolean>>
  setSelectedLink: Dispatch<SetStateAction<GraphLinkLike | null>>
  setConnectSourceNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setIsConnectMode: Dispatch<SetStateAction<boolean>>
  setConnectTargetNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setConnectLabelDraft: Dispatch<SetStateAction<string>>
  setConnectLabelOpen: Dispatch<SetStateAction<boolean>>
  setCurrentStepIndex: Dispatch<SetStateAction<number>>
  setExplainSteps: Dispatch<SetStateAction<GraphExplainabilityStep[]>>
  setIsExplainMode: Dispatch<SetStateAction<boolean>>
  setViewMode: Dispatch<SetStateAction<'2d' | '3d'>>
  setGraphData: Dispatch<SetStateAction<GraphData>>
  setDataSource: Dispatch<SetStateAction<'live' | 'file'>>
  setKgStats: Dispatch<SetStateAction<KGStatsResponse | null>>
  setKgNodeDetail: Dispatch<SetStateAction<KGEntityDetailResponse | KGEventDetailResponse | null>>
  setFileName: Dispatch<SetStateAction<string | null>>
  setLayoutMode: Dispatch<SetStateAction<LayoutMode>>
  setIncludeEntityLinks: Dispatch<SetStateAction<boolean>>
  setIncludeRelationLinks: Dispatch<SetStateAction<boolean>>
  setMinSharedEvents: Dispatch<SetStateAction<number>>
  resetPathMode: () => void
  resetConnectMode: () => void
  resetExplainMode: () => void
}>

function buildHeuristicExplainSteps(data: GraphData): GraphExplainabilityStep[] {
  if (data.nodes.length === 0) return []

  const trace: GraphNodeLike[] = []
  const visited = new Set<string>()
  let current = data.nodes[0] as GraphNodeLike

  for (let idx = 0; idx < 4; idx += 1) {
    trace.push(current)
    visited.add(current.id)

    const link = data.links.find((candidate) => {
      const sourceId = getGraphLinkEndpointId(candidate.source)
      const targetId = getGraphLinkEndpointId(candidate.target)
      return (sourceId === current.id && !visited.has(targetId)) || (targetId === current.id && !visited.has(sourceId))
    })

    if (link) {
      const sourceId = getGraphLinkEndpointId(link.source)
      const targetId = getGraphLinkEndpointId(link.target)
      const nextId = sourceId === current.id ? targetId : sourceId
      current = data.nodes.find((node) => node.id === nextId) || data.nodes[idx + 1]
    } else {
      current = data.nodes[Math.min(idx + 5, data.nodes.length - 1)]
    }
  }

  return trace.map((node, idx) => ({
    node: node.id,
    reason:
      idx === 0
        ? '初始查询匹配到的实体'
        : idx === trace.length - 1
          ? '最终推理得出的答案'
          : '通过关系链召回的相关节点',
  }))
}

export function useGraphInteractionModes({
  searchInputRef,
  closeContextMenu,
  handleExpandNode,
  handleDeleteNode,
  getActiveGraph,
  loadInitialData,
  selectedNode,
  isDetailOpen,
  isLinkDetailOpen,
  isPathMode,
  isConnectMode,
  isExplainMode,
  pathStartNode,
  pathEndNode,
  connectSourceNode,
  connectTargetNode,
  connectLabelDraft,
  viewMode,
  layoutMode,
  dataSource,
  traceReplay,
  graphData,
  displayGraphData,
  linksWithIds,
  includeEntityLinks,
  includeRelationLinks,
  minSharedEvents,
  setIsPathMode,
  setPathStartNode,
  setPathEndNode,
  setHighlightedNodeIds,
  setHighlightedLinkIds,
  setIsDetailOpen,
  setSelectedNode,
  setIsLinkDetailOpen,
  setSelectedLink,
  setConnectSourceNode,
  setIsConnectMode,
  setConnectTargetNode,
  setConnectLabelDraft,
  setConnectLabelOpen,
  setCurrentStepIndex,
  setExplainSteps,
  setIsExplainMode,
  setViewMode,
  setGraphData,
  setDataSource,
  setKgStats,
  setKgNodeDetail,
  setFileName,
  setLayoutMode,
  setIncludeEntityLinks,
  setIncludeRelationLinks,
  setMinSharedEvents,
  resetPathMode,
  resetConnectMode,
  resetExplainMode,
}: UseGraphInteractionModesParams) {
  const animateTrace = useCallback(
    async (steps: { node: string }[], graphOverride?: GraphData) => {
      const graph = graphOverride || graphData
      for (let idx = 0; idx < steps.length; idx += 1) {
        const step = steps[idx]
        setCurrentStepIndex(idx)
        setHighlightedNodeIds((prev) => new Set([...Array.from(prev), step.node]))

        getActiveGraph()?.focusNode?.(step.node)

        if (idx > 0) {
          const prevNode = steps[idx - 1]?.node
          const currNode = step.node
          const link = graph.links.find((candidate) => {
            const sourceId = getGraphLinkEndpointId(candidate.source)
            const targetId = getGraphLinkEndpointId(candidate.target)
            return (sourceId === prevNode && targetId === currNode) || (sourceId === currNode && targetId === prevNode)
          })

          if (link) {
            const rawId = link.id
            const linkIndex = link.index
            const idxInGraph = graph.links.indexOf(link)
            const linkId =
              rawId ||
              (linkIndex === undefined ? (idxInGraph >= 0 ? `link-${idxInGraph}` : null) : `link-${linkIndex}`)

            if (linkId) {
              setHighlightedLinkIds((prev) => new Set([...Array.from(prev), String(linkId)]))
            }
          }
        }

        await new Promise((resolve) => globalThis.window.setTimeout(resolve, 1500))
      }
    },
    [getActiveGraph, graphData, setCurrentStepIndex, setHighlightedLinkIds, setHighlightedNodeIds]
  )

  const calculatePath = useCallback(
    (start: GraphNodeLike, end: GraphNodeLike) => {
      const result = findShortestPath(displayGraphData.nodes, linksWithIds, start.id, end.id)

      if (result) {
        setHighlightedNodeIds(new Set(result.nodeIds))
        setHighlightedLinkIds(new Set(result.linkIds))
        getActiveGraph()?.zoomToFit?.()
      } else {
        toast.info('未找到连接这两个节点的路径')
        setPathEndNode(null)
      }
    },
    [displayGraphData.nodes, getActiveGraph, linksWithIds, setHighlightedLinkIds, setHighlightedNodeIds, setPathEndNode]
  )

  const finishConnection = useCallback(
    (targetNode: GraphNodeLike) => {
      if (!connectSourceNode) return
      if (connectSourceNode.id === targetNode.id) {
        toast.error('不能连接自己')
        return
      }

      setConnectTargetNode(targetNode)
      setConnectLabelDraft('related_to')
      setConnectLabelOpen(true)
    },
    [connectSourceNode, setConnectLabelDraft, setConnectLabelOpen, setConnectTargetNode]
  )

  const handleNodeClick = useCallback(
    (node: GraphNodeLike) => {
      if (isPathMode) {
        if (pathStartNode) {
          if (pathEndNode) {
            setPathStartNode(node)
            setPathEndNode(null)
            setHighlightedNodeIds(new Set())
            setHighlightedLinkIds(new Set())
          } else {
            if (node.id === pathStartNode.id) {
              setPathStartNode(null)
              return
            }
            setPathEndNode(node)
            calculatePath(pathStartNode, node)
          }
        } else {
          setPathStartNode(node)
        }
        return
      }

      if (isConnectMode) {
        finishConnection(node)
        return
      }

      if (!isExplainMode) {
        setSelectedNode(node)
        setIsDetailOpen(true)
        setIsLinkDetailOpen(false)
        setSelectedLink(null)
      }
    },
    [
      calculatePath,
      finishConnection,
      isConnectMode,
      isExplainMode,
      isPathMode,
      pathEndNode,
      pathStartNode,
      setHighlightedLinkIds,
      setHighlightedNodeIds,
      setIsDetailOpen,
      setIsLinkDetailOpen,
      setPathEndNode,
      setPathStartNode,
      setSelectedLink,
      setSelectedNode,
    ]
  )

  const handleLinkClick = useCallback(
    (link: GraphLinkLike) => {
      if (isPathMode || isConnectMode || isExplainMode) return
      setSelectedLink(link)
      setIsLinkDetailOpen(true)
      setIsDetailOpen(false)
      setSelectedNode(null)
    },
    [isConnectMode, isExplainMode, isPathMode, setIsDetailOpen, setIsLinkDetailOpen, setSelectedLink, setSelectedNode]
  )

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'f') {
        event.preventDefault()
        searchInputRef.current?.focus()
      }

      if (event.key === 'Escape') {
        if (isDetailOpen) setIsDetailOpen(false)
        if (isLinkDetailOpen) {
          setIsLinkDetailOpen(false)
          setSelectedLink(null)
        }
        if (isPathMode) resetPathMode()
        if (isConnectMode) resetConnectMode()
        if (isExplainMode) resetExplainMode()
        closeContextMenu()
        searchInputRef.current?.blur()
      }

      if (
        event.key === ' ' &&
        selectedNode &&
        isDetailOpen &&
        !['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName)
      ) {
        event.preventDefault()
        handleExpandNode()
      }

      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (
          selectedNode &&
          isDetailOpen &&
          !['INPUT', 'TEXTAREA'].includes((event.target as HTMLElement).tagName)
        ) {
          handleDeleteNode()
        }
      }
    }

    globalThis.window.addEventListener('keydown', handleKeyDown)
    return () => globalThis.window.removeEventListener('keydown', handleKeyDown)
  }, [
    closeContextMenu,
    handleDeleteNode,
    handleExpandNode,
    isConnectMode,
    isDetailOpen,
    isExplainMode,
    isLinkDetailOpen,
    isPathMode,
    resetConnectMode,
    resetExplainMode,
    resetPathMode,
    searchInputRef,
    selectedNode,
    setIsDetailOpen,
    setIsLinkDetailOpen,
    setSelectedLink,
  ])

  const startConnectMode = useCallback(() => {
    if (!selectedNode) return
    setConnectSourceNode(selectedNode)
    setIsConnectMode(true)
    setIsDetailOpen(false)
    toast(`连线模式：请选择终点节点（起点：${String(selectedNode.label || selectedNode.id || '')}）`)
  }, [selectedNode, setConnectSourceNode, setIsConnectMode, setIsDetailOpen])

  const confirmConnectionLabel = useCallback(() => {
    if (!connectSourceNode || !connectTargetNode) {
      setConnectLabelOpen(false)
      setConnectTargetNode(null)
      resetConnectMode()
      return
    }

    const label = connectLabelDraft.trim() || 'related_to'
    setGraphData((prev) => ({
      ...prev,
      links: [
        ...prev.links,
        {
          source: connectSourceNode.id,
          target: connectTargetNode.id,
          label,
        },
      ],
    }))

    setConnectLabelOpen(false)
    setConnectTargetNode(null)
    resetConnectMode()
  }, [
    connectLabelDraft,
    connectSourceNode,
    connectTargetNode,
    resetConnectMode,
    setConnectLabelOpen,
    setConnectTargetNode,
    setGraphData,
  ])

  const startExplainMode = useCallback(() => {
    if (traceReplay) {
      const built = buildGraphFromTrace(traceReplay)

      if (viewMode === '3d') {
        setViewMode('2d')
      }

      const prefix = `rag-trace:${traceReplay.request_id || traceReplay.ts_ms}`
      const isTraceGraph = graphData.nodes.some((node) => String(node.id || '').startsWith(prefix))
      if (!isTraceGraph) {
        setGraphData(built.graph)
        setDataSource('file')
        setKgStats(null)
        setKgNodeDetail(null)
        setFileName(`${prefix}.json`)
      }

      setHighlightedNodeIds(new Set())
      setHighlightedLinkIds(new Set())
      setCurrentStepIndex(-1)
      setExplainSteps(built.steps)
      setIsExplainMode(true)
      setIsDetailOpen(false)
      setSelectedNode(null)

      globalThis.window.requestAnimationFrame(() => {
        void animateTrace(built.steps, built.graph)
      })
      return
    }

    if (displayGraphData.nodes.length < 3) {
      toast.warning('图谱节点过少，无法演示推理路径')
      return
    }

    const steps = buildHeuristicExplainSteps(displayGraphData)

    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
    setCurrentStepIndex(-1)
    setExplainSteps(steps)
    setIsExplainMode(true)
    setIsDetailOpen(false)
    setSelectedNode(null)

    void animateTrace(steps)
  }, [
    animateTrace,
    displayGraphData,
    graphData.nodes,
    setCurrentStepIndex,
    setDataSource,
    setExplainSteps,
    setFileName,
    setGraphData,
    setHighlightedLinkIds,
    setHighlightedNodeIds,
    setIsDetailOpen,
    setIsExplainMode,
    setKgNodeDetail,
    setKgStats,
    setSelectedNode,
    setViewMode,
    traceReplay,
    viewMode,
  ])

  const togglePathMode = useCallback(() => {
    if (isPathMode) {
      resetPathMode()
      return
    }

    setIsPathMode(true)
    setIsDetailOpen(false)
    setSelectedNode(null)
    setHighlightedNodeIds(new Set())
    resetConnectMode()
    resetExplainMode()
  }, [
    isPathMode,
    resetConnectMode,
    resetExplainMode,
    resetPathMode,
    setHighlightedNodeIds,
    setIsDetailOpen,
    setIsPathMode,
    setSelectedNode,
  ])

  const cycleLayoutMode = useCallback(() => {
    setLayoutMode((current) => {
      if (current === 'force') return 'tree'
      if (current === 'tree') return 'radial'
      return 'force'
    })

    globalThis.window.setTimeout(() => {
      getActiveGraph()?.zoomToFit?.()
    }, 500)
  }, [getActiveGraph, setLayoutMode])

  const layoutLabel = useMemo(() => {
    switch (layoutMode) {
      case 'force':
        return '力导向'
      case 'tree':
        return '树状'
      case 'radial':
        return '辐射'
      default:
        return '力导向'
    }
  }, [layoutMode])

  const toggleEntityLinks = useCallback(() => {
    const next = !includeEntityLinks
    setIncludeEntityLinks(next)
    if (dataSource === 'live') {
      void loadInitialData('live', { includeEntityLinks: next })
    }
  }, [dataSource, includeEntityLinks, loadInitialData, setIncludeEntityLinks])

  const toggleRelationLinks = useCallback(() => {
    const next = !includeRelationLinks
    setIncludeRelationLinks(next)
    if (dataSource === 'live') {
      void loadInitialData('live', { includeRelationLinks: next })
    }
  }, [dataSource, includeRelationLinks, loadInitialData, setIncludeRelationLinks])

  const cycleMinSharedEvents = useCallback(() => {
    const options = [1, 2, 3, 4]
    const idx = options.indexOf(minSharedEvents)
    const next = options[(idx + 1) % options.length] || 2
    setMinSharedEvents(next)
    if (dataSource === 'live') {
      void loadInitialData('live', { minSharedEvents: next })
    }
  }, [dataSource, loadInitialData, minSharedEvents, setMinSharedEvents])

  const handleStartPathFromContextNode = useCallback(
    (node: GraphNodeLike) => {
      resetConnectMode()
      resetExplainMode()
      setIsPathMode(true)
      setPathStartNode(node)
      setPathEndNode(null)
      setHighlightedNodeIds(new Set())
      setHighlightedLinkIds(new Set())
      toast(`路径模式：请选择终点节点（起点：${String(node.label || node.id || '')}）`)
    },
    [
      resetConnectMode,
      resetExplainMode,
      setHighlightedLinkIds,
      setHighlightedNodeIds,
      setIsPathMode,
      setPathEndNode,
      setPathStartNode,
    ]
  )

  const handleStartConnectFromContextNode = useCallback(
    (node: GraphNodeLike) => {
      resetPathMode()
      resetExplainMode()
      setConnectSourceNode(node)
      setIsConnectMode(true)
      toast(`连线模式：请选择终点节点（起点：${String(node.label || node.id || '')}）`)
    },
    [resetExplainMode, resetPathMode, setConnectSourceNode, setIsConnectMode]
  )

  const handleOpenLinkDetailFromContextMenu = useCallback(
    (link: GraphLinkLike) => {
      setSelectedLink(link)
      setIsLinkDetailOpen(true)
      setIsDetailOpen(false)
      setSelectedNode(null)
    },
    [setIsDetailOpen, setIsLinkDetailOpen, setSelectedLink, setSelectedNode]
  )

  const handleClearHighlightsFromContextMenu = useCallback(() => {
    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
    setPathStartNode(null)
    setPathEndNode(null)
  }, [setHighlightedLinkIds, setHighlightedNodeIds, setPathEndNode, setPathStartNode])

  const handleConnectLabelOpenChange = useCallback(
    (open: boolean) => {
      setConnectLabelOpen(open)
      if (!open) {
        setConnectTargetNode(null)
        resetConnectMode()
      }
    },
    [resetConnectMode, setConnectLabelOpen, setConnectTargetNode]
  )

  return {
    startConnectMode,
    confirmConnectionLabel,
    startExplainMode,
    handleNodeClick,
    handleLinkClick,
    togglePathMode,
    cycleLayoutMode,
    layoutLabel,
    toggleEntityLinks,
    toggleRelationLinks,
    cycleMinSharedEvents,
    handleStartPathFromContextNode,
    handleStartConnectFromContextNode,
    handleOpenLinkDetailFromContextMenu,
    handleClearHighlightsFromContextMenu,
    handleConnectLabelOpenChange,
  }
}

export type UseGraphInteractionModesResult = ReturnType<typeof useGraphInteractionModes>
