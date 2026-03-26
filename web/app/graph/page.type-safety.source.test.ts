import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('graph page type safety', () => {
  it('extracts graph helper types and removes the most obvious any-based hotspots from the page', () => {
    const page = read('./page.tsx')
    const utils = read('./graph-page-utils.ts')

    expect(page).toContain("from './graph-page-utils'")
    expect(utils).toContain('export type GraphNodeLike')
    expect(utils).toContain('export type GraphLinkLike')
    expect(utils).toContain('export function getGraphNodeKind')
    expect(utils).toContain('export function getGraphLinkEndpointId')
    expect(page).not.toContain("| { type: 'node'; node: any }")
    expect(page).not.toContain("| { type: 'link'; link: any }")
    expect(page).not.toContain('function getGraphNodeKind(node: any)')
    expect(page).not.toContain('function getGraphNodeType(node: any)')
    expect(page).not.toContain('function getGraphLinkKind(link: any)')
    expect(page).not.toContain('function getGraphLinkPredicate(link: any)')
    expect(page).not.toContain('function getGraphLinkConfidence(link: any)')
    expect(page).not.toContain('function getGraphLinkEndpointId(raw: any)')
    expect(page).not.toContain('items.map((d: any)')
    expect(page).not.toContain('items.filter((d: any)')
    expect(page).not.toContain('const nextLinks: any[] = []')
    expect(page).not.toContain('const _extractTraceFromPayload = (payload: any)')
    expect(page).not.toContain('const handleDeleteNode = useCallback((node?: any)')
    expect(page).not.toContain('const finishConnection = (targetNode: any)')
    expect(page).not.toContain('const handleNodeClick = (node: any)')
    expect(page).not.toContain('const handleLinkClick = (link: any)')
    expect(page).not.toContain('(start: any, end: any)')
    expect(page).not.toContain('(node?: any)')
    expect(page).not.toContain('.filter((l: any)')
    expect(page).not.toContain('.map((l: any, idx: number)')
    expect(utils).toContain('export function extractTraceFromPayload')
    expect(utils).toContain('export function buildGraphFromTrace')
    expect(page).not.toContain('const _extractTraceFromPayload = (payload: unknown)')
    expect(page).not.toContain('const _buildGraphFromTrace = (trace: RagTrace)')
  })

  it('keeps heavy right-side detail panels extracted into dedicated graph components', () => {
    const page = read('./page.tsx')
    const body = read('./_components/graph-page-body.tsx')
    const nodePanel = read('./_components/graph-node-detail-panel.tsx')
    const linkPanel = read('./_components/graph-link-detail-panel.tsx')

    expect(page).toContain('GraphPageBody')
    expect(body).toContain('GraphNodeDetailPanel')
    expect(body).toContain('GraphLinkDetailPanel')
    expect(nodePanel).toContain('export function GraphNodeDetailPanel')
    expect(linkPanel).toContain('export function GraphLinkDetailPanel')
    expect(page).not.toContain('属性详情')
    expect(page).not.toContain('KG Detail')
    expect(page).not.toContain('Self-loop Group')
  })

  it('keeps graph action dialogs extracted into a dedicated overlay component', () => {
    const page = read('./page.tsx')
    const dialogs = read('./_components/graph-action-dialogs.tsx')

    expect(page).toContain('GraphActionDialogs')
    expect(dialogs).toContain('export function GraphActionDialogs')
    expect(page).not.toContain('删除节点？')
    expect(page).not.toContain('确认合并？')
    expect(page).not.toContain('拆分实体')
    expect(page).not.toContain('关系名称')
  })

  it('keeps explainability and floating graph controls extracted into dedicated components', () => {
    const page = read('./page.tsx')
    const body = read('./_components/graph-page-body.tsx')
    const explainabilityPanel = read('./_components/graph-explainability-panel.tsx')
    const floatingControls = read('./_components/graph-floating-controls.tsx')

    expect(page).toContain('GraphPageBody')
    expect(body).toContain('GraphExplainabilityPanel')
    expect(body).toContain('GraphFloatingControls')
    expect(explainabilityPanel).toContain('export function GraphExplainabilityPanel')
    expect(floatingControls).toContain('export function GraphFloatingControls')
    expect(page).not.toContain('RAG 推理过程')
    expect(page).not.toContain('title="导出 PNG/SVG"')
    expect(page).not.toContain("title=\"推理演示 (Explain)\"")
    expect(page).not.toContain("title=\"路径发现 (Shortest Path)\"")
  })

  it('keeps graph search, filter, and status overlays extracted into dedicated components', () => {
    const page = read('./page.tsx')
    const header = read('./_components/graph-page-header.tsx')
    const searchOverlay = read('./_components/graph-search-overlay.tsx')
    const statusBanners = read('./_components/graph-status-banners.tsx')
    const filtersPopover = read('./_components/graph-filters-popover.tsx')

    expect(page).toContain('GraphPageHeader')
    expect(header).toContain('GraphSearchOverlay')
    expect(header).toContain('GraphStatusBanners')
    expect(header).toContain('GraphFiltersPopover')
    expect(searchOverlay).toContain('export function GraphSearchOverlay')
    expect(statusBanners).toContain('export function GraphStatusBanners')
    expect(filtersPopover).toContain('export function GraphFiltersPopover')
    expect(page).not.toContain('placeholder="搜索实体节点..."')
    expect(page).not.toContain('Predicate 仅对关系边生效；Type 仅对实体节点生效。')
    expect(page).not.toContain('推理路径演示中...')
  })

  it('keeps graph canvas and context menu extracted into dedicated components', () => {
    const page = read('./page.tsx')
    const body = read('./_components/graph-page-body.tsx')
    const graphCanvas = read('./_components/graph-canvas.tsx')
    const graphContextMenu = read('./_components/graph-context-menu.tsx')

    expect(page).toContain('GraphPageBody')
    expect(body).toContain('GraphCanvas')
    expect(body).toContain('GraphContextMenu')
    expect(graphCanvas).toContain('export function GraphCanvas')
    expect(graphContextMenu).toContain('export function GraphContextMenu')
    expect(page).not.toContain('Loading graph...')
    expect(page).not.toContain('探索知识网络')
    expect(page).not.toContain('展开邻居')
    expect(page).not.toContain('复制 Predicate')
  })

  it('keeps the graph page header extracted into a dedicated component', () => {
    const page = read('./page.tsx')
    const header = read('./_components/graph-page-header.tsx')

    expect(page).toContain('GraphPageHeader')
    expect(header).toContain('export function GraphPageHeader')
    expect(page).not.toContain('title="实体-实体共现连线"')
    expect(page).not.toContain('title="导入 RAG trace JSON（回放检索路径）"')
    expect(page).not.toContain('accept=".graphml,.xml"')
    expect(page).not.toContain('accept=".json,application/json"')
  })

  it('keeps the graph page body extracted into a dedicated component', () => {
    const page = read('./page.tsx')
    const body = read('./_components/graph-page-body.tsx')

    expect(page).toContain('GraphPageBody')
    expect(body).toContain('export function GraphPageBody')
    expect(body).toContain('GraphStatsBar')
    expect(body).toContain('GraphLegend')
    expect(page).not.toContain('待处理文档')
    expect(page).not.toContain('GraphStatsBar')
    expect(page).not.toContain('GraphLegend')
  })

  it('keeps graph data loading and trace import logic extracted into a dedicated hook', () => {
    const page = read('./page.tsx')
    const hook = read('./use-graph-data-loading.ts')

    expect(page).toContain('useGraphDataLoading')
    expect(hook).toContain('export function useGraphDataLoading')
    expect(hook).toContain('buildGraphFromTrace')
    expect(page).not.toContain('const handleFileUpload = async')
    expect(page).not.toContain('const handleTraceFileUpload = async')
    expect(page).not.toContain('const triggerTraceUpload = () =>')
  })

  it('keeps graph entity resolution state and actions extracted into a dedicated hook', () => {
    const page = read('./page.tsx')
    const hook = read('./use-graph-entity-resolution.ts')

    expect(page).toContain('useGraphEntityResolution')
    expect(hook).toContain('export function useGraphEntityResolution')
    expect(hook).toContain('const reloadEntityResolution = useCallback')
    expect(page).not.toContain('const reloadEntityResolution = useCallback')
    expect(page).not.toContain('const handleSaveAlias = useCallback')
    expect(page).not.toContain('const submitMerge = useCallback')
    expect(page).not.toContain('const submitSplit = useCallback')
    expect(page).not.toContain('const undoLastResolution = useCallback')
  })

  it('keeps graph interaction modes extracted into a dedicated hook', () => {
    const page = read('./page.tsx')
    const hook = read('./use-graph-interaction-modes.ts')

    expect(page).toContain('useGraphInteractionModes')
    expect(hook).toContain('export function useGraphInteractionModes')
    expect(hook).toContain('const startExplainMode = useCallback')
    expect(hook).toContain('const handleStartPathFromContextNode = useCallback')
    expect(page).not.toContain('const startConnectMode = () =>')
    expect(page).not.toContain('const startExplainMode = () =>')
    expect(page).not.toContain('const togglePathMode = () =>')
    expect(page).not.toContain('const cycleLayoutMode = () =>')
    expect(page).not.toContain('const handleStartPathFromContextNode = useCallback')
    expect(page).not.toContain('const handleStartConnectFromContextNode = useCallback')
    expect(page).not.toContain('const handleOpenLinkDetailFromContextMenu = useCallback')
    expect(page).not.toContain('const handleClearHighlightsFromContextMenu = useCallback')
    expect(page).not.toContain('const handleConnectLabelOpenChange = useCallback')
    expect(page).not.toContain('// Keyboard Shortcuts')
  })

  it('keeps graph display filters and search highlighting extracted into a dedicated hook', () => {
    const page = read('./page.tsx')
    const hook = read('./use-graph-display-filters.ts')

    expect(page).toContain('useGraphDisplayFilters')
    expect(hook).toContain('export function useGraphDisplayFilters')
    expect(hook).toContain('const displayGraphData = useMemo<GraphData>')
    expect(hook).toContain('const searchMatches = useMemo')
    expect(page).not.toContain('const availableEntityTypes = useMemo(() =>')
    expect(page).not.toContain('const filteredPredicates = useMemo(() =>')
    expect(page).not.toContain('const displayGraphData = useMemo<GraphData>(() =>')
    expect(page).not.toContain('const searchMatches = useMemo(() =>')
    expect(page).not.toContain('const resetGraphFilters = () =>')
    expect(page).not.toContain('const handleEntityTypeCheckedChange = useCallback')
    expect(page).not.toContain('const handlePredicateCheckedChange = useCallback')
    expect(page).not.toContain('const toggleConfidenceBucket = (bucket: GraphConfBucket) =>')
  })
})
