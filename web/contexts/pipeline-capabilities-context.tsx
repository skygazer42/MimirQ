'use client'

import { useQuery } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo } from 'react'
import type { PipelineCapabilitiesResponse } from '@/types'
import { pipelineApi } from '@/lib/api/pipeline'
import { formatApiError } from '@/lib/api-errors'
import { normalizeParserBackendName } from '@/lib/parser-compat'
import { queryKeys } from '@/lib/query-keys'

type PipelineCapabilitiesContextValue = {
  capabilities: PipelineCapabilitiesResponse | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  parserBackendAvailable: (name?: string) => boolean | undefined
  chunkStrategyAvailable: (name?: string) => boolean | undefined
}

const PipelineCapabilitiesContext = createContext<PipelineCapabilitiesContextValue | null>(null)

function normalizeChunkStrategyName(value?: string) {
  return (value || '').toLowerCase().trim()
}

export function PipelineCapabilitiesProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const {
    data,
    error: queryError,
    isFetching,
    isLoading,
    refetch,
  } = useQuery<PipelineCapabilitiesResponse>({
    queryKey: queryKeys.pipeline.capabilities,
    queryFn: () => pipelineApi.getCapabilities(),
    staleTime: 5 * 60_000,
  })

  const capabilities = data ?? null
  const loading = isLoading || isFetching
  const error = queryError ? formatApiError(queryError, 'Failed to load pipeline capabilities') : null

  const refresh = useCallback(async () => {
    await refetch()
  }, [refetch])

  const parserBackendMap = useMemo(() => {
    const map = new Map<string, boolean>()
    for (const item of capabilities?.pdf_backends || []) {
      map.set(normalizeParserBackendName(item.name), !!item.available)
    }
    return map
  }, [capabilities])

  const chunkStrategyMap = useMemo(() => {
    const map = new Map<string, boolean>()
    for (const item of capabilities?.chunk_strategies || []) {
      map.set(normalizeChunkStrategyName(item.name), !!item.available)
    }
    return map
  }, [capabilities])

  const value = useMemo<PipelineCapabilitiesContextValue>(() => ({
    capabilities,
    loading,
    error,
    refresh,
    parserBackendAvailable: (name) => {
      const key = normalizeParserBackendName(name)
      if (!key) return undefined
      return parserBackendMap.get(key)
    },
    chunkStrategyAvailable: (name) => {
      const key = normalizeChunkStrategyName(name)
      if (!key) return undefined
      return chunkStrategyMap.get(key)
    },
  }), [capabilities, loading, error, refresh, parserBackendMap, chunkStrategyMap])

  return (
    <PipelineCapabilitiesContext.Provider value={value}>
      {children}
    </PipelineCapabilitiesContext.Provider>
  )
}

export function usePipelineCapabilities() {
  const ctx = useContext(PipelineCapabilitiesContext)
  if (!ctx) {
    throw new Error('usePipelineCapabilities must be used within PipelineCapabilitiesProvider')
  }
  return ctx
}
