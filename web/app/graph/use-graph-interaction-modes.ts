'use client'

import type { Dispatch, RefObject, SetStateAction } from 'react'
import { useCallback, useEffect, useRef } from 'react'

import type { LayoutMode } from '@/components/graph/graph-viewer'
import { findShortestPath } from '@/lib/graph-algorithms'
import type { GraphData } from '@/lib/graph-types'
import { detachPromise } from '@/lib/utils'
import { toast } from 'sonner'

import {
  buildGraphFromTrace,
  getGraphLinkEndpointId,
  getGraphLinkPredicate,
  type GraphLinkLike,
  type GraphNodeLike,
  type GraphTraceReplay,
} from './graph-page-utils'
import type { UseGraphDataLoadingResult } from './use-graph-data-loading'
import type { UseGraphPageStateResult } from './use-graph-page-state'

type GraphViewportApi = {
  focusNode?: (nodeId: string) => void
  zoomToFit?: () => void
} | null

type UseGraphInteractionModesParams = Readonly<{
  searchInputRef: RefObject<HTMLInputElement | null>
  closeContextMenu: () => void
  handleExpandNode: () => void
  handleDeleteNode: (node?: GraphNodeLike) => void
  getActiveGraph: () => GraphViewportApi
  loadLiveGraph: UseGraphDataLoadingResult['loadLiveGraph']
  selectedNode: GraphNodeLike | null
  isDetailOpen: boolean
  isLinkDetailOpen: boolean
  isPathMode: boolean
  isConnectMode: boolean
  isExplainMode: boolean
  explainSteps: UseGraphPageStateResult['explainSteps']
  pathStartNode: GraphNodeLike | null
  pathEndNode: GraphNodeLike | null
  connectSourceNode: GraphNodeLike | null
  connectTargetNode: GraphNodeLike | null
  connectLabelDraft: string
  viewMode: '2d' | '3d'
  layoutMode: LayoutMode
  dataSource: 'live' | 'file'
  traceReplay: GraphTraceReplay | null
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
  setExplainSteps: Dispatch<SetStateAction<UseGraphPageStateResult['explainSteps']>>
  setIsExplainMode: Dispatch<SetStateAction<boolean>>
  setViewMode: Dispatch<SetStateAction<'2d' | '3d'>>
  setGraphData: Dispatch<SetStateAction<GraphData>>
  setDataSource: Dispatch<SetStateAction<'live' | 'file'>>
  setFileName: Dispatch<SetStateAction<string | null>>
  setLayoutMode: Dispatch<SetStateAction<LayoutMode>>
  setIncludeEntityLinks: Dispatch<SetStateAction<boolean>>
  setIncludeRelationLinks: Dispatch<SetStateAction<boolean>>
  setMinSharedEvents: Dispatch<SetStateAction<number>>
  resetPathMode: () => void
  resetConnectMode: () => void
  resetExplainMode: () => void
}>

const LAYOUT_LABELS: Record<LayoutMode, string> = { force: '力导向', tree: '树状', radial: '辐射' }

function buildGraphPathSteps(data: GraphData): UseGraphPageStateResult['explainSteps'] {
  const nodeIds = new Set(data.nodes.map((node) => node.id))
  const edges = data.links
    .map((link) => ({
      source: getGraphLinkEndpointId(link.source),
      target: getGraphLinkEndpointId(link.target),
      predicate: getGraphLinkPredicate(link),
    }))
    .filter(({ source, target }) => source !== target && nodeIds.has(source) && nodeIds.has(target))
  const [firstEdge] = edges
  if (firstEdge === undefined) return []

  let nodeId = firstEdge.source
  const visited = new Set([nodeId])
  const steps = [{ node: nodeId, reason: '路径起点' }]
  while (steps.length < 4) {
    const edge = edges.find(
      ({ source, target }) =>
        (source === nodeId && !visited.has(target)) || (target === nodeId && !visited.has(source)),
    )
    if (edge === undefined) break
    nodeId = edge.source === nodeId ? edge.target : edge.source
    visited.add(nodeId)
    steps.push({ node: nodeId, reason: edge.predicate === '' ? '相邻节点' : edge.predicate })
  }
  return steps
}

export function useGraphInteractionModes({
  searchInputRef,
  closeContextMenu,
  handleExpandNode,
  handleDeleteNode,
  getActiveGraph,
  loadLiveGraph,
  selectedNode,
  isDetailOpen,
  isLinkDetailOpen,
  isPathMode,
  isConnectMode,
  isExplainMode,
  explainSteps,
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
  setFileName,
  setLayoutMode,
  setIncludeEntityLinks,
  setIncludeRelationLinks,
  setMinSharedEvents,
  resetPathMode,
  resetConnectMode,
  resetExplainMode,
}: UseGraphInteractionModesParams) {
  const zoomTimeoutRef = useRef<number | undefined>(undefined)
  useEffect(() => () => globalThis.window.clearTimeout(zoomTimeoutRef.current), [])

  useEffect(() => {
    if (!isExplainMode || explainSteps.length === 0) return

    let stepIndex = 0
    let stepTimerId: number | undefined

    function showNextStep() {
      const step = explainSteps[stepIndex]
      setCurrentStepIndex(stepIndex)
      setHighlightedNodeIds((previous) => new Set([...previous, step.node]))
      getActiveGraph()?.focusNode?.(step.node)

      if (stepIndex > 0) {
        const previousNode = explainSteps[stepIndex - 1].node
        const link = linksWithIds.find((candidate) => {
          const source = getGraphLinkEndpointId(candidate.source)
          const target = getGraphLinkEndpointId(candidate.target)
          return (source === previousNode && target === step.node) || (source === step.node && target === previousNode)
        })
        if (link?.id != null) {
          const linkId = String(link.id)
          setHighlightedLinkIds((previous) => new Set([...previous, linkId]))
        }
      }

      stepIndex += 1
      if (stepIndex < explainSteps.length) {
        stepTimerId = globalThis.window.setTimeout(showNextStep, 1500)
      }
    }

    const frameId = globalThis.window.requestAnimationFrame(showNextStep)
    return () => {
      globalThis.window.cancelAnimationFrame(frameId)
      if (stepTimerId !== undefined) globalThis.window.clearTimeout(stepTimerId)
    }
  }, [
    explainSteps,
    getActiveGraph,
    isExplainMode,
    linksWithIds,
    setCurrentStepIndex,
    setHighlightedLinkIds,
    setHighlightedNodeIds,
  ])

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
    [
      displayGraphData.nodes,
      getActiveGraph,
      linksWithIds,
      setHighlightedLinkIds,
      setHighlightedNodeIds,
      setPathEndNode,
    ],
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
    [connectSourceNode, setConnectLabelDraft, setConnectLabelOpen, setConnectTargetNode],
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
    ],
  )

  const handleLinkClick = useCallback(
    (link: GraphLinkLike) => {
      if (isPathMode || isConnectMode || isExplainMode) return
      setSelectedLink(link)
      setIsLinkDetailOpen(true)
      setIsDetailOpen(false)
      setSelectedNode(null)
    },
    [isConnectMode, isExplainMode, isPathMode, setIsDetailOpen, setIsLinkDetailOpen, setSelectedLink, setSelectedNode],
  )

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return
      const target = event.target instanceof Element ? event.target : null
      if (target?.closest('[role="dialog"], [role="alertdialog"]')) return

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

      if (target?.closest('button, input, textarea, select, a[href]')) return
      if (target instanceof HTMLElement && target.isContentEditable) return
      if (!selectedNode || !isDetailOpen) return

      if (event.key === ' ') {
        event.preventDefault()
        handleExpandNode()
      }

      if (event.key === 'Delete' || event.key === 'Backspace') {
        handleDeleteNode()
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
    toast(`连线模式：请选择终点节点（起点：${selectedNode.label === '' ? selectedNode.id : selectedNode.label}）`)
  }, [selectedNode, setConnectSourceNode, setIsConnectMode, setIsDetailOpen])

  const confirmConnectionLabel = useCallback(() => {
    if (!connectSourceNode || !connectTargetNode) {
      resetConnectMode()
      return
    }

    const label = connectLabelDraft.trim()
    setGraphData((prev) => ({
      ...prev,
      links: [
        ...prev.links,
        {
          source: connectSourceNode.id,
          target: connectTargetNode.id,
          label: label === '' ? 'related_to' : label,
        },
      ],
    }))

    resetConnectMode()
  }, [connectLabelDraft, connectSourceNode, connectTargetNode, resetConnectMode, setGraphData])

  const startExplainMode = useCallback(() => {
    if (traceReplay) {
      const built = buildGraphFromTrace(traceReplay)

      if (viewMode === '3d') {
        setViewMode('2d')
      }

      const isTraceGraph = graphData.nodes.some((node) => node.id === built.rootId)
      if (!isTraceGraph) {
        setGraphData(built.graph)
        setDataSource('file')
        setFileName(`${built.rootId}.json`)
      }

      setHighlightedNodeIds(new Set())
      setHighlightedLinkIds(new Set())
      setCurrentStepIndex(-1)
      setExplainSteps(built.steps)
      setIsExplainMode(true)
      setIsDetailOpen(false)
      setSelectedNode(null)

      return
    }

    const steps = buildGraphPathSteps(displayGraphData)
    if (steps.length === 0) {
      toast.info('当前图谱没有可演示的连接')
      return
    }

    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
    setCurrentStepIndex(-1)
    setExplainSteps(steps)
    setIsExplainMode(true)
    setIsDetailOpen(false)
    setSelectedNode(null)
  }, [
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
    setHighlightedNodeIds(new Set())
    resetConnectMode()
    resetExplainMode()
  }, [isPathMode, resetConnectMode, resetExplainMode, resetPathMode, setHighlightedNodeIds, setIsPathMode])

  const cycleLayoutMode = useCallback(() => {
    setLayoutMode((current) => {
      if (current === 'force') return 'tree'
      if (current === 'tree') return 'radial'
      return 'force'
    })

    globalThis.window.clearTimeout(zoomTimeoutRef.current)
    zoomTimeoutRef.current = globalThis.window.setTimeout(() => {
      getActiveGraph()?.zoomToFit?.()
    }, 500)
  }, [getActiveGraph, setLayoutMode])

  const layoutLabel = LAYOUT_LABELS[layoutMode]

  const toggleEntityLinks = useCallback(() => {
    const next = !includeEntityLinks
    setIncludeEntityLinks(next)
    if (dataSource === 'live') {
      detachPromise(loadLiveGraph({ includeEntityLinks: next }))
    }
  }, [dataSource, includeEntityLinks, loadLiveGraph, setIncludeEntityLinks])

  const toggleRelationLinks = useCallback(() => {
    const next = !includeRelationLinks
    setIncludeRelationLinks(next)
    if (dataSource === 'live') {
      detachPromise(loadLiveGraph({ includeRelationLinks: next }))
    }
  }, [dataSource, includeRelationLinks, loadLiveGraph, setIncludeRelationLinks])

  const cycleMinSharedEvents = useCallback(() => {
    const options = [1, 2, 3, 4]
    const idx = options.indexOf(minSharedEvents)
    const next = options[(idx + 1) % options.length]
    setMinSharedEvents(next)
    if (dataSource === 'live') {
      detachPromise(loadLiveGraph({ minSharedEvents: next }))
    }
  }, [dataSource, loadLiveGraph, minSharedEvents, setMinSharedEvents])

  const handleStartPathFromContextNode = useCallback(
    (node: GraphNodeLike) => {
      resetConnectMode()
      resetExplainMode()
      setIsPathMode(true)
      setPathStartNode(node)
      setPathEndNode(null)
      setHighlightedNodeIds(new Set())
      setHighlightedLinkIds(new Set())
      toast(`路径模式：请选择终点节点（起点：${node.label === '' ? node.id : node.label}）`)
    },
    [
      resetConnectMode,
      resetExplainMode,
      setHighlightedLinkIds,
      setHighlightedNodeIds,
      setIsPathMode,
      setPathEndNode,
      setPathStartNode,
    ],
  )

  const handleStartConnectFromContextNode = useCallback(
    (node: GraphNodeLike) => {
      resetPathMode()
      resetExplainMode()
      setConnectSourceNode(node)
      setIsConnectMode(true)
      toast(`连线模式：请选择终点节点（起点：${node.label === '' ? node.id : node.label}）`)
    },
    [resetExplainMode, resetPathMode, setConnectSourceNode, setIsConnectMode],
  )

  const handleOpenLinkDetailFromContextMenu = useCallback(
    (link: GraphLinkLike) => {
      setSelectedLink(link)
      setIsLinkDetailOpen(true)
      setIsDetailOpen(false)
      setSelectedNode(null)
    },
    [setIsDetailOpen, setIsLinkDetailOpen, setSelectedLink, setSelectedNode],
  )

  const handleClearHighlightsFromContextMenu = useCallback(() => {
    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
    setPathStartNode(null)
    setPathEndNode(null)
  }, [setHighlightedLinkIds, setHighlightedNodeIds, setPathEndNode, setPathStartNode])

  const handleConnectLabelOpenChange = useCallback(
    (open: boolean) => {
      if (!open) resetConnectMode()
    },
    [resetConnectMode],
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
