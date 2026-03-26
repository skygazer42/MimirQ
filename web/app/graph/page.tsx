'use client'

/**
 * 知识图谱可视化页面
 * 功能：上传 .graphml 文件并进行可视化展示
 * 优化：主流视觉设计、交互侧边栏、玻璃拟态控件、搜索与高级筛选、后端集成、路径分析、布局切换、图编辑、RAG可解释性、3D可视化
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useTheme } from 'next-themes'
import { useSearchParams } from 'next/navigation'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Share2 } from 'lucide-react'
import { GraphActionDialogs } from './_components/graph-action-dialogs'
import { GraphPageBody } from './_components/graph-page-body'
import { GraphPageHeader } from './_components/graph-page-header'
import { GraphViewerRef, LayoutMode } from '@/components/graph/graph-viewer'
import { type KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { GraphData } from '@/lib/graph-parser'
import { GraphService } from '@/lib/graph-service'
import { detachPromise } from '@/lib/utils'
import { documentApi } from '@/lib/api/documents'
import { kgApi } from '@/lib/api/graph'
import { useGraphDataLoading } from './use-graph-data-loading'
import { useGraphDisplayFilters } from './use-graph-display-filters'
import { useGraphEntityResolution } from './use-graph-entity-resolution'
import { useGraphInteractionModes } from './use-graph-interaction-modes'
import { useGraphPageActions } from './use-graph-page-actions'
import {
  GraphConfBucket,
  type GraphDatasetDocumentSummary,
  type GraphLinkLike,
  type GraphNodeLike,
  coerceBoundedInt,
  getGraphLinkEndpointId,
  getScopedDocumentId,
  isPendingScopedDocument,
  parseCsvList,
} from './graph-page-utils'
import type {
  KGEntityDetailResponse,
  KGEventDetailResponse,
  KGStatsResponse,
  RagTrace,
} from '@/types'
import { useResizeObserver } from '@/hooks/use-resize-observer'

export default function GraphPage() {
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === 'dark'
  const searchParams = useSearchParams()
  const scopeParamKey = searchParams.toString()
  const scope = useMemo(() => {
    const sp = new URLSearchParams(scopeParamKey)
    const directDocIds = [
      ...parseCsvList(sp.get('document_ids')),
      ...sp.getAll('document_id'),
    ]
      .map((s) => String(s || '').trim())
      .filter(Boolean)

    const uniqDocIds = Array.from(new Set(directDocIds))
    const datasetId = (sp.get('dataset_id') || '').trim() || null
    const pipelineHash = (sp.get('pipeline_hash') || '').trim() || null
    const docLimit = coerceBoundedInt(sp.get('doc_limit'), 200, 1, 500)
    const hasScope = uniqDocIds.length > 0 || Boolean(datasetId) || Boolean(pipelineHash)
    return {
      hasScope,
      directDocIds: uniqDocIds,
      datasetId,
      pipelineHash,
      docLimit,
    }
  }, [scopeParamKey])

  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] })
  const [fileName, setFileName] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNodeLike | null>(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const [selectedLink, setSelectedLink] = useState<GraphLinkLike | null>(null)
  const [isLinkDetailOpen, setIsLinkDetailOpen] = useState(false)
  const [selfLoopGroupExpanded, setSelfLoopGroupExpanded] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [deleteNodeOpen, setDeleteNodeOpen] = useState(false)
  const [deleteNodeTarget, setDeleteNodeTarget] = useState<{ id: string; label: string } | null>(null)
  const [dataSource, setDataSource] = useState<'live' | 'mock' | 'file'>('live')
  const [includeEntityLinks, setIncludeEntityLinks] = useState(true)
  const [includeRelationLinks, setIncludeRelationLinks] = useState(false)
  const [minSharedEvents, setMinSharedEvents] = useState(2)
  const maxEntityLinks = 1000

  // Optional scope:
  // - /graph?document_ids=a,b,c&pipeline_hash=... (direct scope)
  // - /graph?dataset_id=...&doc_limit=200 (dataset scope; resolves to document ids client-side)
  const [scopedDatasetDocIds, setScopedDatasetDocIds] = useState<string[] | null>(null)
  const [scopedDatasetDocIdsLoading, setScopedDatasetDocIdsLoading] = useState(false)
  const [scopedDatasetPendingDocs, setScopedDatasetPendingDocs] = useState<number | null>(null)

  const scopedDocumentIds: string[] | null = useMemo(() => {
    if (scope.directDocIds.length > 0) return scope.directDocIds
    if (scope.datasetId) return scopedDatasetDocIds
    return null
  }, [scope.datasetId, scope.directDocIds, scopedDatasetDocIds])
  const scopedDocumentIdsKey = useMemo(() => (scopedDocumentIds ? scopedDocumentIds.join(',') : ''), [scopedDocumentIds])
  const scopeParams = useMemo(() => {
    const document_ids = scopedDocumentIds && scopedDocumentIds.length > 0 ? scopedDocumentIds : undefined
    const pipeline_hash = scope.pipelineHash ? scope.pipelineHash : undefined
    if (!document_ids && !pipeline_hash) return null
    return { document_ids, pipeline_hash }
  }, [scopedDocumentIds, scope.pipelineHash])

  useEffect(() => {
    let cancelled = false

    if (scope.directDocIds.length > 0) {
      setScopedDatasetDocIds(null)
      setScopedDatasetDocIdsLoading(false)
      setScopedDatasetPendingDocs(null)
      return () => {
        cancelled = true
      }
    }

    const datasetId = scope.datasetId
    if (!datasetId) {
      setScopedDatasetDocIds(null)
      setScopedDatasetDocIdsLoading(false)
      setScopedDatasetPendingDocs(null)
      return () => {
        cancelled = true
      }
    }

    setScopedDatasetDocIdsLoading(true)
    setScopedDatasetPendingDocs(null)
    ;(async () => {
      try {
        const list = await documentApi.list({
          skip: 0,
          limit: scope.docLimit,
          dataset_id: datasetId,
          order_by: 'created_at',
          order_dir: 'desc',
        })
        const items: GraphDatasetDocumentSummary[] = Array.isArray(list.items) ? list.items : []
        const ids = items.map((item) => getScopedDocumentId(item)).filter(Boolean)
        const pending = items.filter((item) => isPendingScopedDocument(item)).length
        if (!cancelled) setScopedDatasetDocIds(ids)
        if (!cancelled) setScopedDatasetPendingDocs(pending)
      } catch {
        if (!cancelled) setScopedDatasetDocIds([])
        if (!cancelled) setScopedDatasetPendingDocs(null)
      } finally {
        if (!cancelled) setScopedDatasetDocIdsLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [scope.datasetId, scope.docLimit, scope.directDocIds])

  const [kgStats, setKgStats] = useState<KGStatsResponse | null>(null)
  const [kgNodeDetail, setKgNodeDetail] = useState<KGEntityDetailResponse | KGEventDetailResponse | null>(null)
  const [kgNodeDetailLoading, setKgNodeDetailLoading] = useState(false)
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('3d')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [entityTypeFilters, setEntityTypeFilters] = useState<string[]>([])
  const [predicateFilters, setPredicateFilters] = useState<string[]>([])
  const [confidenceBucketFilters, setConfidenceBucketFilters] = useState<GraphConfBucket[]>([])
  const [entityTypeQuery, setEntityTypeQuery] = useState('')
  const [predicateQuery, setPredicateQuery] = useState('')
  
  // Search & Filter State
  const [searchTerm, setSearchTerm] = useState('')
  const [showEdgeLabels, setShowEdgeLabels] = useState(true)
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set())
  const [highlightedLinkIds, setHighlightedLinkIds] = useState<Set<string>>(new Set())

  // Path Finding State
  const [isPathMode, setIsPathMode] = useState(false)
  const [pathStartNode, setPathStartNode] = useState<GraphNodeLike | null>(null)
  const [pathEndNode, setPathEndNode] = useState<GraphNodeLike | null>(null)

  // Layout & View Mode
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('force')

  // Editing State
  const [isConnectMode, setIsConnectMode] = useState(false)
  const [connectSourceNode, setConnectSourceNode] = useState<GraphNodeLike | null>(null)
  const [connectLabelOpen, setConnectLabelOpen] = useState(false)
  const [connectTargetNode, setConnectTargetNode] = useState<GraphNodeLike | null>(null)
  const [connectLabelDraft, setConnectLabelDraft] = useState('related_to')

  const detailScrollRef = useRef<HTMLDivElement>(null)
  const selectedNodeId = selectedNode?.id

  // Reset the detail panel scroll when switching nodes so it doesn't appear "half scrolled".
  useEffect(() => {
    if (!isDetailOpen || !selectedNodeId) return
    const raf = globalThis.window.requestAnimationFrame(() => {
      detailScrollRef.current?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
    })
    return () => globalThis.window.cancelAnimationFrame(raf)
  }, [isDetailOpen, selectedNodeId])

  // Explainability State
  const [isExplainMode, setIsExplainMode] = useState(false)
  const [explainSteps, setExplainSteps] = useState<{node: string, reason: string}[]>([])
  const [currentStepIndex, setCurrentStepIndex] = useState(-1)
  const [traceReplay, setTraceReplay] = useState<RagTrace | null>(null)

  const graphViewportRef = useRef<HTMLDivElement>(null)
  const graph2dRef = useRef<GraphViewerRef>(null)
  const graph3dRef = useRef<KnowledgeGraph3DRef>(null)
  const { width: graphViewportWidth, height: graphViewportHeight } = useResizeObserver(graphViewportRef)

  const getActiveGraph = useCallback(() => {
    return viewMode === '3d' ? graph3dRef.current : graph2dRef.current
  }, [viewMode])

  const fileInputRef = useRef<HTMLInputElement>(null)
  const traceFileInputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    // Reset per-link expanded state when the selection/panel changes.
    setSelfLoopGroupExpanded(false)
  }, [selectedLink, isLinkDetailOpen])

  const resetConnectMode = useCallback(() => {
    setIsConnectMode(false)
    setConnectSourceNode(null)
  }, [])

  const resetExplainMode = useCallback(() => {
    setIsExplainMode(false)
    setExplainSteps([])
    setCurrentStepIndex(-1)
    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
  }, [])

  const resetPathMode = useCallback(() => {
    setIsPathMode(false)
    setPathStartNode(null)
    setPathEndNode(null)
    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
  }, [])

  const {
    loadInitialData,
    handleFileUpload,
    triggerFileUpload,
    handleTraceFileUpload,
    triggerTraceUpload,
  } = useGraphDataLoading({
    scope,
    scopedDocumentIds,
    scopedDatasetDocIdsLoading,
    scopeParams,
    includeEntityLinks,
    includeRelationLinks,
    minSharedEvents,
    maxEntityLinks,
    setGraphData,
    setFileName,
    setDataSource,
    setTraceReplay,
    setKgStats,
    setKgNodeDetail,
    setIsLoading,
    setIsDetailOpen,
    setSelectedNode,
    setViewMode,
    fileInputRef,
    traceFileInputRef,
    resetPathMode,
    resetConnectMode,
    resetExplainMode,
  })

  const {
    entityAliases,
    entityAliasesLoading,
    aliasDraft,
    setAliasDraft,
    aliasSaving,
    aliasDeleteOpen,
    aliasDeleteTarget,
    aliasSuggestions,
    aliasSuggestionsLoading,
    mergeOpen,
    mergeSearch,
    setMergeSearch,
    mergeSearchLoading,
    mergeSearchResults,
    mergeTarget,
    mergePreview,
    mergePreviewLoading,
    mergeConfirmOpen,
    setMergeConfirmOpen,
    mergeSubmitting,
    mergeError,
    splitOpen,
    splitNameDraft,
    setSplitNameDraft,
    splitSelectedEventIds,
    splitSubmitting,
    splitError,
    lastResolutionActionId,
    undoSubmitting,
    handleSaveAlias,
    requestDeleteAlias,
    confirmDeleteAlias,
    openMergeDialog,
    selectMergeTarget,
    handleMergeAliasSuggestion,
    submitMerge,
    openSplitDialog,
    toggleSplitEvent,
    submitSplit,
    undoLastResolution,
    handleAliasDeleteOpenChange,
    handleMergeOpenChange,
    handleSplitOpenChange,
  } = useGraphEntityResolution({
    dataSource,
    isDetailOpen,
    selectedNode,
    scopeParams,
    loadInitialData,
  })

  const {
    availableEntityTypes,
    filteredEntityTypes,
    filteredPredicates,
    activeGraphFilterCount,
    displayGraphData,
    linksWithIds,
    graphRenderData,
    resetGraphFilters,
    handleEntityTypeCheckedChange,
    handlePredicateCheckedChange,
    toggleConfidenceBucket,
    toggleEntityTypeFilter,
  } = useGraphDisplayFilters({
    graphData,
    searchTerm,
    entityTypeFilters,
    predicateFilters,
    confidenceBucketFilters,
    entityTypeQuery,
    predicateQuery,
    isPathMode,
    isConnectMode,
    isExplainMode,
    selectedNodeId: selectedNodeId ?? null,
    isDetailOpen,
    getActiveGraph,
    setIsDetailOpen,
    setSelectedNode,
    setEntityTypeFilters,
    setPredicateFilters,
    setConfidenceBucketFilters,
    setEntityTypeQuery,
    setPredicateQuery,
    setHighlightedNodeIds,
    setHighlightedLinkIds,
    setPathStartNode,
    setPathEndNode,
  })

  useEffect(() => {
    if (dataSource !== 'live') {
      setKgNodeDetail(null)
      setKgNodeDetailLoading(false)
      return
    }
    if (!isDetailOpen || !selectedNode?.id) {
      setKgNodeDetail(null)
      return
    }

    const kind = selectedNode?.meta?.kind
    if (kind !== 'entity' && kind !== 'event') {
      setKgNodeDetail(null)
      return
    }

    let cancelled = false
	    setKgNodeDetail(null)
	    setKgNodeDetailLoading(true)
	    ;(async () => {
	      try {
	        const detail =
	          kind === 'entity'
	            ? await kgApi.getEntity(selectedNode.id, scopeParams || undefined)
	            : await kgApi.getEvent(selectedNode.id, scopeParams || undefined)
	        if (!cancelled) setKgNodeDetail(detail)
	      } catch (error) {
	        console.error('Fetch KG node detail failed:', error)
	        if (!cancelled) setKgNodeDetail(null)
      } finally {
        if (!cancelled) setKgNodeDetailLoading(false)
      }
    })()

	    return () => {
	      cancelled = true
	    }
	  }, [dataSource, isDetailOpen, selectedNode?.id, selectedNode?.meta?.kind, scopeParams])

  const expandNodeById = useCallback(
    async (nodeId: string) => {
      const id = String(nodeId || '').trim()
      if (!id) return

      setIsLoading(true)
      try {
        const newData = await GraphService.expandNode(id, {
          includeEntityLinks: includeEntityLinks && dataSource === 'live',
          includeRelationLinks: includeRelationLinks && dataSource === 'live',
          minSharedEvents,
          maxEntityLinks,
          documentIds:
            dataSource === 'live' && scopedDocumentIds && scopedDocumentIds.length ? scopedDocumentIds : undefined,
          pipelineHash: dataSource === 'live' ? (scope.pipelineHash || undefined) : undefined,
        })

        setGraphData((prev) => {
          const existingNodeIds = new Set(prev.nodes.map((n) => n.id))
          const uniqueNewNodes = newData.nodes.filter((n) => !existingNodeIds.has(n.id))

          const existingLinks = new Set(
            prev.links.map((l) => `${getGraphLinkEndpointId(l.source)}-${getGraphLinkEndpointId(l.target)}`)
          )
          const uniqueNewLinks = newData.links.filter((l) => !existingLinks.has(`${l.source}-${l.target}`))

          return {
            nodes: [...prev.nodes, ...uniqueNewNodes],
            links: [...prev.links, ...uniqueNewLinks],
          }
        })
      } catch (error) {
        console.error('Failed to expand node:', error)
      } finally {
        setIsLoading(false)
      }
    },
    [includeEntityLinks, includeRelationLinks, minSharedEvents, maxEntityLinks, dataSource, scopedDocumentIds, scope.pipelineHash]
  )

  const handleExpandNode = useCallback(() => {
    if (!selectedNode) return
    detachPromise(expandNodeById(String(selectedNode.id)))
  }, [expandNodeById, selectedNode])

  const handleDeleteNode = useCallback((node?: GraphNodeLike) => {
    const target = node ?? selectedNode
    if (!target) return
    setDeleteNodeTarget({
      id: String(target.id),
      label: String(target.label || target.id || ''),
    })
    setDeleteNodeOpen(true)
  }, [selectedNode])

  const confirmDeleteNode = useCallback(() => {
    const nodeId = (deleteNodeTarget?.id || '').trim()
    if (!nodeId) return

    setGraphData((prev) => ({
      nodes: prev.nodes.filter((n) => String(n.id) !== nodeId),
      links: prev.links.filter((l) => {
        const s = getGraphLinkEndpointId(l.source)
        const t = getGraphLinkEndpointId(l.target)
        return String(s) !== nodeId && String(t) !== nodeId
      }),
    }))

    if (String(selectedNode?.id) === nodeId) {
      setSelectedNode(null)
      setIsDetailOpen(false)
    }
    setDeleteNodeTarget(null)
    setDeleteNodeOpen(false)
  }, [deleteNodeTarget, selectedNode])

  const {
    isFullscreen,
    contextMenu,
    exportOpen,
    setExportOpen,
    closeContextMenu,
    handleBackgroundClick,
    handleNodeRightClick,
    handleLinkRightClick,
    handleBackgroundRightClick,
    handleToggleFullscreen,
    handleCopyNodeId,
    handleCopyLinkPredicate,
    chatWithNode,
    handleChatWithNode,
    viewSourceForNode,
    handleViewSource,
    handleExportPngDownload,
    handleExportSvgDownload,
    handleExportPngCopy,
    handleExportSvgCopy,
    handleExportGraphML,
    handleDeleteNodeOpenChange,
  } = useGraphPageActions({
    graphViewportRef,
    getActiveGraph,
    selectedNode,
    fileName,
    viewMode,
    datasetId: scope.datasetId,
    dataSource,
    scopeParams,
    includeEntityLinks,
    includeRelationLinks,
    minSharedEvents,
    maxEntityLinks,
    setIsLoading,
    setIsDetailOpen,
    setIsLinkDetailOpen,
    setSelectedNode,
    setSelectedLink,
    setDeleteNodeOpen,
    setDeleteNodeTarget,
  })

  const {
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
  } = useGraphInteractionModes({
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
  })

  return (
    <AppFrame>
      <PageScaffold
        showHeader={false}
        title="知识图谱"
        description="知识图谱可视化与分析"
        icon={Share2}
        size="full"
        bodyClassName="px-0 pb-0 overflow-hidden"
        bodyContainerClassName="flex h-full min-h-0 flex-col"
      >
        <GraphPageHeader
          fileName={fileName}
          dataSource={dataSource}
          kgStats={kgStats}
          graphNodeCount={displayGraphData.nodes.length}
          graphLinkCount={displayGraphData.links.length}
          activeGraphFilterCount={activeGraphFilterCount}
          searchOpen={displayGraphData.nodes.length > 0 && !isPathMode && !isConnectMode && !isExplainMode}
          searchInputRef={searchInputRef}
          searchTerm={searchTerm}
          highlightedMatchCount={highlightedNodeIds.size}
          onSearchTermChange={setSearchTerm}
          isPathMode={isPathMode}
          hasPathStart={Boolean(pathStartNode)}
          hasPathEnd={Boolean(pathEndNode)}
          isConnectMode={isConnectMode}
          connectSourceLabel={connectSourceNode?.label ?? null}
          isExplainMode={isExplainMode}
          currentStepIndex={currentStepIndex}
          explainStepCount={explainSteps.length}
          onExitPathMode={resetPathMode}
          onExitConnectMode={resetConnectMode}
          onExitExplainMode={resetExplainMode}
          includeEntityLinks={includeEntityLinks}
          includeRelationLinks={includeRelationLinks}
          minSharedEvents={minSharedEvents}
          onToggleEntityLinks={toggleEntityLinks}
          onToggleRelationLinks={toggleRelationLinks}
          onCycleMinSharedEvents={cycleMinSharedEvents}
          onExportGraphML={handleExportGraphML}
          isLoading={isLoading}
          filtersOpen={filtersOpen}
          onFiltersOpenChange={setFiltersOpen}
          entityTypeQuery={entityTypeQuery}
          onEntityTypeQueryChange={setEntityTypeQuery}
          entityTypeFilters={entityTypeFilters}
          filteredEntityTypes={filteredEntityTypes}
          onEntityTypeCheckedChange={handleEntityTypeCheckedChange}
          onResetEntityTypeFilters={() => setEntityTypeFilters([])}
          predicateQuery={predicateQuery}
          onPredicateQueryChange={setPredicateQuery}
          predicateFilters={predicateFilters}
          filteredPredicates={filteredPredicates}
          onPredicateCheckedChange={handlePredicateCheckedChange}
          onResetPredicateFilters={() => setPredicateFilters([])}
          confidenceBucketFilters={confidenceBucketFilters}
          onResetConfidenceBuckets={() => setConfidenceBucketFilters([])}
          onToggleConfidenceBucket={toggleConfidenceBucket}
          onResetGraphFilters={resetGraphFilters}
          onRefreshLiveData={() => {
            detachPromise(loadInitialData('live'))
          }}
          onTriggerTraceUpload={triggerTraceUpload}
          traceFileInputRef={traceFileInputRef}
          onTraceFileUpload={handleTraceFileUpload}
          onTriggerFileUpload={triggerFileUpload}
          fileInputRef={fileInputRef}
          onFileUpload={handleFileUpload}
        />

        <GraphPageBody
          canvasProps={{
            viewportRef: graphViewportRef,
            graph2dRef,
            graph3dRef,
            isDark,
            graphRenderData,
            viewMode,
            graphViewportWidth,
            graphViewportHeight,
            selectedNodeId: selectedNode?.id ?? null,
            highlightedNodeIds,
            highlightedLinkIds,
            showEdgeLabels,
            layoutMode,
            isLoading,
            onNodeClick: handleNodeClick,
            onNodeRightClick: handleNodeRightClick,
            onLinkClick: handleLinkClick,
            onLinkRightClick: handleLinkRightClick,
            onBackgroundClick: handleBackgroundClick,
            onBackgroundRightClick: handleBackgroundRightClick,
            onLoadMock: () => {
              detachPromise(loadInitialData('mock'))
            },
            onTriggerFileUpload: triggerFileUpload,
          }}
          contextMenuProps={{
            contextMenu,
            viewMode,
            showEdgeLabels,
            onClose: closeContextMenu,
            onExpandNode: (nodeId) => {
              detachPromise(expandNodeById(nodeId))
            },
            onStartPathFromNode: handleStartPathFromContextNode,
            onStartConnectFromNode: handleStartConnectFromContextNode,
            onChatWithNode: chatWithNode,
            onViewSourceForNode: viewSourceForNode,
            onCopyNodeId: handleCopyNodeId,
            onDeleteNode: handleDeleteNode,
            onOpenLinkDetail: handleOpenLinkDetailFromContextMenu,
            onCopyLinkPredicate: handleCopyLinkPredicate,
            onZoomToFit: () => getActiveGraph()?.zoomToFit(),
            onClearHighlights: handleClearHighlightsFromContextMenu,
            onToggleShowEdgeLabels: () => setShowEdgeLabels((value) => !value),
          }}
          legendVisible={graphRenderData.nodes.length > 0 && !isExplainMode}
          legendNodes={graphRenderData.nodes}
          legendLinks={graphRenderData.links}
          activeTypeFilters={entityTypeFilters}
          onToggleTypeFilter={toggleEntityTypeFilter}
          explainabilityOpen={isExplainMode}
          explainSteps={explainSteps}
          currentStepIndex={currentStepIndex}
          displayNodes={displayGraphData.nodes}
          showPendingDocs={dataSource === 'live' && typeof scopedDatasetPendingDocs === 'number' && scopedDatasetPendingDocs > 0}
          pendingDocCount={scopedDatasetPendingDocs}
          showStatsBar={graphRenderData.nodes.length > 0}
          statsNodeCount={graphRenderData.nodes.length}
          statsLinkCount={graphRenderData.links.length}
          statsEntityTypeCount={availableEntityTypes.length}
          floatingControlsProps={{
            viewMode,
            isExplainMode,
            isPathMode,
            showEdgeLabels,
            isFullscreen,
            exportOpen,
            layoutLabel,
            onZoomIn: () => getActiveGraph()?.zoomIn(),
            onZoomOut: () => getActiveGraph()?.zoomOut(),
            onZoomToFit: () => getActiveGraph()?.zoomToFit(),
            onToggleViewMode: () => setViewMode(viewMode === '3d' ? '2d' : '3d'),
            onStartExplainMode: startExplainMode,
            onCycleLayoutMode: cycleLayoutMode,
            onTogglePathMode: togglePathMode,
            onToggleShowEdgeLabels: () => setShowEdgeLabels((value) => !value),
            onToggleFullscreen: handleToggleFullscreen,
            onExportOpenChange: setExportOpen,
            onExportPngDownload: handleExportPngDownload,
            onExportSvgDownload: handleExportSvgDownload,
            onExportPngCopy: handleExportPngCopy,
            onExportSvgCopy: handleExportSvgCopy,
          }}
          nodeDetailPanelProps={{
            open: isDetailOpen,
            selectedNode,
            detailScrollRef,
            dataSource,
            kgNodeDetailLoading,
            kgNodeDetail,
            entityAliasesLoading,
            entityAliases,
            aliasDraft,
            aliasSaving,
            aliasSuggestionsLoading,
            aliasSuggestions,
            lastResolutionActionId,
            undoSubmitting,
            isLoading,
            onClose: () => setIsDetailOpen(false),
            onChat: handleChatWithNode,
            onViewSource: handleViewSource,
            onExpandNode: handleExpandNode,
            onStartConnectMode: startConnectMode,
            onDeleteNode: () => handleDeleteNode(),
            onOpenMerge: openMergeDialog,
            onOpenSplit: openSplitDialog,
            onUndoLastResolution: undoLastResolution,
            onAliasDraftChange: setAliasDraft,
            onSaveAlias: handleSaveAlias,
            onRequestDeleteAlias: requestDeleteAlias,
            onMergeAliasSuggestion: handleMergeAliasSuggestion,
          }}
          linkDetailPanelProps={{
            open: isLinkDetailOpen,
            selectedLink,
            graphLinks: linksWithIds,
            selfLoopGroupExpanded,
            onToggleSelfLoopGroup: () => setSelfLoopGroupExpanded((prev) => !prev),
            onClose: () => {
              setIsLinkDetailOpen(false)
              setSelectedLink(null)
            },
          }}
        />

        <GraphActionDialogs
          deleteNodeOpen={deleteNodeOpen}
          deleteNodeTarget={deleteNodeTarget}
          onDeleteNodeOpenChange={handleDeleteNodeOpenChange}
          onConfirmDeleteNode={confirmDeleteNode}
          aliasDeleteOpen={aliasDeleteOpen}
          aliasDeleteTarget={aliasDeleteTarget}
          aliasSaving={aliasSaving}
          onAliasDeleteOpenChange={handleAliasDeleteOpenChange}
          onConfirmDeleteAlias={confirmDeleteAlias}
          mergeOpen={mergeOpen}
          onMergeOpenChange={handleMergeOpenChange}
          mergeSearch={mergeSearch}
          onMergeSearchChange={setMergeSearch}
          mergeSearchLoading={mergeSearchLoading}
          mergeSearchResults={mergeSearchResults}
          mergeTarget={mergeTarget}
          mergePreview={mergePreview}
          mergePreviewLoading={mergePreviewLoading}
          mergeError={mergeError}
          mergeConfirmOpen={mergeConfirmOpen}
          onMergeConfirmOpenChange={setMergeConfirmOpen}
          mergeSubmitting={mergeSubmitting}
          onSelectMergeTarget={selectMergeTarget}
          onContinueMerge={() => setMergeConfirmOpen(true)}
          onSubmitMerge={submitMerge}
          splitOpen={splitOpen}
          onSplitOpenChange={handleSplitOpenChange}
          splitNameDraft={splitNameDraft}
          onSplitNameDraftChange={setSplitNameDraft}
          splitSelectedEventIds={splitSelectedEventIds}
          splitSubmitting={splitSubmitting}
          splitError={splitError}
          splitEvents={(kgNodeDetail as KGEntityDetailResponse | null)?.events ?? []}
          onToggleSplitEvent={toggleSplitEvent}
          onSubmitSplit={submitSplit}
          connectLabelOpen={connectLabelOpen}
          onConnectLabelOpenChange={handleConnectLabelOpenChange}
          connectSourceNode={connectSourceNode}
          connectTargetNode={connectTargetNode}
          connectLabelDraft={connectLabelDraft}
          onConnectLabelDraftChange={setConnectLabelDraft}
          onConfirmConnectionLabel={confirmConnectionLabel}
        />
      </PageScaffold>
    </AppFrame>
  )
}
