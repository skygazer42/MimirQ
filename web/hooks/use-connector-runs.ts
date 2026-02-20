/**
 * Connector runs management (list/cancel/retry/resume) shared by knowledge workbench.
 */
'use client'

import { useCallback, useState } from 'react'
import { toast } from 'sonner'

import type { ConnectorRunOut } from '@/types'
import { connectorApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'

export type ConnectorRunsListParams = {
  datasetId?: string
  limit?: number
}

type UseConnectorRunsOptions = {
  selectedDatasetId?: string
  limit?: number
  loadDocuments?: () => void | Promise<void>
}

export function useConnectorRuns({ selectedDatasetId, limit = 20, loadDocuments }: UseConnectorRunsOptions) {
  const [connectorRuns, setConnectorRuns] = useState<ConnectorRunOut[]>([])
  const [connectorRunsLoading, setConnectorRunsLoading] = useState(false)
  const [connectorRunsUpdatedAt, setConnectorRunsUpdatedAt] = useState<number | null>(null)

  const loadConnectorRuns = useCallback(
    async (params?: ConnectorRunsListParams) => {
      setConnectorRunsLoading(true)
      try {
        const res = await connectorApi.listRuns({
          limit: params?.limit ?? limit,
          dataset_id: params?.datasetId,
        })
        setConnectorRuns(res.items || [])
        setConnectorRunsUpdatedAt(Date.now())
      } catch (err) {
        console.warn('Load connector runs failed:', err)
      } finally {
        setConnectorRunsLoading(false)
      }
    },
    [limit]
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
        void refreshSelectedDatasetRuns()
      } catch (err: any) {
        toast.error(formatApiError(err, '取消导入任务失败'))
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
        void refreshSelectedDatasetRuns()
        void loadDocuments?.()
      } catch (err: any) {
        toast.error(formatApiError(err, '重试失败项失败'))
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
        void refreshSelectedDatasetRuns()
        void loadDocuments?.()
      } catch (err: any) {
        toast.error(formatApiError(err, '续跑失败'))
      }
    },
    [loadDocuments, refreshSelectedDatasetRuns]
  )

  return {
    connectorRuns,
    connectorRunsLoading,
    connectorRunsUpdatedAt,
    loadConnectorRuns,
    refreshSelectedDatasetRuns,
    cancelConnectorRun,
    retryFailedConnectorRun,
    resumeConnectorRun,
  }
}
