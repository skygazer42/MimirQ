/**
 * Index audit runner for retrieval diagnostics.
 */
'use client'

import { useQuery } from '@tanstack/react-query'
import { useCallback, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { toast } from 'sonner'

import type { IndexAuditReconcileStatusResponse } from '@/types/observability'
import { observabilityApi } from '@/lib/api/observability'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
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

type ReconcileStatusPollResult = Pick<ReconcileState, 'status' | 'message' | 'backendStatus' | 'currentIndexReadiness'>

const RECONCILE_STATUS_POLL_DELAY_MS = 2500
const RECONCILE_STATUS_MAX_ATTEMPTS = 12
const IDLE_RECONCILE_STATE: ReconcileState = {
  status: 'idle',
  message: null,
  taskId: null,
  backendStatus: null,
  currentIndexReadiness: null,
}
const STOPPED_RECONCILE_STATUS: ReconcileStatusPollResult = {
  status: 'error',
  message: '索引修复轮询已停止',
  backendStatus: null,
  currentIndexReadiness: null,
}

function readCurrentIndexReadiness(payload: IndexAuditReconcileStatusResponse): string | null {
  const readiness = payload.current_index_readiness
  if (!readiness) return null

  const errorChannels = readiness.error_channels?.filter(Boolean)
  if (errorChannels !== undefined && errorChannels.length > 0) {
    return `error: ${errorChannels.join(', ')}`
  }

  const pendingChannels = readiness.pending_channels?.filter(Boolean)
  if (pendingChannels !== undefined && pendingChannels.length > 0) {
    return `pending: ${pendingChannels.join(', ')}`
  }

  if (readiness.ready === true) return 'ready'
  if (readiness.ready === false) return 'not ready'
  return null
}

export function buildIndexAuditReconcilePayload(
  datasetId: string,
  documentId: string,
): { dataset_id: string; document_id: string } {
  return {
    dataset_id: datasetId,
    document_id: documentId,
  }
}

export async function pollIndexAuditReconcileStatus(args: {
  datasetId: string
  documentId: string
  fetchStatus: (datasetId: string, documentId: string) => Promise<IndexAuditReconcileStatusResponse>
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
    wait = () => new Promise((resolve) => globalThis.window.setTimeout(resolve, RECONCILE_STATUS_POLL_DELAY_MS)),
  } = args

  let lastState: ReconcileStatusPollResult | null = null
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (attempt > 0) {
      await wait(attempt)
    }
    if (!isActive()) return STOPPED_RECONCILE_STATUS

    const payload = await fetchStatus(datasetId, documentId)
    if (!isActive()) return STOPPED_RECONCILE_STATUS

    const currentIndexReadiness = readCurrentIndexReadiness(payload)

    if (payload.status === 'ready') {
      const nextState: ReconcileStatusPollResult = {
        status: 'success',
        message: currentIndexReadiness ? `索引修复完成 · ${currentIndexReadiness}` : '索引修复完成',
        backendStatus: payload.status,
        currentIndexReadiness,
      }
      onUpdate?.(nextState)
      return nextState
    }

    if (payload.status === 'error') {
      const reason = payload.reason?.trim()
      const nextState: ReconcileStatusPollResult = {
        status: 'error',
        message: reason ? reason : '索引修复失败',
        backendStatus: payload.status,
        currentIndexReadiness,
      }
      onUpdate?.(nextState)
      return nextState
    }

    const pending = payload.status === 'pending'
    let message = pending ? '索引修复进行中…' : '索引状态仍未明确，继续等待后端刷新…'
    if (currentIndexReadiness !== null) {
      const status = pending ? '索引修复进行中' : '索引状态仍未明确'
      message = `${status} · ${currentIndexReadiness}`
    }
    lastState = {
      status: 'loading',
      message,
      backendStatus: payload.status,
      currentIndexReadiness,
    }
    onUpdate?.(lastState)
  }

  const timeoutState: ReconcileStatusPollResult = {
    status: 'error',
    message: '索引修复状态轮询超时，请稍后手动刷新审计结果',
    backendStatus: lastState?.backendStatus ?? null,
    currentIndexReadiness: lastState?.currentIndexReadiness ?? null,
  }
  onUpdate?.(timeoutState)
  return timeoutState
}

export function useIndexAudit({ selectedDatasetId, selectedDocumentIds = [] }: UseIndexAuditOptions) {
  const { data, error, isFetching, refetch } = useQuery({
    queryKey: queryKeys.indexAudit.result(selectedDatasetId),
    queryFn: ({ signal }) => {
      if (!selectedDatasetId) {
        throw new Error('missing_dataset_id')
      }
      return observabilityApi.getIndexAudit({ dataset_id: selectedDatasetId }, { signal })
    },
    enabled: false,
    retry: false,
  })
  const [reconcileState, setReconcileState] = useState(IDLE_RECONCILE_STATE)
  const pollAbortRef = useRef<AbortController | null>(null)
  const reconcileSessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const reconcileDocumentId = selectedDocumentIds.length === 1 ? selectedDocumentIds[0] : null
  const reconcileScope = useMemo(
    () => ({ datasetId: selectedDatasetId, documentId: reconcileDocumentId, sessionKey: reconcileSessionKey }),
    [selectedDatasetId, reconcileDocumentId, reconcileSessionKey],
  )
  const activeReconcileScopeRef = useRef<typeof reconcileScope | null>(reconcileScope)

  const stopReconcilePolling = useCallback(() => {
    pollAbortRef.current?.abort()
    pollAbortRef.current = null
  }, [])

  useLayoutEffect(() => {
    activeReconcileScopeRef.current = reconcileScope
    stopReconcilePolling()
    setReconcileState(IDLE_RECONCILE_STATE)
    return () => {
      activeReconcileScopeRef.current = null
      stopReconcilePolling()
    }
  }, [reconcileScope, stopReconcilePolling])

  const runIndexAudit = useCallback(async () => {
    if (!selectedDatasetId) {
      toast.error('请先选择数据集再运行 Index Audit')
      return
    }

    const sessionKey = getAuthSessionKey()
    const result = await refetch()
    if (activeReconcileScopeRef.current?.datasetId !== selectedDatasetId || getAuthSessionKey() !== sessionKey) return
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
    if (activeReconcileScopeRef.current !== reconcileScope || pollAbortRef.current !== null) return
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
    if (reconcileDocumentId === null) return

    const controller = new AbortController()
    const sessionKey = getAuthSessionKey()
    pollAbortRef.current = controller
    const isCurrent = () =>
      activeReconcileScopeRef.current === reconcileScope &&
      pollAbortRef.current === controller &&
      getAuthSessionKey() === sessionKey
    let taskAccepted = false

    setReconcileState({
      status: 'loading',
      message: '正在提交索引修复任务…',
      taskId: null,
      backendStatus: null,
      currentIndexReadiness: null,
    })
    try {
      const data = await observabilityApi.reconcileIndexAudit(
        buildIndexAuditReconcilePayload(selectedDatasetId, reconcileDocumentId),
      )
      if (!isCurrent()) return
      const taskId = data.task_id
      if (data.status === 'noop_ready') {
        const message = '文档索引已就绪，无需修复'
        setReconcileState({
          status: 'success',
          message,
          taskId,
          backendStatus: 'ready',
          currentIndexReadiness: 'ready',
        })
        toast.success(message)
        void refetch()
        return
      }
      if (data.status !== 'enqueued' && data.status !== 'already_queued') {
        let message = '索引修复未能入队'
        if (data.reason === 'task_queue_disabled') message = '后台任务队列未启用，索引修复未提交'
        else if (data.status === 'unsupported') message = '当前范围不支持索引修复'
        setReconcileState({
          status: 'error',
          message,
          taskId,
          backendStatus: null,
          currentIndexReadiness: null,
        })
        toast.error(message)
        return
      }
      taskAccepted = true
      let message = taskId ? `已入队修复任务 ${taskId}` : '索引修复任务已入队'
      if (data.status === 'already_queued') message = '索引修复任务已在队列中，正在读取状态…'
      setReconcileState({
        status: 'loading',
        message,
        taskId,
        backendStatus: null,
        currentIndexReadiness: null,
      })
      toast.success(message)

      const result = await pollIndexAuditReconcileStatus({
        datasetId: selectedDatasetId,
        documentId: reconcileDocumentId,
        fetchStatus: (datasetId, documentId) =>
          observabilityApi.getIndexAuditReconcileStatus(
            {
              dataset_id: datasetId,
              document_id: documentId,
            },
            { signal: controller.signal },
          ),
        isActive: isCurrent,
        onUpdate: (nextState) => {
          setReconcileState({
            ...nextState,
            taskId,
          })
        },
      })
      if (result.status === 'success' && isCurrent()) void refetch()
    } catch (err) {
      if (!isCurrent()) return
      reportClientError('Index audit reconcile failed', err)
      const message = taskAccepted
        ? `修复任务已提交，读取状态失败。${formatApiError(err, '请稍后刷新审计结果')}`
        : formatApiError(err, '索引修复提交失败')
      setReconcileState((current) => ({ ...current, status: 'error', message }))
      toast.error(message)
    } finally {
      if (pollAbortRef.current === controller) pollAbortRef.current = null
    }
  }, [reconcileDocumentId, reconcileScope, refetch, selectedDatasetId])

  return {
    indexAudit: data ?? null,
    indexAuditLoading: isFetching,
    indexAuditError: error ? formatApiError(error, 'Index Audit 失败') : null,
    indexAuditHasDocumentScope: reconcileDocumentId !== null,
    indexAuditReconcileState: reconcileState,
    reconcileIndexAudit,
    runIndexAudit,
  }
}
