'use client'

import type { Dispatch, SetStateAction } from 'react'
import { useCallback, useEffect } from 'react'

import { kgApi } from '@/lib/api/graph'
import type { GraphData } from '@/lib/graph-parser'
import { GraphService } from '@/lib/graph-service'
import type {
  KGEntityDetailResponse,
  KGEventDetailResponse,
} from '@/types'

import {
  getGraphLinkEndpointId,
  type GraphNodeLike,
} from './graph-page-utils'

type DeleteNodeTarget = {
  id: string
  label: string
} | null

type GraphScopeParams = Readonly<{
  document_ids?: string[]
  dataset_id?: string
  pipeline_hash?: string
}> | null

type UseGraphNodeOperationsParams = Readonly<{
  dataSource: 'live' | 'file'
  isDetailOpen: boolean
  selectedNode: GraphNodeLike | null
  scopeParams: GraphScopeParams
  includeEntityLinks: boolean
  includeRelationLinks: boolean
  minSharedEvents: number
  maxEntityLinks: number
  scopedDocumentIds: string[] | null
  pipelineHash: string | null
  deleteNodeTarget: DeleteNodeTarget
  setGraphData: Dispatch<SetStateAction<GraphData>>
  setIsLoading: Dispatch<SetStateAction<boolean>>
  setDeleteNodeOpen: Dispatch<SetStateAction<boolean>>
  setDeleteNodeTarget: Dispatch<SetStateAction<DeleteNodeTarget>>
  setSelectedNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setIsDetailOpen: Dispatch<SetStateAction<boolean>>
  setKgNodeDetail: Dispatch<SetStateAction<KGEntityDetailResponse | KGEventDetailResponse | null>>
  setKgNodeDetailLoading: Dispatch<SetStateAction<boolean>>
}>

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
  setIsLoading,
  setDeleteNodeOpen,
  setDeleteNodeTarget,
  setSelectedNode,
  setIsDetailOpen,
  setKgNodeDetail,
  setKgNodeDetailLoading,
}: UseGraphNodeOperationsParams) {
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

    const kind = selectedNode.meta?.kind
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
  }, [
    dataSource,
    isDetailOpen,
    scopeParams,
    selectedNode,
    setKgNodeDetail,
    setKgNodeDetailLoading,
  ])

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
          datasetId: dataSource === 'live' ? (scopeParams?.dataset_id || undefined) : undefined,
          pipelineHash: dataSource === 'live' ? (pipelineHash || undefined) : undefined,
        })

        setGraphData((prev) => {
          const existingNodeIds = new Set(prev.nodes.map((node) => node.id))
          const uniqueNewNodes = newData.nodes.filter((node) => !existingNodeIds.has(node.id))

          const existingLinks = new Set(
            prev.links.map((link) => `${getGraphLinkEndpointId(link.source)}-${getGraphLinkEndpointId(link.target)}`)
          )
          const uniqueNewLinks = newData.links.filter(
            (link) => !existingLinks.has(`${link.source}-${link.target}`)
          )

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
    [
      dataSource,
      includeEntityLinks,
      includeRelationLinks,
      maxEntityLinks,
      minSharedEvents,
      pipelineHash,
      scopeParams,
      scopedDocumentIds,
      setGraphData,
      setIsLoading,
    ]
  )

  const handleExpandNode = useCallback(() => {
    if (!selectedNode) return
    void expandNodeById(String(selectedNode.id))
  }, [expandNodeById, selectedNode])

  const handleExpandNodeById = useCallback(
    (nodeId: string) => {
      void expandNodeById(nodeId)
    },
    [expandNodeById]
  )

  const handleDeleteNode = useCallback(
    (node?: GraphNodeLike) => {
      const target = node ?? selectedNode
      if (!target) return
      setDeleteNodeTarget({
        id: String(target.id),
        label: String(target.label || target.id || ''),
      })
      setDeleteNodeOpen(true)
    },
    [selectedNode, setDeleteNodeOpen, setDeleteNodeTarget]
  )

  const confirmDeleteNode = useCallback(() => {
    const nodeId = (deleteNodeTarget?.id || '').trim()
    if (!nodeId) return

    setGraphData((prev) => ({
      nodes: prev.nodes.filter((node) => String(node.id) !== nodeId),
      links: prev.links.filter((link) => {
        const sourceId = getGraphLinkEndpointId(link.source)
        const targetId = getGraphLinkEndpointId(link.target)
        return String(sourceId) !== nodeId && String(targetId) !== nodeId
      }),
    }))

    if (String(selectedNode?.id) === nodeId) {
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
    handleExpandNode,
    handleExpandNodeById,
    handleDeleteNode,
    confirmDeleteNode,
  }
}

export type UseGraphNodeOperationsResult = ReturnType<typeof useGraphNodeOperations>
