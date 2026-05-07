'use client'

import type { Remote } from 'comlink'

import type { ChangeEvent, Dispatch, RefObject, SetStateAction } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { toast } from 'sonner'

import { kgApi } from '@/lib/api/graph'
import { GraphService } from '@/lib/graph-service'
import { parseGraphML, type GraphData } from '@/lib/graph-parser'
import type {
  KGEntityDetailResponse,
  KGEventDetailResponse,
  KGStatsResponse,
  RagTrace,
} from '@/types'
import type { GraphParserWorkerApi } from '@/workers/graph-parser.worker'

import {
  buildGraphFromTrace,
  extractTraceFromPayload,
  type GraphNodeLike,
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
  pipeline_hash?: string
}> | null

type UseGraphDataLoadingParams = Readonly<{
  scope: GraphScope
  scopedDocumentIds: string[] | null
  scopedDatasetDocIdsLoading: boolean
  scopeParams: GraphScopeParams
  includeEntityLinks: boolean
  includeRelationLinks: boolean
  minSharedEvents: number
  maxEntityLinks: number
  setGraphData: Dispatch<SetStateAction<GraphData>>
  setFileName: Dispatch<SetStateAction<string | null>>
  setDataSource: Dispatch<SetStateAction<'live' | 'mock' | 'file'>>
  setTraceReplay: Dispatch<SetStateAction<RagTrace | null>>
  setKgStats: Dispatch<SetStateAction<KGStatsResponse | null>>
  setKgNodeDetail: Dispatch<SetStateAction<KGEntityDetailResponse | KGEventDetailResponse | null>>
  setIsLoading: Dispatch<SetStateAction<boolean>>
  setIsDetailOpen: Dispatch<SetStateAction<boolean>>
  setSelectedNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setViewMode: Dispatch<SetStateAction<'2d' | '3d'>>
  fileInputRef: RefObject<HTMLInputElement | null>
  traceFileInputRef: RefObject<HTMLInputElement | null>
  resetPathMode: () => void
  resetConnectMode: () => void
  resetExplainMode: () => void
}>

type UseGraphDataLoadingResult = Readonly<{
  loadInitialData: (
    source?: 'live' | 'mock',
    opts?: { includeEntityLinks?: boolean; includeRelationLinks?: boolean; minSharedEvents?: number }
  ) => Promise<void>
  handleFileUpload: (event: ChangeEvent<HTMLInputElement>) => Promise<void>
  triggerFileUpload: () => void
  handleTraceFileUpload: (event: ChangeEvent<HTMLInputElement>) => Promise<void>
  triggerTraceUpload: () => void
}>

export function useGraphDataLoading({
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
}: UseGraphDataLoadingParams): UseGraphDataLoadingResult {
  const [autoLoadedGraphKey, setAutoLoadedGraphKey] = useState<string | null>(null)
  const graphParserWorkerRef = useRef<Worker | null>(null)
  const graphParserApiRef = useRef<Remote<GraphParserWorkerApi> | null>(null)
  const graphParserWorkerDisabledRef = useRef(false)

  const resetGraphSurface = useCallback(() => {
    setKgNodeDetail(null)
    setIsDetailOpen(false)
    setSelectedNode(null)
    resetPathMode()
    resetConnectMode()
    resetExplainMode()
  }, [resetConnectMode, resetExplainMode, resetPathMode, setIsDetailOpen, setKgNodeDetail, setSelectedNode])

  const loadInitialData = useCallback(
    async (
      source: 'live' | 'mock' = 'live',
      opts?: { includeEntityLinks?: boolean; includeRelationLinks?: boolean; minSharedEvents?: number }
    ) => {
      if (
        source === 'live' &&
        scope.hasScope &&
        scope.datasetId &&
        scope.directDocIds.length === 0 &&
        scopedDocumentIds === null &&
        scopedDatasetDocIdsLoading
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
          documentIds:
            source === 'live' && scopedDocumentIds && scopedDocumentIds.length ? scopedDocumentIds : undefined,
          pipelineHash: source === 'live' ? (scope.pipelineHash || undefined) : undefined,
        })

        setGraphData(data)
        setViewMode('3d')
        setDataSource(source)
        setTraceReplay(null)
        setFileName(
          source === 'mock'
            ? '示例数据'
            : scope.datasetId
              ? '知识库图谱'
              : scope.pipelineHash
                ? '批次图谱'
                : scopeParams
                  ? '范围图谱'
                  : '知识图谱'
        )

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

        resetGraphSurface()
      } catch (error) {
        console.error('Failed to fetch graph data:', error)
      } finally {
        setIsLoading(false)
      }
    },
    [
      includeEntityLinks,
      includeRelationLinks,
      maxEntityLinks,
      minSharedEvents,
      resetGraphSurface,
      scope,
      scopedDatasetDocIdsLoading,
      scopedDocumentIds,
      scopeParams,
      setDataSource,
      setFileName,
      setGraphData,
      setIsLoading,
      setKgStats,
      setTraceReplay,
      setViewMode,
    ]
  )

  useEffect(() => {
    const autoLoadKey = scope.hasScope
      ? `live:${scope.datasetId || ''}:${scope.pipelineHash || ''}:${scope.directDocIds.join(',')}:${scopedDocumentIds?.join(',') || ''}`
      : 'default-mock-3d'
    if (autoLoadedGraphKey === autoLoadKey) return

    if (scope.hasScope && scope.datasetId && scope.directDocIds.length === 0 && scopedDocumentIds === null) return

    setAutoLoadedGraphKey(autoLoadKey)
    void loadInitialData(scope.hasScope ? 'live' : 'mock')
  }, [autoLoadedGraphKey, loadInitialData, scope, scopedDocumentIds])

  useEffect(() => {
    return () => {
      graphParserWorkerRef.current?.terminate()
      graphParserWorkerRef.current = null
      graphParserApiRef.current = null
    }
  }, [])

  const parseGraphFileContent = useCallback(async (content: string): Promise<GraphData> => {
    if (graphParserWorkerDisabledRef.current || typeof Worker === 'undefined') {
      return parseGraphML(content)
    }

    try {
      if (!graphParserWorkerRef.current || !graphParserApiRef.current) {
        const { wrap } = await import('comlink')
        graphParserWorkerRef.current = new Worker(
          new URL('../../workers/graph-parser.worker.ts', import.meta.url),
          { type: 'module' }
        )
        graphParserApiRef.current = wrap<GraphParserWorkerApi>(graphParserWorkerRef.current)
      }

      return await graphParserApiRef.current.parseGraphML(content)
    } catch (error) {
      console.warn('Graph parser worker failed; falling back to main-thread parse', error)
      graphParserWorkerDisabledRef.current = true
      graphParserWorkerRef.current?.terminate()
      graphParserWorkerRef.current = null
      graphParserApiRef.current = null
      return parseGraphML(content)
    }
  }, [])

  const handleFileUpload = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      if (!file) return

      setIsLoading(true)
      setFileName(file.name)

      const reader = new FileReader()
      reader.onload = async (loadEvent) => {
        try {
          const content = loadEvent.target?.result as string
          const parsedData = await parseGraphFileContent(content)
          setGraphData(parsedData)
          setDataSource('file')
          setTraceReplay(null)
          setKgStats(null)
          resetGraphSurface()
        } catch (error) {
          console.error('Failed to parse graph file:', error)
          toast.error('解析文件失败，请确保是有效的 GraphML 文件')
        } finally {
          setIsLoading(false)
        }
      }

      reader.readAsText(file)
      event.target.value = ''
    },
    [
      parseGraphFileContent,
      resetGraphSurface,
      setDataSource,
      setFileName,
      setGraphData,
      setIsLoading,
      setKgStats,
      setTraceReplay,
    ]
  )

  const triggerFileUpload = useCallback(() => {
    fileInputRef.current?.click()
  }, [fileInputRef])

  const handleTraceFileUpload = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      if (!file) return

      setIsLoading(true)
      setFileName(file.name)
      try {
        const text = await file.text()
        const payload = JSON.parse(text)
        const trace = extractTraceFromPayload(payload)
        if (!trace) {
          throw new Error('Invalid trace JSON')
        }

        const built = buildGraphFromTrace(trace)
        setTraceReplay(trace)
        setGraphData(built.graph)
        setDataSource('file')
        setKgStats(null)
        resetGraphSurface()
        setViewMode('2d')
        toast.success('Trace 已导入（可点击右下角 Play 回放）')
      } catch (error) {
        console.error('Failed to import trace JSON:', error)
        setTraceReplay(null)
        toast.error('导入 Trace 失败：请检查 JSON 格式或粘贴/导出内容是否完整')
      } finally {
        setIsLoading(false)
        event.target.value = ''
      }
    },
    [
      resetGraphSurface,
      setDataSource,
      setFileName,
      setGraphData,
      setIsLoading,
      setKgStats,
      setTraceReplay,
      setViewMode,
    ]
  )

  const triggerTraceUpload = useCallback(() => {
    traceFileInputRef.current?.click()
  }, [traceFileInputRef])

  return {
    loadInitialData,
    handleFileUpload,
    triggerFileUpload,
    handleTraceFileUpload,
    triggerTraceUpload,
  }
}

export type { UseGraphDataLoadingResult }
