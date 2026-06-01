/**
 * Connector runs management (list/cancel/retry/resume) shared by knowledge workbench.
 */
'use client'

import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { toast } from 'sonner'

import type { ConnectorRunOut } from '@/types'
import { connectorApi } from '@/lib/api/connectors'
import { formatApiError } from '@/lib/api-errors'
import { reportClientWarning } from '@/lib/client-logging'
import { detachPromise } from '@/lib/utils'
import { queryKeys } from '@/lib/query-keys'


export type ConnectorRunsListParams = {
  datasetId?: string
  limit?: number
}

type UseConnectorRunsOptions = {
  selectedDatasetId?: string
  limit?: number
  loadDocuments?: () => void | Promise<void>
}

type ConnectorRunsScope = {
  datasetId?: string
  limit: number
}

export function useConnectorRuns({ selectedDatasetId, limit = 20, loadDocuments }: UseConnectorRunsOptions) {
  const queryClient = useQueryClient()
  const [scope, setScope] = useState<ConnectorRunsScope>({ datasetId: selectedDatasetId, limit })
  const [enabled, setEnabled] = useState(false)

  const queryParams = useMemo(
    () => ({
      datasetId: scope.datasetId,
      limit: scope.limit,
    }),
    [scope.datasetId, scope.limit]
  )

  const queryFn = useCallback(async () => {
    const res = await connectorApi.listRuns({
      limit: queryParams.limit,
      dataset_id: queryParams.datasetId,
    })
    return res.items || []
  }, [queryParams.datasetId, queryParams.limit])

  const {
    data: connectorRuns = [],
    dataUpdatedAt,
    isFetching,
    isLoading,
  } = useQuery<ConnectorRunOut[]>({
    queryKey: queryKeys.connectors.runs(queryParams),
    queryFn,
    enabled,
    placeholderData: keepPreviousData,
  })

  const loadConnectorRuns = useCallback(
    async (params?: ConnectorRunsListParams) => {
      const nextScope = {
        datasetId: params?.datasetId ?? selectedDatasetId,
        limit: params?.limit ?? limit,
      }
      setScope(nextScope)
      setEnabled(true)

      try {
        await queryClient.fetchQuery({
          queryKey: queryKeys.connectors.runs(nextScope),
          queryFn: async () => {
            const res = await connectorApi.listRuns({
              limit: nextScope.limit,
              dataset_id: nextScope.datasetId,
            })
            return res.items || []
          },
        })
      } catch (err) {
        reportClientWarning('Load connector runs failed', err)
      }
    },
    [limit, queryClient, selectedDatasetId]
  )

  const refreshSelectedDatasetRuns = useCallback(async () => {
    await loadConnectorRuns({ datasetId: selectedDatasetId })
  }, [loadConnectorRuns, selectedDatasetId])

  const cancelConnectorRun = useCallback(
    async (runId: string) => {
      if (!runId) return
      try {
        await connectorApi.cancelRun(runId)
        toast.success('已取消导入任务')
        detachPromise(refreshSelectedDatasetRuns())
      } catch (error: unknown) {
        toast.error(formatApiError(error, '取消导入任务失败'))
      }
    },
    [refreshSelectedDatasetRuns]
  )

  const retryFailedConnectorRun = useCallback(
    async (runId: string) => {
      if (!runId) return
      try {
        const next = await connectorApi.retryFailed(runId)
        toast.success(`已创建重试任务：${String(next.id || '').slice(0, 8)}`)
        detachPromise(refreshSelectedDatasetRuns())
        detachPromise(loadDocuments?.())
      } catch (error: unknown) {
        toast.error(formatApiError(error, '重试失败项失败'))
      }
    },
    [loadDocuments, refreshSelectedDatasetRuns]
  )

  const resumeConnectorRun = useCallback(
    async (runId: string) => {
      if (!runId) return
      try {
        const next = await connectorApi.resumeRun(runId)
        toast.success(`已创建续跑任务：${String(next.id || '').slice(0, 8)}`)
        detachPromise(refreshSelectedDatasetRuns())
        detachPromise(loadDocuments?.())
      } catch (error: unknown) {
        toast.error(formatApiError(error, '续跑失败'))
      }
    },
    [loadDocuments, refreshSelectedDatasetRuns]
  )

  return {
    connectorRuns,
    connectorRunsLoading: enabled && (isLoading || isFetching),
    connectorRunsUpdatedAt: dataUpdatedAt || null,
    loadConnectorRuns,
    refreshSelectedDatasetRuns,
    cancelConnectorRun,
    retryFailedConnectorRun,
    resumeConnectorRun,
  }
}
