'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'

import { type KnowledgeGraph3DRef } from '@/components/graph/force-graph-3d'
import { GraphViewerRef, LayoutMode } from '@/components/graph/graph-viewer'
import { documentApi } from '@/lib/api/documents'
import { queryKeys } from '@/lib/query-keys'
import type { GraphData } from '@/lib/graph-types'
import { useResizeObserver } from '@/hooks/use-resize-observer'
import {
  GraphConfBucket,
  type GraphLinkLike,
  type GraphNodeLike,
  type GraphTraceReplay,
  coerceBoundedInt,
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
    const directDocIds = [...parseCsvList(sp.get('document_ids')), ...sp.getAll('document_id')]
      .map((value) => value.trim())
      .filter((value) => value !== '')

    const uniqDocIds = Array.from(new Set(directDocIds))
    const datasetId = sp.get('dataset_id')?.trim()
    const pipelineHash = sp.get('pipeline_hash')?.trim()
    const docLimit = coerceBoundedInt(sp.get('doc_limit'), 200, 1, 500)
    const hasScope = uniqDocIds.length > 0 || Boolean(datasetId) || Boolean(pipelineHash)

    return {
      hasScope,
      directDocIds: uniqDocIds,
      datasetId: datasetId === '' ? null : (datasetId ?? null),
      pipelineHash: pipelineHash === '' ? null : (pipelineHash ?? null),
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

  const needsScopedDocuments = scope.datasetId !== null && scope.directDocIds.length === 0
  const scopedDocumentParams = {
    skip: 0,
    limit: scope.docLimit,
    dataset_id: scope.datasetId,
    order_by: 'created_at',
    order_dir: 'desc',
  } as const
  const scopedDocumentsQuery = useQuery({
    queryKey: queryKeys.documents.list(scopedDocumentParams),
    queryFn: ({ signal }) => documentApi.list(scopedDocumentParams, { signal }),
    enabled: needsScopedDocuments,
  })
  const scopedDatasetDocuments = needsScopedDocuments ? scopedDocumentsQuery.data?.items : undefined
  const scopedDocumentIds = useMemo(() => {
    if (scope.directDocIds.length > 0) return scope.directDocIds
    return scopedDatasetDocuments?.map((document) => document.id) ?? null
  }, [scope.directDocIds, scopedDatasetDocuments])
  const scopedDatasetPendingDocs = scopedDatasetDocuments?.filter(
    (document) => document.status === 'pending' || document.status === 'processing',
  ).length
  const scopedDatasetDocIdsLoading =
    needsScopedDocuments && scopedDocumentIds === null && scopedDocumentsQuery.isFetching

  const scopeParams = useMemo<GraphScopeParams>(() => {
    const document_ids = scopedDocumentIds && scopedDocumentIds.length > 0 ? scopedDocumentIds : undefined
    const dataset_id = scope.datasetId ?? undefined
    const pipeline_hash = scope.pipelineHash ?? undefined
    if (document_ids === undefined && dataset_id === undefined && pipeline_hash === undefined) return null
    return { document_ids, dataset_id, pipeline_hash }
  }, [scopedDocumentIds, scope.datasetId, scope.pipelineHash])

  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d')
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
  const [traceReplay, setTraceReplay] = useState<GraphTraceReplay | null>(null)

  const graphViewportRef = useRef<HTMLDivElement>(null)
  const graph2dRef = useRef<GraphViewerRef>(null)
  const graph3dRef = useRef<KnowledgeGraph3DRef>(null)
  const { width: graphViewportWidth, height: graphViewportHeight } = useResizeObserver(graphViewportRef)

  const getActiveGraph = useCallback<() => GraphViewportApi>(() => {
    return viewMode === '3d' ? graph3dRef.current : graph2dRef.current
  }, [viewMode])

  const traceFileInputRef = useRef<HTMLInputElement>(null)
  const manualKgFileInputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setSelfLoopGroupExpanded(false)
  }, [selectedLink, isLinkDetailOpen])

  const resetConnectMode = useCallback(() => {
    setIsConnectMode(false)
    setConnectSourceNode(null)
    setConnectTargetNode(null)
    setConnectLabelOpen(false)
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

  const resetGraphSurface = useCallback(() => {
    setSelectedNode(null)
    setIsDetailOpen(false)
    setSelectedLink(null)
    setIsLinkDetailOpen(false)
    setDeleteNodeTarget(null)
    setDeleteNodeOpen(false)
    resetPathMode()
    resetConnectMode()
    resetExplainMode()
  }, [resetConnectMode, resetExplainMode, resetPathMode])

  return {
    scope,
    scopedDocumentIds,
    scopedDatasetDocIdsLoading,
    scopedDatasetPendingDocs,
    scopedDocumentsError: needsScopedDocuments ? scopedDocumentsQuery.error : null,
    refetchScopedDocuments: scopedDocumentsQuery.refetch,
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
    traceFileInputRef,
    manualKgFileInputRef,
    searchInputRef,
    resetConnectMode,
    resetExplainMode,
    resetPathMode,
    resetGraphSurface,
  }
}

export type UseGraphPageStateResult = ReturnType<typeof useGraphPageState>
