'use client'

import type { Dispatch, SetStateAction } from 'react'
import { useCallback, useDeferredValue, useEffect, useMemo, useRef } from 'react'

import type { GraphData } from '@/lib/graph-parser'

import {
  GraphConfBucket,
  bucketConfidence,
  coerceTrimmedString,
  getGraphLinkConfidence,
  getGraphLinkEndpointId,
  getGraphLinkKind,
  getGraphLinkPredicate,
  getGraphNodeKind,
  getGraphNodeType,
  type GraphLinkLike,
  type GraphNodeLike,
} from './graph-page-utils'

type GraphFocusApi = {
  focusNode?: (nodeId: string) => void
} | null

type GraphFilterOption = Readonly<{
  value: string
  count: number
}>

const FRONTEND_TRACE_MIN_DURATION_MS = 12

function getNowMs(): number {
  if (typeof globalThis.performance?.now === 'function') {
    return globalThis.performance.now()
  }
  return Date.now()
}

type UseGraphDisplayFiltersParams = Readonly<{
  graphData: GraphData
  searchTerm: string
  entityTypeFilters: string[]
  predicateFilters: string[]
  confidenceBucketFilters: GraphConfBucket[]
  entityTypeQuery: string
  predicateQuery: string
  isPathMode: boolean
  isConnectMode: boolean
  isExplainMode: boolean
  selectedNodeId: string | null
  isDetailOpen: boolean
  getActiveGraph: () => GraphFocusApi
  setIsDetailOpen: Dispatch<SetStateAction<boolean>>
  setSelectedNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setEntityTypeFilters: Dispatch<SetStateAction<string[]>>
  setPredicateFilters: Dispatch<SetStateAction<string[]>>
  setConfidenceBucketFilters: Dispatch<SetStateAction<GraphConfBucket[]>>
  setEntityTypeQuery: Dispatch<SetStateAction<string>>
  setPredicateQuery: Dispatch<SetStateAction<string>>
  setHighlightedNodeIds: Dispatch<SetStateAction<Set<string>>>
  setHighlightedLinkIds: Dispatch<SetStateAction<Set<string>>>
  setPathStartNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setPathEndNode: Dispatch<SetStateAction<GraphNodeLike | null>>
}>

export function useGraphDisplayFilters({
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
  selectedNodeId,
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
}: UseGraphDisplayFiltersParams) {
  const deferredSearchTerm = useDeferredValue(searchTerm)
  const lastProjectionTraceKeyRef = useRef<string | null>(null)

  const availableEntityTypes = useMemo<GraphFilterOption[]>(() => {
    const counts = new Map<string, number>()
    for (const node of graphData.nodes) {
      if (getGraphNodeKind(node) !== 'entity') continue
      const type = getGraphNodeType(node) || 'unknown'
      counts.set(type, (counts.get(type) || 0) + 1)
    }

    return Array.from(counts.entries())
      .map(([value, count]) => ({ value, count }))
      .sort((left, right) => right.count - left.count || left.value.localeCompare(right.value))
  }, [graphData.nodes])

  const availablePredicates = useMemo<GraphFilterOption[]>(() => {
    const counts = new Map<string, number>()
    for (const link of graphData.links) {
      if (getGraphLinkKind(link) !== 'entity_relation') continue
      const predicate = getGraphLinkPredicate(link)
      if (!predicate) continue
      counts.set(predicate, (counts.get(predicate) || 0) + 1)
    }

    return Array.from(counts.entries())
      .map(([value, count]) => ({ value, count }))
      .sort((left, right) => right.count - left.count || left.value.localeCompare(right.value))
  }, [graphData.links])

  const filteredEntityTypes = useMemo(() => {
    const query = entityTypeQuery.trim().toLowerCase()
    if (!query) return availableEntityTypes.slice(0, 40)
    return availableEntityTypes.filter((item) => item.value.toLowerCase().includes(query)).slice(0, 40)
  }, [availableEntityTypes, entityTypeQuery])

  const filteredPredicates = useMemo(() => {
    const query = predicateQuery.trim().toLowerCase()
    if (!query) return availablePredicates.slice(0, 40)
    return availablePredicates.filter((item) => item.value.toLowerCase().includes(query)).slice(0, 40)
  }, [availablePredicates, predicateQuery])

  const activeGraphFilterCount = entityTypeFilters.length + predicateFilters.length + confidenceBucketFilters.length

  const displayGraphProjection = useMemo(() => {
    const startedAt = getNowMs()
    const hasTypeFilter = entityTypeFilters.length > 0
    const hasPredicateFilter = predicateFilters.length > 0
    const hasConfidenceFilter = confidenceBucketFilters.length > 0

    if (!hasTypeFilter && !hasPredicateFilter && !hasConfidenceFilter) {
      return {
        graphData,
        durationMs: Math.max(0, getNowMs() - startedAt),
      }
    }

    const allowedTypes = new Set(entityTypeFilters.map((value) => coerceTrimmedString(value)))
    const allowedPredicates = new Set(predicateFilters.map((value) => coerceTrimmedString(value)))
    const allowedBuckets = new Set(confidenceBucketFilters)

    const allowedNodeIds = new Set<string>()
    for (const node of graphData.nodes) {
      const nodeId = coerceTrimmedString(node?.id)
      if (!nodeId) continue

      const kind = getGraphNodeKind(node)
      if (kind === 'entity') {
        const type = getGraphNodeType(node) || 'unknown'
        if (!hasTypeFilter || allowedTypes.has(type)) {
          allowedNodeIds.add(nodeId)
        }
        continue
      }

      allowedNodeIds.add(nodeId)
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
          const predicate = getGraphLinkPredicate(link)
          if (!predicate || !allowedPredicates.has(predicate)) continue
        }

        if (hasConfidenceFilter) {
          const confidence = getGraphLinkConfidence(link)
          const bucket = bucketConfidence(confidence)
          if (!bucket || !allowedBuckets.has(bucket)) continue
        }
      }

      nextLinks.push({ ...link, source: sourceId, target: targetId })
    }

    const linkedNodeIds = new Set<string>()
    for (const link of nextLinks) {
      const sourceId = getGraphLinkEndpointId(link?.source)
      const targetId = getGraphLinkEndpointId(link?.target)
      if (sourceId) linkedNodeIds.add(sourceId)
      if (targetId) linkedNodeIds.add(targetId)
    }

    const nextNodes = graphData.nodes.filter((node) => linkedNodeIds.has(coerceTrimmedString(node?.id)))
    return {
      graphData: { nodes: nextNodes, links: nextLinks },
      durationMs: Math.max(0, getNowMs() - startedAt),
    }
  }, [confidenceBucketFilters, entityTypeFilters, graphData, predicateFilters])
  const displayGraphData = useMemo<GraphData>(() => displayGraphProjection.graphData, [displayGraphProjection.graphData])

  const linksWithIds = useMemo<GraphLinkLike[]>(() => {
    return displayGraphData.links.map((link, index) => ({
      ...link,
      id: link.id || `link-${index}`,
    }))
  }, [displayGraphData.links])

  const graphRenderData = useMemo<GraphData>(() => {
    return { nodes: displayGraphData.nodes, links: linksWithIds as GraphData['links'] }
  }, [displayGraphData.nodes, linksWithIds])

  const displayNodeIds = useMemo(() => {
    return new Set(displayGraphData.nodes.map((node) => coerceTrimmedString(node?.id)))
  }, [displayGraphData.nodes])

  useEffect(() => {
    if (graphData.nodes.length === 0 && graphData.links.length === 0) return
    if (displayGraphProjection.durationMs < FRONTEND_TRACE_MIN_DURATION_MS) return

    const traceKey = [
      graphData.nodes.length,
      graphData.links.length,
      displayGraphData.nodes.length,
      displayGraphData.links.length,
      activeGraphFilterCount,
      Math.round(displayGraphProjection.durationMs),
    ].join(':')

    if (lastProjectionTraceKeyRef.current === traceKey) return
    lastProjectionTraceKeyRef.current = traceKey

    const page =
      typeof globalThis.window !== 'undefined' ? globalThis.window.location?.pathname || '/graph' : '/graph'

    void import('@/lib/frontend-trace')
      .then(({ reportFrontendTrace }) =>
        reportFrontendTrace(
          {
            event: 'graph_render_projection',
            duration_ms: displayGraphProjection.durationMs,
            component: 'graph-display-filters',
            page,
            input_node_count: graphData.nodes.length,
            input_link_count: graphData.links.length,
            output_node_count: displayGraphData.nodes.length,
            output_link_count: displayGraphData.links.length,
            active_filter_count: activeGraphFilterCount,
          },
          { keepalive: true }
        )
      )
      .catch((error) => {
        console.warn('Failed to report graph projection trace', error)
      })
  }, [
    activeGraphFilterCount,
    displayGraphData.links.length,
    displayGraphData.nodes.length,
    displayGraphProjection.durationMs,
    graphData.links.length,
    graphData.nodes.length,
  ])

  useEffect(() => {
    if (!isDetailOpen || !selectedNodeId) return
    if (displayNodeIds.has(String(selectedNodeId))) return
    setIsDetailOpen(false)
    setSelectedNode(null)
  }, [displayNodeIds, isDetailOpen, selectedNodeId, setIsDetailOpen, setSelectedNode])

  useEffect(() => {
    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
    setPathStartNode(null)
    setPathEndNode(null)
  }, [
    confidenceBucketFilters,
    entityTypeFilters,
    predicateFilters,
    setHighlightedLinkIds,
    setHighlightedNodeIds,
    setPathEndNode,
    setPathStartNode,
  ])

  const searchMatches = useMemo(() => {
    if (isPathMode || isConnectMode || isExplainMode) return []
    const term = deferredSearchTerm.trim().toLowerCase()
    if (!term) return []

    return displayGraphData.nodes.filter((node) => {
      const label = String(node.label || '').toLowerCase()
      const nodeId = String(node.id || '').toLowerCase()
      return label.includes(term) || nodeId.includes(term)
    })
  }, [deferredSearchTerm, displayGraphData.nodes, isConnectMode, isExplainMode, isPathMode])

  useEffect(() => {
    if (isPathMode || isConnectMode || isExplainMode) return

    const term = deferredSearchTerm.trim()
    if (!term) {
      setHighlightedNodeIds(new Set())
      return
    }

    const nextIds = new Set(searchMatches.map((node) => node.id))
    setHighlightedNodeIds(nextIds)

    const firstMatch = searchMatches[0]
    if (firstMatch) {
      getActiveGraph()?.focusNode?.(firstMatch.id)
    }
  }, [
    deferredSearchTerm,
    getActiveGraph,
    isConnectMode,
    isExplainMode,
    isPathMode,
    searchMatches,
    setHighlightedNodeIds,
  ])

  const resetGraphFilters = useCallback(() => {
    setEntityTypeFilters([])
    setPredicateFilters([])
    setConfidenceBucketFilters([])
    setEntityTypeQuery('')
    setPredicateQuery('')
  }, [
    setConfidenceBucketFilters,
    setEntityTypeFilters,
    setEntityTypeQuery,
    setPredicateFilters,
    setPredicateQuery,
  ])

  const handleEntityTypeCheckedChange = useCallback(
    (value: string, checked: boolean) => {
      setEntityTypeFilters((prev) => {
        const next = new Set(prev)
        if (checked) next.add(value)
        else next.delete(value)
        return Array.from(next)
      })
    },
    [setEntityTypeFilters]
  )

  const handlePredicateCheckedChange = useCallback(
    (value: string, checked: boolean) => {
      setPredicateFilters((prev) => {
        const next = new Set(prev)
        if (checked) next.add(value)
        else next.delete(value)
        return Array.from(next)
      })
    },
    [setPredicateFilters]
  )

  const toggleConfidenceBucket = useCallback(
    (bucket: GraphConfBucket) => {
      setConfidenceBucketFilters((prev) => {
        const hasBucket = prev.includes(bucket)
        const next = hasBucket ? prev.filter((value) => value !== bucket) : [...prev, bucket]
        const unique = Array.from(new Set(next))
        if (unique.length >= 3) return []
        return unique
      })
    },
    [setConfidenceBucketFilters]
  )

  const toggleEntityTypeFilter = useCallback(
    (type: string) => {
      setEntityTypeFilters((prev) => {
        const next = new Set(prev)
        if (next.has(type)) next.delete(type)
        else next.add(type)
        return Array.from(next)
      })
    },
    [setEntityTypeFilters]
  )

  return {
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
  }
}

export type UseGraphDisplayFiltersResult = ReturnType<typeof useGraphDisplayFilters>
