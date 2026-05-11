'use client'

import { useQuery } from '@tanstack/react-query'

import { datasetApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import type { Dataset } from '@/types'

export function useDatasets() {
  const listParams = { skip: 0, limit: 200 }
  const datasetsQuery = useQuery<Dataset[]>({
    queryKey: queryKeys.datasets.list(listParams),
    queryFn: async () => {
      const res = await datasetApi.list(listParams)
      return res.items || []
    },
  })

  const refreshDatasets = async () => {
    await datasetsQuery.refetch()
  }

  return {
    datasets: datasetsQuery.data || [],
    isLoading: datasetsQuery.isLoading,
    error: datasetsQuery.error,
    refreshDatasets,
  }
}
