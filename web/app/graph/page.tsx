'use client'

/**
 * 知识图谱可视化页面
 * 功能：上传 .graphml 文件并进行可视化展示
 * 优化：主流视觉设计、交互侧边栏、玻璃拟态控件、搜索与高级筛选、后端集成、路径分析、布局切换、图编辑、RAG可解释性、3D可视化
 */
import { useState, useRef, useEffect, useCallback, useDeferredValue, useMemo } from 'react'
import { useTheme } from 'next-themes'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { IconButton } from '@/components/ui/icon-button'
import { Kbd } from '@/components/ui/kbd'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { SearchInput } from '@/components/ui/search-input'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Upload, Share2, Info, RefreshCw, Maximize, X, BarChart3, Database, Filter, SlidersHorizontal, Layers, FileCode, MessageSquare, FileText, Type, Trash2, Network, Route, Copy, Lightbulb, Link as LinkIcon } from 'lucide-react'
import { GraphActionDialogs } from './_components/graph-action-dialogs'
import { GraphExplainabilityPanel } from './_components/graph-explainability-panel'
import { GraphFloatingControls } from './_components/graph-floating-controls'
import { GraphViewer, GraphViewerRef, LayoutMode } from '@/components/graph/graph-viewer'
import { KnowledgeGraph3D, type KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { GraphLegend } from '@/components/graph/graph-legend'
import { GraphStatsBar } from '@/components/graph/graph-stats-bar'
import { GraphLinkDetailPanel } from './_components/graph-link-detail-panel'
import { GraphNodeDetailPanel } from './_components/graph-node-detail-panel'
import { parseGraphML, GraphData } from '@/lib/graph-parser'
import { GraphService } from '@/lib/graph-service'
import { findShortestPath } from '@/lib/graph-algorithms'
import { cn, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { documentApi } from '@/lib/api/documents'
import { kgApi } from '@/lib/api/graph'
import {
  GraphConfBucket,
  GraphContextMenuTarget,
  GraphContextMenuState,
  type GraphDatasetDocumentSummary,
  type GraphLinkLike,
  type GraphNodeLike,
  asGraphRecord,
  bucketConfidence,
  coerceBoundedInt,
  coerceTrimmedString,
  getGraphLinkConfidence,
  getGraphLinkEndpointId,
  getGraphLinkKind,
  getGraphLinkPredicate,
  getGraphNodeKind,
  getGraphNodeType,
  getScopedDocumentId,
  isPendingScopedDocument,
  parseCsvList,
  stripFilenameExtension,
} from './graph-page-utils'
import type {
  KGEntityAliasItem,
  KGEntityAliasSuggestionItem,
  KGEntityDetailResponse,
  KGEntityMergePreviewResponse,
  KGEntityMergeResponse,
  KGEntityResolutionUndoResponse,
  KGEntitySplitResponse,
  KGEventDetailResponse,
  KGStatsResponse,
  KGGraphNode,
  RagTrace,
} from '@/types'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import { sanitizeFilename } from '@/lib/sanitize'

export default function GraphPage() {
  const router = useRouter()
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
  const [scopeAutoLoaded, setScopeAutoLoaded] = useState(false)

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

  // Entity Resolution (Wave15)
  const [entityAliases, setEntityAliases] = useState<KGEntityAliasItem[]>([])
  const [entityAliasesLoading, setEntityAliasesLoading] = useState(false)
  const [aliasDraft, setAliasDraft] = useState('')
  const [aliasSaving, setAliasSaving] = useState(false)
  const [aliasDeleteOpen, setAliasDeleteOpen] = useState(false)
  const [aliasDeleteTarget, setAliasDeleteTarget] = useState<KGEntityAliasItem | null>(null)

  const [aliasSuggestions, setAliasSuggestions] = useState<KGEntityAliasSuggestionItem[]>([])
  const [aliasSuggestionsLoading, setAliasSuggestionsLoading] = useState(false)

  const [mergeOpen, setMergeOpen] = useState(false)
  const [mergeSearch, setMergeSearch] = useState('')
  const [mergeSearchLoading, setMergeSearchLoading] = useState(false)
  const [mergeSearchResults, setMergeSearchResults] = useState<KGGraphNode[]>([])
  const [mergeTarget, setMergeTarget] = useState<KGGraphNode | null>(null)
  const [mergePreview, setMergePreview] = useState<KGEntityMergePreviewResponse | null>(null)
  const [mergePreviewLoading, setMergePreviewLoading] = useState(false)
  const [mergeConfirmOpen, setMergeConfirmOpen] = useState(false)
  const [mergeSubmitting, setMergeSubmitting] = useState(false)
  const [mergeError, setMergeError] = useState<string | null>(null)

  const [splitOpen, setSplitOpen] = useState(false)
  const [splitNameDraft, setSplitNameDraft] = useState('')
  const [splitSelectedEventIds, setSplitSelectedEventIds] = useState<Set<string>>(new Set())
  const [splitSubmitting, setSplitSubmitting] = useState(false)
  const [splitError, setSplitError] = useState<string | null>(null)

  const [lastResolutionActionId, setLastResolutionActionId] = useState<string | null>(null)
  const [undoSubmitting, setUndoSubmitting] = useState(false)
  
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
  const deferredSearchTerm = useDeferredValue(searchTerm)

  const [isFullscreen, setIsFullscreen] = useState(false)

  const [contextMenu, setContextMenu] = useState<GraphContextMenuState | null>(null)
  const [exportOpen, setExportOpen] = useState(false)

  const closeContextMenu = useCallback(() => {
    setContextMenu(null)
  }, [])

  const openContextMenu = useCallback((event: MouseEvent, target: GraphContextMenuTarget) => {
    try {
      event.preventDefault?.()
      event.stopPropagation?.()
    } catch {}

    const rect = graphViewportRef.current?.getBoundingClientRect()
    if (!rect) return

    const menuW = 272
    const menuH = 320
    const pad = 12
    let x = event.clientX - rect.left
    let y = event.clientY - rect.top
    x = Math.max(pad, Math.min(x, rect.width - menuW - pad))
    y = Math.max(pad, Math.min(y, rect.height - menuH - pad))
    setContextMenu({ x, y, target })
  }, [])

  useEffect(() => {
    if (!contextMenu) return
    const handle = () => setContextMenu(null)
    globalThis.window.addEventListener('mousedown', handle)
    globalThis.window.addEventListener('scroll', handle, true)
    return () => {
      globalThis.window.removeEventListener('mousedown', handle)
      globalThis.window.removeEventListener('scroll', handle, true)
    }
  }, [contextMenu])

  useEffect(() => {
    if (typeof document === 'undefined') return
    const handler = () => {
      setIsFullscreen(Boolean(document.fullscreenElement))
    }
    handler()
    document.addEventListener('fullscreenchange', handler)
    return () => document.removeEventListener('fullscreenchange', handler)
  }, [])

  const toggleFullscreen = useCallback(async () => {
    if (typeof document === 'undefined') return
    try {
      if (!document.fullscreenElement) {
        await graphViewportRef.current?.requestFullscreen?.()
      } else {
        await document.exitFullscreen?.()
      }
    } catch {
      toast.error('全屏切换失败')
    }
  }, [])

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

  const handleBackgroundClick = useCallback(() => {
    setIsDetailOpen(false)
    setIsLinkDetailOpen(false)
    setSelectedLink(null)
    closeContextMenu()
  }, [closeContextMenu])

  const handleNodeRightClick = useCallback(
    (node: GraphNodeLike, event: MouseEvent) => {
      setSelectedNode(node)
      setSelectedLink(null)
      setIsDetailOpen(false)
      setIsLinkDetailOpen(false)
      openContextMenu(event, { type: 'node', node })
    },
    [openContextMenu]
  )

  const handleLinkRightClick = useCallback(
    (link: GraphLinkLike, event: MouseEvent) => {
      setSelectedLink(link)
      setSelectedNode(null)
      setIsDetailOpen(false)
      setIsLinkDetailOpen(false)
      openContextMenu(event, { type: 'link', link })
    },
    [openContextMenu]
  )

  const handleBackgroundRightClick = useCallback(
    (event: MouseEvent) => {
      setIsDetailOpen(false)
      setIsLinkDetailOpen(false)
      openContextMenu(event, { type: 'background' })
    },
    [openContextMenu]
  )

  const availableEntityTypes = useMemo(() => {
    const counts = new Map<string, number>()
    for (const node of graphData.nodes) {
      if (getGraphNodeKind(node) !== 'entity') continue
      const t = getGraphNodeType(node) || 'unknown'
      counts.set(t, (counts.get(t) || 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([value, count]) => ({ value, count }))
      .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value))
  }, [graphData.nodes])

  const availablePredicates = useMemo(() => {
    const counts = new Map<string, number>()
    for (const link of graphData.links) {
      if (getGraphLinkKind(link) !== 'entity_relation') continue
      const p = getGraphLinkPredicate(link)
      if (!p) continue
      counts.set(p, (counts.get(p) || 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([value, count]) => ({ value, count }))
      .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value))
  }, [graphData.links])

  const filteredEntityTypes = useMemo(() => {
    const q = entityTypeQuery.trim().toLowerCase()
    const base = availableEntityTypes
    if (!q) return base.slice(0, 40)
    return base.filter((t) => t.value.toLowerCase().includes(q)).slice(0, 40)
  }, [availableEntityTypes, entityTypeQuery])

  const filteredPredicates = useMemo(() => {
    const q = predicateQuery.trim().toLowerCase()
    const base = availablePredicates
    if (!q) return base.slice(0, 40)
    return base.filter((p) => p.value.toLowerCase().includes(q)).slice(0, 40)
  }, [availablePredicates, predicateQuery])

  const activeGraphFilterCount = entityTypeFilters.length + predicateFilters.length + confidenceBucketFilters.length

  const displayGraphData = useMemo<GraphData>(() => {
    const hasTypeFilter = entityTypeFilters.length > 0
    const hasPredicateFilter = predicateFilters.length > 0
    const hasConfBucketFilter = confidenceBucketFilters.length > 0

    if (!hasTypeFilter && !hasPredicateFilter && !hasConfBucketFilter) {
      return graphData
    }

    const allowedTypes = new Set(entityTypeFilters.map((t) => coerceTrimmedString(t)))
    const allowedPredicates = new Set(predicateFilters.map((p) => coerceTrimmedString(p)))
    const allowedBuckets = new Set(confidenceBucketFilters)

    const allowedNodeIds = new Set<string>()
    for (const node of graphData.nodes) {
      const id = coerceTrimmedString(node?.id)
      if (!id) continue

      const kind = getGraphNodeKind(node)
      if (kind === 'entity') {
        const t = getGraphNodeType(node) || 'unknown'
        if (!hasTypeFilter || allowedTypes.has(t)) {
          allowedNodeIds.add(id)
        }
        continue
      }

      allowedNodeIds.add(id)
    }

    const nextLinks: GraphData['links'] = []
    for (const link of graphData.links) {
      const sourceId = getGraphLinkEndpointId(link?.source)
      const targetId = getGraphLinkEndpointId(link?.target)
      if (!sourceId || !targetId) continue
      if (!allowedNodeIds.has(sourceId) || !allowedNodeIds.has(targetId)) continue

      const kind = getGraphLinkKind(link)
      if (kind === 'entity_relation') {
        if (hasPredicateFilter) {
          const pred = getGraphLinkPredicate(link)
          if (!pred || !allowedPredicates.has(pred)) continue
        }

        if (hasConfBucketFilter) {
          const conf = getGraphLinkConfidence(link)
          const bucket = bucketConfidence(conf)
          if (!bucket || !allowedBuckets.has(bucket)) continue
        }
      }

      nextLinks.push({ ...link, source: sourceId, target: targetId })
    }

    const linkedNodeIds = new Set<string>()
    for (const link of nextLinks) {
      const s = getGraphLinkEndpointId(link?.source)
      const t = getGraphLinkEndpointId(link?.target)
      if (s) linkedNodeIds.add(s)
      if (t) linkedNodeIds.add(t)
    }

    const nextNodes = graphData.nodes.filter((node) => linkedNodeIds.has(coerceTrimmedString(node?.id)))
    return { nodes: nextNodes, links: nextLinks }
  }, [graphData, entityTypeFilters, predicateFilters, confidenceBucketFilters])

  const displayNodeIds = useMemo(() => {
    return new Set(displayGraphData.nodes.map((node) => coerceTrimmedString(node?.id)))
  }, [displayGraphData.nodes])

  // Close node detail panel if the current node is filtered out.
  useEffect(() => {
    if (!isDetailOpen || !selectedNodeId) return
    if (displayNodeIds.has(String(selectedNodeId))) return
    setIsDetailOpen(false)
    setSelectedNode(null)
  }, [displayNodeIds, isDetailOpen, selectedNodeId])

  // Filters can invalidate highlights (e.g. path/search results). Fail open: clear highlights on filter changes.
  useEffect(() => {
    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
    setPathStartNode(null)
    setPathEndNode(null)
  }, [entityTypeFilters, predicateFilters, confidenceBucketFilters])

  const linksWithIds = useMemo<GraphLinkLike[]>(() => {
    return displayGraphData.links.map((link, index) => ({
      ...link,
      id: link.id || `link-${index}`,
    }))
  }, [displayGraphData.links])

  const graphRenderData = useMemo<GraphData>(() => {
    return { nodes: displayGraphData.nodes, links: linksWithIds as GraphData['links'] }
  }, [displayGraphData.nodes, linksWithIds])

  const searchMatches = useMemo(() => {
    if (isPathMode || isConnectMode || isExplainMode) return []
    const term = deferredSearchTerm.trim().toLowerCase()
    if (!term) return []

    return displayGraphData.nodes.filter((node) => {
      const label = (node.label || '').toLowerCase()
      const id = (node.id || '').toLowerCase()
      return label.includes(term) || id.includes(term)
    })
  }, [deferredSearchTerm, displayGraphData.nodes, isPathMode, isConnectMode, isExplainMode])

  useEffect(() => {
    if (isPathMode || isConnectMode || isExplainMode) return
    const term = deferredSearchTerm.trim()
    if (!term) {
      setHighlightedNodeIds(new Set())
      return
    }

    const nextIds = new Set(searchMatches.map((node) => node.id))
    setHighlightedNodeIds(nextIds)

    if (searchMatches.length > 0) {
      getActiveGraph()?.focusNode(searchMatches[0].id)
    }
  }, [deferredSearchTerm, searchMatches, isPathMode, isConnectMode, isExplainMode, getActiveGraph])

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

  // Fetch entity resolution data (aliases + suggestions) when an entity is selected.
  useEffect(() => {
    if (dataSource !== 'live') {
      setEntityAliases([])
      setAliasSuggestions([])
      setAliasDraft('')
      setLastResolutionActionId(null)
      return
    }
    if (!isDetailOpen || !selectedNode?.id || selectedNode?.meta?.kind !== 'entity') {
      setEntityAliases([])
      setAliasSuggestions([])
      setAliasDraft('')
      return
    }

    let cancelled = false
    const entityId = String(selectedNode.id)

    setEntityAliasesLoading(true)
    setAliasSuggestionsLoading(true)
    setMergeError(null)
    setSplitError(null)

    ;(async () => {
      try {
        const resp = (await kgApi.listEntityAliases(entityId))
        if (!cancelled) setEntityAliases(resp.aliases || [])
      } catch {
        if (!cancelled) setEntityAliases([])
      } finally {
        if (!cancelled) setEntityAliasesLoading(false)
      }
    })()

    ;(async () => {
      try {
        const resp = (await kgApi.suggestEntityAliases(entityId, {
    mode: 'offline',
    k: 6,
    min_similarity: 0.75,
}))
        if (!cancelled) setAliasSuggestions(resp.suggestions || [])
      } catch {
        if (!cancelled) setAliasSuggestions([])
      } finally {
        if (!cancelled) setAliasSuggestionsLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [dataSource, isDetailOpen, selectedNode?.id, selectedNode?.meta?.kind])

  // Initialize with real (mock) data from service
  const loadInitialData = useCallback(async (
    source: 'live' | 'mock' = 'live',
    opts?: { includeEntityLinks?: boolean; includeRelationLinks?: boolean; minSharedEvents?: number }
  ) => {
    if (
      source === 'live'
      && scope.hasScope
      && scope.datasetId
      && scope.directDocIds.length === 0
      && scopedDocumentIds === null
      && scopedDatasetDocIdsLoading
    ) {
      toast.message('正在解析 dataset scope 的文档列表…')
      return
    }

    setIsLoading(true)
    try {
      const includeLinks = opts?.includeEntityLinks ?? includeEntityLinks
      const includeRels = opts?.includeRelationLinks ?? includeRelationLinks
      const sharedThreshold = opts?.minSharedEvents ?? minSharedEvents

      const data = await GraphService.fetchInitialGraph({
        preferMock: source === 'mock',
        includeEntityLinks: source === 'live' ? includeLinks : undefined,
        includeRelationLinks: source === 'live' ? includeRels : undefined,
        minSharedEvents: source === 'live' ? sharedThreshold : undefined,
        maxEntityLinks: source === 'live' ? maxEntityLinks : undefined,
        documentIds: source === 'live' ? (scopedDocumentIds && scopedDocumentIds.length ? scopedDocumentIds : undefined) : undefined,
        pipelineHash: source === 'live' ? (scope.pipelineHash || undefined) : undefined,
      })
      setGraphData(data)
      setDataSource(source)
      setTraceReplay(null)
      setKgNodeDetail(null)
      setFileName(source === 'mock' ? '示例数据' : (scopeParams ? 'Knowledge Base (Scoped)' : 'Knowledge Base (Live)'))

      if (source === 'live') {
        try {
          const stats = await kgApi.getStats(scopeParams || undefined)
          setKgStats(stats)
        } catch {
          setKgStats(null)
        }
      } else {
        setKgStats(null)
      }

      setIsDetailOpen(false)
      setSelectedNode(null)
      resetPathMode()
      resetConnectMode()
      resetExplainMode()
    } catch (error) {
      console.error('Failed to fetch graph data:', error)
    } finally {
      setIsLoading(false)
    }
  }, [
    includeEntityLinks,
    includeRelationLinks,
    maxEntityLinks,
    minSharedEvents,
    resetConnectMode,
    resetExplainMode,
    resetPathMode,
    scope.hasScope,
    scope.datasetId,
    scope.directDocIds,
    scope.pipelineHash,
    scopedDatasetDocIdsLoading,
    scopeParams,
    scopedDocumentIds,
  ])

  useEffect(() => {
    if (scopeAutoLoaded) return
    if (!scope.hasScope) return

    // If we need to resolve dataset -> document ids, wait for that first.
    if (scope.datasetId && scope.directDocIds.length === 0 && scopedDocumentIds === null) return

    setScopeAutoLoaded(true)
    detachPromise(loadInitialData('live'))
  }, [loadInitialData, scope.hasScope, scope.datasetId, scope.directDocIds, scopeAutoLoaded, scopedDocumentIds])

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsLoading(true)
    setFileName(file.name)
    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const content = event.target?.result as string
        const parsedData = parseGraphML(content)
        setGraphData(parsedData)
        setDataSource('file')
        setTraceReplay(null)
        setKgStats(null)
        setKgNodeDetail(null)
        setIsDetailOpen(false)
        setSelectedNode(null)
        resetPathMode()
        resetConnectMode()
        resetExplainMode()
      } catch (error) {
        console.error('Failed to parse graph file:', error)
        toast.error('解析文件失败，请确保是有效的 GraphML 文件')
      } finally {
        setIsLoading(false)
      }
    }
    reader.readAsText(file)
    e.target.value = '' 
  }

  const triggerFileUpload = () => {
    fileInputRef.current?.click()
  }

  const isRagTraceValue = (value: unknown): value is RagTrace => {
    const record = asGraphRecord(value)
    return Boolean(record && typeof record.ts_ms === 'number' && Array.isArray(record.steps))
  }

  const _extractTraceFromPayload = (payload: unknown): RagTrace | null => {
    if (!payload) return null
    if (Array.isArray(payload)) {
      const first = payload[0]
      return isRagTraceValue(first) ? first : null
    }
    const payloadRecord = asGraphRecord(payload)
    if (!payloadRecord) return null

    // API response: { enabled, items: [...] }
    const responseItems = payloadRecord.items
    if (Array.isArray(responseItems)) {
      const first = responseItems[0]
      return isRagTraceValue(first) ? first : null
    }

    // Single item.
    if (isRagTraceValue(payloadRecord)) {
      return payloadRecord
    }

    return null
  }

  const _buildGraphFromTrace = (trace: RagTrace): { graph: GraphData; steps: { node: string; reason: string }[] } => {
    const rootId = `rag-trace:${trace.request_id || trace.ts_ms}`
    const nodes: GraphData['nodes'] = []
    const links: GraphData['links'] = []

    const hasRerank = Boolean(trace?.rerank?.enabled || trace?.rerank?.elapsed_sec != null)

    const idRetrieve = `${rootId}:retrieve`
    const idRerank = `${rootId}:rerank`
    const idCitations = `${rootId}:citations`

        nodes.push({ id: rootId, label: 'RAG Trace', kind: 'trace', val: 2.5, color: '#0ea5e9' }, { id: idRetrieve, label: 'Retrieve', kind: 'step', val: 2.0, color: '#2563eb' })
    if (hasRerank) nodes.push({ id: idRerank, label: 'Rerank', kind: 'step', val: 2.0, color: '#14b8a6' })
    nodes.push({ id: idCitations, label: 'Citations', kind: 'step', val: 2.0, color: '#f97316' })

    links.push({ source: rootId, target: idRetrieve, label: 'start' })
    if (hasRerank) {
            links.push({ source: idRetrieve, target: idRerank, label: 'rerank' }, { source: idRerank, target: idCitations, label: 'cite' })
    } else {
      links.push({ source: idRetrieve, target: idCitations, label: 'cite' })
    }

    const citations = (trace.citations || []).slice(0, 20)
    const citationNodeIds: string[] = []
    citations.forEach((c, idx) => {
      const doc = String(c.document_id || '').slice(0, 8) || 'doc'
      const page = c.page_number == null ? '' : `p${c.page_number}`
      const score = (c.rerank_score ?? c.retrieval_score ?? c.relevance_score)
      const scoreTxt = score == null ? '' : ` score=${Number(score).toFixed(3)}`
      const id = `${rootId}:c${idx}`
      citationNodeIds.push(id)
      nodes.push({
        id,
        label: `#${idx + 1} ${doc}${page ? ` · ${page}` : ''}${scoreTxt}`,
        kind: 'citation',
        val: 1.2,
        color: '#64748b',
        meta: c,
      })
    })

    if (citationNodeIds.length) {
      links.push({ source: idCitations, target: citationNodeIds[0], label: 'topk' })
      for (let i = 1; i < citationNodeIds.length; i++) {
        links.push({ source: citationNodeIds[i - 1], target: citationNodeIds[i], label: 'next' })
      }
    }

    const steps: { node: string; reason: string }[] = []
    steps.push({ node: idRetrieve, reason: `mode=${trace?.retrieval?.mode || '—'} · elapsed=${trace?.retrieval?.elapsed_sec ?? '—'}s` })
    if (hasRerank) {
      steps.push({ node: idRerank, reason: `provider=${trace?.rerank?.provider || '—'} · elapsed=${trace?.rerank?.elapsed_sec ?? '—'}s` })
    }
    steps.push({ node: idCitations, reason: `count=${trace.citations_count}` })
    citationNodeIds.forEach((id) => steps.push({ node: id, reason: 'retrieved citation' }))

    return { graph: { nodes, links }, steps }
  }

  const handleTraceFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsLoading(true)
    setFileName(file.name)
    try {
      const text = await file.text()
      const payload = JSON.parse(text)
      const trace = _extractTraceFromPayload(payload)
      if (!trace) {
        throw new Error('Invalid trace JSON')
      }

      const built = _buildGraphFromTrace(trace)
      setTraceReplay(trace)
      setGraphData(built.graph)
      setDataSource('file')
      setKgStats(null)
      setKgNodeDetail(null)
      setIsDetailOpen(false)
      setSelectedNode(null)
      resetPathMode()
      resetConnectMode()
      resetExplainMode()
      setViewMode('2d')
      toast.success('Trace 已导入（可点击右下角 Play 回放）')
    } catch (error) {
      console.error('Failed to import trace JSON:', error)
      setTraceReplay(null)
      toast.error('导入 Trace 失败：请检查 JSON 格式或粘贴/导出内容是否完整')
    } finally {
      setIsLoading(false)
      e.target.value = ''
    }
  }

  const triggerTraceUpload = () => {
    traceFileInputRef.current?.click()
  }

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

  const reloadEntityResolution = useCallback(
    async (entityId: string) => {
      try {
        setEntityAliasesLoading(true)
        const resp = await kgApi.listEntityAliases(entityId)
        setEntityAliases(resp.aliases || [])
      } catch {
        setEntityAliases([])
      } finally {
        setEntityAliasesLoading(false)
      }

      try {
        setAliasSuggestionsLoading(true)
        const resp = await kgApi.suggestEntityAliases(entityId, { mode: 'offline', k: 6, min_similarity: 0.75 })
        setAliasSuggestions(resp.suggestions || [])
      } catch {
        setAliasSuggestions([])
      } finally {
        setAliasSuggestionsLoading(false)
      }
    },
    []
  )

  const handleSaveAlias = useCallback(async () => {
    const entityId = selectedNode?.meta?.kind === 'entity' ? String(selectedNode?.id || '') : ''
    const alias = aliasDraft.trim()
    if (!entityId) return
    if (!alias) {
      toast.error('请输入 alias')
      return
    }

    setAliasSaving(true)
    try {
      await kgApi.createEntityAlias(entityId, { alias })
      setAliasDraft('')
      toast.success('已添加 alias')
      await reloadEntityResolution(entityId)
    } catch (error) {
      toast.error(formatApiError(error, '添加 alias 失败'))
    } finally {
      setAliasSaving(false)
    }
  }, [aliasDraft, reloadEntityResolution, selectedNode])

  const requestDeleteAlias = useCallback((row: KGEntityAliasItem) => {
    setAliasDeleteTarget(row)
    setAliasDeleteOpen(true)
  }, [])

  const confirmDeleteAlias = useCallback(async () => {
    const entityId = selectedNode?.meta?.kind === 'entity' ? String(selectedNode?.id || '') : ''
    const aliasId = aliasDeleteTarget?.id ? String(aliasDeleteTarget.id) : ''
    if (!entityId || !aliasId) {
      setAliasDeleteOpen(false)
      setAliasDeleteTarget(null)
      return
    }

    setAliasSaving(true)
    try {
      const resp = await kgApi.deleteEntityAlias(entityId, aliasId)
      setEntityAliases(resp.aliases || [])
      toast.success('已删除 alias')
      await reloadEntityResolution(entityId)
    } catch (error) {
      toast.error(formatApiError(error, '删除 alias 失败'))
    } finally {
      setAliasSaving(false)
      setAliasDeleteOpen(false)
      setAliasDeleteTarget(null)
    }
  }, [aliasDeleteTarget, reloadEntityResolution, selectedNode])

  // Merge UI helpers
  const openMergeDialog = useCallback(() => {
    setMergeOpen(true)
    setMergeSearch('')
    setMergeSearchResults([])
    setMergeTarget(null)
    setMergePreview(null)
    setMergeError(null)
  }, [])

  useEffect(() => {
    if (!mergeOpen) return
    const q = mergeSearch.trim()
    if (q.length < 2) {
      setMergeSearchResults([])
      return
    }

    let cancelled = false
    setMergeSearchLoading(true)
	    const t = globalThis.window.setTimeout(() => {
	      ;(async () => {
	        try {
	          const rows = await kgApi.searchGraphNodes({
	            q,
	            kind: 'entity',
	            limit: 8,
	            document_ids: scopeParams?.document_ids,
	            pipeline_hash: scopeParams?.pipeline_hash,
	          })
	          const currentId = selectedNode?.meta?.kind === 'entity' ? String(selectedNode?.id || '') : ''
	          const filtered = (rows || []).filter((r) => String(r.id) !== currentId)
	          if (!cancelled) setMergeSearchResults(filtered)
	        } catch {
	          if (!cancelled) setMergeSearchResults([])
        } finally {
          if (!cancelled) setMergeSearchLoading(false)
        }
      })()
    }, 250)

	    return () => {
	      cancelled = true
	      globalThis.window.clearTimeout(t)
	    }
	  }, [mergeOpen, mergeSearch, selectedNode, scopeParams])

  const selectMergeTarget = useCallback(
    async (node: KGGraphNode) => {
      const sourceId = selectedNode?.meta?.kind === 'entity' ? String(selectedNode?.id || '') : ''
      const targetId = String(node?.id || '')
      if (!sourceId || !targetId) return

      setMergeTarget(node)
      setMergePreview(null)
      setMergeError(null)
      setMergePreviewLoading(true)
      try {
        const preview = await kgApi.previewMergeEntities({ source_entity_id: sourceId, target_entity_id: targetId })
        setMergePreview(preview)
      } catch (error) {
        setMergeError(formatApiError(error, '无法预览合并影响'))
        setMergePreview(null)
      } finally {
        setMergePreviewLoading(false)
      }
    },
    [selectedNode]
  )

  const handleMergeAliasSuggestion = useCallback(
    (suggestion: KGEntityAliasSuggestionItem) => {
      openMergeDialog()
      detachPromise(
        selectMergeTarget({
          id: suggestion.entity_id,
          label: suggestion.name || suggestion.entity_id,
          meta: { kind: 'entity', type: suggestion.type },
        })
      )
    },
    [openMergeDialog, selectMergeTarget]
  )

  const submitMerge = useCallback(async () => {
    const sourceId = selectedNode?.meta?.kind === 'entity' ? String(selectedNode?.id || '') : ''
    const targetId = String(mergeTarget?.id || '')
    if (!sourceId || !targetId) return

    setMergeSubmitting(true)
    setMergeError(null)
    try {
      const out: KGEntityMergeResponse = await kgApi.mergeEntities({ source_entity_id: sourceId, target_entity_id: targetId })
      setLastResolutionActionId(String(out.action_id))
      toast.success('合并已完成（可撤销）')
      setMergeConfirmOpen(false)
      setMergeOpen(false)
      await loadInitialData('live')
      await reloadEntityResolution(sourceId)
    } catch (error) {
      setMergeError(formatApiError(error, '合并失败'))
    } finally {
      setMergeSubmitting(false)
    }
  }, [loadInitialData, mergeTarget, reloadEntityResolution, selectedNode])

  // Split UI helpers
  const openSplitDialog = useCallback(() => {
    setSplitOpen(true)
    setSplitNameDraft('')
    setSplitSelectedEventIds(new Set())
    setSplitError(null)
  }, [])

  const toggleSplitEvent = useCallback((eventId: string, checked: boolean) => {
    setSplitSelectedEventIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(eventId)
      else next.delete(eventId)
      return next
    })
  }, [])

  const submitSplit = useCallback(async () => {
    const entityId = selectedNode?.meta?.kind === 'entity' ? String(selectedNode?.id || '') : ''
    const name = splitNameDraft.trim()
    const eventIds = Array.from(splitSelectedEventIds)
    if (!entityId) return
    if (!name) {
      setSplitError('请输入新实体名称')
      return
    }
    if (!eventIds.length) {
      setSplitError('请选择要移动的事件（events）')
      return
    }

    setSplitSubmitting(true)
    setSplitError(null)
    try {
      const out: KGEntitySplitResponse = await kgApi.splitEntity({ entity_id: entityId, new_entity_name: name, event_ids: eventIds })
      setLastResolutionActionId(String(out.action_id))
      toast.success('拆分已完成（可撤销）')
      setSplitOpen(false)
      await loadInitialData('live')
      await reloadEntityResolution(entityId)
    } catch (error) {
      setSplitError(formatApiError(error, '拆分失败'))
    } finally {
      setSplitSubmitting(false)
    }
  }, [loadInitialData, reloadEntityResolution, selectedNode, splitNameDraft, splitSelectedEventIds])

  const undoLastResolution = useCallback(async () => {
    const actionId = (lastResolutionActionId || '').trim()
    if (!actionId) return
    setUndoSubmitting(true)
    try {
      const out: KGEntityResolutionUndoResponse = await kgApi.undoResolutionAction(actionId)
      toast.success(`已撤销：${String(out.status || 'ok')}`)
      setLastResolutionActionId(null)
      await loadInitialData('live')
    } catch (error) {
      toast.error(formatApiError(error, '撤销失败'))
    } finally {
      setUndoSubmitting(false)
    }
  }, [lastResolutionActionId, loadInitialData])

  // Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Search (Ctrl/Cmd + F)
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault()
        searchInputRef.current?.focus()
      }

      // Escape (Close panels, reset modes)
      if (e.key === 'Escape') {
        if (isDetailOpen) setIsDetailOpen(false)
        if (isLinkDetailOpen) { setIsLinkDetailOpen(false); setSelectedLink(null) }
        if (isPathMode) resetPathMode()
        if (isConnectMode) resetConnectMode()
        if (isExplainMode) resetExplainMode()
        closeContextMenu()
        searchInputRef.current?.blur()
      }

      // Space (Expand Node if selected)
      if (e.key === ' ' && selectedNode && isDetailOpen && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault()
        handleExpandNode()
      }

      // Delete (Delete Node if selected)
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedNode && isDetailOpen && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
          handleDeleteNode()
        }
      }
    }

    globalThis.window.addEventListener('keydown', handleKeyDown)
    return () => globalThis.window.removeEventListener('keydown', handleKeyDown)
  }, [
    selectedNode,
    isDetailOpen,
    isLinkDetailOpen,
    isPathMode,
    isConnectMode,
    isExplainMode,
    handleDeleteNode,
    handleExpandNode,
    resetPathMode,
    resetConnectMode,
    resetExplainMode,
    closeContextMenu,
  ])

  const startConnectMode = () => {
    if (!selectedNode) return
    setConnectSourceNode(selectedNode)
    setIsConnectMode(true)
    setIsDetailOpen(false)
    toast(`连线模式：请选择终点节点（起点：${selectedNode.label}）`)
  }

  const finishConnection = (targetNode: GraphNodeLike) => {
    if (!connectSourceNode) return
    if (connectSourceNode.id === targetNode.id) {
      toast.error('不能连接自己')
      return
    }

    setConnectTargetNode(targetNode)
    setConnectLabelDraft('related_to')
    setConnectLabelOpen(true)
  }

  const confirmConnectionLabel = () => {
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
  }

  // --- Explainability Logic ---
  const startExplainMode = () => {
    // Trace replay mode: when user imported a RAG trace JSON, prefer replaying the
    // real retrieve/rerank/citations path instead of a random walk.
    if (traceReplay) {
      const built = _buildGraphFromTrace(traceReplay)

      // Ensure 2D so highlight/focus works consistently.
      if (viewMode === '3d') {
        setViewMode('2d')
      }

      // If the current graph isn't a trace graph, swap it in (best-effort).
      const prefix = `rag-trace:${traceReplay.request_id || traceReplay.ts_ms}`
      const isTraceGraph = graphData.nodes.some((n) => String(n.id || '').startsWith(prefix))
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

      // Let the graph render once before running animation/focus.
      globalThis.window.requestAnimationFrame(() => {
        detachPromise(animateTrace(built.steps, built.graph))
      })
      return
    }

    if (displayGraphData.nodes.length < 3) {
      toast.warning('图谱节点过少，无法演示推理路径')
      return
    }

    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
    setCurrentStepIndex(-1)

    const trace: GraphNodeLike[] = []
    const visited = new Set()
    let current = displayGraphData.nodes[0]
    
    for (let i = 0; i < 4; i++) {
        trace.push(current)
        visited.add(current.id)
        
        const link = displayGraphData.links.find(l => {
            const s = getGraphLinkEndpointId(l.source)
            const t = getGraphLinkEndpointId(l.target)
            return (s === current.id && !visited.has(t)) || (t === current.id && !visited.has(s))
        })
        
        if (link) {
            const s = getGraphLinkEndpointId(link.source)
            const t = getGraphLinkEndpointId(link.target)
            const nextId = s === current.id ? t : s
            current = displayGraphData.nodes.find(n => n.id === nextId) || displayGraphData.nodes[i+1]
        } else {
            current = displayGraphData.nodes[Math.min(i + 5, displayGraphData.nodes.length - 1)]
        }
    }

    const steps = trace.map((node, i) => ({
        node: node.id,
        reason: (() => {
    if (i === 0) {
        return "初始查询匹配到的实体";
    }
    else if (i === trace.length - 1) {
            return "最终推理得出的答案";
        }
        else {
            return "通过关系链召回的相关节点";
        }
})()
    }))

    setExplainSteps(steps)
    setIsExplainMode(true)
    setIsDetailOpen(false)
    setSelectedNode(null)
    
    animateTrace(steps)
  }

  const animateTrace = async (steps: {node: string}[], graphOverride?: GraphData) => {
    const g = graphOverride || graphData
    for (let i = 0; i < steps.length; i++) {
        setCurrentStepIndex(i)
        const step = steps[i]
        
        setHighlightedNodeIds(prev => new Set([...Array.from(prev), step.node]))
        
        getActiveGraph()?.focusNode(step.node)

        if (i > 0) {
            const prevNode = steps[i-1].node
            const currNode = step.node
            const link = g.links.find(l => {
                const s = getGraphLinkEndpointId(l.source)
                const t = getGraphLinkEndpointId(l.target)
                return (s === prevNode && t === currNode) || (s === currNode && t === prevNode)
            })
            if (link) {
                const rawId = link.id
                const idx = g.links.indexOf(link)
                const linkIndex = link.index
                let linkId = rawId
                if (!linkId) {
                  if (linkIndex !== undefined) {
                    linkId = `link-${linkIndex}`
                  } else if (idx >= 0) {
                    linkId = `link-${idx}`
                  } else {
                    linkId = null
                  }
                }
                if (linkId) {
                    setHighlightedLinkIds(prev => new Set([...Array.from(prev), linkId]))
                }
            }
        }

        await new Promise(r => setTimeout(r, 1500))
    }
  }

  const handleNodeClick = (node: GraphNodeLike) => {
    if (isPathMode) {
      if (pathStartNode) { if (pathEndNode) {
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
      } } else {
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
  }

  const handleLinkClick = (link: GraphLinkLike) => {
    if (isPathMode || isConnectMode || isExplainMode) return
    setSelectedLink(link)
    setIsLinkDetailOpen(true)
    setIsDetailOpen(false)
    setSelectedNode(null)
  }

  const calculatePath = useCallback(
    (start: GraphNodeLike, end: GraphNodeLike) => {
      const result = findShortestPath(displayGraphData.nodes, linksWithIds, start.id, end.id)

      if (result) {
        setHighlightedNodeIds(new Set(result.nodeIds))
        setHighlightedLinkIds(new Set(result.linkIds))
        getActiveGraph()?.zoomToFit()
      } else {
        toast.info('未找到连接这两个节点的路径')
        setPathEndNode(null)
      }
    },
    [displayGraphData.nodes, linksWithIds, getActiveGraph]
  )

  const togglePathMode = () => {
    if (isPathMode) {
      resetPathMode()
    } else {
      setIsPathMode(true)
      setIsDetailOpen(false)
      setSelectedNode(null)
      setHighlightedNodeIds(new Set())
      resetConnectMode()
      resetExplainMode()
    }
  }

  const cycleLayoutMode = () => {
    setLayoutMode(current => {
      if (current === 'force') return 'tree'
      if (current === 'tree') return 'radial'
      return 'force'
    })
    setTimeout(() => {
       getActiveGraph()?.zoomToFit()
    }, 500)
  }

  const getLayoutLabel = () => {
    switch (layoutMode) {
      case 'force': return '力导向'
      case 'tree': return '树状'
      case 'radial': return '辐射'
    }
  }

  const toggleEntityLinks = () => {
    const next = !includeEntityLinks
    setIncludeEntityLinks(next)
    if (dataSource === 'live') {
      loadInitialData('live', { includeEntityLinks: next })
    }
  }

  const toggleRelationLinks = () => {
    const next = !includeRelationLinks
    setIncludeRelationLinks(next)
    if (dataSource === 'live') {
      loadInitialData('live', { includeRelationLinks: next })
    }
  }

  const cycleMinSharedEvents = () => {
    const options = [1, 2, 3, 4]
    const idx = options.indexOf(minSharedEvents)
    const next = options[(idx + 1) % options.length] || 2
    setMinSharedEvents(next)
    if (dataSource === 'live') {
      loadInitialData('live', { minSharedEvents: next })
    }
  }

  const resetGraphFilters = () => {
    setEntityTypeFilters([])
    setPredicateFilters([])
    setConfidenceBucketFilters([])
    setEntityTypeQuery('')
    setPredicateQuery('')
  }

  const toggleConfidenceBucket = (bucket: GraphConfBucket) => {
    setConfidenceBucketFilters((prev) => {
      const has = prev.includes(bucket)
      const next = has ? prev.filter((b) => b !== bucket) : [...prev, bucket]
      const unique = Array.from(new Set(next))
      // Selecting all buckets is equivalent to "Any" (no filter).
      if (unique.length >= 3) return []
      return unique
    })
  }

  const copyToClipboard = useCallback(async (text: string, label: string) => {
    const v = String(text || '').trim()
    if (!v) {
      toast.error('无可复制内容')
      return
    }
    try {
      if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
        throw new Error('Clipboard API unavailable')
      }
      await navigator.clipboard.writeText(v)
      toast.success(`已复制 ${label}`)
    } catch (err) {
      console.error('clipboard.writeText failed:', err)
      toast.error('复制失败（浏览器权限限制）')
    }
  }, [])

  const chatWithNode = useCallback(
    (node?: GraphNodeLike) => {
      const target = node ?? selectedNode
      const label = String(target?.label || '').trim()
      if (!label) return
      const prompt = `请告诉我关于 ${label} 的信息`
      router.push(`/?prompt=${encodeURIComponent(prompt)}`)
    },
    [router, selectedNode]
  )

  const viewSourceForNode = useCallback(
    (node?: GraphNodeLike) => {
      const target = node ?? selectedNode
      const docId = target?.meta?.document_id || target?.source
      if (docId) {
        toast(`源文档：${docId}`)
        return
      }
      toast('未找到源文档信息')
    },
    [selectedNode]
  )

  const exportBaseName = useMemo(() => {
    const base =
      stripFilenameExtension(fileName || '') ||
      (scope.datasetId ? `dataset-${scope.datasetId}` : '') ||
      'mimirq-kg'
    return sanitizeFilename(`${base}-${viewMode}`)
  }, [fileName, scope.datasetId, viewMode])

  const exportGraph = useCallback(
    async (format: 'png' | 'svg', mode: 'download' | 'copy') => {
      const api = getActiveGraph()
      if (!api) {
        toast.error('图谱尚未就绪')
        return
      }

      if (format === 'png') {
        const dataUrl = api.exportPngDataUrl?.()
        if (!dataUrl) {
          toast.error('导出 PNG 失败')
          return
        }
        if (mode === 'copy') {
          await copyToClipboard(dataUrl, 'PNG DataURL')
          return
        }
        const a = document.createElement('a')
        a.href = dataUrl
        a.download = `${exportBaseName}.png`
        a.click()
        toast.success('已导出 PNG')
        return
      }

      const svg = api.exportSvgString?.()
      if (!svg) {
        toast.error('导出 SVG 失败')
        return
      }
      if (mode === 'copy') {
        await copyToClipboard(svg, 'SVG')
        return
      }

      const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${exportBaseName}.svg`
      a.click()
      globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      toast.success('已导出 SVG')
    },
    [copyToClipboard, exportBaseName, getActiveGraph]
  )

  const handleExportGraphML = async () => {
    if (dataSource !== 'live') {
      toast.info('仅支持导出后端 KG 实时图谱')
      return
    }

    setIsLoading(true)
    try {
      const xml = await kgApi.exportGraphML({
        document_ids: scopeParams?.document_ids,
        pipeline_hash: scopeParams?.pipeline_hash,
        include_entity_links: includeEntityLinks,
        include_relation_links: includeRelationLinks,
        min_shared_events: minSharedEvents,
        max_entity_links: maxEntityLinks,
      })
      const blob = new Blob([xml], { type: 'application/graphml+xml;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'mimirq-kg.graphml'
      a.click()
      URL.revokeObjectURL(url)
      toast.success('已导出 GraphML')
    } catch (error) {
      console.error('Export GraphML failed:', error)
      toast.error('导出 GraphML 失败')
    } finally {
      setIsLoading(false)
    }
  }

  const handleChatWithNode = () => {
    chatWithNode()
  }

  const handleViewSource = () => {
    viewSourceForNode()
  }

  const handleDeleteNodeOpenChange = useCallback((open: boolean) => {
    setDeleteNodeOpen(open)
    if (!open) setDeleteNodeTarget(null)
  }, [])

  const handleAliasDeleteOpenChange = useCallback((open: boolean) => {
    setAliasDeleteOpen(open)
    if (!open) setAliasDeleteTarget(null)
  }, [])

  const handleMergeOpenChange = useCallback((open: boolean) => {
    setMergeOpen(open)
    if (!open) {
      setMergeSearch('')
      setMergeSearchResults([])
      setMergeTarget(null)
      setMergePreview(null)
      setMergeError(null)
      setMergeConfirmOpen(false)
    }
  }, [])

  const handleSplitOpenChange = useCallback((open: boolean) => {
    setSplitOpen(open)
    if (!open) {
      setSplitNameDraft('')
      setSplitSelectedEventIds(new Set())
      setSplitError(null)
    }
  }, [])

  const handleConnectLabelOpenChange = useCallback((open: boolean) => {
    setConnectLabelOpen(open)
    if (!open) {
      setConnectTargetNode(null)
      resetConnectMode()
    }
  }, [resetConnectMode])

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
         {/* Header */}
         <header className="absolute top-0 left-0 right-0 z-20 h-16 px-6 flex items-center justify-between bg-card border-b border-border/50 pointer-events-none">
	          <div className="flex items-center gap-3 pointer-events-auto">
		            <div className="p-2 rounded-lg bg-primary text-primary-foreground shadow-sm border border-primary/20">
		              <Share2 className="w-5 h-5" />
		            </div>
	            <div>
	              <h1 className="text-3xl font-bold text-foreground ">知识图谱</h1>
	            </div>
	          </div>
          
          {/* Centered Search Bar */}
          {displayGraphData.nodes.length > 0 && !isPathMode && !isConnectMode && !isExplainMode && (
            <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 w-full max-w-md">
              <div className="relative">
                <SearchInput
                  ref={searchInputRef}
                  value={searchTerm}
                  onValueChange={setSearchTerm}
                  placeholder="搜索实体节点..."
                  aria-label="搜索实体节点"
                  inputClassName="h-10 rounded-full bg-muted/60 shadow-sm pr-16"
                />
                <div className="pointer-events-none absolute right-11 top-1/2 -translate-y-1/2 flex items-center gap-2 text-xs text-muted-foreground">
                  {searchTerm ? <span>{highlightedNodeIds.size} 匹配</span> : null}
                  <span className="flex items-center gap-1">
                    <Kbd className="h-5 px-1.5">Ctrl</Kbd>
                    <Kbd className="h-5 px-1.5">F</Kbd>
                  </span>
                </div>
              </div>
            </div>
          )}

	          {/* Status Banners */}
	           {isPathMode && (
	              <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-full shadow-lg animate-in fade-in slide-in-from-top-4 motion-reduce:animate-none">
	                 <Route className="w-4 h-4" />
	                 <span className="text-sm font-medium">
	                   {(() => {
    if (pathStartNode) {
        if (pathEndNode) {
            return "路径分析完成";
        }
        else {
            return "请点击选择【终点】";
        }
    }
    else {
        return "请点击选择【起点】";
    }
})()}
	                 </span>
	                 <IconButton
	                   label="退出路径分析"
	                   onClick={resetPathMode}
	                   className="ml-2 h-7 w-7 rounded-full text-primary-foreground/80 hover:text-primary-foreground hover:bg-primary-foreground/10"
	                 >
	                   <X className="w-4 h-4" />
	                 </IconButton>
	              </div>
	           )}
	            {isConnectMode && (
	              <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 flex items-center gap-2 px-4 py-2 bg-success text-success-foreground rounded-full shadow-lg animate-in fade-in slide-in-from-top-4 motion-reduce:animate-none">
	                 <LinkIcon className="w-4 h-4" />
	                 <span className="text-sm font-medium">
	                    正在连接: {connectSourceNode?.label} ... 请点击目标节点
	                 </span>
	                 <IconButton
	                   label="退出连接模式"
	                   onClick={resetConnectMode}
	                   className="ml-2 h-7 w-7 rounded-full text-success-foreground/80 hover:text-success-foreground hover:bg-success-foreground/10"
	                 >
	                   <X className="w-4 h-4" />
	                 </IconButton>
	              </div>
	           )}
	           {isExplainMode && (
	              <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 flex items-center gap-2 px-4 py-2 bg-info text-info-foreground rounded-full shadow-lg animate-in fade-in slide-in-from-top-4 motion-reduce:animate-none">
	                 <Lightbulb className="w-4 h-4" />
	                 <span className="text-sm font-medium">
	                    推理路径演示中... ({currentStepIndex + 1}/{explainSteps.length})
	                 </span>
	                 <IconButton
	                   label="退出推理演示"
	                   onClick={resetExplainMode}
	                   className="ml-2 h-7 w-7 rounded-full text-info-foreground/80 hover:text-info-foreground hover:bg-info-foreground/10"
	                 >
	                   <X className="w-4 h-4" />
	                 </IconButton>
	              </div>
	           )}

           <div className="flex items-center gap-3 pointer-events-auto">
              {fileName && (
               <div className="hidden md:flex items-center gap-2 px-3 py-1.5 bg-muted/50 border border-border rounded-full text-xs text-muted-foreground font-medium">
                 <FileCode className="w-3.5 h-3.5 text-muted-foreground" />
                 <span className="truncate max-w-[150px]">{fileName}</span>
               </div>
              )}

              {dataSource === 'live' && kgStats && (
                <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 bg-muted/50 border border-border rounded-full text-xs text-muted-foreground font-medium">
                  <BarChart3 className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="font-mono">
                    E:{kgStats.events} N:{kgStats.entities} L:{kgStats.links}
                  </span>
                </div>
              )}

              {dataSource === 'live' && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={toggleEntityLinks}
                    className={cn(
                      "text-muted-foreground hover:text-sky-600 dark:hover:text-sky-300 hover:bg-sky-500/10 dark:hover:bg-sky-500/20",
                      includeEntityLinks && "bg-sky-500/10 dark:bg-sky-500/20 text-sky-600 dark:text-sky-300"
                    )}
                    title="实体-实体共现连线"
                  >
                    <LinkIcon className="w-4 h-4 mr-2" />
                    {includeEntityLinks ? '实体连线: ON' : '实体连线: OFF'}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={toggleRelationLinks}
                    className={cn(
                      "text-muted-foreground hover:text-teal-600 dark:hover:text-teal-300 hover:bg-teal-500/10 dark:hover:bg-teal-500/20",
                      includeRelationLinks && "bg-teal-500/10 dark:bg-teal-500/20 text-teal-600 dark:text-teal-300"
                    )}
                    title="实体-实体关系连线（来自 KG triples / kg_relations）"
                  >
                    <Network className="w-4 h-4 mr-2" />
                    {includeRelationLinks ? '关系连线: ON' : '关系连线: OFF'}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={cycleMinSharedEvents}
                    className="text-muted-foreground hover:text-sky-600 dark:hover:text-sky-300 hover:bg-sky-500/10 dark:hover:bg-sky-500/20"
                    title="最小共现事件数（点击循环）"
                  >
                    <Filter className="w-4 h-4 mr-2" />
                    Co≥{minSharedEvents}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleExportGraphML}
                    disabled={isLoading}
                    className="text-muted-foreground hover:text-sky-600 dark:hover:text-sky-300 hover:bg-sky-500/10 dark:hover:bg-sky-500/20"
                    title="导出 GraphML"
                  >
                    <FileCode className="w-4 h-4 mr-2" />
                    导出
                  </Button>
                </>
              )}

              {(graphData.nodes.length > 0 || activeGraphFilterCount > 0) && (
                <Popover open={filtersOpen} onOpenChange={setFiltersOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      className={cn(
                        "text-muted-foreground hover:text-foreground hover:bg-muted/60",
                        activeGraphFilterCount > 0 && "bg-primary/10 text-primary hover:text-primary"
                      )}
                      title="图谱筛选：predicate / entity type / confidence bucket"
                    >
                      <SlidersHorizontal className="w-4 h-4 mr-2" />
                      筛选
                      {activeGraphFilterCount > 0 ? (
                        <Badge variant="soft" className="ml-2 px-2 py-0.5 text-[10px]">
                          {activeGraphFilterCount}
                        </Badge>
                      ) : null}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="end" className="w-[420px] p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <SlidersHorizontal className="w-4 h-4 text-muted-foreground" />
                          <div className="text-sm font-semibold text-foreground">图谱筛选</div>
                          <div className="text-[11px] text-muted-foreground font-mono">
                            {displayGraphData.nodes.length}N / {displayGraphData.links.length}L
                          </div>
                        </div>
                        <div className="mt-1 text-[11px] text-muted-foreground">
                          Predicate 仅对关系边生效；Type 仅对实体节点生效。
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs"
                          onClick={resetGraphFilters}
                          disabled={activeGraphFilterCount === 0 && !entityTypeQuery && !predicateQuery}
                        >
                          清除
                        </Button>
                      </div>
                    </div>

                    <div className="mt-4 space-y-5">
                      <div>
                        <div className="flex items-center justify-between">
                          <div className="text-[11px] font-semibold text-muted-foreground uppercase">Entity Type</div>
                          {entityTypeFilters.length === 0 ? (
                            <span className="text-[11px] text-muted-foreground">Any</span>
                          ) : (
                            <button
                              type="button"
                              className="text-[11px] text-primary hover:underline"
                              onClick={() => setEntityTypeFilters([])}
                            >
                              Any
                            </button>
                          )}
                        </div>
                        <Input
                          value={entityTypeQuery}
                          onChange={(e) => setEntityTypeQuery(e.target.value)}
                          placeholder="Search types…"
                          className="mt-2 h-8 text-xs"
                        />
                        <div className="mt-2 max-h-36 overflow-y-auto overscroll-contain no-scrollbar pr-1 space-y-1">
                          {filteredEntityTypes.length === 0 ? (
                            <div className="text-xs text-muted-foreground">No entity types found</div>
                          ) : (
                            filteredEntityTypes.map((t) => {
                              const checked = entityTypeFilters.includes(t.value)
                              return (
                                <label
                                  key={t.value}
                                  className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-muted/60"
                                >
                                  <Checkbox
                                    checked={checked}
                                    onCheckedChange={(next) => {
                                      const isChecked = !!next
                                      setEntityTypeFilters((prev) => {
                                        const set = new Set(prev)
                                        if (isChecked) set.add(t.value)
                                        else set.delete(t.value)
                                        return Array.from(set)
                                      })
                                    }}
                                  />
                                  <span className="flex-1 min-w-0 text-xs text-foreground truncate">{t.value}</span>
                                  <span className="text-[11px] text-muted-foreground font-mono">{t.count}</span>
                                </label>
                              )
                            })
                          )}
                        </div>
                      </div>

                      <div>
                        <div className="flex items-center justify-between">
                          <div className="text-[11px] font-semibold text-muted-foreground uppercase">Predicate</div>
                          {predicateFilters.length === 0 ? (
                            <span className="text-[11px] text-muted-foreground">Any</span>
                          ) : (
                            <button
                              type="button"
                              className="text-[11px] text-primary hover:underline"
                              onClick={() => setPredicateFilters([])}
                            >
                              Any
                            </button>
                          )}
                        </div>
                        <Input
                          value={predicateQuery}
                          onChange={(e) => setPredicateQuery(e.target.value)}
                          placeholder="Search predicates…"
                          className="mt-2 h-8 text-xs"
                        />
                        <div className="mt-2 max-h-36 overflow-y-auto overscroll-contain no-scrollbar pr-1 space-y-1">
                          {filteredPredicates.length === 0 ? (
                            <div className="text-xs text-muted-foreground">No predicates found</div>
                          ) : (
                            filteredPredicates.map((p) => {
                              const checked = predicateFilters.includes(p.value)
                              return (
                                <label
                                  key={p.value}
                                  className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-muted/60"
                                >
                                  <Checkbox
                                    checked={checked}
                                    onCheckedChange={(next) => {
                                      const isChecked = !!next
                                      setPredicateFilters((prev) => {
                                        const set = new Set(prev)
                                        if (isChecked) set.add(p.value)
                                        else set.delete(p.value)
                                        return Array.from(set)
                                      })
                                    }}
                                  />
                                  <span className="flex-1 min-w-0 text-xs text-foreground truncate">{p.value}</span>
                                  <span className="text-[11px] text-muted-foreground font-mono">{p.count}</span>
                                </label>
                              )
                            })
                          )}
                        </div>
                      </div>

                      <div>
                        <div className="flex items-center justify-between">
                          <div className="text-[11px] font-semibold text-muted-foreground uppercase">Confidence</div>
                          {confidenceBucketFilters.length === 0 ? (
                            <span className="text-[11px] text-muted-foreground">Any</span>
                          ) : (
                            <button
                              type="button"
                              className="text-[11px] text-primary hover:underline"
                              onClick={() => setConfidenceBucketFilters([])}
                            >
                              Any
                            </button>
                          )}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant={confidenceBucketFilters.length === 0 ? 'info' : 'outline'}
                            className="h-7 px-2 text-xs"
                            onClick={() => setConfidenceBucketFilters([])}
                          >
                            Any
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant={confidenceBucketFilters.includes('high') ? 'info' : 'outline'}
                            className="h-7 px-2 text-xs"
                            onClick={() => toggleConfidenceBucket('high')}
                          >
                            High (≥0.8)
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant={confidenceBucketFilters.includes('medium') ? 'info' : 'outline'}
                            className="h-7 px-2 text-xs"
                            onClick={() => toggleConfidenceBucket('medium')}
                          >
                            Mid (0.5-0.8)
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant={confidenceBucketFilters.includes('low') ? 'info' : 'outline'}
                            className="h-7 px-2 text-xs"
                            onClick={() => toggleConfidenceBucket('low')}
                          >
                            Low (&lt;0.5)
                          </Button>
                        </div>
                      </div>
                    </div>
                  </PopoverContent>
                </Popover>
              )}
 
             <div className="h-6 w-px bg-muted mx-1 hidden sm:block"></div>
 
	             <Button variant="ghost" size="sm" onClick={() => loadInitialData('live')} disabled={isLoading} className="text-muted-foreground hover:text-sky-600 dark:hover:text-sky-300 hover:bg-sky-500/10 dark:hover:bg-sky-500/20">
	               <RefreshCw className={cn("w-4 h-4 mr-2", isLoading && "animate-spin motion-reduce:animate-none")} />
	              {isLoading ? '加载中...' : '刷新'}
	            </Button>

            <Button
              variant="ghost"
              size="sm"
              onClick={triggerTraceUpload}
              className="text-muted-foreground hover:text-teal-600 dark:hover:text-teal-300 hover:bg-teal-500/10 dark:hover:bg-teal-500/20"
              title="导入 RAG trace JSON（回放检索路径）"
            >
              <FileText className="w-4 h-4 mr-2" />
              Trace
            </Button>
            <input
              ref={traceFileInputRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={handleTraceFileUpload}
            />

	            <Button 
	              variant="info"
	              size="sm" 
	              className="gap-2"
	              onClick={triggerFileUpload}
	            >
              <Upload className="w-4 h-4" />
              导入
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".graphml,.xml"
              className="hidden"
              onChange={handleFileUpload}
            />
          </div>
        </header>

        {/* Graph Area */}
        <div ref={graphViewportRef} className="flex-1 w-full relative bg-background overflow-hidden min-h-[500px]">
          {/* Dot Pattern Background */}
          <div className="absolute inset-0 z-0 opacity-[0.4]" style={{
             backgroundImage: isDark
               ? 'radial-gradient(rgba(148, 163, 184, 0.16) 1px, transparent 1px)'
               : 'radial-gradient(rgba(203, 213, 225, 0.9) 1px, transparent 1px)',
             backgroundSize: '24px 24px'
          }}></div>

          { }
          {graphRenderData.nodes.length > 0 ? (
            viewMode === '3d' ? (
              graphViewportWidth > 0 && graphViewportHeight > 0 ? (
                <KnowledgeGraph3D
                  ref={graph3dRef}
                  data={graphRenderData}
                  width={graphViewportWidth}
                  height={graphViewportHeight}
                  onNodeClick={handleNodeClick}
                  onNodeRightClick={handleNodeRightClick}
                  onLinkClick={handleLinkClick}
                  onLinkRightClick={handleLinkRightClick}
                  onBackgroundClick={handleBackgroundClick}
                  onBackgroundRightClick={handleBackgroundRightClick}
                  highlightedNodeIds={highlightedNodeIds}
                  highlightedLinkIds={highlightedLinkIds}
                  selectedNodeId={selectedNode?.id ?? null}
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
                data={graphRenderData} 
                onNodeClick={handleNodeClick}
                onNodeRightClick={handleNodeRightClick}
                onLinkClick={handleLinkClick}
                onLinkRightClick={handleLinkRightClick}
                onBackgroundClick={handleBackgroundClick}
                onBackgroundRightClick={handleBackgroundRightClick}
                highlightedNodeIds={highlightedNodeIds}
                highlightedLinkIds={highlightedLinkIds}
                selectedNodeId={selectedNode?.id ?? null}
                showEdgeLabels={showEdgeLabels}
                layoutMode={layoutMode}
                />
            )
           ) : (
             <div className="absolute inset-0 z-10 flex items-center justify-center p-6">
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
                   onClick={() => loadInitialData('mock')}
                   disabled={isLoading}
                   className="border-border hover:bg-muted hover:text-foreground"
                 >
                   {isLoading ? '加载中...' : '加载示例数据'}
                 </Button>
	               <Button
	                 size="lg"
	                 className="bg-primary text-primary-foreground hover:bg-primary/90 shadow-soft"
	                 onClick={triggerFileUpload}
	               >
	                 <Upload className="w-5 h-5" />
	                 开始上传
	               </Button>
               </EmptyState>
             </div>
           )}

          {contextMenu && (
            <div
              className="absolute z-30"
              style={{ left: contextMenu.x, top: contextMenu.y }}
              onMouseDown={(e) => e.stopPropagation()}
              onContextMenu={(e) => e.preventDefault()}
            >
              <div className="w-64 rounded-xl border border-border/60 bg-card/95 backdrop-blur-sm shadow-strong overflow-hidden">
                {contextMenu.target.type === 'node' ? (
                  (() => {
                    const node = contextMenu.target.node
                    return (
                      <div>
                        <div className="px-3 py-2 border-b border-border/60 bg-muted/30">
                          <div className="text-[10px] font-medium text-muted-foreground uppercase">Node</div>
                          <div className="text-sm font-semibold text-foreground truncate">
                            {String(node?.label || node?.id || 'Node')}
                          </div>
                          <div className="text-[10px] font-mono text-muted-foreground truncate">
                            {String(node?.id || '')}
                          </div>
                        </div>
                        <div className="p-1">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="w-full justify-start h-8"
                            onClick={() => {
                              closeContextMenu()
                              detachPromise(expandNodeById(String(node?.id || '')))
                            }}
                          >
                            <Layers className="w-4 h-4 mr-2" />
                            展开邻居
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="w-full justify-start h-8"
                            onClick={() => {
                              closeContextMenu()
                              resetConnectMode()
                              resetExplainMode()
                              setIsPathMode(true)
                              setPathStartNode(node)
                              setPathEndNode(null)
                              setHighlightedNodeIds(new Set())
                              setHighlightedLinkIds(new Set())
                              toast(`路径模式：请选择终点节点（起点：${String(node?.label || node?.id || '')}）`)
                            }}
                          >
                            <Route className="w-4 h-4 mr-2" />
                            查找路径
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="w-full justify-start h-8"
                            onClick={() => {
                              closeContextMenu()
                              resetPathMode()
                              resetExplainMode()
                              setConnectSourceNode(node)
                              setIsConnectMode(true)
                              toast(`连线模式：请选择终点节点（起点：${String(node?.label || node?.id || '')}）`)
                            }}
                          >
                            <LinkIcon className="w-4 h-4 mr-2" />
                            连线
                          </Button>
                          <div className="my-1 h-px bg-border/60" />
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="w-full justify-start h-8"
                            onClick={() => {
                              closeContextMenu()
                              chatWithNode(node)
                            }}
                          >
                            <MessageSquare className="w-4 h-4 mr-2" />
                            对话
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="w-full justify-start h-8"
                            onClick={() => {
                              closeContextMenu()
                              viewSourceForNode(node)
                            }}
                          >
                            <FileText className="w-4 h-4 mr-2" />
                            来源
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="w-full justify-start h-8"
                            onClick={() => {
                              closeContextMenu()
                              detachPromise(copyToClipboard(String(node?.id || ''), '节点 ID'))
                            }}
                          >
                            <Copy className="w-4 h-4 mr-2" />
                            复制 ID
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="w-full justify-start h-8 text-red-600 hover:text-red-700 dark:text-red-300 dark:hover:text-red-200"
                            onClick={() => {
                              closeContextMenu()
                              handleDeleteNode(node)
                            }}
                          >
                            <Trash2 className="w-4 h-4 mr-2" />
                            删除
                          </Button>
                        </div>
                      </div>
                    )
                  })()
                ) : contextMenu.target.type === 'link' ? (
                  (() => {
                    const link = contextMenu.target.link
                    return (
                      <div>
                        <div className="px-3 py-2 border-b border-border/60 bg-muted/30">
                          <div className="text-[10px] font-medium text-muted-foreground uppercase">Link</div>
                          <div className="text-sm font-semibold text-foreground truncate">
                            {getGraphLinkPredicate(link) || 'Relationship'}
                          </div>
                          <div className="text-[10px] font-mono text-muted-foreground truncate">
                            {String(link?.id || link?.meta?.id || '')}
                          </div>
                        </div>
                        <div className="p-1">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="w-full justify-start h-8"
                            onClick={() => {
                              closeContextMenu()
                              setSelectedLink(link)
                              setIsLinkDetailOpen(true)
                              setIsDetailOpen(false)
                              setSelectedNode(null)
                            }}
                          >
                            <Info className="w-4 h-4 mr-2" />
                            查看详情
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="w-full justify-start h-8"
                            onClick={() => {
                              closeContextMenu()
                              detachPromise(copyToClipboard(getGraphLinkPredicate(link) || '', 'Predicate'))
                            }}
                          >
                            <Copy className="w-4 h-4 mr-2" />
                            复制 Predicate
                          </Button>
                        </div>
                      </div>
                    )
                  })()
                ) : (
                  <div>
                    <div className="px-3 py-2 border-b border-border/60 bg-muted/30">
                      <div className="text-[10px] font-medium text-muted-foreground uppercase">Graph</div>
                      <div className="text-sm font-semibold text-foreground truncate">
                        {viewMode === '3d' ? '3D View' : '2D View'}
                      </div>
                    </div>
                    <div className="p-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="w-full justify-start h-8"
                        onClick={() => {
                          closeContextMenu()
                          getActiveGraph()?.zoomToFit()
                        }}
                      >
                        <Maximize className="w-4 h-4 mr-2" />
                        适应屏幕
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="w-full justify-start h-8"
                        onClick={() => {
                          closeContextMenu()
                          setHighlightedNodeIds(new Set())
                          setHighlightedLinkIds(new Set())
                          setPathStartNode(null)
                          setPathEndNode(null)
                        }}
                      >
                        <X className="w-4 h-4 mr-2" />
                        清除高亮
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="w-full justify-start h-8"
                        onClick={() => {
                          closeContextMenu()
                          setShowEdgeLabels((v) => !v)
                        }}
                      >
                        <Type className="w-4 h-4 mr-2" />
                        {showEdgeLabels ? '隐藏连线标签' : '显示连线标签'}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Entity Type Legend (Bottom Left) */}
          {graphRenderData.nodes.length > 0 && !isExplainMode && (
            <GraphLegend
              nodes={graphRenderData.nodes}
              links={graphRenderData.links}
              activeTypeFilters={entityTypeFilters}
              onToggleTypeFilter={(type) => {
                setEntityTypeFilters((prev) => {
                  const set = new Set(prev)
                  if (set.has(type)) set.delete(type)
                  else set.add(type)
                  return Array.from(set)
                })
              }}
            />
          )}

          {/* Explainability Panel (Bottom Left) */}
          <GraphExplainabilityPanel
            open={isExplainMode}
            explainSteps={explainSteps}
            currentStepIndex={currentStepIndex}
            nodes={displayGraphData.nodes}
          />

          {/* Graph Stats Bar */}
          {dataSource === 'live' && typeof scopedDatasetPendingDocs === 'number' && scopedDatasetPendingDocs > 0 && (
            <div className="absolute bottom-20 left-1/2 -translate-x-1/2 z-20">
              <div className="flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1.5 shadow-sm animate-pulse motion-reduce:animate-none">
                <span className="text-[11px] font-medium text-primary">KG 构建中</span>
                <span className="text-[10px] text-muted-foreground">待处理文档</span>
                <span className="text-[10px] font-mono text-foreground">{scopedDatasetPendingDocs}</span>
              </div>
            </div>
          )}
          {graphRenderData.nodes.length > 0 && (
            <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10">
              <GraphStatsBar
                nodeCount={graphRenderData.nodes.length}
                linkCount={graphRenderData.links.length}
                entityTypeCount={availableEntityTypes.length}
              />
            </div>
          )}

          {/* Floating Controls */}
          <GraphFloatingControls
            viewMode={viewMode}
            isExplainMode={isExplainMode}
            isPathMode={isPathMode}
            showEdgeLabels={showEdgeLabels}
            isFullscreen={isFullscreen}
            exportOpen={exportOpen}
            layoutLabel={getLayoutLabel()}
            onZoomIn={() => getActiveGraph()?.zoomIn()}
            onZoomOut={() => getActiveGraph()?.zoomOut()}
            onZoomToFit={() => getActiveGraph()?.zoomToFit()}
            onToggleViewMode={() => setViewMode(viewMode === '3d' ? '2d' : '3d')}
            onStartExplainMode={startExplainMode}
            onCycleLayoutMode={cycleLayoutMode}
            onTogglePathMode={togglePathMode}
            onToggleShowEdgeLabels={() => setShowEdgeLabels((value) => !value)}
            onToggleFullscreen={() => {
              detachPromise(toggleFullscreen())
            }}
            onExportOpenChange={setExportOpen}
            onExportPngDownload={() => {
              setExportOpen(false)
              detachPromise(exportGraph('png', 'download'))
            }}
            onExportSvgDownload={() => {
              setExportOpen(false)
              detachPromise(exportGraph('svg', 'download'))
            }}
            onExportPngCopy={() => {
              setExportOpen(false)
              detachPromise(exportGraph('png', 'copy'))
            }}
            onExportSvgCopy={() => {
              setExportOpen(false)
              detachPromise(exportGraph('svg', 'copy'))
            }}
          />

          <GraphNodeDetailPanel
            open={isDetailOpen}
            selectedNode={selectedNode}
            detailScrollRef={detailScrollRef}
            dataSource={dataSource}
            kgNodeDetailLoading={kgNodeDetailLoading}
            kgNodeDetail={kgNodeDetail}
            entityAliasesLoading={entityAliasesLoading}
            entityAliases={entityAliases}
            aliasDraft={aliasDraft}
            aliasSaving={aliasSaving}
            aliasSuggestionsLoading={aliasSuggestionsLoading}
            aliasSuggestions={aliasSuggestions}
            lastResolutionActionId={lastResolutionActionId}
            undoSubmitting={undoSubmitting}
            isLoading={isLoading}
            onClose={() => setIsDetailOpen(false)}
            onChat={handleChatWithNode}
            onViewSource={handleViewSource}
            onExpandNode={handleExpandNode}
            onStartConnectMode={startConnectMode}
            onDeleteNode={() => handleDeleteNode()}
            onOpenMerge={openMergeDialog}
            onOpenSplit={openSplitDialog}
            onUndoLastResolution={undoLastResolution}
            onAliasDraftChange={setAliasDraft}
            onSaveAlias={handleSaveAlias}
            onRequestDeleteAlias={requestDeleteAlias}
            onMergeAliasSuggestion={handleMergeAliasSuggestion}
          />

          <GraphLinkDetailPanel
            open={isLinkDetailOpen}
            selectedLink={selectedLink}
            graphLinks={linksWithIds}
            selfLoopGroupExpanded={selfLoopGroupExpanded}
            onToggleSelfLoopGroup={() => setSelfLoopGroupExpanded((prev) => !prev)}
            onClose={() => {
              setIsLinkDetailOpen(false)
              setSelectedLink(null)
            }}
          />
        </div>

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
