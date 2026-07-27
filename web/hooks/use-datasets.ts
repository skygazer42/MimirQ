'use client'

import { useQuery } from '@tanstack/react-query'

import { datasetApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import type { Dataset } from '@/types'

export function useDatasets() {
  const listParams = { exhaustive: true }
  const datasetsQuery = useQuery<Dataset[]>({
    queryKey: queryKeys.datasets.exhaustive(listParams),
    queryFn: async () => {
      return datasetApi.listAll()
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
