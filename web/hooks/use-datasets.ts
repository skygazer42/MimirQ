'use client'

import { useCallback, useEffect, useState } from 'react'
import { datasetApi } from '@/lib/api'
import type { Dataset } from '@/types'
import { detachPromise } from '@/lib/utils'

export function useDatasets() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<unknown | null>(null)

  const loadDatasets = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await datasetApi.list({ skip: 0, limit: 200 })
      setDatasets(res.items || [])
    } catch (err) {
      console.error('Failed to load datasets:', err)
      setError(err)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    detachPromise(loadDatasets())
  }, [loadDatasets])

  return {
    datasets,
    isLoading,
    error,
    refreshDatasets: loadDatasets,
  }
}
