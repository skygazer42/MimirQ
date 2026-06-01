/**
 * Index audit runner for retrieval diagnostics.
 */
'use client'

import { useQuery } from '@tanstack/react-query'
import { useCallback } from 'react'
import { toast } from 'sonner'

import type { IndexAuditResponse } from '@/types'
import { observabilityApi } from '@/lib/api/observability'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'

type UseIndexAuditOptions = {
  selectedDatasetId?: string
}

export function useIndexAudit({ selectedDatasetId }: UseIndexAuditOptions) {
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

  return {
    indexAudit: data ?? null,
    indexAuditLoading: isFetching,
    indexAuditError: error ? formatApiError(error, 'Index Audit 失败') : null,
    runIndexAudit,
  }
}
