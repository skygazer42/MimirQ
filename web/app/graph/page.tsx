'use client'

/**
 * 知识图谱可视化页面
 * 功能：上传 .graphml 文件并进行可视化展示
 * 优化：主流视觉设计、交互侧边栏、玻璃拟态控件、搜索与高级筛选、后端集成、路径分析、布局切换、图编辑、RAG可解释性、3D可视化
 */
import { useState, useRef, useEffect, useCallback, useDeferredValue, useMemo } from 'react'
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Upload, Share2, Info, RefreshCw, ZoomIn, ZoomOut, Maximize, X, BarChart3, Database, Filter, SlidersHorizontal, Layers, FileCode, MessageSquare, FileText, Type, Trash2, Network, Route, PlayCircle, Layout, Link as LinkIcon, Lightbulb, Box, BoxSelect } from 'lucide-react'
import { GraphViewer, GraphViewerRef, LayoutMode } from '@/components/graph/graph-viewer'
import { KnowledgeGraph3D } from '@/components/graph/force-graph-3d'
import { parseGraphML, GraphData, type GraphNode } from '@/lib/graph-parser'
import { GraphService } from '@/services/graph-service'
import { findShortestPath } from '@/lib/graph-algorithms'
import { cn, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { documentApi, kgApi } from '@/lib/api-client'
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
  RagTraceListResponse,
} from '@/types'

type GraphConfBucket = 'high' | 'medium' | 'low'

function coerceTrimmedString(value: unknown): string {
  return toTrimmedPrimitiveString(value)
}

function getGraphNodeKind(node: any): string {
  return coerceTrimmedString(node?.meta?.kind ?? node?.kind)
}

function getGraphNodeType(node: any): string {
  return coerceTrimmedString(node?.meta?.type ?? node?.type)
}

function getGraphLinkKind(link: any): string {
  return coerceTrimmedString(link?.meta?.kind ?? link?.kind)
}

function getGraphLinkPredicate(link: any): string {
  return coerceTrimmedString(link?.meta?.predicate ?? link?.predicate ?? link?.label)
}

function getGraphLinkConfidence(link: any): number | null {
  const raw = link?.meta?.confidence ?? link?.confidence ?? link?.weight
  const num = Number(raw)
  if (!Number.isFinite(num)) return null
  return num
}

function getGraphLinkEndpointId(raw: any): string {
  if (raw == null) return ''
  if (typeof raw === 'string' || typeof raw === 'number') return String(raw)
  if (typeof raw === 'object' && 'id' in raw) return String((raw).id || '')
  return ''
}

function bucketConfidence(conf: number | null): GraphConfBucket | null {
  if (conf == null) return null
  if (conf >= 0.8) return 'high'
  if (conf >= 0.5) return 'medium'
  return 'low'
}

function parseCsvList(value: string | null): string[] {
  if (!value) return []
  return value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function coerceBoundedInt(value: string | null, fallback: number, min: number, max: number): number {
  const n = Math.floor(Number(value))
  if (!Number.isFinite(n)) return fallback
  return Math.min(max, Math.max(min, n))
}

export default function GraphPage() {
  const router = useRouter()
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
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)
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
      return () => {
        cancelled = true
      }
    }

    const datasetId = scope.datasetId
    if (!datasetId) {
      setScopedDatasetDocIds(null)
      setScopedDatasetDocIdsLoading(false)
      return () => {
        cancelled = true
      }
    }

    setScopedDatasetDocIdsLoading(true)
    ;(async () => {
      try {
        const list = await documentApi.list({
          skip: 0,
          limit: scope.docLimit,
          dataset_id: datasetId,
          order_by: 'created_at',
          order_dir: 'desc',
        })
        const ids = Array.isArray(list.items)
          ? list.items.map((d: any) => String(d?.id || '').trim()).filter(Boolean)
          : []
        if (!cancelled) setScopedDatasetDocIds(ids)
      } catch {
        if (!cancelled) setScopedDatasetDocIds([])
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
  const [pathStartNode, setPathStartNode] = useState<GraphNode | null>(null)
  const [pathEndNode, setPathEndNode] = useState<GraphNode | null>(null)

  // Layout & View Mode
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('force')

  // Editing State
  const [isConnectMode, setIsConnectMode] = useState(false)
  const [connectSourceNode, setConnectSourceNode] = useState<GraphNode | null>(null)
  const [connectLabelOpen, setConnectLabelOpen] = useState(false)
  const [connectTargetNode, setConnectTargetNode] = useState<GraphNode | null>(null)
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

  const graphRef = useRef<GraphViewerRef>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const traceFileInputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const deferredSearchTerm = useDeferredValue(searchTerm)

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

    const nextLinks: any[] = []
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

  const linksWithIds = useMemo(() => {
    return displayGraphData.links.map((link, index) => ({
      ...link,
      id: link.id || `link-${index}`,
    }))
  }, [displayGraphData.links])

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

    if (searchMatches.length > 0 && graphRef.current) {
      graphRef.current.focusNode(searchMatches[0].id)
    }
  }, [deferredSearchTerm, searchMatches, isPathMode, isConnectMode, isExplainMode])

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

  const _extractTraceFromPayload = (payload: any): RagTrace | null => {
    if (!payload) return null
    if (Array.isArray(payload)) {
      const first = payload[0]
      return first && typeof first === 'object' ? (first as RagTrace) : null
    }
    if (typeof payload !== 'object') return null

    // API response: { enabled, items: [...] }
    if (Array.isArray((payload as RagTraceListResponse).items)) {
      const first = (payload as RagTraceListResponse).items?.[0]
      return first && typeof first === 'object' ? (first) : null
    }

    // Single item.
    if (typeof (payload).ts_ms === 'number' && Array.isArray((payload).steps)) {
      return payload as RagTrace
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

	  const handleExpandNode = useCallback(async () => {
	    if (!selectedNode) return
	    
	      setIsLoading(true)
	      try {
	      const newData = await GraphService.expandNode(selectedNode.id, {
	        includeEntityLinks: includeEntityLinks && dataSource === 'live',
	        includeRelationLinks: includeRelationLinks && dataSource === 'live',
	        minSharedEvents,
	        maxEntityLinks,
	        documentIds: dataSource === 'live' ? (scopedDocumentIds && scopedDocumentIds.length ? scopedDocumentIds : undefined) : undefined,
	        pipelineHash: dataSource === 'live' ? (scope.pipelineHash || undefined) : undefined,
	      })
       
       setGraphData(prev => {
        const existingNodeIds = new Set(prev.nodes.map(n => n.id))
        const uniqueNewNodes = newData.nodes.filter(n => !existingNodeIds.has(n.id))
        
        const existingLinks = new Set(prev.links.map((l) => `${getGraphLinkEndpointId(l.source)}-${getGraphLinkEndpointId(l.target)}`))
        const uniqueNewLinks = newData.links.filter(l => !existingLinks.has(`${l.source}-${l.target}`))

        return {
          nodes: [...prev.nodes, ...uniqueNewNodes],
          links: [...prev.links, ...uniqueNewLinks]
        }
      })
    } catch (error) {
      console.error('Failed to expand node:', error)
	    } finally {
	      setIsLoading(false)
	    }
		  }, [selectedNode, includeEntityLinks, includeRelationLinks, minSharedEvents, maxEntityLinks, dataSource, scopedDocumentIds, scope.pipelineHash])

  const handleDeleteNode = useCallback(() => {
    if (!selectedNode) return
    setDeleteNodeTarget({
      id: String(selectedNode.id),
      label: String(selectedNode.label || selectedNode.id || ''),
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
        if (isPathMode) resetPathMode()
        if (isConnectMode) resetConnectMode()
        if (isExplainMode) resetExplainMode()
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
    isPathMode,
    isConnectMode,
    isExplainMode,
    handleDeleteNode,
    handleExpandNode,
    resetPathMode,
    resetConnectMode,
    resetExplainMode,
  ])

  const startConnectMode = () => {
    if (!selectedNode) return
    setConnectSourceNode(selectedNode)
    setIsConnectMode(true)
    setIsDetailOpen(false)
    toast(`连线模式：请选择终点节点（起点：${selectedNode.label}）`)
  }

  const finishConnection = (targetNode: any) => {
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

    const trace = []
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
        
        if (graphRef.current) {
            graphRef.current.focusNode(step.node)
        }

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

  const handleNodeClick = (node: any) => {
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
    }
  }

  const calculatePath = useCallback(
    (start: any, end: any) => {
      const result = findShortestPath(displayGraphData.nodes, linksWithIds, start.id, end.id)

      if (result) {
        setHighlightedNodeIds(new Set(result.nodeIds))
        setHighlightedLinkIds(new Set(result.linkIds))
        if (graphRef.current) {
          graphRef.current.zoomToFit()
        }
      } else {
        toast.info('未找到连接这两个节点的路径')
        setPathEndNode(null)
      }
    },
    [displayGraphData.nodes, linksWithIds]
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
       graphRef.current?.zoomToFit()
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
    if (!selectedNode?.label) return
    const prompt = `请告诉我关于 ${selectedNode.label} 的信息`
    router.push(`/?prompt=${encodeURIComponent(prompt)}`)
  }

  const handleViewSource = () => {
    const docId = selectedNode?.meta?.document_id || selectedNode?.source
    if (docId) {
      toast(`源文档：${docId}`)
      return
    }
    toast('未找到源文档信息')
  }

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
        <div className="flex-1 w-full relative bg-background overflow-hidden min-h-[500px]">
          {/* Dot Pattern Background */}
          <div className="absolute inset-0 z-0 opacity-[0.4]" style={{
             backgroundImage: 'radial-gradient(#cbd5e1 1px, transparent 1px)', 
             backgroundSize: '24px 24px'
          }}></div>

          { }
          {displayGraphData.nodes.length > 0 ? (
            viewMode === '3d' ? (
                <KnowledgeGraph3D 
                    data={displayGraphData}
                    onNodeClick={(node) => {
                        handleNodeClick(node)
                    }}
                />
            ) : (
                <GraphViewer 
                ref={graphRef as React.RefObject<GraphViewerRef>}
                data={displayGraphData} 
                onNodeClick={handleNodeClick}
                onBackgroundClick={() => setIsDetailOpen(false)}
                highlightedNodeIds={highlightedNodeIds}
                highlightedLinkIds={highlightedLinkIds}
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

	          {/* Explainability Panel (Bottom Left) */}
		          {isExplainMode && (
		            <div className="absolute bottom-8 left-8 z-20 w-80 bg-card rounded-2xl shadow-strong border border-border overflow-hidden">
		               <div className="p-4 border-b border-border bg-muted/30 flex items-center gap-2">
		                 <Lightbulb className="w-4 h-4 text-primary" />
		                 <h3 className="font-bold text-foreground text-sm">RAG 推理过程</h3>
		               </div>
               <div className="p-4 space-y-4 max-h-[300px] overflow-y-auto overscroll-contain no-scrollbar">
                  {explainSteps.map((step, idx) => {
                    const node = displayGraphData.nodes.find(n => n.id === step.node)
                    const isActive = idx === currentStepIndex
                    const isDone = idx < currentStepIndex
                    let borderClass = "border-border opacity-50"
                    let dotClass = "bg-muted"
                    if (isActive) {
                      borderClass = "border-teal-500"
                      dotClass = "bg-teal-500"
                    } else if (isDone) {
                      borderClass = "border-teal-500/30"
                      dotClass = "bg-teal-500/20"
                    }
                    
                    return (
	                     <div key={`${step.node}-${step.reason}`} className={cn("relative pl-4 border-l-2 transition-colors duration-150 motion-reduce:transition-none", borderClass)}>
                        <div className={cn("absolute -left-[5px] top-0 w-2 h-2 rounded-full transition-colors", dotClass)}></div>
                        <p className="text-xs font-semibold text-foreground mb-0.5">
                          {node?.label || step.node}
                        </p>
                        <p className="text-[10px] text-muted-foreground leading-snug">
                          {step.reason}
                        </p>
                     </div>
                   )
                 })}
               </div>
            </div>
          )}

          {/* Floating Controls */}
          <div className="absolute bottom-8 right-8 z-10 flex flex-col gap-3">
             {/* Main Zoom Controls */}
             <div className="flex flex-col gap-1 bg-card/90 p-1.5 rounded-2xl shadow-md border border-border/50">
	               <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomIn()} className="rounded-xl" title="放大" aria-label="放大">
	                  <ZoomIn className="w-5 h-5" />
	                </Button>
	                <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomOut()} className="rounded-xl" title="缩小" aria-label="缩小">
	                  <ZoomOut className="w-5 h-5" />
	                </Button>
                <div className="h-px bg-muted mx-2 my-0.5"></div>
	                <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomToFit()} className="rounded-xl" title="适应屏幕" aria-label="适应屏幕">
	                  <Maximize className="w-5 h-5" />
	                </Button>
             </div>
             
             {/* View Options */}
             <div className="bg-card/90 p-1.5 rounded-2xl shadow-md border border-border/50 flex flex-col gap-1">
	                <Button 
	                   variant="ghost" 
	                   size="icon" 
	                   onClick={() => setViewMode(viewMode === '3d' ? '2d' : '3d')}
                   className={cn(
                     "rounded-xl",
                     viewMode === '3d' && "bg-primary/10 text-primary ring-2 ring-primary/20"
	                   )}
	                   title={viewMode === '3d' ? "切换至 2D 平面" : "切换至 3D 空间"}
	                   aria-label={viewMode === '3d' ? "切换至 2D 平面" : "切换至 3D 空间"}
	                >
                  {viewMode === '3d' ? <Box className="w-5 h-5" /> : <BoxSelect className="w-5 h-5" />}
                </Button>
	                <Button 
	                   variant="ghost" 
	                   size="icon" 
	                   onClick={startExplainMode}
                   className={cn(
                     "rounded-xl",
                     isExplainMode && "bg-primary/10 text-primary ring-2 ring-primary/20"
	                   )}
	                   title="推理演示 (Explain)"
	                   aria-label="推理演示"
	                >
                  <PlayCircle className="w-5 h-5" />
                </Button>
	                <Button 
	                   variant="ghost" 
	                   size="icon" 
	                   onClick={cycleLayoutMode}
	                   className="rounded-xl"
	                   title={`切换布局: ${getLayoutLabel()}`}
	                   aria-label={`切换布局：${getLayoutLabel()}`}
	                >
                  <Layout className="w-5 h-5" />
                  <span className="sr-only">{getLayoutLabel()}</span>
                </Button>
	                <Button 
	                   variant="ghost" 
	                   size="icon" 
	                   onClick={togglePathMode}
                   className={cn(
                     "rounded-xl",
                     isPathMode && "bg-primary/10 text-primary ring-2 ring-primary/20"
	                   )}
	                   title="路径发现 (Shortest Path)"
	                   aria-label="路径发现"
	                >
                  <Route className="w-5 h-5" />
                </Button>
	                <Button 
	                  variant="ghost" 
	                  size="icon" 
	                  onClick={() => setShowEdgeLabels(!showEdgeLabels)} 
	                  className={cn("rounded-xl", showEdgeLabels && "bg-primary/10 text-primary ring-2 ring-primary/20")} 
	                  title="显示/隐藏连线标签"
	                  aria-label="显示或隐藏连线标签"
	                >
                  <Type className="w-5 h-5" />
                </Button>
             </div>
          </div>

	          {/* Info Panel / Sidebar (Right) */}
	          <div
	            className={cn(
	              "absolute top-4 right-4 bottom-24 w-80 bg-card rounded-2xl shadow-strong border border-border transform transition-transform duration-200 ease-out z-20 flex flex-col overflow-hidden",
	              isDetailOpen && selectedNode ? "translate-x-0" : "translate-x-[120%]"
	            )}
	          >
            {selectedNode && (
              <>
	                <div className="p-5 border-b border-border flex items-start justify-between bg-card">
                  <div>
                    <h2 className="font-bold text-lg text-foreground line-clamp-2">{selectedNode.label}</h2>
                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-sky-500/10 dark:bg-sky-500/20 text-sky-600 dark:text-sky-300 mt-2 border border-sky-500/30">
                      <Database className="w-3 h-3" />
                      ID: {selectedNode.id}
                    </span>
                  </div>
	                  <button 
	                    type="button"
	                    onClick={() => setIsDetailOpen(false)}
	                    aria-label="关闭详情面板"
	                    className="text-muted-foreground hover:text-muted-foreground hover:bg-muted rounded-lg p-1 transition-colors"
	                  >
	                    <X className="w-5 h-5" />
	                  </button>
                </div>
                
                <div ref={detailScrollRef} className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-5 space-y-6">
                  {/* Deep Linking Actions */}
	                  <div className="grid grid-cols-2 gap-3">
	                    <Button 
	                      variant="info"
	                      onClick={handleChatWithNode}
	                      className="w-full"
	                    >
	                      <MessageSquare className="w-4 h-4 mr-2" />
	                      对话
	                    </Button>
                    <Button 
                      variant="outline" 
                      onClick={handleViewSource}
                      className="w-full"
                    >
                      <FileText className="w-4 h-4 mr-2" />
                      来源
                    </Button>
                  </div>

                  {/* KG Detail (Live) */}
                  {dataSource === 'live' && (selectedNode?.meta?.kind === 'entity' || selectedNode?.meta?.kind === 'event') && (
                    <div>
                      <h3 className="text-xs font-semibold text-muted-foreground uppercase  mb-3 flex items-center gap-2">
                        <Network className="w-3 h-3" />
                        KG Detail
                      </h3>

                      {(() => {
    if (kgNodeDetailLoading) {
        return (<div className="text-xs text-muted-foreground bg-muted rounded-xl p-3 border border-border">
                          Loading...
                        </div>);
    }
    else if (kgNodeDetail) {
            if (selectedNode?.meta?.kind === 'entity') {
                return (<div className="space-y-3">
                          <div className="bg-muted rounded-xl p-3 border border-border">
                            <div className="text-[10px] font-medium text-muted-foreground mb-1">Recent Events</div>
                            <div className="space-y-1">
                              {(kgNodeDetail as KGEntityDetailResponse).events?.slice(0, 6)?.map((ev) => (<div key={ev.id} className="text-xs text-foreground truncate" title={ev.title}>
                                  {ev.title}
                                </div>))}
                            </div>
                          </div>
                          <div className="bg-muted rounded-xl p-3 border border-border">
                            <div className="text-[10px] font-medium text-muted-foreground mb-1">Top Neighbors</div>
                            <div className="space-y-1">
                              {(kgNodeDetail as KGEntityDetailResponse).neighbors?.slice(0, 8)?.map((n) => (<div key={n.entity_id} className="flex items-center justify-between gap-2 text-xs">
                                  <span className="text-foreground truncate" title={n.name}>
                                    {n.name || n.entity_id}
                                  </span>
                                  <span className="text-muted-foreground font-mono">{n.count}</span>
                                </div>))}
                            </div>
                          </div>
                          <div className="bg-muted rounded-xl p-3 border border-border">
                            <div className="text-[10px] font-medium text-muted-foreground mb-2">Aliases</div>
                            {(() => {
                        if (entityAliasesLoading) {
                            return (<div className="text-xs text-muted-foreground">Loading...</div>);
                        }
                        else if (entityAliases.length === 0) {
                                return (<div className="text-xs text-muted-foreground">No aliases</div>);
                            }
                            else {
                                return (<div className="flex flex-wrap gap-2">
                                {entityAliases.slice(0, 12).map((a) => (<div key={a.id} className="inline-flex items-center gap-1 rounded-full bg-background/60 px-2 py-1 text-[11px] border border-border">
                                    <span className="max-w-[150px] truncate" title={a.alias}>
                                      {a.alias}
                                    </span>
                                    <button type="button" onClick={() => requestDeleteAlias(a)} aria-label={`删除 alias ${a.alias}`} className="text-muted-foreground hover:text-foreground hover:bg-muted rounded-md p-0.5 transition-colors">
                                      <X className="size-3"/>
                                    </button>
                                  </div>))}
                              </div>);
                            }
                    })()}

                            <div className="mt-3 flex items-center gap-2">
                              <Input value={aliasDraft} onChange={(e) => setAliasDraft(e.target.value)} placeholder="Add alias…" className="h-8 text-xs"/>
                              <Button type="button" variant="outline" className="h-8 text-xs" onClick={handleSaveAlias} disabled={aliasSaving || !aliasDraft.trim()}>
                                添加
                              </Button>
                            </div>
                          </div>

                          <div className="bg-muted rounded-xl p-3 border border-border">
                            <div className="text-[10px] font-medium text-muted-foreground mb-2">Suggestions</div>
                            {(() => {
                        if (aliasSuggestionsLoading) {
                            return (<div className="text-xs text-muted-foreground">Loading...</div>);
                        }
                        else if (aliasSuggestions.length === 0) {
                                return (<div className="text-xs text-muted-foreground">No suggestions</div>);
                            }
                            else {
                                return (<div className="space-y-1">
                                {aliasSuggestions.slice(0, 6).map((s) => (<div key={s.entity_id} className="flex items-center justify-between gap-2 text-xs">
                                    <span className="text-foreground truncate" title={s.name}>
                                      {s.name || s.entity_id}
                                    </span>
                                    <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-[11px]" onClick={() => {
                                            openMergeDialog();
                                            selectMergeTarget({
                                                id: s.entity_id,
                                                label: s.name || s.entity_id,
                                                meta: { kind: 'entity', type: s.type },
                                            });
                                        }}>
                                      合并
                                    </Button>
                                  </div>))}
                              </div>);
                            }
                    })()}
                          </div>
                        </div>);
            }
            else {
                return (<div className="bg-muted rounded-xl p-3 border border-border">
                          <div className="text-[10px] font-medium text-muted-foreground mb-2">Entities</div>
                          <div className="space-y-1">
                            {(kgNodeDetail as KGEventDetailResponse).entities?.slice(0, 12)?.map((row) => (<div key={row.entity.id} className="flex items-center justify-between gap-2 text-xs">
                                <span className="text-foreground truncate" title={row.entity.name}>
                                  {row.entity.name || row.entity.id}
                                </span>
                                <span className="text-muted-foreground">{row.role || row.entity.type}</span>
                              </div>))}
                          </div>
                        </div>);
            }
        }
        else {
            return (<div className="text-xs text-muted-foreground bg-muted rounded-xl p-3 border border-border">
                          No KG detail available
                        </div>);
        }
})()}
                    </div>
                  )}

                  {/* Properties List */}
                  <div>
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase  mb-3 flex items-center gap-2">
                      <Info className="w-3 h-3" />
                      属性详情
                    </h3>
                    <div className="space-y-3">
                      {Object.entries(selectedNode)
                        .filter(([key]) => !['id', 'label', 'x', 'y', 'z', 'vx', 'vy', 'vz', 'fx', 'fy', 'fz', 'index', 'color', '__bckgDimensions', 'source', 'meta'].includes(key))
                        .map(([key, value]) => (
                          <div key={key} className="bg-muted rounded-xl p-3 border border-border">
                            <span className="block text-xs font-medium text-muted-foreground mb-1 capitalize">{key}</span>
                            <span className="block text-sm text-foreground break-words">{String(value)}</span>
                          </div>
                        ))}
                         {selectedNode.source && (
                          <div className="rounded-xl border border-info/25 bg-info/10 p-3">
                            <span className="block text-xs font-medium text-info mb-1 capitalize">Source Document</span>
                            <button
                              type="button"
                              onClick={handleViewSource}
                              className="block w-full text-left text-sm text-info break-words underline underline-offset-4 hover:text-info/80 rounded-md focus-ring"
                            >
                              {selectedNode.source}
                            </button>
                          </div>
                        )}
                    </div>
                  </div>

                  {/* Edit Actions */}
                  <div>
                     <h3 className="text-xs font-semibold text-muted-foreground uppercase  mb-3 flex items-center gap-2">
                      <Layers className="w-3 h-3" />
                      操作
                    </h3>
                    <div className="space-y-2">
                       <Button 
                        variant="outline" 
                        onClick={handleExpandNode} 
                        disabled={isLoading}
                        className="w-full justify-start text-xs h-9 hover:bg-sky-500/10 dark:hover:bg-sky-500/20 hover:text-sky-600 dark:hover:text-sky-300 text-muted-foreground"
                      >
                        <Network className="w-3 h-3 mr-2" />
                        {isLoading ? '展开中...' : '展开邻居节点'}
                      </Button>
                      <div className="grid grid-cols-2 gap-2">
                         <Button 
                          variant="outline" 
                          onClick={startConnectMode}
                          className="w-full justify-start text-xs h-9 hover:bg-emerald-500/10 dark:hover:bg-emerald-500/20 hover:text-emerald-600 dark:hover:text-emerald-300 hover:border-emerald-500/30 text-muted-foreground"
                        >
                          <LinkIcon className="w-3 h-3 mr-2" />
                          连接
                        </Button>
                        <Button 
                          variant="outline" 
                          onClick={handleDeleteNode}
                          className="w-full justify-start text-xs h-9 hover:bg-red-500/10 dark:hover:bg-red-500/20 dark:bg-red-500/20 hover:text-red-600 dark:hover:text-red-300 hover:border-red-500/30 text-muted-foreground"
                        >
                          <Trash2 className="w-3 h-3 mr-2" />
                          删除
                        </Button>
                      </div>
                      {dataSource === 'live' && selectedNode?.meta?.kind === 'entity' && (
                        <div className="grid grid-cols-2 gap-2">
                          <Button
                            variant="outline"
                            onClick={openMergeDialog}
                            className="w-full justify-start text-xs h-9 hover:bg-amber-500/10 dark:hover:bg-amber-500/20 hover:text-amber-700 dark:hover:text-amber-200 hover:border-amber-500/30 text-muted-foreground"
                          >
                            <BoxSelect className="w-3 h-3 mr-2" />
                            合并
                          </Button>
                          <Button
                            variant="outline"
                            onClick={openSplitDialog}
                            className="w-full justify-start text-xs h-9 hover:bg-violet-500/10 dark:hover:bg-violet-500/20 hover:text-violet-700 dark:hover:text-violet-200 hover:border-violet-500/30 text-muted-foreground"
                          >
                            <Box className="w-3 h-3 mr-2" />
                            拆分
                          </Button>
                        </div>
                      )}
                      {lastResolutionActionId && (
                        <Button
                          variant="outline"
                          onClick={undoLastResolution}
                          disabled={undoSubmitting}
                          className="w-full justify-start text-xs h-9 hover:bg-primary/10 hover:text-primary text-muted-foreground"
                        >
                          <RefreshCw className="w-3 h-3 mr-2" />
                          {undoSubmitting ? '撤销中…' : '撤销上次变更'}
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        <AlertDialog
          open={deleteNodeOpen}
          onOpenChange={(open) => {
            setDeleteNodeOpen(open)
            if (!open) setDeleteNodeTarget(null)
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>删除节点？</AlertDialogTitle>
              <AlertDialogDescription>
                你将删除节点 <span className="font-mono">{deleteNodeTarget?.label || '-'}</span> 及其所有连线。此操作不可撤销。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction onClick={confirmDeleteNode}>删除</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <AlertDialog
          open={aliasDeleteOpen}
          onOpenChange={(open) => {
            setAliasDeleteOpen(open)
            if (!open) setAliasDeleteTarget(null)
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>删除 alias？</AlertDialogTitle>
              <AlertDialogDescription>
                你将删除 alias <span className="font-mono">{aliasDeleteTarget?.alias || '-'}</span>。此操作可通过重新添加恢复。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction onClick={confirmDeleteAlias} disabled={aliasSaving}>
                删除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <Dialog
          open={mergeOpen}
          onOpenChange={(open) => {
            setMergeOpen(open)
            if (!open) {
              setMergeSearch('')
              setMergeSearchResults([])
              setMergeTarget(null)
              setMergePreview(null)
              setMergeError(null)
              setMergeConfirmOpen(false)
            }
          }}
        >
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>合并实体</DialogTitle>
              <DialogDescription>将当前实体合并到另一个实体（可撤销）。建议先查看 Preview。</DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="kg-merge-search">搜索目标实体</Label>
                <Input
                  id="kg-merge-search"
                  value={mergeSearch}
                  onChange={(e) => setMergeSearch(e.target.value)}
                  placeholder="输入名称关键词…"
                />
                {(() => {
    if (mergeSearchLoading) {
        return (<div className="text-xs text-muted-foreground">Searching…</div>);
    }
    else if (mergeSearchResults.length === 0) {
            return (<div className="text-xs text-muted-foreground">输入至少 2 个字符开始搜索</div>);
        }
        else {
            return (<div className="space-y-1">
                    {mergeSearchResults.slice(0, 8).map((n) => (<button key={n.id} type="button" onClick={() => selectMergeTarget(n)} className={cn("w-full text-left rounded-lg border border-border bg-background/60 px-3 py-2 text-xs hover:bg-background transition-colors", mergeTarget?.id === n.id && "ring-2 ring-primary/20 border-primary/30")}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate">{n.label || n.id}</span>
                          <span className="text-muted-foreground font-mono">{String(n.id).slice(0, 8)}</span>
                        </div>
                      </button>))}
                  </div>);
        }
})()}
              </div>

              {mergeTarget && (
                <div className="rounded-xl border border-border bg-muted p-3 space-y-2">
                  <div className="text-[10px] font-medium text-muted-foreground">Preview</div>
                  <div className="text-xs text-foreground truncate" title={mergeTarget.label}>
                    Target: {mergeTarget.label || mergeTarget.id}
                  </div>
                  {(() => {
    if (mergePreviewLoading) {
        return (<div className="text-xs text-muted-foreground">Loading preview…</div>);
    }
    else if (mergePreview) {
            return (<div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                      <div>source edges: {String(mergePreview.stats?.source_event_entity_edges ?? '—')}</div>
                      <div>overlap: {String(mergePreview.stats?.overlap_events ?? '—')}</div>
                      <div>relations: {String(mergePreview.stats?.source_relations ?? '—')}</div>
                      <div>self removed: {String(mergePreview.stats?.self_relations_removed ?? '—')}</div>
                    </div>);
        }
        else {
            return (<div className="text-xs text-muted-foreground">No preview available</div>);
        }
})()}
                </div>
              )}

              {mergeError && (
                <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                  {mergeError}
                </div>
              )}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setMergeOpen(false)}>
                取消
              </Button>
              <Button
                type="button"
                onClick={() => setMergeConfirmOpen(true)}
                disabled={!mergeTarget || mergeSubmitting || mergePreviewLoading}
              >
                继续
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <AlertDialog open={mergeConfirmOpen} onOpenChange={setMergeConfirmOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认合并？</AlertDialogTitle>
              <AlertDialogDescription>
                你将把当前实体合并到 <span className="font-mono">{mergeTarget?.label || '-'}</span>。合并会重写事件边与关系边，但可通过“撤销上次变更”恢复。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={mergeSubmitting}>取消</AlertDialogCancel>
              <AlertDialogAction onClick={submitMerge} disabled={mergeSubmitting || !mergeTarget}>
                {mergeSubmitting ? '合并中…' : '确认合并'}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <Dialog
          open={splitOpen}
          onOpenChange={(open) => {
            setSplitOpen(open)
            if (!open) {
              setSplitNameDraft('')
              setSplitSelectedEventIds(new Set())
              setSplitError(null)
            }
          }}
        >
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>拆分实体</DialogTitle>
              <DialogDescription>选择需要移动到新实体的事件（可撤销）。</DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="kg-split-name">新实体名称</Label>
                <Input
                  id="kg-split-name"
                  value={splitNameDraft}
                  onChange={(e) => setSplitNameDraft(e.target.value)}
                  placeholder="例如：Python (language)"
                />
              </div>

              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">选择事件（Recent Events）</div>
                <div className="max-h-48 overflow-y-auto rounded-xl border border-border bg-background/60 p-2 space-y-2">
                  {(kgNodeDetail as KGEntityDetailResponse | null)?.events?.slice(0, 30)?.map((ev) => {
                    const checked = splitSelectedEventIds.has(String(ev.id))
                    return (
                      <label key={ev.id} className="flex items-start gap-2 text-xs text-foreground">
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(v) => toggleSplitEvent(String(ev.id), Boolean(v))}
                          aria-label={`选择事件 ${ev.title}`}
                        />
                        <span className="flex-1 truncate" title={ev.title}>
                          {ev.title || ev.id}
                        </span>
                      </label>
                    )
                  })}
                  {(kgNodeDetail as KGEntityDetailResponse | null)?.events?.length ? null : (
                    <div className="text-xs text-muted-foreground p-2">No events available</div>
                  )}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  已选择 {splitSelectedEventIds.size} 个事件（最多显示 30 条）
                </div>
              </div>

              {splitError && (
                <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                  {splitError}
                </div>
              )}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setSplitOpen(false)}>
                取消
              </Button>
              <Button type="button" onClick={submitSplit} disabled={splitSubmitting}>
                {splitSubmitting ? '拆分中…' : '确认拆分'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog
          open={connectLabelOpen}
          onOpenChange={(open) => {
            setConnectLabelOpen(open)
            if (!open) {
              setConnectTargetNode(null)
              resetConnectMode()
            }
          }}
        >
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>关系名称</DialogTitle>
              <DialogDescription>
                {connectSourceNode?.label && connectTargetNode?.label ? (
                  <>
                    将创建连线：<span className="font-mono">{String(connectSourceNode.label)}</span> →{' '}
                    <span className="font-mono">{String(connectTargetNode.label)}</span>
                  </>
                ) : (
                  '请输入关系名称（例如：related_to）'
                )}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-2">
              <Label htmlFor="graph-connect-label">关系名称</Label>
              <Input
                id="graph-connect-label"
                value={connectLabelDraft}
                onChange={(e) => setConnectLabelDraft(e.target.value)}
                placeholder="related_to"
                className="font-mono"
              />
              <div className="text-xs text-muted-foreground">
                留空将使用默认值：<span className="font-mono">related_to</span>
              </div>
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setConnectLabelOpen(false)}>
                取消
              </Button>
              <Button type="button" onClick={confirmConnectionLabel}>
                创建连线
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </PageScaffold>
    </AppFrame>
  )
}
