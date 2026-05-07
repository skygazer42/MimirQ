'use client'

import { useState } from 'react'

import { Share2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { detachPromise } from '@/lib/utils'
import type { KGEntityDetailResponse } from '@/types'

import type { UseGraphDataLoadingResult } from '../use-graph-data-loading'
import type { UseGraphDisplayFiltersResult } from '../use-graph-display-filters'
import type { UseGraphEntityResolutionResult } from '../use-graph-entity-resolution'
import type { UseGraphInteractionModesResult } from '../use-graph-interaction-modes'
import type { UseGraphNodeOperationsResult } from '../use-graph-node-operations'
import type { UseGraphPageActionsResult } from '../use-graph-page-actions'
import type { UseGraphPageStateResult } from '../use-graph-page-state'
import { GraphActionDialogs } from './graph-action-dialogs'
import { GraphPageBody } from './graph-page-body'
import { GraphPageHeader } from './graph-page-header'
import { GraphScopePickerDialog } from './graph-scope-picker-dialog'

type GraphPageShellProps = Readonly<{
  isDark: boolean
  state: UseGraphPageStateResult
  dataLoading: UseGraphDataLoadingResult
  entityResolution: UseGraphEntityResolutionResult
  displayFilters: UseGraphDisplayFiltersResult
  nodeOperations: UseGraphNodeOperationsResult
  pageActions: UseGraphPageActionsResult
  interactionModes: UseGraphInteractionModesResult
}>

export function GraphPageShell({
  isDark,
  state,
  dataLoading,
  entityResolution,
  displayFilters,
  nodeOperations,
  pageActions,
  interactionModes,
}: GraphPageShellProps) {
  const [graphScopePickerOpen, setGraphScopePickerOpen] = useState(false)

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
          viewMode={state.viewMode}
          kgStats={state.kgStats}
          graphNodeCount={displayFilters.displayGraphData.nodes.length}
          graphLinkCount={displayFilters.displayGraphData.links.length}
          activeGraphFilterCount={displayFilters.activeGraphFilterCount}
          searchOpen={
            displayFilters.displayGraphData.nodes.length > 0 &&
            !state.isPathMode &&
            !state.isConnectMode &&
            !state.isExplainMode
          }
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
          onToggleEntityLinks={interactionModes.toggleEntityLinks}
          onToggleRelationLinks={interactionModes.toggleRelationLinks}
          onCycleMinSharedEvents={interactionModes.cycleMinSharedEvents}
          onExportGraphML={pageActions.handleExportGraphML}
          isLoading={state.isLoading}
          filtersOpen={state.filtersOpen}
          onFiltersOpenChange={state.setFiltersOpen}
          entityTypeQuery={state.entityTypeQuery}
          onEntityTypeQueryChange={state.setEntityTypeQuery}
          entityTypeFilters={state.entityTypeFilters}
          filteredEntityTypes={displayFilters.filteredEntityTypes}
          onEntityTypeCheckedChange={displayFilters.handleEntityTypeCheckedChange}
          onResetEntityTypeFilters={() => state.setEntityTypeFilters([])}
          predicateQuery={state.predicateQuery}
          onPredicateQueryChange={state.setPredicateQuery}
          predicateFilters={state.predicateFilters}
          filteredPredicates={displayFilters.filteredPredicates}
          onPredicateCheckedChange={displayFilters.handlePredicateCheckedChange}
          onResetPredicateFilters={() => state.setPredicateFilters([])}
          confidenceBucketFilters={state.confidenceBucketFilters}
          onResetConfidenceBuckets={() => state.setConfidenceBucketFilters([])}
          onToggleConfidenceBucket={displayFilters.toggleConfidenceBucket}
          onResetGraphFilters={displayFilters.resetGraphFilters}
          onRefreshLiveData={() => {
            detachPromise(dataLoading.loadInitialData('live'))
          }}
          onOpenGraphPicker={() => setGraphScopePickerOpen(true)}
          onTriggerTraceUpload={dataLoading.triggerTraceUpload}
          traceFileInputRef={state.traceFileInputRef}
          onTraceFileUpload={dataLoading.handleTraceFileUpload}
          onTriggerFileUpload={dataLoading.triggerFileUpload}
          fileInputRef={state.fileInputRef}
          onFileUpload={dataLoading.handleFileUpload}
        />

        <GraphPageBody
          canvasProps={{
            viewportRef: state.graphViewportRef,
            graph2dRef: state.graph2dRef,
            graph3dRef: state.graph3dRef,
            isDark,
            graphRenderData: displayFilters.graphRenderData,
            paletteSeed: state.scope.datasetId || state.scope.pipelineHash || state.fileName || null,
            viewMode: state.viewMode,
            graphViewportWidth: state.graphViewportWidth,
            graphViewportHeight: state.graphViewportHeight,
            selectedNodeId: state.selectedNode?.id ?? null,
            highlightedNodeIds: state.highlightedNodeIds,
            highlightedLinkIds: state.highlightedLinkIds,
            showEdgeLabels: state.showEdgeLabels,
            layoutMode: state.layoutMode,
            isLoading: state.isLoading,
            hasActiveScope: state.scope.hasScope,
            onNodeClick: interactionModes.handleNodeClick,
            onNodeRightClick: pageActions.handleNodeRightClick,
            onLinkClick: interactionModes.handleLinkClick,
            onLinkRightClick: pageActions.handleLinkRightClick,
            onBackgroundClick: pageActions.handleBackgroundClick,
            onBackgroundRightClick: pageActions.handleBackgroundRightClick,
            onLoadMock: () => {
              detachPromise(dataLoading.loadInitialData('mock'))
            },
            onOpenGraphPicker: () => setGraphScopePickerOpen(true),
            onTriggerFileUpload: dataLoading.triggerFileUpload,
          }}
          contextMenuProps={{
            contextMenu: pageActions.contextMenu,
            viewMode: state.viewMode,
            showEdgeLabels: state.showEdgeLabels,
            onClose: pageActions.closeContextMenu,
            onExpandNode: nodeOperations.handleExpandNodeById,
            onStartPathFromNode: interactionModes.handleStartPathFromContextNode,
            onStartConnectFromNode: interactionModes.handleStartConnectFromContextNode,
            onChatWithNode: pageActions.chatWithNode,
            onViewSourceForNode: pageActions.viewSourceForNode,
            onCopyNodeId: pageActions.handleCopyNodeId,
            onDeleteNode: nodeOperations.handleDeleteNode,
            onOpenLinkDetail: interactionModes.handleOpenLinkDetailFromContextMenu,
            onCopyLinkPredicate: pageActions.handleCopyLinkPredicate,
            onZoomToFit: () => state.getActiveGraph()?.zoomToFit?.(),
            onClearHighlights: interactionModes.handleClearHighlightsFromContextMenu,
            onToggleShowEdgeLabels: () => state.setShowEdgeLabels((value) => !value),
          }}
          legendVisible={displayFilters.graphRenderData.nodes.length > 0 && !state.isExplainMode}
          legendNodes={displayFilters.graphRenderData.nodes}
          legendLinks={displayFilters.graphRenderData.links}
          activeTypeFilters={state.entityTypeFilters}
          onToggleTypeFilter={displayFilters.toggleEntityTypeFilter}
          explainabilityOpen={state.isExplainMode}
          explainSteps={state.explainSteps}
          currentStepIndex={state.currentStepIndex}
          displayNodes={displayFilters.displayGraphData.nodes}
          showPendingDocs={
            state.dataSource === 'live' &&
            typeof state.scopedDatasetPendingDocs === 'number' &&
            state.scopedDatasetPendingDocs > 0
          }
          pendingDocCount={state.scopedDatasetPendingDocs}
          showStatsBar={displayFilters.graphRenderData.nodes.length > 0}
          statsNodeCount={displayFilters.graphRenderData.nodes.length}
          statsLinkCount={displayFilters.graphRenderData.links.length}
          statsEntityTypeCount={displayFilters.availableEntityTypes.length}
          networkAnalysisNodes={displayFilters.displayGraphData.nodes}
          networkAnalysisLinks={displayFilters.displayGraphData.links}
          networkAnalysisSelectedNodeId={state.selectedNode?.id ?? null}
          floatingControlsProps={{
            viewMode: state.viewMode,
            isExplainMode: state.isExplainMode,
            isPathMode: state.isPathMode,
            showEdgeLabels: state.showEdgeLabels,
            isFullscreen: pageActions.isFullscreen,
            exportOpen: pageActions.exportOpen,
            layoutLabel: interactionModes.layoutLabel,
            onZoomIn: () => state.getActiveGraph()?.zoomIn?.(),
            onZoomOut: () => state.getActiveGraph()?.zoomOut?.(),
            onZoomToFit: () => state.getActiveGraph()?.zoomToFit?.(),
            onToggleViewMode: () => state.setViewMode(state.viewMode === '3d' ? '2d' : '3d'),
            onStartExplainMode: interactionModes.startExplainMode,
            onCycleLayoutMode: interactionModes.cycleLayoutMode,
            onTogglePathMode: interactionModes.togglePathMode,
            onToggleShowEdgeLabels: () => state.setShowEdgeLabels((value) => !value),
            onToggleFullscreen: pageActions.handleToggleFullscreen,
            onExportOpenChange: pageActions.setExportOpen,
            onExportPngDownload: pageActions.handleExportPngDownload,
            onExportSvgDownload: pageActions.handleExportSvgDownload,
            onExportPngCopy: pageActions.handleExportPngCopy,
            onExportSvgCopy: pageActions.handleExportSvgCopy,
          }}
          nodeDetailPanelProps={{
            open: state.isDetailOpen,
            selectedNode: state.selectedNode,
            detailScrollRef: state.detailScrollRef,
            dataSource: state.dataSource,
            kgNodeDetailLoading: state.kgNodeDetailLoading,
            kgNodeDetail: state.kgNodeDetail,
            entityAliasesLoading: entityResolution.entityAliasesLoading,
            entityAliases: entityResolution.entityAliases,
            aliasDraft: entityResolution.aliasDraft,
            aliasSaving: entityResolution.aliasSaving,
            aliasSuggestionsLoading: entityResolution.aliasSuggestionsLoading,
            aliasSuggestions: entityResolution.aliasSuggestions,
            lastResolutionActionId: entityResolution.lastResolutionActionId,
            undoSubmitting: entityResolution.undoSubmitting,
            isLoading: state.isLoading,
            onClose: () => state.setIsDetailOpen(false),
            onChat: pageActions.handleChatWithNode,
            onViewSource: pageActions.handleViewSource,
            onExpandNode: nodeOperations.handleExpandNode,
            onStartConnectMode: interactionModes.startConnectMode,
            onDeleteNode: () => nodeOperations.handleDeleteNode(),
            onOpenMerge: entityResolution.openMergeDialog,
            onOpenSplit: entityResolution.openSplitDialog,
            onUndoLastResolution: entityResolution.undoLastResolution,
            onAliasDraftChange: entityResolution.setAliasDraft,
            onSaveAlias: entityResolution.handleSaveAlias,
            onRequestDeleteAlias: entityResolution.requestDeleteAlias,
            onMergeAliasSuggestion: entityResolution.handleMergeAliasSuggestion,
          }}
          linkDetailPanelProps={{
            open: state.isLinkDetailOpen,
            selectedLink: state.selectedLink,
            graphLinks: displayFilters.linksWithIds,
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
          onDeleteNodeOpenChange={pageActions.handleDeleteNodeOpenChange}
          onConfirmDeleteNode={nodeOperations.confirmDeleteNode}
          aliasDeleteOpen={entityResolution.aliasDeleteOpen}
          aliasDeleteTarget={entityResolution.aliasDeleteTarget}
          aliasSaving={entityResolution.aliasSaving}
          onAliasDeleteOpenChange={entityResolution.handleAliasDeleteOpenChange}
          onConfirmDeleteAlias={entityResolution.confirmDeleteAlias}
          mergeOpen={entityResolution.mergeOpen}
          onMergeOpenChange={entityResolution.handleMergeOpenChange}
          mergeSearch={entityResolution.mergeSearch}
          onMergeSearchChange={entityResolution.setMergeSearch}
          mergeSearchLoading={entityResolution.mergeSearchLoading}
          mergeSearchResults={entityResolution.mergeSearchResults}
          mergeTarget={entityResolution.mergeTarget}
          mergePreview={entityResolution.mergePreview}
          mergePreviewLoading={entityResolution.mergePreviewLoading}
          mergeError={entityResolution.mergeError}
          mergeConfirmOpen={entityResolution.mergeConfirmOpen}
          onMergeConfirmOpenChange={entityResolution.setMergeConfirmOpen}
          mergeSubmitting={entityResolution.mergeSubmitting}
          onSelectMergeTarget={entityResolution.selectMergeTarget}
          onContinueMerge={() => entityResolution.setMergeConfirmOpen(true)}
          onSubmitMerge={entityResolution.submitMerge}
          splitOpen={entityResolution.splitOpen}
          onSplitOpenChange={entityResolution.handleSplitOpenChange}
          splitNameDraft={entityResolution.splitNameDraft}
          onSplitNameDraftChange={entityResolution.setSplitNameDraft}
          splitSelectedEventIds={entityResolution.splitSelectedEventIds}
          splitSubmitting={entityResolution.splitSubmitting}
          splitError={entityResolution.splitError}
          splitEvents={(state.kgNodeDetail as KGEntityDetailResponse | null)?.events ?? []}
          onToggleSplitEvent={entityResolution.toggleSplitEvent}
          onSubmitSplit={entityResolution.submitSplit}
          connectLabelOpen={state.connectLabelOpen}
          onConnectLabelOpenChange={interactionModes.handleConnectLabelOpenChange}
          connectSourceNode={state.connectSourceNode}
          connectTargetNode={state.connectTargetNode}
          connectLabelDraft={state.connectLabelDraft}
          onConnectLabelDraftChange={state.setConnectLabelDraft}
          onConfirmConnectionLabel={interactionModes.confirmConnectionLabel}
        />

        <GraphScopePickerDialog
          open={graphScopePickerOpen}
          onOpenChange={setGraphScopePickerOpen}
          currentDatasetId={state.scope.datasetId}
          currentPipelineHash={state.scope.pipelineHash}
          currentDocumentCount={state.scopedDocumentIds?.length ?? 0}
          onTriggerFileUpload={dataLoading.triggerFileUpload}
        />
      </PageScaffold>
    </AppFrame>
  )
}
