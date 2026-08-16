/**
 * Index audit runner for retrieval diagnostics.
 */
'use client'

import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import type {
  IndexAuditReconcileResponse,
  IndexAuditReconcileStatusResponse,
  IndexAuditResponse,
} from '@/types'
import { observabilityApi } from '@/lib/api/observability'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'

type UseIndexAuditOptions = {
  selectedDatasetId?: string
  selectedDocumentIds?: string[]
}

type ReconcileState = {
  status: 'idle' | 'loading' | 'success' | 'error'
  message: string | null
  taskId: string | null
  backendStatus: IndexAuditReconcileStatusResponse['status'] | null
  currentIndexReadiness: string | null
}

type ReconcileStatusPollResult = Pick<
  ReconcileState,
  'status' | 'message' | 'backendStatus' | 'currentIndexReadiness'
>

const RECONCILE_STATUS_POLL_DELAY_MS = 2500
const RECONCILE_STATUS_MAX_ATTEMPTS = 12

function readReconcileTaskId(
  payload: IndexAuditReconcileResponse | null
): string | null {
  if (!payload) return null
  if (typeof payload.task_id === 'string' && payload.task_id.trim())
    return payload.task_id.trim()
  if (
    typeof payload.reconcile_task_id === 'string' &&
    payload.reconcile_task_id.trim()
  )
    return payload.reconcile_task_id.trim()
  return null
}

function readCurrentIndexReadiness(
  payload: IndexAuditReconcileStatusResponse | null | undefined
): string | null {
  const readiness = payload?.current_index_readiness
  if (!readiness) return null

  const errorChannels = Array.isArray(readiness.error_channels)
    ? readiness.error_channels.filter(Boolean)
    : []
  if (errorChannels.length > 0) {
    return `error: ${errorChannels.join(', ')}`
  }

  const pendingChannels = Array.isArray(readiness.pending_channels)
    ? readiness.pending_channels.filter(Boolean)
    : []
  if (pendingChannels.length > 0) {
    return `pending: ${pendingChannels.join(', ')}`
  }

  if (readiness.ready === true) return 'ready'
  if (readiness.ready === false) return 'not ready'
  return null
}

function readReconcileReason(
  payload: IndexAuditReconcileStatusResponse | null | undefined
): string | null {
  return typeof payload?.reason === 'string' && payload.reason.trim()
    ? payload.reason.trim()
    : null
}

export function buildIndexAuditReconcilePayload(
  datasetId: string,
  documentId: string
): { dataset_id: string; document_id: string } {
  return {
    dataset_id: datasetId,
    document_id: documentId,
  }
}

export async function pollIndexAuditReconcileStatus(args: {
  datasetId: string
  documentId: string
  fetchStatus: (
    datasetId: string,
    documentId: string
  ) => Promise<IndexAuditReconcileStatusResponse>
  isActive?: () => boolean
  maxAttempts?: number
  wait?: (attempt: number) => Promise<void>
  onUpdate?: (state: ReconcileStatusPollResult) => void
}): Promise<ReconcileStatusPollResult> {
  const {
    datasetId,
    documentId,
    fetchStatus,
    isActive = () => true,
    maxAttempts = RECONCILE_STATUS_MAX_ATTEMPTS,
    onUpdate,
    wait = () =>
      new Promise((resolve) =>
        globalThis.window.setTimeout(resolve, RECONCILE_STATUS_POLL_DELAY_MS)
      ),
  } = args

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (attempt > 0) {
      await wait(attempt)
    }
    if (!isActive()) {
      return {
        status: 'error',
        message: '索引修复轮询已停止',
        backendStatus: null,
        currentIndexReadiness: null,
      }
    }

    const payload = await fetchStatus(datasetId, documentId)
    if (!isActive()) {
      return {
        status: 'error',
        message: '索引修复轮询已停止',
        backendStatus: null,
        currentIndexReadiness: null,
      }
    }

    const currentIndexReadiness = readCurrentIndexReadiness(payload)
    const reason = readReconcileReason(payload)

    if (payload.status === 'ready') {
      const nextState = {
        status: 'success' as const,
        message: currentIndexReadiness
          ? `索引修复完成 · ${currentIndexReadiness}`
          : '索引修复完成',
        backendStatus: payload.status,
        currentIndexReadiness,
      }
      onUpdate?.(nextState)
      return nextState
    }

    if (payload.status === 'error') {
      const nextState = {
        status: 'error' as const,
        message: reason || '索引修复失败',
        backendStatus: payload.status,
        currentIndexReadiness,
      }
      onUpdate?.(nextState)
      return nextState
    }

    const nextState = {
      status: 'loading' as const,
      message:
        payload.status === 'pending'
          ? currentIndexReadiness
            ? `索引修复进行中 · ${currentIndexReadiness}`
            : '索引修复进行中…'
          : currentIndexReadiness
            ? `索引状态仍未明确 · ${currentIndexReadiness}`
            : '索引状态仍未明确，继续等待后端刷新…',
      backendStatus: payload.status,
      currentIndexReadiness,
    }
    onUpdate?.(nextState)
  }

  const timeoutState = {
    status: 'error' as const,
    message: '索引修复状态轮询超时，请稍后手动刷新审计结果',
    backendStatus: 'unknown' as const,
    currentIndexReadiness: null,
  }
  onUpdate?.(timeoutState)
  return timeoutState
}

export function useIndexAudit({
  selectedDatasetId,
  selectedDocumentIds = [],
}: UseIndexAuditOptions) {
  const {
    data,
    error,
    isFetching,
    refetch,
  } = useQuery<IndexAuditResponse>({
    queryKey: queryKeys.indexAudit.result(selectedDatasetId || 'unselected'),
    queryFn: () => {
      if (!selectedDatasetId) {
        throw new Error('missing_dataset_id')
      }
      return observabilityApi.getIndexAudit({ dataset_id: selectedDatasetId })
    },
    enabled: false,
    retry: false,
  })
  const [reconcileState, setReconcileState] = useState<ReconcileState>({
    status: 'idle',
    message: null,
    taskId: null,
    backendStatus: null,
    currentIndexReadiness: null,
  })
  const pollAbortRef = useRef<AbortController | null>(null)
  const pollGenerationRef = useRef(0)
  const reconcileDocumentId =
    selectedDocumentIds.length === 1 ? selectedDocumentIds[0] : null
  const hasDocumentScope = reconcileDocumentId !== null

  const stopReconcilePolling = useCallback(() => {
    pollGenerationRef.current += 1
    pollAbortRef.current?.abort()
    pollAbortRef.current = null
  }, [])

  useEffect(() => {
    stopReconcilePolling()
    setReconcileState({
      status: 'idle',
      message: null,
      taskId: null,
      backendStatus: null,
      currentIndexReadiness: null,
    })
  }, [
    hasDocumentScope,
    selectedDatasetId,
    stopReconcilePolling,
  ])

  useEffect(() => stopReconcilePolling, [stopReconcilePolling])

  const runIndexAudit = useCallback(async () => {
    if (!selectedDatasetId) {
      toast.error('请先选择数据集再运行 Index Audit')
      return
    }

    const result = await refetch()
    if (result.error) {
      reportClientError('Index audit failed', result.error)
      toast.error(formatApiError(result.error, 'Index Audit 失败'))
      return
    }

    if (result.data) {
      toast.success('Index Audit 完成')
    }
  }, [refetch, selectedDatasetId])

  const reconcileIndexAudit = useCallback(async () => {
    if (!selectedDatasetId) {
      const message = '请先选择数据集再执行索引修复'
      setReconcileState({
        status: 'error',
        message,
        taskId: null,
        backendStatus: null,
        currentIndexReadiness: null,
      })
      toast.error(message)
      return
    }
    if (!hasDocumentScope) return

    setReconcileState({
      status: 'loading',
      message: '正在提交索引修复任务…',
      taskId: null,
      backendStatus: null,
      currentIndexReadiness: null,
    })
    try {
      const data = await observabilityApi.reconcileIndexAudit(
        buildIndexAuditReconcilePayload(
          selectedDatasetId,
          reconcileDocumentId
        )
      )
      const taskId = readReconcileTaskId(data ?? null)
      const message =
        (typeof data?.message === 'string' && data.message.trim()) ||
        (taskId ? `已入队修复任务 ${taskId}` : '已提交索引修复任务')
      setReconcileState({
        status: 'loading',
        message,
        taskId,
        backendStatus: null,
        currentIndexReadiness: null,
      })
      toast.success(message)

      stopReconcilePolling()
      const generation = pollGenerationRef.current + 1
      pollGenerationRef.current = generation
      const controller = new AbortController()
      pollAbortRef.current = controller

      const finalState = await pollIndexAuditReconcileStatus({
        datasetId: selectedDatasetId,
        documentId: reconcileDocumentId,
        fetchStatus: (datasetId, documentId) =>
          observabilityApi.getIndexAuditReconcileStatus(
            {
              dataset_id: datasetId,
              document_id: documentId,
            },
            { signal: controller.signal }
          ),
        isActive: () =>
          !controller.signal.aborted &&
          pollGenerationRef.current === generation,
        onUpdate: (nextState) => {
          setReconcileState({
            ...nextState,
            taskId,
          })
        },
      })
      if (controller.signal.aborted || pollGenerationRef.current !== generation) {
        return
      }
      setReconcileState({
        ...finalState,
        taskId,
      })
      pollAbortRef.current = null
    } catch (err) {
      if (
        err &&
        typeof err === 'object' &&
        'name' in err &&
        (err as { name?: string }).name === 'CanceledError'
      ) {
        return
      }
      reportClientError('Index audit reconcile failed', err)
      const message = formatApiError(err, '索引修复提交失败')
      setReconcileState({
        status: 'error',
        message,
        taskId: null,
        backendStatus: null,
        currentIndexReadiness: null,
      })
      toast.error(message)
    }
  }, [
    hasDocumentScope,
    reconcileDocumentId,
    selectedDatasetId,
    stopReconcilePolling,
  ])

  return {
    indexAudit: data ?? null,
    indexAuditLoading: isFetching,
    indexAuditError: error ? formatApiError(error, 'Index Audit 失败') : null,
    indexAuditHasDocumentScope: hasDocumentScope,
    indexAuditReconcileState: reconcileState,
    reconcileIndexAudit,
    runIndexAudit,
  }
}
