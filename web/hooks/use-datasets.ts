'use client'

import { useQuery } from '@tanstack/react-query'

import { datasetApi } from '@/lib/api/datasets'
import { queryKeys } from '@/lib/query-keys'
import type { Dataset } from '@/types/datasets'

const EMPTY_DATASETS: Dataset[] = []

export function useDatasets() {
  const {
    data: datasets = EMPTY_DATASETS,
    isLoading,
    isFetching,
    error,
    refetch: refreshDatasets,
  } = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
  })

  return { datasets, isLoading, isFetching, error, refreshDatasets }
}
