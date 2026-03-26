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
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Share2, Database, Route } from 'lucide-react'
import { GraphActionDialogs } from './_components/graph-action-dialogs'
import { GraphPageBody } from './_components/graph-page-body'
import { GraphPageHeader } from './_components/graph-page-header'
import { GraphViewerRef, LayoutMode } from '@/components/graph/graph-viewer'
import { type KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { GraphData } from '@/lib/graph-parser'
import { GraphService } from '@/lib/graph-service'
import { findShortestPath } from '@/lib/graph-algorithms'
import { cn, detachPromise } from '@/lib/utils'
import { documentApi } from '@/lib/api/documents'
import { kgApi } from '@/lib/api/graph'
import { useGraphDataLoading } from './use-graph-data-loading'
import { useGraphEntityResolution } from './use-graph-entity-resolution'
import {
  GraphConfBucket,
  GraphContextMenuTarget,
  GraphContextMenuState,
  type GraphDatasetDocumentSummary,
  type GraphLinkLike,
  type GraphNodeLike,
  buildGraphFromTrace,
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
  KGEntityDetailResponse,
  KGEventDetailResponse,
  KGStatsResponse,
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
      const built = buildGraphFromTrace(traceReplay)

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

  const handleEntityTypeCheckedChange = useCallback((value: string, checked: boolean) => {
    setEntityTypeFilters((prev) => {
      const next = new Set(prev)
      if (checked) next.add(value)
      else next.delete(value)
      return Array.from(next)
    })
  }, [])

  const handlePredicateCheckedChange = useCallback((value: string, checked: boolean) => {
    setPredicateFilters((prev) => {
      const next = new Set(prev)
      if (checked) next.add(value)
      else next.delete(value)
      return Array.from(next)
    })
  }, [])

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

  const handleStartPathFromContextNode = useCallback(
    (node: GraphNodeLike) => {
      resetConnectMode()
      resetExplainMode()
      setIsPathMode(true)
      setPathStartNode(node)
      setPathEndNode(null)
      setHighlightedNodeIds(new Set())
      setHighlightedLinkIds(new Set())
      toast(`路径模式：请选择终点节点（起点：${String(node?.label || node?.id || '')}）`)
    },
    [resetConnectMode, resetExplainMode]
  )

  const handleStartConnectFromContextNode = useCallback(
    (node: GraphNodeLike) => {
      resetPathMode()
      resetExplainMode()
      setConnectSourceNode(node)
      setIsConnectMode(true)
      toast(`连线模式：请选择终点节点（起点：${String(node?.label || node?.id || '')}）`)
    },
    [resetPathMode, resetExplainMode]
  )

  const handleOpenLinkDetailFromContextMenu = useCallback((link: GraphLinkLike) => {
    setSelectedLink(link)
    setIsLinkDetailOpen(true)
    setIsDetailOpen(false)
    setSelectedNode(null)
  }, [])

  const handleClearHighlightsFromContextMenu = useCallback(() => {
    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
    setPathStartNode(null)
    setPathEndNode(null)
  }, [])

  const handleDeleteNodeOpenChange = useCallback((open: boolean) => {
    setDeleteNodeOpen(open)
    if (!open) setDeleteNodeTarget(null)
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
            onCopyNodeId: (nodeId) => {
              detachPromise(copyToClipboard(nodeId, '节点 ID'))
            },
            onDeleteNode: handleDeleteNode,
            onOpenLinkDetail: handleOpenLinkDetailFromContextMenu,
            onCopyLinkPredicate: (predicate) => {
              detachPromise(copyToClipboard(predicate, 'Predicate'))
            },
            onZoomToFit: () => getActiveGraph()?.zoomToFit(),
            onClearHighlights: handleClearHighlightsFromContextMenu,
            onToggleShowEdgeLabels: () => setShowEdgeLabels((value) => !value),
          }}
          legendVisible={graphRenderData.nodes.length > 0 && !isExplainMode}
          legendNodes={graphRenderData.nodes}
          legendLinks={graphRenderData.links}
          activeTypeFilters={entityTypeFilters}
          onToggleTypeFilter={(type) => {
            setEntityTypeFilters((prev) => {
              const next = new Set(prev)
              if (next.has(type)) next.delete(type)
              else next.add(type)
              return Array.from(next)
            })
          }}
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
            layoutLabel: getLayoutLabel(),
            onZoomIn: () => getActiveGraph()?.zoomIn(),
            onZoomOut: () => getActiveGraph()?.zoomOut(),
            onZoomToFit: () => getActiveGraph()?.zoomToFit(),
            onToggleViewMode: () => setViewMode(viewMode === '3d' ? '2d' : '3d'),
            onStartExplainMode: startExplainMode,
            onCycleLayoutMode: cycleLayoutMode,
            onTogglePathMode: togglePathMode,
            onToggleShowEdgeLabels: () => setShowEdgeLabels((value) => !value),
            onToggleFullscreen: () => {
              detachPromise(toggleFullscreen())
            },
            onExportOpenChange: setExportOpen,
            onExportPngDownload: () => {
              setExportOpen(false)
              detachPromise(exportGraph('png', 'download'))
            },
            onExportSvgDownload: () => {
              setExportOpen(false)
              detachPromise(exportGraph('svg', 'download'))
            },
            onExportPngCopy: () => {
              setExportOpen(false)
              detachPromise(exportGraph('png', 'copy'))
            },
            onExportSvgCopy: () => {
              setExportOpen(false)
              detachPromise(exportGraph('svg', 'copy'))
            },
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
