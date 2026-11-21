'use client'

import { useQuery } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react'
import type { PipelineCapabilitiesResponse } from '@/types/processing'
import { pipelineApi } from '@/lib/api/pipeline'
import { formatApiError } from '@/lib/api-errors'
import { isRetiredChunkStrategy } from '@/lib/chunk-strategies'
import { normalizeParserBackendName } from '@/lib/parser-compat'
import { queryKeys } from '@/lib/query-keys'

type PipelineCapabilitiesContextValue = {
  capabilities: PipelineCapabilitiesResponse | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  parserBackendAvailable: (name: string) => boolean | undefined
  chunkStrategyAvailable: (name?: string) => boolean | undefined
}

const PipelineCapabilitiesContext = createContext<PipelineCapabilitiesContextValue | null>(null)

function normalizeChunkStrategyName(value: string) {
  return value.toLowerCase().trim()
}

export function PipelineCapabilitiesProvider({ children }: Readonly<{ children: ReactNode }>) {
  const {
    data: capabilities = null,
    error: queryError,
    isFetching: loading,
    refetch,
  } = useQuery({
    queryKey: queryKeys.pipeline.capabilities,
    queryFn: ({ signal }) => pipelineApi.getCapabilities({ signal }),
    staleTime: 5 * 60_000,
  })

  const error = queryError ? formatApiError(queryError, 'Failed to load pipeline capabilities') : null

  const refresh = useCallback(async () => {
    await refetch()
  }, [refetch])

  const parserBackendMap = useMemo(
    () =>
      new Map<string, boolean>(
        capabilities?.pdf_backends.map(({ name, available }) => [normalizeParserBackendName(name), available]),
      ),
    [capabilities],
  )

  const chunkStrategyMap = useMemo(
    () =>
      new Map<string, boolean>(
        capabilities?.chunk_strategies.map(({ name, available }) => [normalizeChunkStrategyName(name), available]),
      ),
    [capabilities],
  )

  const value = useMemo<PipelineCapabilitiesContextValue>(
    () => ({
      capabilities,
      loading,
      error,
      refresh,
      parserBackendAvailable: (name) => parserBackendMap.get(normalizeParserBackendName(name)),
      chunkStrategyAvailable: (name) => {
        if (name === undefined) return undefined
        if (isRetiredChunkStrategy(name)) return false
        const key = normalizeChunkStrategyName(name)
        if (key.length === 0) return undefined
        return chunkStrategyMap.get(key)
      },
    }),
    [capabilities, loading, error, refresh, parserBackendMap, chunkStrategyMap],
  )

  return <PipelineCapabilitiesContext.Provider value={value}>{children}</PipelineCapabilitiesContext.Provider>
}

export function usePipelineCapabilities() {
  const context = useContext(PipelineCapabilitiesContext)
  if (context === null) {
    throw new Error('usePipelineCapabilities must be used within PipelineCapabilitiesProvider')
  }
  return context
}
