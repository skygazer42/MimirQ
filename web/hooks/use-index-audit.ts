/**
 * Index audit runner for retrieval diagnostics.
 */
'use client'

import { useCallback, useState } from 'react'
import { toast } from 'sonner'

import type { IndexAuditResponse } from '@/types'
import { observabilityApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'

type UseIndexAuditOptions = {
  selectedDatasetId?: string
}

export function useIndexAudit({ selectedDatasetId }: UseIndexAuditOptions) {
  const [indexAudit, setIndexAudit] = useState<IndexAuditResponse | null>(null)
  const [indexAuditLoading, setIndexAuditLoading] = useState(false)
  const [indexAuditError, setIndexAuditError] = useState<string | null>(null)

  const runIndexAudit = useCallback(async () => {
    if (!selectedDatasetId) {
      toast.error('请先选择数据集再运行 Index Audit')
      return
    }

    setIndexAuditLoading(true)
    setIndexAuditError(null)
    try {
      const res = await observabilityApi.getIndexAudit({ dataset_id: selectedDatasetId })
      setIndexAudit(res)
      toast.success('Index Audit 完成')
    } catch (err: any) {
      console.error('Index audit failed:', err)
      setIndexAuditError(formatApiError(err, 'Index Audit 失败'))
    } finally {
      setIndexAuditLoading(false)
    }
  }, [selectedDatasetId])

  return {
    indexAudit,
    indexAuditLoading,
    indexAuditError,
    runIndexAudit,
  }
}

