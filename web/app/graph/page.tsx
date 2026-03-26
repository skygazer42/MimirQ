'use client'

/**
 * 知识图谱可视化页面
 * 功能：上传 .graphml 文件并进行可视化展示
 * 优化：主流视觉设计、交互侧边栏、玻璃拟态控件、搜索与高级筛选、后端集成、路径分析、布局切换、图编辑、RAG可解释性、3D可视化
 */
import { useTheme } from 'next-themes'
import { Share2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { detachPromise } from '@/lib/utils'
import type { KGEntityDetailResponse } from '@/types'

import { GraphActionDialogs } from './_components/graph-action-dialogs'
import { GraphPageBody } from './_components/graph-page-body'
import { GraphPageHeader } from './_components/graph-page-header'
import { useGraphDataLoading } from './use-graph-data-loading'
import { useGraphDisplayFilters } from './use-graph-display-filters'
import { useGraphEntityResolution } from './use-graph-entity-resolution'
import { useGraphInteractionModes } from './use-graph-interaction-modes'
import { useGraphNodeOperations } from './use-graph-node-operations'
import { useGraphPageActions } from './use-graph-page-actions'
import { useGraphPageState } from './use-graph-page-state'

export default function GraphPage() {
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === 'dark'
  const state = useGraphPageState()

  const {
    loadInitialData,
    handleFileUpload,
    triggerFileUpload,
    handleTraceFileUpload,
    triggerTraceUpload,
  } = useGraphDataLoading({
    scope: state.scope,
    scopedDocumentIds: state.scopedDocumentIds,
    scopedDatasetDocIdsLoading: state.scopedDatasetDocIdsLoading,
    scopeParams: state.scopeParams,
    includeEntityLinks: state.includeEntityLinks,
    includeRelationLinks: state.includeRelationLinks,
    minSharedEvents: state.minSharedEvents,
    maxEntityLinks: state.maxEntityLinks,
    setGraphData: state.setGraphData,
    setFileName: state.setFileName,
    setDataSource: state.setDataSource,
    setTraceReplay: state.setTraceReplay,
    setKgStats: state.setKgStats,
    setKgNodeDetail: state.setKgNodeDetail,
    setIsLoading: state.setIsLoading,
    setIsDetailOpen: state.setIsDetailOpen,
    setSelectedNode: state.setSelectedNode,
    setViewMode: state.setViewMode,
    fileInputRef: state.fileInputRef,
    traceFileInputRef: state.traceFileInputRef,
    resetPathMode: state.resetPathMode,
    resetConnectMode: state.resetConnectMode,
    resetExplainMode: state.resetExplainMode,
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
    dataSource: state.dataSource,
    isDetailOpen: state.isDetailOpen,
    selectedNode: state.selectedNode,
    scopeParams: state.scopeParams,
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

  const {
    handleExpandNode,
    handleExpandNodeById,
    handleDeleteNode,
    confirmDeleteNode,
  } = useGraphNodeOperations({
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
    setIsLoading: state.setIsLoading,
    setDeleteNodeOpen: state.setDeleteNodeOpen,
    setDeleteNodeTarget: state.setDeleteNodeTarget,
    setSelectedNode: state.setSelectedNode,
    setIsDetailOpen: state.setIsDetailOpen,
    setKgNodeDetail: state.setKgNodeDetail,
    setKgNodeDetailLoading: state.setKgNodeDetailLoading,
  })

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
    setIsLoading: state.setIsLoading,
    setIsDetailOpen: state.setIsDetailOpen,
    setIsLinkDetailOpen: state.setIsLinkDetailOpen,
    setSelectedNode: state.setSelectedNode,
    setSelectedLink: state.setSelectedLink,
    setDeleteNodeOpen: state.setDeleteNodeOpen,
    setDeleteNodeTarget: state.setDeleteNodeTarget,
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
    searchInputRef: state.searchInputRef,
    closeContextMenu,
    handleExpandNode,
    handleDeleteNode,
    getActiveGraph: state.getActiveGraph,
    loadInitialData,
    selectedNode: state.selectedNode,
    isDetailOpen: state.isDetailOpen,
    isLinkDetailOpen: state.isLinkDetailOpen,
    isPathMode: state.isPathMode,
    isConnectMode: state.isConnectMode,
    isExplainMode: state.isExplainMode,
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
    displayGraphData,
    linksWithIds,
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
    setKgStats: state.setKgStats,
    setKgNodeDetail: state.setKgNodeDetail,
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
          fileName={state.fileName}
          dataSource={state.dataSource}
          kgStats={state.kgStats}
          graphNodeCount={displayGraphData.nodes.length}
          graphLinkCount={displayGraphData.links.length}
          activeGraphFilterCount={activeGraphFilterCount}
          searchOpen={displayGraphData.nodes.length > 0 && !state.isPathMode && !state.isConnectMode && !state.isExplainMode}
          searchInputRef={state.searchInputRef}
          searchTerm={state.searchTerm}
          highlightedMatchCount={state.highlightedNodeIds.size}
          onSearchTermChange={state.setSearchTerm}
          isPathMode={state.isPathMode}
          hasPathStart={Boolean(state.pathStartNode)}
          hasPathEnd={Boolean(state.pathEndNode)}
          isConnectMode={state.isConnectMode}
          connectSourceLabel={state.connectSourceNode?.label ?? null}
          isExplainMode={state.isExplainMode}
          currentStepIndex={state.currentStepIndex}
          explainStepCount={state.explainSteps.length}
          onExitPathMode={state.resetPathMode}
          onExitConnectMode={state.resetConnectMode}
          onExitExplainMode={state.resetExplainMode}
          includeEntityLinks={state.includeEntityLinks}
          includeRelationLinks={state.includeRelationLinks}
          minSharedEvents={state.minSharedEvents}
          onToggleEntityLinks={toggleEntityLinks}
          onToggleRelationLinks={toggleRelationLinks}
          onCycleMinSharedEvents={cycleMinSharedEvents}
          onExportGraphML={handleExportGraphML}
          isLoading={state.isLoading}
          filtersOpen={state.filtersOpen}
          onFiltersOpenChange={state.setFiltersOpen}
          entityTypeQuery={state.entityTypeQuery}
          onEntityTypeQueryChange={state.setEntityTypeQuery}
          entityTypeFilters={state.entityTypeFilters}
          filteredEntityTypes={filteredEntityTypes}
          onEntityTypeCheckedChange={handleEntityTypeCheckedChange}
          onResetEntityTypeFilters={() => state.setEntityTypeFilters([])}
          predicateQuery={state.predicateQuery}
          onPredicateQueryChange={state.setPredicateQuery}
          predicateFilters={state.predicateFilters}
          filteredPredicates={filteredPredicates}
          onPredicateCheckedChange={handlePredicateCheckedChange}
          onResetPredicateFilters={() => state.setPredicateFilters([])}
          confidenceBucketFilters={state.confidenceBucketFilters}
          onResetConfidenceBuckets={() => state.setConfidenceBucketFilters([])}
          onToggleConfidenceBucket={toggleConfidenceBucket}
          onResetGraphFilters={resetGraphFilters}
          onRefreshLiveData={() => {
            detachPromise(loadInitialData('live'))
          }}
          onTriggerTraceUpload={triggerTraceUpload}
          traceFileInputRef={state.traceFileInputRef}
          onTraceFileUpload={handleTraceFileUpload}
          onTriggerFileUpload={triggerFileUpload}
          fileInputRef={state.fileInputRef}
          onFileUpload={handleFileUpload}
        />

        <GraphPageBody
          canvasProps={{
            viewportRef: state.graphViewportRef,
            graph2dRef: state.graph2dRef,
            graph3dRef: state.graph3dRef,
            isDark,
            graphRenderData,
            viewMode: state.viewMode,
            graphViewportWidth: state.graphViewportWidth,
            graphViewportHeight: state.graphViewportHeight,
            selectedNodeId: state.selectedNode?.id ?? null,
            highlightedNodeIds: state.highlightedNodeIds,
            highlightedLinkIds: state.highlightedLinkIds,
            showEdgeLabels: state.showEdgeLabels,
            layoutMode: state.layoutMode,
            isLoading: state.isLoading,
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
            viewMode: state.viewMode,
            showEdgeLabels: state.showEdgeLabels,
            onClose: closeContextMenu,
            onExpandNode: handleExpandNodeById,
            onStartPathFromNode: handleStartPathFromContextNode,
            onStartConnectFromNode: handleStartConnectFromContextNode,
            onChatWithNode: chatWithNode,
            onViewSourceForNode: viewSourceForNode,
            onCopyNodeId: handleCopyNodeId,
            onDeleteNode: handleDeleteNode,
            onOpenLinkDetail: handleOpenLinkDetailFromContextMenu,
            onCopyLinkPredicate: handleCopyLinkPredicate,
            onZoomToFit: () => state.getActiveGraph()?.zoomToFit?.(),
            onClearHighlights: handleClearHighlightsFromContextMenu,
            onToggleShowEdgeLabels: () => state.setShowEdgeLabels((value) => !value),
          }}
          legendVisible={graphRenderData.nodes.length > 0 && !state.isExplainMode}
          legendNodes={graphRenderData.nodes}
          legendLinks={graphRenderData.links}
          activeTypeFilters={state.entityTypeFilters}
          onToggleTypeFilter={toggleEntityTypeFilter}
          explainabilityOpen={state.isExplainMode}
          explainSteps={state.explainSteps}
          currentStepIndex={state.currentStepIndex}
          displayNodes={displayGraphData.nodes}
          showPendingDocs={
            state.dataSource === 'live' &&
            typeof state.scopedDatasetPendingDocs === 'number' &&
            state.scopedDatasetPendingDocs > 0
          }
          pendingDocCount={state.scopedDatasetPendingDocs}
          showStatsBar={graphRenderData.nodes.length > 0}
          statsNodeCount={graphRenderData.nodes.length}
          statsLinkCount={graphRenderData.links.length}
          statsEntityTypeCount={availableEntityTypes.length}
          floatingControlsProps={{
            viewMode: state.viewMode,
            isExplainMode: state.isExplainMode,
            isPathMode: state.isPathMode,
            showEdgeLabels: state.showEdgeLabels,
            isFullscreen,
            exportOpen,
            layoutLabel,
            onZoomIn: () => state.getActiveGraph()?.zoomIn?.(),
            onZoomOut: () => state.getActiveGraph()?.zoomOut?.(),
            onZoomToFit: () => state.getActiveGraph()?.zoomToFit?.(),
            onToggleViewMode: () => state.setViewMode(state.viewMode === '3d' ? '2d' : '3d'),
            onStartExplainMode: startExplainMode,
            onCycleLayoutMode: cycleLayoutMode,
            onTogglePathMode: togglePathMode,
            onToggleShowEdgeLabels: () => state.setShowEdgeLabels((value) => !value),
            onToggleFullscreen: handleToggleFullscreen,
            onExportOpenChange: setExportOpen,
            onExportPngDownload: handleExportPngDownload,
            onExportSvgDownload: handleExportSvgDownload,
            onExportPngCopy: handleExportPngCopy,
            onExportSvgCopy: handleExportSvgCopy,
          }}
          nodeDetailPanelProps={{
            open: state.isDetailOpen,
            selectedNode: state.selectedNode,
            detailScrollRef: state.detailScrollRef,
            dataSource: state.dataSource,
            kgNodeDetailLoading: state.kgNodeDetailLoading,
            kgNodeDetail: state.kgNodeDetail,
            entityAliasesLoading,
            entityAliases,
            aliasDraft,
            aliasSaving,
            aliasSuggestionsLoading,
            aliasSuggestions,
            lastResolutionActionId,
            undoSubmitting,
            isLoading: state.isLoading,
            onClose: () => state.setIsDetailOpen(false),
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
            open: state.isLinkDetailOpen,
            selectedLink: state.selectedLink,
            graphLinks: linksWithIds,
            selfLoopGroupExpanded: state.selfLoopGroupExpanded,
            onToggleSelfLoopGroup: () => state.setSelfLoopGroupExpanded((prev) => !prev),
            onClose: () => {
              state.setIsLinkDetailOpen(false)
              state.setSelectedLink(null)
            },
          }}
        />

        <GraphActionDialogs
          deleteNodeOpen={state.deleteNodeOpen}
          deleteNodeTarget={state.deleteNodeTarget}
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
          splitEvents={(state.kgNodeDetail as KGEntityDetailResponse | null)?.events ?? []}
          onToggleSplitEvent={toggleSplitEvent}
          onSubmitSplit={submitSplit}
          connectLabelOpen={state.connectLabelOpen}
          onConnectLabelOpenChange={handleConnectLabelOpenChange}
          connectSourceNode={state.connectSourceNode}
          connectTargetNode={state.connectTargetNode}
          connectLabelDraft={state.connectLabelDraft}
          onConnectLabelDraftChange={state.setConnectLabelDraft}
          onConfirmConnectionLabel={confirmConnectionLabel}
        />
      </PageScaffold>
    </AppFrame>
  )
}
