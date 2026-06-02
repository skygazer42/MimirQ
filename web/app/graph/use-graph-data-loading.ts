'use client'

import type { ChangeEvent, Dispatch, RefObject, SetStateAction } from 'react'
import { useCallback, useEffect, useState } from 'react'

import { toast } from 'sonner'

import { metaApi } from '@/lib/api'
import { kgApi } from '@/lib/api/graph'
import { GraphService } from '@/lib/graph-service'
import { reportClientError } from '@/lib/client-logging'
import type { GraphData } from '@/lib/graph-parser'
import { detachPromise } from '@/lib/utils'
import type {
  KGEntityDetailResponse,
  KGEventDetailResponse,
  KGManualEntityInput,
  KGManualImportRequest,
  KGManualRelationInput,
  KGStatsResponse,
  RagTrace,
} from '@/types'

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
  dataset_id?: string
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
  setDataSource: Dispatch<SetStateAction<'live' | 'file'>>
  setTraceReplay: Dispatch<SetStateAction<RagTrace | null>>
  setKgStats: Dispatch<SetStateAction<KGStatsResponse | null>>
  setKgNodeDetail: Dispatch<SetStateAction<KGEntityDetailResponse | KGEventDetailResponse | null>>
  setIsLoading: Dispatch<SetStateAction<boolean>>
  setIsDetailOpen: Dispatch<SetStateAction<boolean>>
  setSelectedNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setViewMode: Dispatch<SetStateAction<'2d' | '3d'>>
  traceFileInputRef: RefObject<HTMLInputElement | null>
  manualKgFileInputRef: RefObject<HTMLInputElement | null>
  resetPathMode: () => void
  resetConnectMode: () => void
  resetExplainMode: () => void
}>

type UseGraphDataLoadingResult = Readonly<{
  loadInitialData: (
    source?: 'live',
    opts?: { includeEntityLinks?: boolean; includeRelationLinks?: boolean; minSharedEvents?: number }
  ) => Promise<void>
  handleTraceFileUpload: (event: ChangeEvent<HTMLInputElement>) => Promise<void>
  triggerTraceUpload: () => void
  handleManualKgFileUpload: (event: ChangeEvent<HTMLInputElement>) => Promise<void>
  triggerManualKgUpload: () => void
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
  traceFileInputRef,
  manualKgFileInputRef,
  resetPathMode,
  resetConnectMode,
  resetExplainMode,
}: UseGraphDataLoadingParams): UseGraphDataLoadingResult {
  const [autoLoadedGraphKey, setAutoLoadedGraphKey] = useState<string | null>(null)

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
      source: 'live' = 'live',
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
          includeEntityLinks: includeLinks,
          includeRelationLinks: includeRels,
          minSharedEvents: sharedThreshold,
          maxEntityLinks,
          documentIds: scopedDocumentIds?.length ? scopedDocumentIds : undefined,
          datasetId: scope.datasetId || undefined,
          pipelineHash: scope.pipelineHash || undefined,
        })

        setGraphData(data)
        setViewMode('3d')
        setDataSource(source)
        setTraceReplay(null)
        setFileName(
          scope.datasetId
            ? '知识库图谱'
            : scope.pipelineHash
              ? '批次图谱'
              : scopeParams
                ? '范围图谱'
                : '知识图谱'
        )

        try {
          const meta = await metaApi.get()
          if (meta.features?.kg_enabled === false) {
            setKgStats(null)
          } else {
            const stats = await kgApi.getStats(scopeParams || undefined)
            setKgStats(stats)
          }
        } catch {
          setKgStats(null)
        }

        resetGraphSurface()
      } catch (error) {
        reportClientError('Failed to fetch graph data', error)
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
      : 'default-live'
    if (autoLoadedGraphKey === autoLoadKey) return

    if (scope.hasScope && scope.datasetId && scope.directDocIds.length === 0 && scopedDocumentIds === null) return

    setAutoLoadedGraphKey(autoLoadKey)
    detachPromise(loadInitialData('live'))
  }, [autoLoadedGraphKey, loadInitialData, scope, scopedDocumentIds])

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
        reportClientError('Failed to import trace JSON', error)
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

  const parseManualKgPayload = useCallback((text: string, fileName: string): KGManualImportRequest => {
    const trimmed = text.trim()
    if (!trimmed) {
      throw new Error('empty manual KG file')
    }

    const firstString = (...values: unknown[]) => values.find((value): value is string => typeof value === 'string') ?? ''
    const coerceRows = (rows: unknown[]): KGManualImportRequest => {
      const entities: KGManualEntityInput[] = []
      const relations: KGManualRelationInput[] = []
      for (const row of rows) {
        if (!row || typeof row !== 'object') continue
        const item = row as Record<string, unknown>
        const kind = firstString(item.kind, item.row_type, item.type_hint).toLowerCase()
        if (kind === 'relation' || ('subject' in item && 'object' in item && 'predicate' in item)) {
          relations.push(item as unknown as KGManualRelationInput)
          continue
        }
        if (kind === 'entity' || ('name' in item && 'type' in item)) {
          entities.push(item as unknown as KGManualEntityInput)
        }
      }
      return {
        name: fileName.replace(/\.(jsonl|json)$/i, '') || '手动知识图谱导入',
        entities,
        relations,
      }
    }

    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      const parsed = JSON.parse(trimmed)
      if (Array.isArray(parsed)) return coerceRows(parsed)
      if (parsed && typeof parsed === 'object') {
        const payload = parsed as KGManualImportRequest
        return {
          name: payload.name || fileName.replace(/\.(jsonl|json)$/i, '') || '手动知识图谱导入',
          entities: Array.isArray(payload.entities) ? payload.entities : [],
          relations: Array.isArray(payload.relations) ? payload.relations : [],
          import_id: payload.import_id,
          dataset_id: payload.dataset_id,
          dataset_name: payload.dataset_name,
          pipeline_hash: payload.pipeline_hash,
          replace_existing: payload.replace_existing,
          upsert_entities: payload.upsert_entities,
          allow_label_truncation: payload.allow_label_truncation,
          index_vectors: payload.index_vectors,
        }
      }
    }

    const rows = trimmed
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => JSON.parse(line))
    return coerceRows(rows)
  }, [])

  const handleManualKgFileUpload = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      if (!file) return

      setIsLoading(true)
      try {
        const payload = parseManualKgPayload(await file.text(), file.name)
        const preview = await kgApi.previewManualImport(payload)
        if (!preview.valid) {
          const first = preview.issues?.find((issue) => issue.level === 'error') || preview.issues?.[0]
          toast.error(first ? `KG 导入预检失败：${first.message}` : 'KG 导入预检失败')
          return
        }

        const imported = await kgApi.importManualGraph(payload)
        if (!imported.valid) {
          toast.error(imported.issues?.[0]?.message || 'KG 导入失败')
          return
        }
        toast.success(`KG 已导入：实体 ${imported.stats.entities}，关系 ${imported.stats.relations}`)
        await loadInitialData('live')
      } catch (error) {
        reportClientError('Failed to import manual KG', error)
        toast.error('导入 KG 失败：请检查 JSON / JSONL 格式或后端校验信息')
      } finally {
        setIsLoading(false)
        event.target.value = ''
      }
    },
    [loadInitialData, parseManualKgPayload, setIsLoading]
  )

  const triggerManualKgUpload = useCallback(() => {
    manualKgFileInputRef.current?.click()
  }, [manualKgFileInputRef])

  return {
    loadInitialData,
    handleTraceFileUpload,
    triggerTraceUpload,
    handleManualKgFileUpload,
    triggerManualKgUpload,
  }
}

export type { UseGraphDataLoadingResult }
