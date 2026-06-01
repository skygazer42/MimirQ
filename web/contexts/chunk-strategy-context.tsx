'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'

const STORAGE_KEY = 'mimirq_chunk_strategy'

type ChunkStrategyContextValue = {
  chunkStrategy: string
  setChunkStrategy: (value: string) => void
}

const ChunkStrategyContext = createContext<ChunkStrategyContextValue | null>(null)

export function ChunkStrategyProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [chunkStrategy, setChunkStrategy] = useState('langchain_recursive')
  const { capabilities, chunkStrategyAvailable } = usePipelineCapabilities()

  useEffect(() => {
    const stored = readClientStorage(STORAGE_KEY)
    if (stored) {
      setChunkStrategy(stored)
    }

    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue) {
        setChunkStrategy(event.newValue)
      }
    }

    globalThis.window.addEventListener('storage', onStorage)
    return () => globalThis.window.removeEventListener('storage', onStorage)
  }, [])

  const persistChunkStrategy = useCallback((value: string) => {
    const next = (value || '').trim().toLowerCase() || 'langchain_recursive'
    setChunkStrategy(next)
    writeClientStorage(STORAGE_KEY, next)
  }, [])

  useEffect(() => {
    if (!capabilities) return
    const ok = chunkStrategyAvailable(chunkStrategy)
    if (ok === false) {
      persistChunkStrategy(capabilities.default_chunk_strategy || 'langchain_recursive')
    }
  }, [capabilities, chunkStrategy, chunkStrategyAvailable, persistChunkStrategy])

  const contextValue = useMemo(() => ({
    chunkStrategy,
    setChunkStrategy: persistChunkStrategy,
  }), [chunkStrategy, persistChunkStrategy])

  return (
    <ChunkStrategyContext.Provider value={contextValue}>
      {children}
    </ChunkStrategyContext.Provider>
  )
}

export function useChunkStrategyPreference() {
  const ctx = useContext(ChunkStrategyContext)
  if (!ctx) {
    throw new Error('useChunkStrategyPreference must be used within ChunkStrategyProvider')
  }
  return ctx
}
