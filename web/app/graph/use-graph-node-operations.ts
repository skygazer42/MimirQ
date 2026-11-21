'use client'

import type { Dispatch, SetStateAction } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { skipToken, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'

import { kgApi } from '@/lib/api/graph'
import type { GraphData } from '@/lib/graph-types'
import { expandGraphNode } from '@/lib/graph-service'
import { detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'
import type { KGEntityDetailResponse, KGEventDetailResponse } from '@/types'

import {
  getGraphLinkEndpointId,
  getGraphLinkKind,
  getGraphLinkPredicate,
  getGraphNodeKind,
  type GraphLinkLike,
  type GraphNodeLike,
} from './graph-page-utils'
import type { UseGraphPageStateResult } from './use-graph-page-state'

type UseGraphNodeOperationsParams = Readonly<{
  dataSource: 'live' | 'file'
  isDetailOpen: boolean
  selectedNode: GraphNodeLike | null
  scopeParams: UseGraphPageStateResult['scopeParams']
  includeEntityLinks: boolean
  includeRelationLinks: boolean
  minSharedEvents: number
  maxEntityLinks: number
  scopedDocumentIds: string[] | null
  pipelineHash: string | null
  deleteNodeTarget: UseGraphPageStateResult['deleteNodeTarget']
  setGraphData: Dispatch<SetStateAction<GraphData>>
  setDeleteNodeOpen: Dispatch<SetStateAction<boolean>>
  setDeleteNodeTarget: Dispatch<SetStateAction<UseGraphPageStateResult['deleteNodeTarget']>>
  setSelectedNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setIsDetailOpen: Dispatch<SetStateAction<boolean>>
}>

function getExpansionLinkKey(link: GraphLinkLike): string {
  if (link.id !== null && link.id !== undefined && link.id !== '') return JSON.stringify(['id', String(link.id)])
  return JSON.stringify([
    getGraphLinkEndpointId(link.source),
    getGraphLinkEndpointId(link.target),
    getGraphLinkKind(link),
    getGraphLinkPredicate(link),
    link.meta?.document_id,
    link.meta?.chunk_id,
    link.meta?.event_id,
  ])
}

export function useGraphNodeOperations({
  dataSource,
  isDetailOpen,
  selectedNode,
  scopeParams,
  includeEntityLinks,
  includeRelationLinks,
  minSharedEvents,
  maxEntityLinks,
  scopedDocumentIds,
  pipelineHash,
  deleteNodeTarget,
  setGraphData,
  setDeleteNodeOpen,
  setDeleteNodeTarget,
  setSelectedNode,
  setIsDetailOpen,
}: UseGraphNodeOperationsParams) {
  const kind = getGraphNodeKind(selectedNode)
  const nodeId = selectedNode?.id
  const canReadDetail =
    dataSource === 'live' &&
    isDetailOpen &&
    nodeId !== undefined &&
    nodeId !== '' &&
    (kind === 'entity' || kind === 'event')
  const nodeDetailQuery = useQuery<KGEntityDetailResponse | KGEventDetailResponse>({
    queryKey: queryKeys.kg.nodeDetail(kind, canReadDetail ? nodeId : undefined, scopeParams),
    queryFn: canReadDetail
      ? ({ signal }) =>
          kind === 'entity'
            ? kgApi.getEntity(nodeId, scopeParams ?? undefined, { signal })
            : kgApi.getEvent(nodeId, scopeParams ?? undefined, { signal })
      : skipToken,
    retry: false,
  })
  const [pendingExpansionCount, setPendingExpansionCount] = useState(0)
  const expansionOptions = useMemo(
    () => ({
      includeEntityLinks: includeEntityLinks && dataSource === 'live',
      includeRelationLinks: includeRelationLinks && dataSource === 'live',
      minSharedEvents,
      maxEntityLinks,
      documentIds: dataSource === 'live' && scopedDocumentIds?.length ? scopedDocumentIds : undefined,
      datasetId: dataSource === 'live' ? scopeParams?.dataset_id : undefined,
      pipelineHash: dataSource === 'live' ? (pipelineHash ?? undefined) : undefined,
    }),
    [
      dataSource,
      includeEntityLinks,
      includeRelationLinks,
      maxEntityLinks,
      minSharedEvents,
      pipelineHash,
      scopeParams,
      scopedDocumentIds,
    ],
  )
  const expansionRef = useRef<{ options: typeof expansionOptions; controller: AbortController } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    expansionRef.current = { options: expansionOptions, controller }
    setPendingExpansionCount(0)
    return () => {
      controller.abort()
    }
  }, [expansionOptions])

  const expandNodeById = useCallback(
    async (nodeId: string) => {
      const id = nodeId.trim()
      const expansion = expansionRef.current
      if (id === '' || expansion?.options !== expansionOptions || expansion.controller.signal.aborted) return
      const { signal } = expansion.controller

      setPendingExpansionCount((count) => count + 1)
      try {
        const newData = await expandGraphNode(id, expansionOptions, signal)
        if (signal.aborted) return

        setGraphData((prev) => {
          const existingNodeIds = new Set(prev.nodes.map((node) => node.id))
          const uniqueNewNodes = newData.nodes.filter((node) => {
            if (existingNodeIds.has(node.id)) return false
            existingNodeIds.add(node.id)
            return true
          })

          const existingLinkKeys = new Set(prev.links.map(getExpansionLinkKey))
          const uniqueNewLinks = newData.links.filter((link) => {
            const key = getExpansionLinkKey(link)
            if (existingLinkKeys.has(key)) return false
            existingLinkKeys.add(key)
            return true
          })

          if (uniqueNewNodes.length === 0 && uniqueNewLinks.length === 0) return prev

          return {
            nodes: [...prev.nodes, ...uniqueNewNodes],
            links: [...prev.links, ...uniqueNewLinks],
          }
        })
      } catch (error) {
        if (signal.aborted) return
        reportClientError('Failed to expand node', error)
        toast.error(formatApiError(error, '图谱展开失败'))
      } finally {
        if (!signal.aborted) setPendingExpansionCount((count) => count - 1)
      }
    },
    [expansionOptions, setGraphData],
  )

  const handleExpandNode = useCallback(() => {
    if (!selectedNode) return
    detachPromise(expandNodeById(selectedNode.id))
  }, [expandNodeById, selectedNode])

  const handleExpandNodeById = useCallback(
    (nodeId: string) => {
      detachPromise(expandNodeById(nodeId))
    },
    [expandNodeById],
  )

  const handleDeleteNode = useCallback(
    (node?: GraphNodeLike) => {
      const target = node ?? selectedNode
      if (!target) return
      setDeleteNodeTarget({
        id: target.id,
        label: target.label === '' ? target.id : target.label,
      })
      setDeleteNodeOpen(true)
    },
    [selectedNode, setDeleteNodeOpen, setDeleteNodeTarget],
  )

  const confirmDeleteNode = useCallback(() => {
    const nodeId = deleteNodeTarget?.id.trim()
    if (nodeId === undefined || nodeId === '') return

    setGraphData((prev) => ({
      nodes: prev.nodes.filter((node) => node.id !== nodeId),
      links: prev.links.filter((link) => {
        const sourceId = getGraphLinkEndpointId(link.source)
        const targetId = getGraphLinkEndpointId(link.target)
        return sourceId !== nodeId && targetId !== nodeId
      }),
    }))

    if (selectedNode?.id === nodeId) {
      setSelectedNode(null)
      setIsDetailOpen(false)
    }
    setDeleteNodeTarget(null)
    setDeleteNodeOpen(false)
  }, [
    deleteNodeTarget,
    selectedNode,
    setDeleteNodeOpen,
    setDeleteNodeTarget,
    setGraphData,
    setIsDetailOpen,
    setSelectedNode,
  ])

  return {
    nodeDetail: canReadDetail ? (nodeDetailQuery.data ?? null) : null,
    nodeDetailLoading: canReadDetail && nodeDetailQuery.isFetching,
    nodeDetailError:
      canReadDetail && nodeDetailQuery.isError ? formatApiError(nodeDetailQuery.error, '读取节点详情失败') : null,
    retryNodeDetail: nodeDetailQuery.refetch,
    isExpanding: pendingExpansionCount > 0,
    handleExpandNode,
    handleExpandNodeById,
    handleDeleteNode,
    confirmDeleteNode,
  }
}

export type UseGraphNodeOperationsResult = ReturnType<typeof useGraphNodeOperations>
