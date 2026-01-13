'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { PipelineCapabilitiesResponse } from '@/types'
import { pipelineApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'

type PipelineCapabilitiesContextValue = {
  capabilities: PipelineCapabilitiesResponse | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  parserBackendAvailable: (name?: string) => boolean | undefined
  chunkStrategyAvailable: (name?: string) => boolean | undefined
}

const PipelineCapabilitiesContext = createContext<PipelineCapabilitiesContextValue | null>(null)

function normalizeParserBackendName(value?: string) {
  const raw = (value || '').toLowerCase().trim()
  const normalized = raw.replace(/_/g, '-')
  if (normalized === 'magic-pdf') return 'magicpdf'
  if (normalized === 'olm-ocr') return 'olmocr'
  if (normalized === 'olmocr-pdf') return 'olmocr'
  if (normalized === 'etl-4llm') return 'etl4llm'
  if (normalized === 'bisheng-unstructured') return 'etl4llm'
  if (normalized === 'bishengunstructured') return 'etl4llm'
  if (normalized === 'bisheng') return 'etl4llm'
  return normalized
}

function normalizeChunkStrategyName(value?: string) {
  return (value || '').toLowerCase().trim()
}

export function PipelineCapabilitiesProvider({ children }: { children: React.ReactNode }) {
  const [capabilities, setCapabilities] = useState<PipelineCapabilitiesResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await pipelineApi.getCapabilities()
      setCapabilities(data)
      setError(null)
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to load pipeline capabilities'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

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
