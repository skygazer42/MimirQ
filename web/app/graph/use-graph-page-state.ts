'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useSearchParams } from 'next/navigation'

import { type KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { GraphViewerRef, LayoutMode } from '@/components/graph/graph-viewer'
import { documentApi } from '@/lib/api/documents'
import { type GraphData } from '@/lib/graph-parser'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import type {
  KGEntityDetailResponse,
  KGEventDetailResponse,
  KGStatsResponse,
  RagTrace,
} from '@/types'

import {
  GraphConfBucket,
  type GraphDatasetDocumentSummary,
  type GraphLinkLike,
  type GraphNodeLike,
  coerceBoundedInt,
  getScopedDocumentId,
  isPendingScopedDocument,
  parseCsvList,
} from './graph-page-utils'

type GraphScope = Readonly<{
  hasScope: boolean
  directDocIds: string[]
  datasetId: string | null
  pipelineHash: string | null
  docLimit: number
}>

type GraphScopeParams = Readonly<{
  document_ids?: string[]
  dataset_id?: string
  pipeline_hash?: string
}> | null

type GraphDataSource = 'live' | 'file'

type GraphDeleteNodeTarget = {
  id: string
  label: string
} | null

type GraphExplainabilityStep = {
  node: string
  reason: string
}

type GraphViewportApi = {
  focusNode?: (nodeId: string) => void
  zoomToFit?: () => void
  zoomIn?: () => void
  zoomOut?: () => void
  exportPngDataUrl?: () => string | null
  exportSvgString?: () => string | null
} | null

export function useGraphPageState() {
  const searchParams = useSearchParams()
  const scopeParamKey = searchParams.toString()
  const scope = useMemo<GraphScope>(() => {
    const sp = new URLSearchParams(scopeParamKey)
    const directDocIds = [
      ...parseCsvList(sp.get('document_ids')),
      ...sp.getAll('document_id'),
    ]
      .map((value) => String(value || '').trim())
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

  const [graphData, setGraphData] = useState<GraphData>(() => ({ nodes: [], links: [] }))
  const [fileName, setFileName] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNodeLike | null>(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const [selectedLink, setSelectedLink] = useState<GraphLinkLike | null>(null)
  const [isLinkDetailOpen, setIsLinkDetailOpen] = useState(false)
  const [selfLoopGroupExpanded, setSelfLoopGroupExpanded] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [deleteNodeOpen, setDeleteNodeOpen] = useState(false)
  const [deleteNodeTarget, setDeleteNodeTarget] = useState<GraphDeleteNodeTarget>(null)
  const [dataSource, setDataSource] = useState<GraphDataSource>('live')
  const [includeEntityLinks, setIncludeEntityLinks] = useState(true)
  const [includeRelationLinks, setIncludeRelationLinks] = useState(false)
  const [minSharedEvents, setMinSharedEvents] = useState(2)
  const maxEntityLinks = 1000

  const [scopedDatasetDocIds, setScopedDatasetDocIds] = useState<string[] | null>(null)
  const [scopedDatasetDocIdsLoading, setScopedDatasetDocIdsLoading] = useState(false)
  const [scopedDatasetPendingDocs, setScopedDatasetPendingDocs] = useState<number | null>(null)

  const scopedDocumentIds = useMemo(() => {
    if (scope.directDocIds.length > 0) return scope.directDocIds
    if (scope.datasetId) return scopedDatasetDocIds
    return null
  }, [scope.datasetId, scope.directDocIds, scopedDatasetDocIds])

  const scopeParams = useMemo<GraphScopeParams>(() => {
    const document_ids = scopedDocumentIds && scopedDocumentIds.length > 0 ? scopedDocumentIds : undefined
    const dataset_id = scope.datasetId || undefined
    const pipeline_hash = scope.pipelineHash || undefined
    if (!document_ids && !dataset_id && !pipeline_hash) return null
    return { document_ids, dataset_id, pipeline_hash }
  }, [scopedDocumentIds, scope.datasetId, scope.pipelineHash])

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

        if (!cancelled) {
          setScopedDatasetDocIds(ids)
          setScopedDatasetPendingDocs(pending)
        }
      } catch {
        if (!cancelled) {
          setScopedDatasetDocIds([])
          setScopedDatasetPendingDocs(null)
        }
      } finally {
        if (!cancelled) {
          setScopedDatasetDocIdsLoading(false)
        }
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

  const [searchTerm, setSearchTerm] = useState('')
  const [showEdgeLabels, setShowEdgeLabels] = useState(false)
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(() => new Set())
  const [highlightedLinkIds, setHighlightedLinkIds] = useState<Set<string>>(() => new Set())

  const [isPathMode, setIsPathMode] = useState(false)
  const [pathStartNode, setPathStartNode] = useState<GraphNodeLike | null>(null)
  const [pathEndNode, setPathEndNode] = useState<GraphNodeLike | null>(null)

  const [layoutMode, setLayoutMode] = useState<LayoutMode>('force')

  const [isConnectMode, setIsConnectMode] = useState(false)
  const [connectSourceNode, setConnectSourceNode] = useState<GraphNodeLike | null>(null)
  const [connectLabelOpen, setConnectLabelOpen] = useState(false)
  const [connectTargetNode, setConnectTargetNode] = useState<GraphNodeLike | null>(null)
  const [connectLabelDraft, setConnectLabelDraft] = useState('related_to')

  const detailScrollRef = useRef<HTMLDivElement>(null)
  const selectedNodeId = selectedNode?.id ?? null

  useEffect(() => {
    if (!isDetailOpen || !selectedNodeId) return

    const raf = globalThis.window.requestAnimationFrame(() => {
      detailScrollRef.current?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
    })

    return () => globalThis.window.cancelAnimationFrame(raf)
  }, [isDetailOpen, selectedNodeId])

  const [isExplainMode, setIsExplainMode] = useState(false)
  const [explainSteps, setExplainSteps] = useState<GraphExplainabilityStep[]>([])
  const [currentStepIndex, setCurrentStepIndex] = useState(-1)
  const [traceReplay, setTraceReplay] = useState<RagTrace | null>(null)

  const graphViewportRef = useRef<HTMLDivElement>(null)
  const graph2dRef = useRef<GraphViewerRef>(null)
  const graph3dRef = useRef<KnowledgeGraph3DRef>(null)
  const { width: graphViewportWidth, height: graphViewportHeight } = useResizeObserver(graphViewportRef)

  const getActiveGraph = useCallback<() => GraphViewportApi>(() => {
    return viewMode === '3d' ? graph3dRef.current : graph2dRef.current
  }, [viewMode])

  const fileInputRef = useRef<HTMLInputElement>(null)
  const traceFileInputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
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

  return {
    scope,
    scopedDocumentIds,
    scopedDatasetDocIdsLoading,
    scopedDatasetPendingDocs,
    scopeParams,
    graphData,
    setGraphData,
    fileName,
    setFileName,
    selectedNode,
    setSelectedNode,
    selectedNodeId,
    isDetailOpen,
    setIsDetailOpen,
    selectedLink,
    setSelectedLink,
    isLinkDetailOpen,
    setIsLinkDetailOpen,
    selfLoopGroupExpanded,
    setSelfLoopGroupExpanded,
    isLoading,
    setIsLoading,
    deleteNodeOpen,
    setDeleteNodeOpen,
    deleteNodeTarget,
    setDeleteNodeTarget,
    dataSource,
    setDataSource,
    includeEntityLinks,
    setIncludeEntityLinks,
    includeRelationLinks,
    setIncludeRelationLinks,
    minSharedEvents,
    setMinSharedEvents,
    maxEntityLinks,
    kgStats,
    setKgStats,
    kgNodeDetail,
    setKgNodeDetail,
    kgNodeDetailLoading,
    setKgNodeDetailLoading,
    viewMode,
    setViewMode,
    filtersOpen,
    setFiltersOpen,
    entityTypeFilters,
    setEntityTypeFilters,
    predicateFilters,
    setPredicateFilters,
    confidenceBucketFilters,
    setConfidenceBucketFilters,
    entityTypeQuery,
    setEntityTypeQuery,
    predicateQuery,
    setPredicateQuery,
    searchTerm,
    setSearchTerm,
    showEdgeLabels,
    setShowEdgeLabels,
    highlightedNodeIds,
    setHighlightedNodeIds,
    highlightedLinkIds,
    setHighlightedLinkIds,
    isPathMode,
    setIsPathMode,
    pathStartNode,
    setPathStartNode,
    pathEndNode,
    setPathEndNode,
    layoutMode,
    setLayoutMode,
    isConnectMode,
    setIsConnectMode,
    connectSourceNode,
    setConnectSourceNode,
    connectLabelOpen,
    setConnectLabelOpen,
    connectTargetNode,
    setConnectTargetNode,
    connectLabelDraft,
    setConnectLabelDraft,
    detailScrollRef,
    isExplainMode,
    setIsExplainMode,
    explainSteps,
    setExplainSteps,
    currentStepIndex,
    setCurrentStepIndex,
    traceReplay,
    setTraceReplay,
    graphViewportRef,
    graph2dRef,
    graph3dRef,
    graphViewportWidth,
    graphViewportHeight,
    getActiveGraph,
    fileInputRef,
    traceFileInputRef,
    searchInputRef,
    resetConnectMode,
    resetExplainMode,
    resetPathMode,
  }
}

export type UseGraphPageStateResult = ReturnType<typeof useGraphPageState>
