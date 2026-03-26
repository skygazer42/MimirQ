'use client'

/**
 * 知识图谱可视化页面
 * 功能：上传 .graphml 文件并进行可视化展示
 * 优化：主流视觉设计、交互侧边栏、玻璃拟态控件、搜索与高级筛选、后端集成、路径分析、布局切换、图编辑、RAG可解释性、3D可视化
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
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
import { cn, detachPromise } from '@/lib/utils'
import { documentApi } from '@/lib/api/documents'
import { kgApi } from '@/lib/api/graph'
import { useGraphDataLoading } from './use-graph-data-loading'
import { useGraphDisplayFilters } from './use-graph-display-filters'
import { useGraphEntityResolution } from './use-graph-entity-resolution'
import { useGraphInteractionModes } from './use-graph-interaction-modes'
import {
  GraphConfBucket,
  GraphContextMenuTarget,
  GraphContextMenuState,
  type GraphDatasetDocumentSummary,
  type GraphLinkLike,
  type GraphNodeLike,
  coerceBoundedInt,
  getGraphLinkEndpointId,
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
