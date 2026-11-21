'use client'

import type { ChangeEvent, Dispatch, RefObject, SetStateAction } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { toast } from 'sonner'

import { kgApi } from '@/lib/api/graph'
import { fetchInitialGraph } from '@/lib/graph-service'
import { reportClientError } from '@/lib/client-logging'
import { formatApiError } from '@/lib/api-errors'
import type { GraphData } from '@/lib/graph-types'
import { detachPromise } from '@/lib/utils'

import { buildGraphFromTrace, extractTraceFromPayload, type GraphTraceReplay } from './graph-page-utils'
import type { UseGraphPageStateResult } from './use-graph-page-state'

type UseGraphDataLoadingParams = Readonly<{
  scope: UseGraphPageStateResult['scope']
  scopedDocumentIds: string[] | null
  scopedDatasetDocIdsLoading: boolean
  refetchScopedDocuments: UseGraphPageStateResult['refetchScopedDocuments']
  scopeParams: UseGraphPageStateResult['scopeParams']
  includeEntityLinks: boolean
  includeRelationLinks: boolean
  minSharedEvents: number
  maxEntityLinks: number
  setGraphData: Dispatch<SetStateAction<GraphData>>
  setFileName: Dispatch<SetStateAction<string | null>>
  setDataSource: Dispatch<SetStateAction<'live' | 'file'>>
  setTraceReplay: Dispatch<SetStateAction<GraphTraceReplay | null>>
  setIsLoading: Dispatch<SetStateAction<boolean>>
  setViewMode: Dispatch<SetStateAction<'2d' | '3d'>>
  traceFileInputRef: RefObject<HTMLInputElement | null>
  manualKgFileInputRef: RefObject<HTMLInputElement | null>
  resetGraphSurface: () => void
}>

type UseGraphDataLoadingResult = Readonly<{
  liveGraphError: string | null
  loadLiveGraph: (options?: {
    refreshDocuments?: boolean
    includeEntityLinks?: boolean
    includeRelationLinks?: boolean
    minSharedEvents?: number
  }) => Promise<void>
  handleTraceFileUpload: (event: ChangeEvent<HTMLInputElement>) => Promise<void>
  triggerTraceUpload: () => void
  handleManualKgFileUpload: (event: ChangeEvent<HTMLInputElement>) => Promise<void>
  triggerManualKgUpload: () => void
}>

function parseManualKgPayload(text: string, fileName: string): Record<string, unknown> {
  const content = text.trim()
  if (content === '') throw new Error('知识图谱文件为空')
  const fileStem = fileName.replace(/\.(jsonl|json)$/i, '')
  const importName = fileStem === '' ? '手动知识图谱导入' : fileStem
  const isJsonLines = fileName.toLowerCase().endsWith('.jsonl')

  // The import preview validates the fields after the file records are grouped by kind.
  function groupRows(rows: unknown[]) {
    const entities: Record<string, unknown>[] = []
    const relations: Record<string, unknown>[] = []
    for (const [index, row] of rows.entries()) {
      if (typeof row !== 'object' || row === null || Array.isArray(row)) {
        throw new TypeError(`第 ${index + 1} 条记录必须是对象`)
      }
      const item = row as Record<string, unknown>
      const kind = [item.kind, item.row_type, item.type_hint].find((value) => typeof value === 'string')?.toLowerCase()
      if (kind === 'relation' || ('subject' in item && 'object' in item && 'predicate' in item)) {
        relations.push(item)
        continue
      }
      if (kind === 'entity' || ('name' in item && 'type' in item)) {
        entities.push(item)
        continue
      }
      throw new TypeError(`第 ${index + 1} 条记录无法识别为实体或关系`)
    }
    return { name: importName, entities, relations }
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(content)
  } catch (error) {
    if (!isJsonLines) throw error
  }
  if (Array.isArray(parsed)) return groupRows(parsed)
  if (parsed !== null && typeof parsed === 'object') {
    if (isJsonLines && !('entities' in parsed) && !('relations' in parsed)) return groupRows([parsed])
    const payload = parsed as Record<string, unknown>
    const { name, entities = [], relations = [] } = payload
    if (!Array.isArray(entities)) throw new TypeError('entities 必须是数组')
    if (!Array.isArray(relations)) throw new TypeError('relations 必须是数组')
    return {
      name: name === undefined || name === null || name === '' ? importName : name,
      entities,
      relations,
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
  if (!isJsonLines) throw new TypeError('知识图谱 JSON 必须是对象或数组')

  const rows = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line))
  return groupRows(rows)
}

export function useGraphDataLoading({
  scope,
  scopedDocumentIds,
  scopedDatasetDocIdsLoading,
  refetchScopedDocuments,
  scopeParams,
  includeEntityLinks,
  includeRelationLinks,
  minSharedEvents,
  maxEntityLinks,
  setGraphData,
  setFileName,
  setDataSource,
  setTraceReplay,
  setIsLoading,
  setViewMode,
  traceFileInputRef,
  manualKgFileInputRef,
  resetGraphSurface,
}: UseGraphDataLoadingParams): UseGraphDataLoadingResult {
  const [liveGraphError, setLiveGraphError] = useState<string | null>(null)
  const autoLoadScopeRef = useRef<string | null>(null)
  const graphLoadRef = useRef<AbortController | null>(null)
  const startGraphLoad = useCallback(() => {
    graphLoadRef.current?.abort()
    const request = new AbortController()
    graphLoadRef.current = request
    return request
  }, [])

  useEffect(
    () => () => {
      graphLoadRef.current?.abort()
      autoLoadScopeRef.current = null
    },
    [],
  )

  const loadLiveGraph = useCallback<UseGraphDataLoadingResult['loadLiveGraph']>(
    async (options) => {
      const request = startGraphLoad()
      const usesDatasetDocuments = scope.datasetId !== null && scope.directDocIds.length === 0
      const refreshDocuments = usesDatasetDocuments && options?.refreshDocuments === true
      if (usesDatasetDocuments && scopedDocumentIds === null && !refreshDocuments) {
        setIsLoading(false)
        if (scopedDatasetDocIdsLoading) toast.message('正在读取数据集文档…')
        return
      }

      setIsLoading(true)
      setLiveGraphError(null)
      try {
        if (refreshDocuments) {
          const documents = await refetchScopedDocuments()
          if (request.signal.aborted || !documents.isSuccess) return
          const ids = documents.data.items.map((document) => document.id)
          // The scope effect loads the graph when the document IDs change.
          if (scopedDocumentIds === null || ids.length !== scopedDocumentIds.length) return
          if (ids.some((id, index) => id !== scopedDocumentIds[index])) return
        }
        const data = await fetchInitialGraph(
          {
            includeEntityLinks: options?.includeEntityLinks ?? includeEntityLinks,
            includeRelationLinks: options?.includeRelationLinks ?? includeRelationLinks,
            minSharedEvents: options?.minSharedEvents ?? minSharedEvents,
            maxEntityLinks,
            documentIds: scopedDocumentIds?.length ? scopedDocumentIds : undefined,
            datasetId: scope.datasetId ?? undefined,
            pipelineHash: scope.pipelineHash ?? undefined,
          },
          request.signal,
        )
        if (request.signal.aborted) return

        setGraphData(data)
        setViewMode('2d')
        setDataSource('live')
        setTraceReplay(null)
        setFileName(
          scope.datasetId ? '知识库图谱' : scope.pipelineHash ? '批次图谱' : scopeParams ? '范围图谱' : '知识图谱',
        )

        resetGraphSurface()
      } catch (error) {
        if (!request.signal.aborted) {
          reportClientError('Failed to fetch graph data', error)
          const message = formatApiError(error, '图谱加载失败')
          setLiveGraphError(message)
          toast.error(message)
        }
      } finally {
        if (!request.signal.aborted) setIsLoading(false)
      }
    },
    [
      includeEntityLinks,
      includeRelationLinks,
      maxEntityLinks,
      minSharedEvents,
      refetchScopedDocuments,
      resetGraphSurface,
      scope,
      scopedDatasetDocIdsLoading,
      scopedDocumentIds,
      scopeParams,
      setDataSource,
      setFileName,
      setGraphData,
      setIsLoading,
      setTraceReplay,
      setViewMode,
      startGraphLoad,
    ],
  )

  useEffect(() => {
    const autoLoadKey = scope.hasScope
      ? JSON.stringify([scope.datasetId, scope.pipelineHash, scope.docLimit, scope.directDocIds, scopedDocumentIds])
      : 'default-live'
    if (autoLoadScopeRef.current === autoLoadKey) return
    autoLoadScopeRef.current = autoLoadKey

    graphLoadRef.current?.abort()
    setGraphData({ nodes: [], links: [] })
    setTraceReplay(null)
    setFileName(null)
    setDataSource('live')
    setIsLoading(false)
    setLiveGraphError(null)
    resetGraphSurface()

    if (scope.hasScope && scope.datasetId && scope.directDocIds.length === 0 && scopedDocumentIds === null) return

    detachPromise(loadLiveGraph())
  }, [
    loadLiveGraph,
    resetGraphSurface,
    scope,
    scopedDocumentIds,
    setDataSource,
    setFileName,
    setGraphData,
    setIsLoading,
    setTraceReplay,
  ])

  const handleTraceFileUpload = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.currentTarget.files?.[0]
      if (!file) return
      event.currentTarget.value = ''

      const request = startGraphLoad()
      setIsLoading(true)
      try {
        const text = await file.text()
        if (request.signal.aborted) return
        const payload = JSON.parse(text)
        const trace = extractTraceFromPayload(payload)
        if (!trace) {
          throw new Error('Invalid trace JSON')
        }

        const built = buildGraphFromTrace(trace)
        setTraceReplay(trace)
        setGraphData(built.graph)
        setFileName(file.name)
        setDataSource('file')
        setLiveGraphError(null)
        resetGraphSurface()
        setViewMode('2d')
        toast.success('Trace 已导入（可点击右下角 Play 回放）')
      } catch (error) {
        if (!request.signal.aborted) {
          reportClientError('Failed to import trace JSON', error)
          toast.error('导入 Trace 失败：请检查 JSON 格式或粘贴/导出内容是否完整')
        }
      } finally {
        if (!request.signal.aborted) setIsLoading(false)
      }
    },
    [
      resetGraphSurface,
      setDataSource,
      setFileName,
      setGraphData,
      setIsLoading,
      setTraceReplay,
      setViewMode,
      startGraphLoad,
    ],
  )

  const triggerTraceUpload = useCallback(() => {
    traceFileInputRef.current?.click()
  }, [traceFileInputRef])

  const handleManualKgFileUpload = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.currentTarget.files?.[0]
      if (!file) return

      const request = startGraphLoad()
      const isCurrent = () => !request.signal.aborted
      event.currentTarget.value = ''
      setIsLoading(true)
      try {
        const payload = parseManualKgPayload(await file.text(), file.name)
        if (!isCurrent()) return
        const preview = await kgApi.previewManualImport(payload, { signal: request.signal })
        if (!isCurrent()) return
        if (!preview.valid) {
          const first = preview.issues?.find((issue) => issue.level === 'error') ?? preview.issues?.[0]
          toast.error(first ? `KG 导入预检失败：${first.message}` : 'KG 导入预检失败')
          return
        }

        const imported = await kgApi.importManualGraph(payload)
        if (!isCurrent()) return
        if (!imported.valid) {
          toast.error(imported.issues?.[0]?.message || 'KG 导入失败')
          return
        }
        toast.success(`KG 已导入：实体 ${imported.stats.entities}，关系 ${imported.stats.relations}`)
        await loadLiveGraph()
      } catch (error) {
        if (!isCurrent()) return
        reportClientError('Failed to import manual KG', error)
        toast.error(formatApiError(error, '导入 KG 失败，请检查文件格式或后端校验信息'))
      } finally {
        if (isCurrent()) setIsLoading(false)
      }
    },
    [loadLiveGraph, setIsLoading, startGraphLoad],
  )

  const triggerManualKgUpload = useCallback(() => {
    manualKgFileInputRef.current?.click()
  }, [manualKgFileInputRef])

  return {
    liveGraphError,
    loadLiveGraph,
    handleTraceFileUpload,
    triggerTraceUpload,
    handleManualKgFileUpload,
    triggerManualKgUpload,
  }
}

export type { UseGraphDataLoadingResult }
