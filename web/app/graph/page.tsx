'use client'

import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { GraphPageShell } from './_components/graph-page-shell'
import { useGraphDataLoading } from './use-graph-data-loading'
import { useGraphDisplayFilters } from './use-graph-display-filters'
import { useGraphEntityResolution } from './use-graph-entity-resolution'
import { useGraphInteractionModes } from './use-graph-interaction-modes'
import { useGraphNodeOperations } from './use-graph-node-operations'
import { useGraphPageActions } from './use-graph-page-actions'
import { useGraphPageState } from './use-graph-page-state'

export default function GraphPage() {
  return (
    <NavigationVisibilityGate moduleKey="knowledgeGraph" pageName="知识图谱">
      <GraphPageContent />
    </NavigationVisibilityGate>
  )
}

function GraphPageContent() {
  const state = useGraphPageState()

  const dataLoading = useGraphDataLoading({
    scope: state.scope,
    scopedDocumentIds: state.scopedDocumentIds,
    scopedDatasetDocIdsLoading: state.scopedDatasetDocIdsLoading,
    refetchScopedDocuments: state.refetchScopedDocuments,
    scopeParams: state.scopeParams,
    includeEntityLinks: state.includeEntityLinks,
    includeRelationLinks: state.includeRelationLinks,
    minSharedEvents: state.minSharedEvents,
    maxEntityLinks: state.maxEntityLinks,
    setGraphData: state.setGraphData,
    setFileName: state.setFileName,
    setDataSource: state.setDataSource,
    setTraceReplay: state.setTraceReplay,
    setIsLoading: state.setIsLoading,
    setViewMode: state.setViewMode,
    traceFileInputRef: state.traceFileInputRef,
    manualKgFileInputRef: state.manualKgFileInputRef,
    resetGraphSurface: state.resetGraphSurface,
  })

  const entityResolution = useGraphEntityResolution({
    dataSource: state.dataSource,
    isDetailOpen: state.isDetailOpen,
    selectedNode: state.selectedNode,
    scopeParams: state.scopeParams,
    loadLiveGraph: dataLoading.loadLiveGraph,
  })

  const displayFilters = useGraphDisplayFilters({
    graphData: state.graphData,
    searchTerm: state.searchTerm,
    entityTypeFilters: state.entityTypeFilters,
    predicateFilters: state.predicateFilters,
    confidenceBucketFilters: state.confidenceBucketFilters,
    entityTypeQuery: state.entityTypeQuery,
    predicateQuery: state.predicateQuery,
    isPathMode: state.isPathMode,
    isConnectMode: state.isConnectMode,
    isExplainMode: state.isExplainMode,
    selectedNodeId: state.selectedNodeId,
    isDetailOpen: state.isDetailOpen,
    getActiveGraph: state.getActiveGraph,
    setIsDetailOpen: state.setIsDetailOpen,
    setSelectedNode: state.setSelectedNode,
    setEntityTypeFilters: state.setEntityTypeFilters,
    setPredicateFilters: state.setPredicateFilters,
    setConfidenceBucketFilters: state.setConfidenceBucketFilters,
    setEntityTypeQuery: state.setEntityTypeQuery,
    setPredicateQuery: state.setPredicateQuery,
    setHighlightedNodeIds: state.setHighlightedNodeIds,
    setHighlightedLinkIds: state.setHighlightedLinkIds,
    setPathStartNode: state.setPathStartNode,
    setPathEndNode: state.setPathEndNode,
  })

  const nodeOperations = useGraphNodeOperations({
    dataSource: state.dataSource,
    isDetailOpen: state.isDetailOpen,
    selectedNode: state.selectedNode,
    scopeParams: state.scopeParams,
    includeEntityLinks: state.includeEntityLinks,
    includeRelationLinks: state.includeRelationLinks,
    minSharedEvents: state.minSharedEvents,
    maxEntityLinks: state.maxEntityLinks,
    scopedDocumentIds: state.scopedDocumentIds,
    pipelineHash: state.scope.pipelineHash,
    deleteNodeTarget: state.deleteNodeTarget,
    setGraphData: state.setGraphData,
    setDeleteNodeOpen: state.setDeleteNodeOpen,
    setDeleteNodeTarget: state.setDeleteNodeTarget,
    setSelectedNode: state.setSelectedNode,
    setIsDetailOpen: state.setIsDetailOpen,
  })

  const pageActions = useGraphPageActions({
    graphViewportRef: state.graphViewportRef,
    getActiveGraph: state.getActiveGraph,
    selectedNode: state.selectedNode,
    fileName: state.fileName,
    viewMode: state.viewMode,
    datasetId: state.scope.datasetId,
    dataSource: state.dataSource,
    scopeParams: state.scopeParams,
    includeEntityLinks: state.includeEntityLinks,
    includeRelationLinks: state.includeRelationLinks,
    minSharedEvents: state.minSharedEvents,
    maxEntityLinks: state.maxEntityLinks,
    setIsDetailOpen: state.setIsDetailOpen,
    setIsLinkDetailOpen: state.setIsLinkDetailOpen,
    setSelectedNode: state.setSelectedNode,
    setSelectedLink: state.setSelectedLink,
    setDeleteNodeOpen: state.setDeleteNodeOpen,
    setDeleteNodeTarget: state.setDeleteNodeTarget,
  })

  const interactionModes = useGraphInteractionModes({
    searchInputRef: state.searchInputRef,
    closeContextMenu: pageActions.closeContextMenu,
    handleExpandNode: nodeOperations.handleExpandNode,
    handleDeleteNode: nodeOperations.handleDeleteNode,
    getActiveGraph: state.getActiveGraph,
    loadLiveGraph: dataLoading.loadLiveGraph,
    selectedNode: state.selectedNode,
    isDetailOpen: state.isDetailOpen,
    isLinkDetailOpen: state.isLinkDetailOpen,
    isPathMode: state.isPathMode,
    isConnectMode: state.isConnectMode,
    isExplainMode: state.isExplainMode,
    explainSteps: state.explainSteps,
    pathStartNode: state.pathStartNode,
    pathEndNode: state.pathEndNode,
    connectSourceNode: state.connectSourceNode,
    connectTargetNode: state.connectTargetNode,
    connectLabelDraft: state.connectLabelDraft,
    viewMode: state.viewMode,
    layoutMode: state.layoutMode,
    dataSource: state.dataSource,
    traceReplay: state.traceReplay,
    graphData: state.graphData,
    displayGraphData: displayFilters.displayGraphData,
    linksWithIds: displayFilters.linksWithIds,
    includeEntityLinks: state.includeEntityLinks,
    includeRelationLinks: state.includeRelationLinks,
    minSharedEvents: state.minSharedEvents,
    setIsPathMode: state.setIsPathMode,
    setPathStartNode: state.setPathStartNode,
    setPathEndNode: state.setPathEndNode,
    setHighlightedNodeIds: state.setHighlightedNodeIds,
    setHighlightedLinkIds: state.setHighlightedLinkIds,
    setIsDetailOpen: state.setIsDetailOpen,
    setSelectedNode: state.setSelectedNode,
    setIsLinkDetailOpen: state.setIsLinkDetailOpen,
    setSelectedLink: state.setSelectedLink,
    setConnectSourceNode: state.setConnectSourceNode,
    setIsConnectMode: state.setIsConnectMode,
    setConnectTargetNode: state.setConnectTargetNode,
    setConnectLabelDraft: state.setConnectLabelDraft,
    setConnectLabelOpen: state.setConnectLabelOpen,
    setCurrentStepIndex: state.setCurrentStepIndex,
    setExplainSteps: state.setExplainSteps,
    setIsExplainMode: state.setIsExplainMode,
    setViewMode: state.setViewMode,
    setGraphData: state.setGraphData,
    setDataSource: state.setDataSource,
    setFileName: state.setFileName,
    setLayoutMode: state.setLayoutMode,
    setIncludeEntityLinks: state.setIncludeEntityLinks,
    setIncludeRelationLinks: state.setIncludeRelationLinks,
    setMinSharedEvents: state.setMinSharedEvents,
    resetPathMode: state.resetPathMode,
    resetConnectMode: state.resetConnectMode,
    resetExplainMode: state.resetExplainMode,
  })

  return (
    <GraphPageShell
      state={{ ...state, isLoading: state.isLoading || nodeOperations.isExpanding }}
      dataLoading={dataLoading}
      entityResolution={entityResolution}
      displayFilters={displayFilters}
      nodeOperations={nodeOperations}
      pageActions={pageActions}
      interactionModes={interactionModes}
    />
  )
}
