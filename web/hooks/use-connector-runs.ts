/**
 * Connector runs management (list/cancel/retry/resume) shared by knowledge workbench.
 */
'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'

import type { ConnectorRunOut } from '@/types/connectors'
import { connectorApi } from '@/lib/api/connectors'
import { formatApiError } from '@/lib/api-errors'
import { reportClientWarning } from '@/lib/client-logging'
import { detachPromise } from '@/lib/utils'
import { queryKeys } from '@/lib/query-keys'

type ConnectorRunsListParams = {
  datasetId?: string
  limit?: number
}

export type LoadConnectorRuns = (params?: ConnectorRunsListParams, options?: { selectScope?: boolean }) => Promise<void>

type UseConnectorRunsOptions = {
  selectedDatasetId?: string
}

type ConnectorRunsScope = {
  datasetId?: string
  limit: number
}

async function fetchConnectorRuns(scope: ConnectorRunsScope, signal: AbortSignal): Promise<ConnectorRunOut[]> {
  const res = await connectorApi.listRuns({ limit: scope.limit, dataset_id: scope.datasetId }, { signal })
  return res.items
}

const CONNECTOR_RUNS_LIMIT = 20

export function useConnectorRuns({ selectedDatasetId }: UseConnectorRunsOptions) {
  const queryClient = useQueryClient()
  const [scope, setScope] = useState<ConnectorRunsScope>({ datasetId: selectedDatasetId, limit: CONNECTOR_RUNS_LIMIT })
  const [enabled, setEnabled] = useState(false)

  const {
    data: connectorRuns = [],
    dataUpdatedAt,
    error,
    isFetching,
    isLoading,
  } = useQuery({
    queryKey: queryKeys.connectors.runs(scope),
    queryFn: ({ signal }) => fetchConnectorRuns(scope, signal),
    enabled,
  })

  const fetchRunsForScope = useCallback(
    async (targetScope: ConnectorRunsScope) => {
      try {
        await queryClient.fetchQuery({
          queryKey: queryKeys.connectors.runs(targetScope),
          staleTime: 0,
          queryFn: ({ signal }) => fetchConnectorRuns(targetScope, signal),
        })
      } catch (err) {
        reportClientWarning('Load connector runs failed', err)
      }
    },
    [queryClient],
  )

  const loadConnectorRuns = useCallback<LoadConnectorRuns>(
    async (params, options) => {
      const nextScope = {
        datasetId: params?.datasetId ?? selectedDatasetId,
        limit: params?.limit ?? CONNECTOR_RUNS_LIMIT,
      }
      if (options?.selectScope !== false) {
        setScope((current) =>
          current.datasetId === nextScope.datasetId && current.limit === nextScope.limit ? current : nextScope,
        )
        setEnabled(true)
      }
      await fetchRunsForScope(nextScope)
    },
    [fetchRunsForScope, selectedDatasetId],
  )

  const refreshActionDatasetRuns = useCallback(() => fetchRunsForScope(scope), [fetchRunsForScope, scope])

  const cancelConnectorRun = useCallback(
    async (runId: string) => {
      try {
        const run = await connectorApi.cancelRun(runId)
        if (run.status === 'cancelled') {
          toast.success('已取消导入任务')
        } else {
          toast.info('任务状态已变化，正在刷新列表')
        }
        detachPromise(refreshActionDatasetRuns())
      } catch (error: unknown) {
        toast.error(formatApiError(error, '取消导入任务失败'))
      }
    },
    [refreshActionDatasetRuns],
  )

  const retryFailedConnectorRun = useCallback(
    async (runId: string) => {
      try {
        const next = await connectorApi.retryFailed(runId)
        toast.success(`已创建重试任务：${next.id.slice(0, 8)}`)
        detachPromise(refreshActionDatasetRuns())
      } catch (error: unknown) {
        toast.error(formatApiError(error, '重试失败项失败'))
      }
    },
    [refreshActionDatasetRuns],
  )

  const resumeConnectorRun = useCallback(
    async (runId: string) => {
      try {
        const next = await connectorApi.resumeRun(runId)
        toast.success(`已创建续跑任务：${next.id.slice(0, 8)}`)
        detachPromise(refreshActionDatasetRuns())
      } catch (error: unknown) {
        toast.error(formatApiError(error, '续跑失败'))
      }
    },
    [refreshActionDatasetRuns],
  )

  return {
    connectorRuns,
    connectorRunsLoading: enabled && (isLoading || isFetching),
    connectorRunsError: error === null ? null : formatApiError(error, '加载导入任务失败'),
    connectorRunsUpdatedAt: dataUpdatedAt === 0 ? null : dataUpdatedAt,
    loadConnectorRuns,
    cancelConnectorRun,
    retryFailedConnectorRun,
    resumeConnectorRun,
  }
}
