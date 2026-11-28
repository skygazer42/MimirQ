'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { BarChart3, FileText, GitBranch, GitCompare, Route, Share2, Wrench } from '@/components/icons'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { SplitEmptyStudio } from '@/components/ui/split-empty-studio'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'

import type { UseGraphDataLoadingResult } from '../use-graph-data-loading'
import type { UseGraphDisplayFiltersResult } from '../use-graph-display-filters'
import type { UseGraphEntityResolutionResult } from '../use-graph-entity-resolution'
import type { UseGraphInteractionModesResult } from '../use-graph-interaction-modes'
import type { UseGraphNodeOperationsResult } from '../use-graph-node-operations'
import type { UseGraphPageActionsResult } from '../use-graph-page-actions'
import type { UseGraphPageStateResult } from '../use-graph-page-state'
import { GraphActionDialogs } from './graph-action-dialogs'
import { GraphPageBody } from './graph-page-body'
import { GraphPageHeader, GraphWorkspaceFilters } from './graph-page-header'
import { GraphNodeDirectory } from './graph-node-directory'
import { GraphSelectionSummary } from './graph-selection-summary'
import { GraphStatusBanners } from './graph-status-banners'
import { buildDirectoryIndex, getNeighborhood } from '../graph-directory-model'
import { ontologyGraphTarget, type GraphNodeLike, type OntologyGraphTarget } from '../graph-page-utils'
import styles from './graph-workspace.module.css'
import { GraphScopePickerDialog } from './graph-scope-picker-dialog'
import { OntologyGraphTool } from './ontology-graph-tool'

type GraphPageShellProps = Readonly<{
  state: UseGraphPageStateResult
  dataLoading: UseGraphDataLoadingResult
  entityResolution: UseGraphEntityResolutionResult
  displayFilters: UseGraphDisplayFiltersResult
  nodeOperations: UseGraphNodeOperationsResult
  pageActions: UseGraphPageActionsResult
  interactionModes: UseGraphInteractionModesResult
}>

function GraphHubIllustration() {
  return (
    <svg width="168" height="148" viewBox="0 0 168 148" fill="none" aria-hidden="true">
      <line x1="84" y1="74" x2="84" y2="24" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <line x1="84" y1="74" x2="132" y2="56" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <line x1="84" y1="74" x2="116" y2="118" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <line x1="84" y1="74" x2="52" y2="118" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <line x1="84" y1="74" x2="36" y2="56" stroke="hsl(var(--border))" strokeWidth="1.25" />

      <circle cx="84" cy="24" r="15" fill="hsl(var(--card))" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <rect x="78.5" y="18.5" width="11" height="11" rx="2" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" />
      <line x1="81.5" y1="22.5" x2="86.5" y2="22.5" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" strokeLinecap="round" />
      <line x1="81.5" y1="25.8" x2="85" y2="25.8" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" strokeLinecap="round" />

      <circle cx="132" cy="56" r="15" fill="hsl(var(--card))" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <path d="M126 53.5L132 50L138 53.5L132 57L126 53.5Z" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M126 57.5L132 61L138 57.5" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />

      <circle cx="116" cy="118" r="15" fill="hsl(var(--card))" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <path d="M111.5 117.5L116 113H120.5V117.5L116 122L111.5 117.5Z" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" strokeLinejoin="round" />
      <circle cx="118" cy="115.5" r="1" fill="hsl(var(--muted-foreground))" />

      <circle cx="52" cy="118" r="15" fill="hsl(var(--card))" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <path d="M46.5 114.5H50.5C51.6 114.5 52 115.1 52 116V122.5C52 121.7 51.2 121.2 50.2 121.2H46.5V114.5Z" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M57.5 114.5H53.5C52.4 114.5 52 115.1 52 116V122.5C52 121.7 52.8 121.2 53.8 121.2H57.5V114.5Z" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" strokeLinejoin="round" />

      <circle cx="36" cy="56" r="15" fill="hsl(var(--card))" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <path d="M36 50L41.5 53V59L36 62L30.5 59V53L36 50Z" stroke="hsl(var(--muted-foreground))" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="M36 56V62M36 56L41.5 53M36 56L30.5 53" stroke="hsl(var(--muted-foreground))" strokeWidth="1.1" strokeLinejoin="round" />

      <circle cx="84" cy="74" r="21" fill="hsl(var(--accent))" />
      <circle cx="84" cy="69.5" r="4.2" stroke="hsl(var(--accent-foreground))" strokeWidth="1.5" />
      <path d="M76.5 81.5C77.7 77.7 80.5 76 84 76C87.5 76 90.3 77.7 91.5 81.5" stroke="hsl(var(--accent-foreground))" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

const GRAPH_EMPTY_STEPS = [
  {
    index: '01',
    title: '数据集抽取',
    description: '入库开启图谱后自动沉淀实体与关系',
  },
  {
    index: '02',
    title: '路径与网络分析',
    description: '支持多跳展开、最短路径与社区洞察',
  },
  {
    index: '03',
    title: '溯源原文片段',
    description: '点击节点或连线定位原始文档出处',
  },
] as const

export function GraphPageShell({
  state,
  dataLoading,
  entityResolution,
  displayFilters,
  nodeOperations,
  pageActions,
  interactionModes,
}: GraphPageShellProps) {
  const [graphScopePickerOpen, setGraphScopePickerOpen] = useState(false)

  const [mobileView, setMobileView] = useState<'directory' | 'graph' | null>(null)
  const [focused, setFocused] = useState(true)
  const [depth, setDepth] = useState<1 | 2>(1)
  const [detailsExpanded, setDetailsExpanded] = useState(false)
  const [analysisOpen, setAnalysisOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<{ datasetId: string; target: OntologyGraphTarget } | null>(null)
  const detailsButtonRef = useRef<HTMLButtonElement>(null)
  const mobileTabsRef = useRef<HTMLDivElement>(null)
  const focusGraphAfterSelection = useRef(false)
  const { graphViewportRef, searchInputRef } = state
  const isLoading = state.isLoading || (state.dataSource === 'live' && state.scopedDatasetDocIdsLoading)
  const scopeError = state.dataSource === 'live' ? state.scopedDocumentsError : null
  const graphReadError =
    scopeError === null ? dataLoading.liveGraphError : formatApiError(scopeError, '读取图谱范围内的文档失败')
  const isEmptyGraph =
    !isLoading &&
    graphReadError === null &&
    displayFilters.displayGraphData.nodes.length === 0 &&
    displayFilters.activeGraphFilterCount === 0
  const detail = nodeOperations.nodeDetail
  const splitEvents = detail !== null && 'entity' in detail ? detail.events : []
  const directoryIndex = useMemo(
    () => buildDirectoryIndex(displayFilters.graphRenderData),
    [displayFilters.graphRenderData],
  )
  const activeMobileView =
    mobileView ?? (!isLoading && graphReadError === null && directoryIndex.nodes.size === 0 ? 'graph' : 'directory')
  const selected = state.selectedNode === null ? null : (directoryIndex.nodes.get(state.selectedNode.id) ?? null)
  const ontologyVersionId = state.dataSource === 'live' ? state.graphData.ontologyVersionId : undefined
  const nodeEditTarget = ontologyVersionId ? ontologyGraphTarget(selected?.meta) : null
  const linkEditTarget = ontologyVersionId ? ontologyGraphTarget(state.selectedLink?.meta) : null
  const specialMode = state.isPathMode || state.isConnectMode || state.isExplainMode
  const focusedNode = focused && !specialMode ? selected : null
  const focusedNodeId = focusedNode?.id ?? null
  const isFocused = focusedNode !== null
  const visibleGraph = useMemo(
    () =>
      focusedNodeId === null
        ? displayFilters.graphRenderData
        : getNeighborhood(displayFilters.graphRenderData, directoryIndex, focusedNodeId, depth),
    [depth, directoryIndex, displayFilters.graphRenderData, focusedNodeId],
  )
  const visibleTypeCount = useMemo(() => {
    const visibleIds = new Set(visibleGraph.nodes.map((node) => node.id))
    return directoryIndex.groups.filter((group) => group.nodes.some((node) => visibleIds.has(node.id))).length
  }, [directoryIndex.groups, visibleGraph.nodes])
  const selectNode = (node: GraphNodeLike) => {
    interactionModes.handleNodeClick(node)
    setDetailsExpanded(false)
    if (!specialMode) setFocused(true)
    focusGraphAfterSelection.current = mobileView === 'directory'
    setMobileView('graph')
  }
  function refreshLiveGraph() {
    detachPromise(dataLoading.loadLiveGraph({ refreshDocuments: true }))
  }
  function openOntologyItem(target: OntologyGraphTarget) {
    if (state.scope.datasetId) setEditTarget({ datasetId: state.scope.datasetId, target })
  }
  useLayoutEffect(() => {
    if (mobileView !== 'graph' || !focusGraphAfterSelection.current) return
    focusGraphAfterSelection.current = false
    if (mobileTabsRef.current?.getClientRects().length) graphViewportRef.current?.focus()
  }, [graphViewportRef, mobileView])
  useEffect(() => {
    let focusFrameId: number | undefined
    const onSearch = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return
      if (event.target instanceof Element && event.target.closest('[role="dialog"], [role="alertdialog"]')) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        setMobileView('directory')
        if (focusFrameId !== undefined) cancelAnimationFrame(focusFrameId)
        focusFrameId = requestAnimationFrame(() => searchInputRef.current?.focus())
      }
    }
    window.addEventListener('keydown', onSearch)
    return () => {
      window.removeEventListener('keydown', onSearch)
      if (focusFrameId !== undefined) cancelAnimationFrame(focusFrameId)
    }
  }, [searchInputRef])

  return (
    <AppFrame>
      <PageScaffold
        showHeader={false}
        title="知识图谱"
        description="知识图谱可视化与分析"
        icon={Share2}
        size="full"
        bodyGutter="none"
        bodyClassName="p-0 overflow-hidden"
        bodyContainerClassName="flex h-full min-h-0 flex-col"
      >
        <div className={styles.workspace} data-graph-directory-page>
          <GraphPageHeader
            fileName={state.fileName}
            dataSource={state.dataSource}
            graphNodeCount={displayFilters.displayGraphData.nodes.length}
            isEmptyGraph={isEmptyGraph}
            isLoading={isLoading}
            isExportingGraphML={pageActions.isExportingGraphML}
            includeEntityLinks={state.includeEntityLinks}
            includeRelationLinks={state.includeRelationLinks}
            isOntologyGraph={Boolean(ontologyVersionId)}
            minSharedEvents={state.minSharedEvents}
            onToggleEntityLinks={interactionModes.toggleEntityLinks}
            onToggleRelationLinks={interactionModes.toggleRelationLinks}
            onCycleMinSharedEvents={interactionModes.cycleMinSharedEvents}
            onExportGraphML={pageActions.handleExportGraphML}
            onRefreshLiveData={refreshLiveGraph}
            onOpenGraphPicker={() => setGraphScopePickerOpen(true)}
            onTriggerTraceUpload={dataLoading.triggerTraceUpload}
            traceFileInputRef={state.traceFileInputRef}
            onTraceFileUpload={dataLoading.handleTraceFileUpload}
            onTriggerManualKgUpload={dataLoading.triggerManualKgUpload}
            manualKgFileInputRef={state.manualKgFileInputRef}
            onManualKgFileUpload={dataLoading.handleManualKgFileUpload}
            ontologyTool={
              ontologyVersionId && state.scope.datasetId ? (
                <OntologyGraphTool
                  key={`${state.scope.datasetId}:${ontologyVersionId}`}
                  datasetId={state.scope.datasetId}
                  documentIds={state.scope.directDocIds}
                  versionId={ontologyVersionId}
                  target={
                    editTarget?.datasetId === state.scope.datasetId && editTarget.target.versionId === ontologyVersionId
                      ? editTarget.target
                      : null
                  }
                  onCloseTarget={() => setEditTarget(null)}
                  onSaved={() => detachPromise(dataLoading.loadLiveGraph())}
                />
              ) : undefined
            }
          />

          {graphReadError !== null ? (
            <div className={displayFilters.displayGraphData.nodes.length > 0 ? undefined : 'px-7 pt-3'}>
              <WorkspaceNotice
                placement={displayFilters.displayGraphData.nodes.length > 0 ? 'floating' : 'inline'}
                tone={displayFilters.displayGraphData.nodes.length > 0 ? 'warning' : 'error'}
                retry={refreshLiveGraph}
                pending={isLoading}
              >
                {graphReadError}
              </WorkspaceNotice>
            </div>
          ) : null}

          {isEmptyGraph ? (
            <SplitEmptyStudio
              illustration={<GraphHubIllustration />}
              title="选择或导入知识图谱"
              description="选择已有数据集图谱，或导入 KG JSON / JSONL 查看实体关系与原文来源。"
              actions={
                <>
                  <Button
                    className="bg-accent text-accent-foreground hover:bg-accent/90"
                    onClick={() => setGraphScopePickerOpen(true)}
                  >
                    选择图谱
                  </Button>
                  <Button variant="outline" onClick={dataLoading.triggerManualKgUpload}>
                    导入 KG JSON / JSONL
                  </Button>
                </>
              }
              stepsHeading="图谱构建与分析"
              steps={GRAPH_EMPTY_STEPS}
              shortcutsHeading="常用入口"
              shortcuts={[
                {
                  key: 'trace-upload',
                  icon: <FileText />,
                  title: '导入检索回放',
                  description: '加载问答检索轨迹并回放子图',
                  onClick: dataLoading.triggerTraceUpload,
                },
                {
                  key: 'graph-diagnostics',
                  icon: <Wrench />,
                  title: '图谱诊断',
                  description: '检查孤立节点、冲突与抽取质量',
                  href: '/graph/diagnostics',
                },
                {
                  key: 'graph-snapshots',
                  icon: <GitCompare />,
                  title: '图谱快照',
                  description: '对比不同版本知识图谱差异',
                  href: '/graph/snapshots',
                },
              ]}
            />
          ) : (
            <>
              <div ref={mobileTabsRef} className={styles.mobileTabs} aria-label="图谱工作区视图">
            <button
              type="button"
              aria-pressed={activeMobileView === 'directory'}
              onClick={() => setMobileView('directory')}
            >
              实体目录
            </button>
            <button type="button" aria-pressed={activeMobileView === 'graph'} onClick={() => setMobileView('graph')}>
              关系图谱
            </button>
          </div>
          <div className={styles.columns} data-mobile-view={activeMobileView}>
            <GraphNodeDirectory
              groups={directoryIndex.groups}
              neighbors={directoryIndex.neighbors}
              selectedId={selected?.id ?? null}
              query={state.searchTerm}
              inputRef={state.searchInputRef}
              loading={isLoading}
              hasLoadError={graphReadError !== null}
              onQueryChange={state.setSearchTerm}
              onSelect={selectNode}
            />
            <div className={styles.stage}>
              <div className={styles.toolbar}>
                <div className={styles.viewSwitch} aria-label="图谱显示范围">
                  <button type="button" aria-pressed={!isFocused} onClick={() => setFocused(false)}>
                    全部图谱
                  </button>
                  <button
                    type="button"
                    aria-pressed={isFocused}
                    disabled={!selected || specialMode}
                    onClick={() => setFocused(true)}
                  >
                    聚焦实体
                  </button>
                </div>
                <Select
                  value={String(depth)}
                  onValueChange={(value) => setDepth(value === '2' ? 2 : 1)}
                  disabled={!isFocused}
                >
                  <SelectTrigger className={styles.depthSelect} aria-label="邻域展开层数">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">展开 1 层</SelectItem>
                    <SelectItem value="2">展开 2 层</SelectItem>
                  </SelectContent>
                </Select>
                <GraphWorkspaceFilters state={state} filters={displayFilters} />
                <div className={styles.toolbarEnd}>
                  <Button
                    variant="ghost"
                    aria-label="路径发现"
                    aria-pressed={state.isPathMode}
                    onClick={interactionModes.togglePathMode}
                    disabled={!directoryIndex.nodes.size}
                  >
                    <Route />
                    <span className={styles.secondaryLabel}>路径发现</span>
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setAnalysisOpen(true)}
                    disabled={!directoryIndex.nodes.size}
                    aria-label="网络分析"
                  >
                    <BarChart3 />
                    <span className={styles.secondaryLabel}>网络分析</span>
                  </Button>
                  {selected && !specialMode && !ontologyVersionId ? (
                    <Button
                      className={styles.expandAction}
                      onClick={nodeOperations.handleExpandNode}
                      disabled={isLoading}
                    >
                      <GitBranch />
                      展开邻居
                    </Button>
                  ) : null}
                </div>
              </div>
              <div className={styles.modeBanner}>
                <GraphStatusBanners
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
                />
              </div>
              <GraphPageBody
                analysisOpen={analysisOpen}
                onAnalysisOpenChange={setAnalysisOpen}
                canvasLabel={
                  directoryIndex.nodes.size ? (
                    <div className={styles.canvasLabel}>
                      <strong>{focusedNode === null ? '全部图谱' : `${focusedNode.label}的周边`}</strong>
                      {focusedNode !== null ? (
                        <>
                          <button type="button" className="focus-ring" onClick={() => setFocused(false)}>
                            返回完整图谱
                          </button>
                          <p>
                            {directoryIndex.neighbors.get(focusedNode.id)?.size ?? 0} 个直接关联 · 当前显示{' '}
                            {visibleGraph.nodes.length} 个节点
                            {state.viewMode === '3d' ? ' · 点选节点查看名称' : ''}
                          </p>
                        </>
                      ) : (
                        <p>
                          {state.viewMode === '2d' ? '2D 平面' : '3D 空间'} ·{' '}
                          {state.scopedDatasetPendingDocs
                            ? `${state.scopedDatasetPendingDocs} 份文档正在处理`
                            : '选择实体查看关联与来源'}
                        </p>
                      )}
                    </div>
                  ) : null
                }
                summary={
                  selected && state.isDetailOpen && !detailsExpanded && !specialMode ? (
                    <GraphSelectionSummary
                      detailsButtonRef={detailsButtonRef}
                      node={selected}
                      count={directoryIndex.neighbors.get(selected.id)?.size ?? 0}
                      detail={detail}
                      loading={nodeOperations.nodeDetailLoading}
                      detailError={nodeOperations.nodeDetailError}
                      isOntologyEntity={nodeEditTarget !== null}
                      onDetails={() => (nodeEditTarget ? openOntologyItem(nodeEditTarget) : setDetailsExpanded(true))}
                      onExpand={nodeOperations.handleExpandNode}
                      onSource={pageActions.handleViewSource}
                      onClose={() => {
                        state.setSelectedNode(null)
                        state.setIsDetailOpen(false)
                      }}
                    />
                  ) : null
                }
                canvasProps={{
                  viewportRef: state.graphViewportRef,
                  graph2dRef: state.graph2dRef,
                  graph3dRef: state.graph3dRef,
                  graphRenderData: visibleGraph,
                  viewMode: state.viewMode,
                  graphViewportWidth: state.graphViewportWidth,
                  graphViewportHeight: state.graphViewportHeight,
                  selectedNodeId: state.selectedNode?.id ?? null,
                  highlightedNodeIds: state.highlightedNodeIds,
                  highlightedLinkIds: state.highlightedLinkIds,
                  showEdgeLabels: state.showEdgeLabels,
                  layoutMode: state.layoutMode,
                  isLoading,
                  hasLoadError: graphReadError !== null,
                  onNodeClick: selectNode,
                  onNodeRightClick: pageActions.handleNodeRightClick,
                  onLinkClick: interactionModes.handleLinkClick,
                  onLinkRightClick: pageActions.handleLinkRightClick,
                  onBackgroundClick: pageActions.handleBackgroundClick,
                  onBackgroundRightClick: pageActions.handleBackgroundRightClick,
                  onOpenGraphPicker: () => setGraphScopePickerOpen(true),
                  onTriggerManualKgUpload: dataLoading.triggerManualKgUpload,
                }}
                contextMenuProps={{
                  contextMenu: pageActions.contextMenu,
                  viewMode: state.viewMode,
                  showEdgeLabels: state.showEdgeLabels,
                  onClose: pageActions.closeContextMenu,
                  onExpandNode: ontologyVersionId ? undefined : nodeOperations.handleExpandNodeById,
                  onStartPathFromNode: interactionModes.handleStartPathFromContextNode,
                  onStartConnectFromNode: ontologyVersionId
                    ? undefined
                    : interactionModes.handleStartConnectFromContextNode,
                  onChatWithNode: pageActions.chatWithNode,
                  onViewSourceForNode: pageActions.viewSourceForNode,
                  onCopyNodeId: pageActions.handleCopyNodeId,
                  onDeleteNode: ontologyVersionId ? undefined : nodeOperations.handleDeleteNode,
                  onOpenLinkDetail: interactionModes.handleOpenLinkDetailFromContextMenu,
                  onCopyLinkPredicate: pageActions.handleCopyLinkPredicate,
                  onZoomToFit: () => state.getActiveGraph()?.zoomToFit?.(),
                  onClearHighlights: interactionModes.handleClearHighlightsFromContextMenu,
                  onToggleShowEdgeLabels: () => state.setShowEdgeLabels((value) => !value),
                }}
                explainabilityOpen={state.isExplainMode}
                explainSteps={state.explainSteps}
                currentStepIndex={state.currentStepIndex}
                displayNodes={displayFilters.displayGraphData.nodes}
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
                  open: state.isDetailOpen && detailsExpanded && !ontologyVersionId,
                  selectedNode: state.selectedNode,
                  detailScrollRef: state.detailScrollRef,
                  dataSource: state.dataSource,
                  kgNodeDetailLoading: nodeOperations.nodeDetailLoading,
                  kgNodeDetail: detail,
                  kgNodeDetailError: nodeOperations.nodeDetailError,
                  onRetryNodeDetail: () => void nodeOperations.retryNodeDetail(),
                  entityAliasesLoading: entityResolution.entityAliasesLoading,
                  entityAliasesError: entityResolution.entityAliasesError,
                  entityAliases: entityResolution.entityAliases,
                  aliasDraft: entityResolution.aliasDraft,
                  aliasSaving: entityResolution.aliasSaving,
                  aliasSuggestionsLoading: entityResolution.aliasSuggestionsLoading,
                  aliasSuggestionsError: entityResolution.aliasSuggestionsError,
                  aliasSuggestions: entityResolution.aliasSuggestions,
                  lastResolutionActionId: entityResolution.lastResolutionActionId,
                  undoSubmitting: entityResolution.undoSubmitting,
                  isLoading,
                  onClose: () => {
                    setDetailsExpanded(false)
                    requestAnimationFrame(() => detailsButtonRef.current?.focus())
                  },
                  onChat: pageActions.handleChatWithNode,
                  onViewSource: pageActions.handleViewSource,
                  onExpandNode: nodeOperations.handleExpandNode,
                  onStartConnectMode: interactionModes.startConnectMode,
                  onDeleteNode: () => nodeOperations.handleDeleteNode(),
                  onOpenMerge: entityResolution.openMergeDialog,
                  onOpenSplit: splitEvents.length > 0 ? entityResolution.openSplitDialog : undefined,
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
                  onOntologyEdit: linkEditTarget ? () => openOntologyItem(linkEditTarget) : undefined,
                  onClose: () => {
                    state.setIsLinkDetailOpen(false)
                    state.setSelectedLink(null)
                  },
                }}
              />
            </div>
          </div>
          <footer className={styles.footer}>
            <span>
              <b>{visibleGraph.nodes.length}</b> 节点
            </span>
            <span>
              <b>{visibleGraph.links.length}</b> 关系
            </span>
            <span>
              {displayFilters.activeGraphFilterCount
                ? `${directoryIndex.nodes.size} 个节点符合筛选`
                : `${visibleTypeCount} 种类型`}
            </span>
            <span>{selected ? `当前选择 · ${selected.label}` : state.fileName || '尚未选择图谱'}</span>
          </footer>
            </>
          )}
        </div>

        <GraphActionDialogs
          deleteNodeOpen={state.deleteNodeOpen}
          deleteNodeTarget={state.deleteNodeTarget}
          onDeleteNodeOpenChange={pageActions.handleDeleteNodeOpenChange}
          onConfirmDeleteNode={nodeOperations.confirmDeleteNode}
          aliasDeleteTarget={entityResolution.aliasDeleteTarget}
          aliasSaving={entityResolution.aliasSaving}
          onAliasDeleteOpenChange={entityResolution.handleAliasDeleteOpenChange}
          onConfirmDeleteAlias={entityResolution.confirmDeleteAlias}
          mergeOpen={entityResolution.mergeOpen}
          onMergeOpenChange={entityResolution.handleMergeOpenChange}
          mergeSearch={entityResolution.mergeSearch}
          onMergeSearchChange={entityResolution.setMergeSearch}
          mergeSearchLoading={entityResolution.mergeSearchLoading}
          mergeSearchError={entityResolution.mergeSearchError}
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
          splitEvents={splitEvents}
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
          onTriggerManualKgUpload={dataLoading.triggerManualKgUpload}
        />
      </PageScaffold>
    </AppFrame>
  )
}
